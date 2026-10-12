from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data")).resolve()
API_DIR = DATA_DIR / "telegram-api"
TEMP_DIR = Path(os.getenv("TELEGRAM_TEMP_DIR", "/tmp/telegram-bot-api"))
API_HOST = os.getenv("TELEGRAM_API_LISTEN_HOST", "127.0.0.1")
API_PORT = os.getenv("TELEGRAM_API_PORT", "8081")


def require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        print(f"خطا: متغیر {name} تنظیم نشده است.", file=sys.stderr, flush=True)
        raise SystemExit(2)
    return value


api_id = require("TELEGRAM_API_ID")
api_hash = require("TELEGRAM_API_HASH")
bot_token = require("BOT_TOKEN")
require("ADMIN_IDS")
DATA_DIR.mkdir(parents=True, exist_ok=True)
API_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

api_command = [
    "telegram-bot-api",
    f"--api-id={api_id}",
    f"--api-hash={api_hash}",
    "--local",
    f"--http-ip-address={API_HOST}",
    f"--http-port={API_PORT}",
    f"--dir={API_DIR}",
    f"--temp-dir={TEMP_DIR}",
]

print("Starting Local Telegram Bot API Server…", flush=True)
api_process = subprocess.Popen(api_command)


def stop_children(*_: object) -> None:
    for process in (app_process, api_process):
        if process and process.poll() is None:
            process.terminate()
    for process in (app_process, api_process):
        if process and process.poll() is None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    raise SystemExit(0)


app_process: subprocess.Popen | None = None
signal.signal(signal.SIGTERM, stop_children)
signal.signal(signal.SIGINT, stop_children)

health_url = f"http://{API_HOST}:{API_PORT}/bot{bot_token}/getMe"
ready = False
for attempt in range(120):
    if api_process.poll() is not None:
        raise SystemExit(f"Local Bot API Server exited with code {api_process.returncode}")
    try:
        with urllib.request.urlopen(health_url, timeout=2) as response:
            if response.status == 200:
                ready = True
                break
    except (urllib.error.URLError, TimeoutError, OSError):
        time.sleep(1)
if not ready:
    api_process.terminate()
    raise SystemExit("Local Bot API Server did not become ready within 120 seconds")

port = os.getenv("PORT", "8000")
print(f"Local Bot API ready; starting downloader on port {port}…", flush=True)
app_process = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", port],
    cwd=str(ROOT),
)

while True:
    app_code = app_process.poll()
    api_code = api_process.poll()
    if app_code is not None:
        api_process.terminate()
        raise SystemExit(app_code)
    if api_code is not None:
        app_process.terminate()
        raise SystemExit(f"Local Bot API Server exited unexpectedly with code {api_code}")
    time.sleep(1)
