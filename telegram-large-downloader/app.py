from __future__ import annotations

import asyncio
import html
import json
import logging
import mimetypes
import os
import secrets
import shutil
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("telegram-large-downloader")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_BASE = os.getenv("BOT_API_URL", "http://127.0.0.1:8081").rstrip("/")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data")).expanduser().resolve()
BOT_API_DATA_DIR = (DATA_DIR / "telegram-api").resolve()
DB_PATH = DATA_DIR / "history.sqlite3"
PORT = int(os.getenv("PORT", "8000"))
MAX_FILE_GB = float(os.getenv("MAX_FILE_GB", "3"))
MAX_FILE_BYTES = int(MAX_FILE_GB * 1024**3)
CHUNK_SIZE = 1024 * 1024
HISTORY_PAGE_SIZE = 8

try:
    ADMIN_IDS = {int(v.strip()) for v in os.getenv("ADMIN_IDS", "").split(",") if v.strip()}
except ValueError as exc:
    raise RuntimeError("ADMIN_IDS باید شناسهٔ عددی تلگرام باشد.") from exc

if not BOT_TOKEN:
    raise RuntimeError("متغیر BOT_TOKEN تنظیم نشده است.")
if not ADMIN_IDS:
    raise RuntimeError("حداقل یک شناسهٔ عددی در ADMIN_IDS لازم است.")

DATA_DIR.mkdir(parents=True, exist_ok=True)
BOT_API_DATA_DIR.mkdir(parents=True, exist_ok=True)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                size INTEGER NOT NULL,
                mime_type TEXT,
                local_path TEXT NOT NULL,
                telegram_file_id TEXT,
                telegram_message_id INTEGER,
                telegram_user_id INTEGER,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_files_created ON files(created_at DESC);
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )


