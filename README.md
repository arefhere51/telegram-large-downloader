# ربات دانلود فایل‌های حجیم تلگرام

ربات خصوصی فارسی برای دریافت فایل ارسالی/فورواردشده در تلگرام، ثبت سابقهٔ آن و ساخت لینک دانلود مستقیم. پنل وب مدیریتی ندارد؛ تاریخچه، وضعیت فضای دیسک و حذف فایل از طریق دکمه‌های فارسی داخل گفت‌وگوی ربات انجام می‌شود.

## نکتهٔ فنی مهم

Bot API ابری تلگرام برای `getFile` دانلود را به **۲۰ مگابایت** محدود می‌کند. این پروژه در کنار ربات، **Local Bot API Server** رسمی Telegram را با گزینهٔ `--local` اجرا می‌کند؛ در این حالت مستند رسمی امکان دانلود فایل بدون محدودیت اندازه را ذکر می‌کند. محدودیت اندازه‌ای که حساب/کلاینت فرستنده برای بارگذاری فایل در تلگرام دارد همچنان پابرجاست؛ ربات نمی‌تواند محدودیت بارگذاری تلگرام را حذف کند. [مستند Bot API](https://core.telegram.org/bots/api) · [مخزن رسمی Local Bot API](https://github.com/tdlib/telegram-bot-api)

پروژه لینک را از سرویس HTTP خودش ارائه می‌دهد و **فایل را دوباره با پیام تلگرام ارسال نمی‌کند**. لینک دارای شناسهٔ تصادفی است و هرکس آن را داشته باشد می‌تواند فایل را دانلود کند. لینک محرمانه یا رمزدار نیست.

## پیش‌نیازها

- Docker Desktop برای Windows و اجرای Docker Compose.
- ربات ساخته‌شده با [@BotFather](https://t.me/BotFather) و توکن آن.
- Telegram API ID و API Hash از [my.telegram.org/apps](https://my.telegram.org/apps). این‌ها برای Local Bot API Server لازم‌اند و با توکن BotFather فرق دارند.
- شناسهٔ عددی تلگرام مدیر. می‌توانی آن را از ربات‌هایی مثل `@userinfobot` بگیری.

## اجرا در Windows با CMD

۱. پوشهٔ پروژه را در یک مسیر دلخواه نگه دار و Docker Desktop را اجرا کن.

۲. در CMD وارد پوشهٔ پروژه شو و فایل تنظیمات بساز:

```bat
copy .env.example .env
notepad .env
```

۳. مقادیر نمونه را در `.env` با مقادیر واقعی جایگزین کن: `BOT_TOKEN`، `TELEGRAM_API_ID`، `TELEGRAM_API_HASH` و `ADMIN_IDS`. نام و شناسهٔ مدیر را با هم اشتباه نگیر؛ `ADMIN_IDS` شناسهٔ **عددی** حساب تلگرام است.

۴. سرویس را اجرا کن:

```bat
run.bat
```

یا مستقیم:

```bat
docker compose up --build
```

پس از دیدن پیام آماده‌شدن Local Bot API، در تلگرام به ربات `/start` بفرست و فایل را در گفت‌وگوی خصوصی با آن ارسال یا فوروارد کن. اجرای `docker compose up` را برای فعال‌ماندن ربات باز بگذار. توقف با `Ctrl+C` یا اجرای `docker compose down` انجام می‌شود. داده‌ها در پوشهٔ `data` می‌مانند و با `docker compose down` پاک نمی‌شوند.

در حالت محلی، مقدار پیش‌فرض `PUBLIC_BASE_URL=http://localhost:8000` است؛ این نشانی فقط روی همان کامپیوتری که برنامه را اجرا می‌کند در دسترس است. برای لینک عمومی اینترنتی، پروژه را روی Railway اجرا کن یا یک میزبان HTTPS در دسترس قرار بده.

## راه‌اندازی در Railway

Railway از Dockerfile پروژه برای ساخت سرویس استفاده می‌کند. در Railway:

۱. پروژه را از مخزن GitHub بساز و deploy کن.
۲. برای همان سرویس یک Volume بساز و مسیر mount را دقیقاً `/app/data` قرار بده. برنامه و Local Bot API در یک کانتینر اجرا می‌شوند و فایل‌ها و پایگاه SQLite هر دو در این Volume ذخیره می‌شوند.
۳. متغیرهای زیر را در Railway Variables وارد کن: `BOT_TOKEN`، `TELEGRAM_API_ID`، `TELEGRAM_API_HASH`، `ADMIN_IDS`، `MAX_FILE_GB=3` و `DATA_DIR=/app/data`.
۴. برای سرویس یک دامنهٔ عمومی HTTPS بگیر. سپس `PUBLIC_BASE_URL` را برابر همان دامنه، بدون اسلش انتهایی، تنظیم کن؛ مثلاً `https://your-service.up.railway.app`. بعد از تغییر متغیرها redeploy کن.
۵. در صورت باقی‌ماندن bot webhook از استقرار قبلی، ربات باید به حالت polling منتقل شود. اگر همان ربات پیش‌تر با Bot API ابری استفاده شده، دستورالعمل رسمی Telegram برای انتقال به سرور محلی را دنبال کن و پیش از فعال‌کردن نمونهٔ جدید، نمونهٔ قدیمی را متوقف کن.

### فضای ذخیره‌سازی Railway

Railway برای Volume به‌صورت پیش‌فرض در Free مقدار **۰٫۵ گیگابایت** و در Hobby مقدار **۵ گیگابایت** اعلام کرده است. فایل ۲–۳ گیگابایتی روی Free جا نمی‌شود؛ حتی ۵ گیگابایت برای نگه‌داری بلندمدت چند فایل بزرگ کافی نیست. برای یک فایل حجیم و مقداری فضای جانبی، Volume بزرگ‌تر از حجم فایل انتخاب کن (مثلاً دست‌کم ۱۰ گیگابایت) و برای تاریخچهٔ چندفایلی ظرفیت بیشتری در نظر بگیر. Railway افزایش حجم Volume را در پلن‌های پولی پشتیبانی می‌کند. هزینهٔ ذخیره‌سازی و ترافیک را در صفحهٔ پلن خود Railway بررسی کن. [محدودیت و قیمت Volumeها](https://docs.railway.com/volumes/reference) · [ساخت Volume](https://docs.railway.com/guides/volumes)

## دکمه‌های ربات

- **راهنمای ارسال فایل**: روش کار و هشدار لینک عمومی.
- **تاریخچهٔ فایل‌ها**: نام، حجم، جزئیات، لینک و وضعیت فایل‌ها.
- **وضعیت و فضای ذخیره‌سازی**: شمار فایل‌ها و فضای آزاد Volume.
- **حذف فایل**: پس از تأیید، فایل را از دیسک حذف می‌کند؛ سابقهٔ آن در تاریخچه می‌ماند.

فقط حساب‌هایی که شناسهٔ عددی‌شان در `ADMIN_IDS` است اجازهٔ استفاده دارند. چند شناسه را با کاما جدا کن.

## متغیرهای اصلی

| متغیر | کاربرد |
|---|---|
| `BOT_TOKEN` | توکن دریافتی از BotFather |
| `TELEGRAM_API_ID` و `TELEGRAM_API_HASH` | اعتبار Local Bot API Server |
| `ADMIN_IDS` | شناسهٔ عددی مدیر یا مدیرها |
| `PUBLIC_BASE_URL` | دامنهٔ HTTPS برای ساخت لینک دانلود |
| `MAX_FILE_GB` | بیشینهٔ اندازهٔ هر فایل؛ پیش‌فرض ۳ گیبی‌بایت |
| `DATA_DIR` | محل پایگاه داده و فایل‌های Local Bot API؛ پیش‌فرض Railway `/app/data` |

## امنیت و نگه‌داری

- فایل `.env` و توکن‌ها را برای کسی نفرست و به GitHub push نکن. `.gitignore` آن را مستثنا کرده است.
- لینک دانلود bearer-link است: هرکس لینک را داشته باشد دسترسی دارد. اگر لینک لو رفت، فایل را از دکمهٔ تاریخچه حذف کن تا مسیر دانلود غیرفعال شود.
- حذف فایل از دیسک برگشت‌پذیر نیست؛ رکورد تاریخچه باقی می‌ماند.
- فایل‌ها خودکار منقضی یا پاک نمی‌شوند. فضای Volume را از دکمهٔ وضعیت بررسی و در صورت نیاز فایل‌های قدیمی را حذف کن.
- اگر یک توکن ربات قبلاً روی Bot API ابری استفاده شده، طبق مستند Telegram انتقال به Local Bot API باید انجام شود؛ تنها یک نمونهٔ polling را هم‌زمان روشن نگه دار.

## ساختار پروژه

- `app.py` — بات تلگرام، منوی فارسی، SQLite، تاریخچه و HTTP download با Range.
- `supervisor.py` — اجرای هم‌زمان Local Bot API Server و برنامه.
- `Dockerfile` — ساخت یک کانتینر واحد مناسب Railway.
- `docker-compose.yml` و `run.bat` — اجرای آسان روی Windows.
- `.env.example` — قالب تنظیمات.

## منابع رسمی

- [Telegram Bot API: getFile و Local Bot API Server](https://core.telegram.org/bots/api)
- [کد منبع رسمی Local Bot API Server](https://github.com/tdlib/telegram-bot-api)
- [Railway Volumes: محدودیت ظرفیت و ویژگی‌ها](https://docs.railway.com/volumes/reference)
- [Railway: استفاده از Volume](https://docs.railway.com/guides/volumes)
- [Railway: Dockerfile](https://docs.railway.com/guides/dockerfiles)


## دریافت و اجرا از مخزن GitHub با یک دستور CMD

این روش وقتی کار می‌کند که مخزن [arefhere51/telegram-large-downloader](https://github.com/arefhere51/telegram-large-downloader) عمومی باشد و ZIP نهایی پروژه با نامی که پسوند `.zip` دارد در شاخهٔ `main` قرار گرفته باشد. فایل ZIP باید شامل `install.ps1` باشد؛ ZIP جدید همین پروژه این نصب‌گر را دارد.

در CMD ویندوز، این یک خط را کپی و اجرا کن:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $t=Join-Path $env:TEMP 'tgdl-bootstrap'; if(Test-Path $t){Remove-Item $t -Recurse -Force}; New-Item -ItemType Directory -Path $t|Out-Null; Invoke-WebRequest 'https://github.com/arefhere51/telegram-large-downloader/archive/refs/heads/main.zip' -OutFile (Join-Path $t 'repo.zip'); Expand-Archive (Join-Path $t 'repo.zip') (Join-Path $t 'repo') -Force; $z=Get-ChildItem (Join-Path $t 'repo') -Recurse -File -Filter '*.zip'|Select-Object -First 1; if(!$z){throw 'Upload the project ZIP to the repository main branch first.'}; Expand-Archive $z.FullName (Join-Path $t 'project') -Force; $s=Get-ChildItem (Join-Path $t 'project') -Recurse -File -Filter 'install.ps1'|Select-Object -First 1; if(!$s){throw 'The ZIP is missing install.ps1.'}; & $s.FullName"
```

دستور اول ZIP شاخهٔ `main` مخزن را می‌گیرد، ZIP پروژه را از داخل آن باز می‌کند و نصب‌گرش را اجرا می‌کند. نصب‌گر فایل‌های برنامه را در `%USERPROFILE%\telegram-large-downloader` کپی می‌کند. بار اول `.env` در Notepad باز می‌شود؛ توکن BotFather، Telegram API ID و API Hash و شناسهٔ عددی تلگرامت را وارد و ذخیره کن. سپس Notepad را ببند و در پنجرهٔ CMD/PowerShell که نصب‌گر باز کرده Enter بزن. Docker Desktop باید نصب و روشن باشد.

فایل‌های داده در پوشهٔ نصب باقی می‌مانند؛ اجرای دوبارهٔ دستور، کد را به‌روز می‌کند و فایل `.env` و تاریخچهٔ محلی را حفظ می‌کند. این روش برای دریافت ZIP از GitHub به Git نصب‌شده احتیاج ندارد.

**مهم دربارهٔ لینک دانلود:** دستور بالا ربات را روی کامپیوتر خودت اجرا می‌کند. لینک پیش‌فرض `localhost` فقط روی همان کامپیوتر باز می‌شود، نه در تلگرام گوشی یا برای افراد دیگر. برای لینک دانلود عمومی، برنامه باید روی Railway اجرا شود و `PUBLIC_BASE_URL` با دامنهٔ HTTPS آن تنظیم شود. اجرای محلی نیز تا وقتی پنجرهٔ سرویس باز است فعال می‌ماند.


### اجرای Bash در Linux یا ترمینال کانتینر

در شاخهٔ `main` ریشهٔ مخزن باید شامل فایل `install.sh` باشد. دستور قبلی PowerShell مخصوص Windows بود؛ وقتی پرامپت شبیه `root@...:/#` است، این دستور Bash را به‌کار ببر:

```bash
curl -fsSL https://raw.githubusercontent.com/arefhere51/telegram-large-downloader/main/install.sh -o /tmp/telegram-large-downloader-install.sh && bash /tmp/telegram-large-downloader-install.sh
```

`install.sh` هم فایل‌های برنامه‌ای را که مستقیم در ریشهٔ مخزن قرار دارند می‌خواند و هم حالت قرارداشتن ZIP در مخزن را پشتیبانی می‌کند. در اجرای اول، مقادیر تلگرام را در ترمینال می‌پرسد و فقط در فایل `.env` محلی نگه می‌دارد. این روش نیازمند Docker daemon قابل‌دسترسی است؛ داخل کانتینرهای بدون Docker socket باید آن را روی سیستم میزبان اجرا کنی.
