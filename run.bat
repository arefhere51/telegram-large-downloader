@echo off
setlocal
cd /d "%~dp0"
if not exist .env (
  copy .env.example .env >nul
  echo .env ساخته شد. لطفاً BOT_TOKEN، TELEGRAM_API_ID، TELEGRAM_API_HASH و ADMIN_IDS را در آن وارد کنید.
  notepad .env
  echo پس از ذخیرهٔ مقادیر، دوباره run.bat را اجرا کنید.
  pause
  exit /b 1
)
docker compose up --build