def get_state(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def fmt_size(n: int | None) -> str:
    if n is None:
        return "نامشخص"
    value = float(n)
    for unit in ("بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"):
        if value < 1024 or unit == "ترابایت":
            return f"{value:.1f} {unit}" if unit != "بایت" else f"{int(value)} بایت"
        value /= 1024
    return f"{n} بایت"


def shorten(value: str, limit: int = 42) -> str:
    value = value.replace("\n", " ").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def keyboard(rows: list[list[dict[str, Any]]]) -> dict[str, Any]:
    return {"inline_keyboard": rows}


def home_keyboard(admin: bool = True) -> dict[str, Any]:
    rows = [
        [{"text": "📥 راهنمای ارسال فایل", "callback_data": "help"}],
        [{"text": "📚 تاریخچهٔ فایل‌ها", "callback_data": "history:0"}],
    ]
    if admin:
        rows.append([{"text": "📊 وضعیت و فضای ذخیره‌سازی", "callback_data": "stats"}])
    return keyboard(rows)


class TelegramAPI:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0))
        self.prefix = f"{API_BASE}/bot{BOT_TOKEN}"

    async def call(self, method: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        try:
            response = await self.client.post(
                f"{self.prefix}/{method}",
                json=payload or {},
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            log.warning("Telegram API network error in %s: %s", method, type(exc).__name__)
            raise RuntimeError("ارتباط با سرور تلگرام برقرار نشد.") from exc
        if not data.get("ok"):
            desc = str(data.get("description", "خطای نامشخص تلگرام"))
            log.warning("Telegram API returned an error for %s: %s", method, desc[:250])
            raise RuntimeError(desc)
        return data.get("result")

    async def send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", payload)

    async def edit(self, chat_id: int, message_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            await self.call("editMessageText", payload)
        except RuntimeError as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except RuntimeError:
            pass


telegram = TelegramAPI()


def file_url(token: str) -> str:
    if not PUBLIC_BASE_URL:
        return ""
    return f"{PUBLIC_BASE_URL}/d/{token}"


def attachment(message: dict[str, Any]) -> tuple[str, str, int | None, str | None] | None:
    for field in ("document", "video", "animation", "audio", "voice", "video_note"):
        item = message.get(field)
        if item:
            default_name = {
                "video": "video.mp4", "animation": "animation.mp4", "audio": "audio", "voice": "voice.ogg",
                "video_note": "video_note.mp4",
            }.get(field, "file")
            name = item.get("file_name") or default_name
            mime = item.get("mime_type") or mimetypes.guess_type(name)[0]
            return str(item["file_id"]), str(name), item.get("file_size"), mime
    photos = message.get("photo")
    if photos:
        photo = photos[-1]
        return str(photo["file_id"]), f"photo_{message.get('message_id', int(time.time()))}.jpg", photo.get("file_size"), "image/jpeg"
    return None


def get_file_row(file_id: int) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()


def record_file(file_id: str, name: str, size: int, mime_type: str | None, path: Path, message: dict[str, Any]) -> tuple[int, str]:
    token = secrets.token_urlsafe(24)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        cursor = conn.execute(
            """INSERT INTO files(token,name,size,mime_type,local_path,telegram_file_id,telegram_message_id,telegram_user_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (token, name, size, mime_type, str(path), file_id, message.get("message_id"),
             (message.get("from") or {}).get("id"), created),
        )
        return int(cursor.lastrowid), token


async def send_file_result(chat_id: int, name: str, size: int, token: str) -> None:
    url = file_url(token)
    if not url:
        await telegram.send(
            chat_id,
            "✅ فایل آماده شد و در تاریخچه ثبت شد.\n\nبرای ساخت لینک عمومی، متغیر PUBLIC_BASE_URL را با نشانی HTTPS سرویس خود تنظیم کن و سرویس را دوباره اجرا کن.",
            keyboard([[{"text": "📚 مشاهدهٔ تاریخچه", "callback_data": "history:0"}]]),
        )
        return
    await telegram.send(
        chat_id,
        f"✅ فایل آمادهٔ دانلود است.\n\n📄 {shorten(name, 100)}\n📦 {fmt_size(size)}\n\nهرکس این لینک را داشته باشد می‌تواند فایل را دریافت کند:",
        keyboard([
            [{"text": "⬇️ دانلود فایل", "url": url}],
            [{"text": "📚 تاریخچهٔ فایل‌ها", "callback_data": "history:0"}],
        ]),
    )


async def handle_media(message: dict[str, Any], chat_id: int) -> None:
    media = attachment(message)
    if not media:
        return
    file_id, name, announced_size, mime = media
    if announced_size and announced_size > MAX_FILE_BYTES:
        await telegram.send(chat_id, f"⛔ اندازهٔ فایل از سقف تنظیم‌شدهٔ {MAX_FILE_GB:g} گیگابایت بیشتر است.")
        return
    progress = await telegram.send(chat_id, "⏳ فایل دریافت شد؛ در حال آماده‌سازی لینک دانلود. برای فایل حجیم کمی صبر کن…")
    try:
        result = await telegram.call("getFile", {"file_id": file_id}, timeout=None)
        raw_path = Path(str(result.get("file_path", "")))
        if not raw_path.is_absolute():
            raw_path = BOT_API_DATA_DIR / raw_path
        resolved = raw_path.resolve()
        if not resolved.is_relative_to(BOT_API_DATA_DIR):
            raise RuntimeError("مسیر فایل برگشتی از Telegram API خارج از فضای مجاز است.")
        # Local Bot API returns a local absolute file_path after it has downloaded the file.
        for _ in range(20):
            if resolved.is_file():
                break
            await asyncio.sleep(1)
        if not resolved.is_file():
            raise RuntimeError("فایل روی دیسک سرور پیدا نشد؛ مطمئن شو Local Bot API و برنامه به یک DATA_DIR وصل‌اند.")
        actual_size = resolved.stat().st_size
        if actual_size > MAX_FILE_BYTES:
            raise RuntimeError(f"اندازهٔ فایل از سقف تنظیم‌شدهٔ {MAX_FILE_GB:g} گیگابایت بیشتر است.")
        if actual_size == 0:
            raise RuntimeError("فایل دانلودشده خالی است.")
        record_id, token = record_file(file_id, name, actual_size, mime, resolved, message)
        url = file_url(token)
        success_text = f"✅ فایل آماده شد.\n\n📄 {shorten(name, 100)}\n📦 {fmt_size(actual_size)}\n🗂 شمارهٔ تاریخچه: {record_id}"
        if url:
            await telegram.edit(
                chat_id, progress["message_id"], success_text + "\n\nلینک برای هرکس که آن را داشته باشد قابل دسترسی است:",
                keyboard([
                    [{"text": "⬇️ دریافت لینک دانلود", "url": url}],
                    [{"text": "📚 تاریخچه", "callback_data": "history:0"}],
                ]),
            )
        else:
            await telegram.edit(chat_id, progress["message_id"], success_text + "\n\nبرای لینک عمومی مقدار PUBLIC_BASE_URL را تنظیم کن.", home_keyboard())
    except Exception as exc:
        log.exception("Could not prepare an incoming file")
        await telegram.edit(
            chat_id,
            progress["message_id"],
            "❌ آماده‌سازی فایل ناموفق شد.\n\n" + shorten(str(exc), 250) + "\n\nاگر فایل بزرگ‌تر از ۲۰ مگابایت است، مطمئن شو Local Bot API Server در حالت local اجرا می‌شود.",
            home_keyboard(),
        )


async def show_history(chat_id: int, message_id: int, page: int) -> None:
    page = max(0, page)
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
        rows = conn.execute("SELECT * FROM files ORDER BY id DESC LIMIT ? OFFSET ?", (HISTORY_PAGE_SIZE, page * HISTORY_PAGE_SIZE)).fetchall()
    if not rows and page > 0:
        page -= 1
        return await show_history(chat_id, message_id, page)
    if not total:
        text = "📚 هنوز فایلی در تاریخچه ثبت نشده است.\n\nبرای شروع، یک فایل را همین‌جا برای ربات بفرست."
        return await telegram.edit(chat_id, message_id, text, home_keyboard())
    buttons: list[list[dict[str, Any]]] = []
    for row in rows:
        status = "🗑 " if row["deleted_at"] else "📄 "
        buttons.append([{"text": f"{status}{shorten(row['name'], 38)} · {fmt_size(row['size'])}", "callback_data": f"view:{row['id']}"}])
    nav: list[dict[str, Any]] = []
    if page > 0:
        nav.append({"text": "⬅️ قبلی", "callback_data": f"history:{page-1}"})
    if (page + 1) * HISTORY_PAGE_SIZE < total:
        nav.append({"text": "بعدی ➡️", "callback_data": f"history:{page+1}"})
    if nav:
        buttons.append(nav)
    buttons.append([{"text": "🏠 منوی اصلی", "callback_data": "menu"}])
    await telegram.edit(chat_id, message_id, f"📚 تاریخچهٔ فایل‌ها\nصفحهٔ {page + 1} · مجموع {total} فایل", keyboard(buttons))


async def show_file(chat_id: int, message_id: int, file_id: int) -> None:
    row = get_file_row(file_id)
    if not row:
        return await telegram.edit(chat_id, message_id, "این مورد در تاریخچه پیدا نشد.", home_keyboard())
    created = row["created_at"][:19].replace("T", " ")
    state = "🗑 فایل از دیسک حذف شده است." if row["deleted_at"] else "✅ فایل در دیسک موجود است." if Path(row["local_path"]).is_file() else "⚠️ مسیر فایل روی دیسک پیدا نشد."
    text = f"📄 {shorten(row['name'], 120)}\n📦 {fmt_size(row['size'])}\n🕒 {created} UTC\n{state}"
    buttons: list[list[dict[str, Any]]] = []
    url = file_url(row["token"])
    if not row["deleted_at"] and Path(row["local_path"]).is_file() and url:
        buttons.append([{"text": "⬇️ دانلود", "url": url}])
    if not row["deleted_at"]:
        buttons.append([{"text": "🗑 حذف فایل از فضای ذخیره‌سازی", "callback_data": f"delete_confirm:{file_id}"}])
    buttons.extend([
        [{"text": "⬅️ بازگشت به تاریخچه", "callback_data": "history:0"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "menu"}],
    ])
    await telegram.edit(chat_id, message_id, text, keyboard(buttons))


async def show_stats(chat_id: int, message_id: int) -> None:
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
        live = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS bytes FROM files WHERE deleted_at IS NULL").fetchone()
    usage = shutil.disk_usage(DATA_DIR)
    text = (
        "📊 وضعیت ذخیره‌سازی\n\n"
        f"فایل‌های ثبت‌شده در تاریخچه: {total}\n"
        f"فایل‌های فعال: {live['n']}\n"
        f"حجم فایل‌های فعال: {fmt_size(live['bytes'])}\n"
        f"فضای آزاد دیسک: {fmt_size(usage.free)} از {fmt_size(usage.total)}\n"
        f"حداکثر اندازهٔ هر فایل: {MAX_FILE_GB:g} گیگابایت\n\n"
        "لینک دانلود عمومی و محرمانه نیست؛ آن را فقط با افراد مورداعتماد به‌اشتراک بگذار."
    )
    await telegram.edit(chat_id, message_id, text, keyboard([[{"text": "🏠 منوی اصلی", "callback_data": "menu"}]]))


async def delete_file(chat_id: int, message_id: int, file_id: int) -> None:
    row = get_file_row(file_id)
    if not row:
        return await telegram.edit(chat_id, message_id, "این فایل در تاریخچه پیدا نشد.", home_keyboard())
    if row["deleted_at"]:
        return await telegram.edit(chat_id, message_id, "این فایل قبلاً حذف شده است؛ رکورد تاریخچه باقی مانده.", home_keyboard())
    path = Path(row["local_path"]).resolve()
    if not path.is_relative_to(BOT_API_DATA_DIR):
        return await telegram.edit(chat_id, message_id, "مسیر فایل خارج از فضای مجاز است؛ حذف انجام نشد.", home_keyboard())
    if path.exists():
        path.unlink()
    with db() as conn:
        conn.execute("UPDATE files SET deleted_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), file_id))
    await telegram.edit(chat_id, message_id, "🗑 فایل از دیسک حذف شد. رکورد تاریخچه برای یادآوری باقی می‌ماند.", home_keyboard())


HELP_TEXT = (
    "📥 راهنما\n\n"
    "۱) یک فایل را در گفت‌وگوی خصوصی برای همین ربات ارسال یا فوروارد کن.\n"
    "۲) ربات فایل را با Local Bot API Server از Telegram دریافت می‌کند.\n"
    "۳) پس از تکمیل دریافت، لینک HTTP مستقیم در اختیارت قرار می‌گیرد.\n\n"
    "فقط مدیرانی که شناسه‌شان در ADMIN_IDS ثبت شده می‌توانند از این ربات استفاده کنند.\n"
    "دارندهٔ لینک دانلود می‌تواند فایل را دریافت کند؛ لینک را عمومی نکن."
)


async def handle_message(message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = chat.get("id")
    user_id = sender.get("id")
    if not chat_id or not user_id:
        return
    if user_id not in ADMIN_IDS or chat.get("type") != "private" or chat_id != user_id:
        await telegram.send(chat_id, "⛔ دسترسی به این ربات برای حساب شما فعال نیست.")
        return
    text = (message.get("text") or "").strip()
    if text.startswith("/start"):
        await telegram.send(chat_id, "سلام! فایل را همین‌جا برای من بفرست تا لینک دانلود مستقیمش را بسازم.\n\nاز دکمه‌های زیر برای مدیریت تاریخچه استفاده کن.", home_keyboard())
        return
    if text.startswith("/help"):
        await telegram.send(chat_id, HELP_TEXT, home_keyboard())
        return
    if text.startswith("/history"):
        sent = await telegram.send(chat_id, "در حال خواندن تاریخچه…")
        await show_history(chat_id, sent["message_id"], 0)
        return
    media = attachment(message)
    if media:
        await handle_media(message, chat_id)
    elif text:
        await telegram.send(chat_id, "من فقط فایل‌های ارسالی را پردازش می‌کنم. برای راهنما /help را بفرست.", home_keyboard())


async def handle_callback(callback: dict[str, Any]) -> None:
    callback_id = callback["id"]
    sender = callback.get("from") or {}
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    user_id = sender.get("id")
    message_id = message.get("message_id")
    if not chat_id or not message_id:
        await telegram.answer_callback(callback_id)
        return
    if user_id not in ADMIN_IDS or chat.get("type") != "private" or chat_id != user_id:
        await telegram.answer_callback(callback_id, "اجازهٔ دسترسی نداری.")
        return
    data = str(callback.get("data", ""))
    await telegram.answer_callback(callback_id)
    try:
        if data == "menu":
            await telegram.edit(chat_id, message_id, "منوی مدیریت ربات دانلودر:", home_keyboard())
        elif data == "help":
            await telegram.edit(chat_id, message_id, HELP_TEXT, home_keyboard())
        elif data == "stats":
            await show_stats(chat_id, message_id)
        elif data.startswith("history:"):
            await show_history(chat_id, message_id, int(data.split(":", 1)[1]))
        elif data.startswith("view:"):
            await show_file(chat_id, message_id, int(data.split(":", 1)[1]))
        elif data.startswith("delete_confirm:"):
            file_id = int(data.split(":", 1)[1])
            await telegram.edit(
                chat_id, message_id,
                "حذف فایل از روی دیسک قابل بازگشت نیست. رکورد تاریخچه باقی می‌ماند. مطمئنی؟",
                keyboard([
                    [{"text": "بله، فایل را حذف کن", "callback_data": f"delete:{file_id}"}],
                    [{"text": "لغو", "callback_data": f"view:{file_id}"}],
                ]),
            )
        elif data.startswith("delete:"):
            await delete_file(chat_id, message_id, int(data.split(":", 1)[1]))
    except Exception:
        log.exception("Callback handling failed")
        await telegram.edit(chat_id, message_id, "❌ اجرای این گزینه ناموفق شد. دوباره تلاش کن.", home_keyboard())


async def process_update(update: dict[str, Any]) -> None:
    if "message" in update:
        await handle_message(update["message"])
    elif "callback_query" in update:
        await handle_callback(update["callback_query"])


async def poll_updates() -> None:
    offset = int(get_state("telegram_offset", "0") or "0")
    log.info("Telegram long polling started")
    while True:
        try:
            updates = await telegram.call(
                "getUpdates",
                {"offset": offset, "timeout": 50, "allowed_updates": ["message", "callback_query"]},
                timeout=65,
            )
            for update in updates or []:
                try:
                    await process_update(update)
                except Exception:
                    log.exception("Update %s could not be handled", update.get("update_id"))
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                set_state("telegram_offset", str(offset))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Polling retry: %s", shorten(str(exc), 180))
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    try:
        await telegram.call("deleteWebhook", {"drop_pending_updates": False}, timeout=30)
    except Exception as exc:
        log.warning("Could not clear webhook at startup: %s", shorten(str(exc), 150))
    task = asyncio.create_task(poll_updates(), name="telegram-long-poll")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await telegram.client.aclose()


app = FastAPI(title="Telegram Large File Downloader", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "telegram-large-downloader"}


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header:
        return None
    if not header.startswith("bytes=") or "," in header:
        raise HTTPException(status_code=416, detail="Only one byte range is supported", headers={"Content-Range": f"bytes */{size}"})
    value = header[6:].strip()
    if "-" not in value:
        raise HTTPException(status_code=416, detail="Invalid byte range", headers={"Content-Range": f"bytes */{size}"})
    first, last = value.split("-", 1)
    try:
        if first == "":
            suffix = int(last)
            if suffix <= 0:
                raise ValueError
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
            if start < 0 or end < start or start >= size:
                raise ValueError
            end = min(end, size - 1)
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="Invalid byte range", headers={"Content-Range": f"bytes */{size}"}) from exc
    return start, end


def safe_download_name(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch not in "\r\n\x00")
    return cleaned or "download.bin"


def resolve_download(token: str) -> sqlite3.Row:
    with db() as conn:
        row = conn.execute("SELECT * FROM files WHERE token=?", (token,)).fetchone()
    if not row or row["deleted_at"]:
        raise HTTPException(status_code=404, detail="File not found")
    path = Path(row["local_path"]).resolve()
    if not path.is_relative_to(BOT_API_DATA_DIR) or not path.is_file():
        raise HTTPException(status_code=404, detail="File is no longer available")
    return row


async def stream_download(token: str, request: Request) -> StreamingResponse:
    row = resolve_download(token)
    path = Path(row["local_path"])
    size = path.stat().st_size
    byte_range = parse_range(request.headers.get("range"), size)
    start, end = byte_range if byte_range else (0, size - 1)
    length = max(0, end - start + 1)
    filename = safe_download_name(row["name"])
    disposition = f"attachment; filename=download; filename*=UTF-8''{quote(filename, safe='')}"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": disposition,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    status_code = 200
    if byte_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        status_code = 206

    def chunks():
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    media_type = row["mime_type"] or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return StreamingResponse(chunks(), status_code=status_code, media_type=media_type, headers=headers)


@app.get("/d/{token}")
async def download(token: str, request: Request):
    return await stream_download(token, request)


@app.head("/d/{token}")
async def download_head(token: str, request: Request):
    return await stream_download(token, request)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "Telegram Large File Downloader", "health": "/health"}
