$ErrorActionPreference = 'Stop'

$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDir = Join-Path $env:USERPROFILE 'telegram-large-downloader'
$envFile = Join-Path $installDir '.env'

$requiredFiles = @(
    'app.py', 'supervisor.py', 'Dockerfile', 'docker-compose.yml',
    'requirements.txt', '.env.example', '.gitignore', '.dockerignore', 'run.bat', 'README.md'
)
foreach ($name in $requiredFiles) {
    if (-not (Test-Path (Join-Path $sourceDir $name))) {
        throw "فایل $name در بسته پیدا نشد. مطمئن شو ZIP کامل پروژه را در مخزن گذاشته‌ای."
    }
}

New-Item -ItemType Directory -Force -Path $installDir | Out-Null
foreach ($name in $requiredFiles) {
    Copy-Item -Force (Join-Path $sourceDir $name) (Join-Path $installDir $name)
}

if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $installDir '.env.example') $envFile
    Write-Host ''
    Write-Host "تنظیمات در $envFile ساخته شد." -ForegroundColor Cyan
    Write-Host 'در پنجرهٔ Notepad مقادیر BOT_TOKEN، TELEGRAM_API_ID، TELEGRAM_API_HASH و ADMIN_IDS را وارد و ذخیره کن.'
    Write-Host 'بعد از ذخیره و بستن Notepad، در این پنجره Enter بزن.'
    Start-Process -FilePath notepad.exe -ArgumentList ('"{0}"' -f $envFile)
    Read-Host 'برای ادامه Enter را بزن'
}

$envText = Get-Content -Raw -Path $envFile
$placeholders = @(
    'PASTE_BOTFATHER_TOKEN_HERE',
    'PASTE_TELEGRAM_API_HASH_HERE',
    'TELEGRAM_API_ID=123456',
    'ADMIN_IDS=123456789'
)
$missing = @($placeholders | Where-Object { $envText.Contains($_) })
if ($missing.Count -gt 0) {
    Write-Host 'مقادیر نمونه هنوز در .env هستند؛ لطفاً آن‌ها را اصلاح کن.' -ForegroundColor Yellow
    Start-Process -FilePath notepad.exe -ArgumentList ('"{0}"' -f $envFile)
    throw 'فایل .env را کامل کن و همان دستور GitHub را دوباره اجرا کن.'
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker پیدا نشد. Docker Desktop را نصب کن، آن را اجرا کن و همین دستور را دوباره بزن.'
}

docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Compose در دسترس نیست. Docker Desktop را به‌روز و اجرا کن.'
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Engine اجرا نیست. Docker Desktop را باز کن و سپس همین دستور را دوباره اجرا کن.'
}

Write-Host ''
Write-Host "پروژه در $installDir نصب شد. برای توقف ربات Ctrl+C بزن." -ForegroundColor Green
Write-Host 'توجه: لینک localhost فقط روی همین کامپیوتر قابل بازشدن است؛ برای لینک عمومی از Railway استفاده کن.' -ForegroundColor Yellow
Push-Location $installDir
try {
    docker compose up --build
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose با کد $LASTEXITCODE تمام شد. لاگ بالا را بررسی کن."
    }
}
finally {
    Pop-Location
}
