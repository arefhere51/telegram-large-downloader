#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/arefhere51/telegram-large-downloader"
BRANCH="${TELEGRAM_DL_BRANCH:-main}"
INSTALL_DIR="${TELEGRAM_DL_DIR:-$HOME/telegram-large-downloader}"
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

for cmd in curl unzip find cp; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd" >&2; exit 1; }
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Engine/Desktop and run this script again." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required. Install or update Docker Desktop/Engine." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "The Docker engine is not running or is not accessible to this shell." >&2
  exit 1
fi

ARCHIVE="$TMP_DIR/repository.zip"
EXTRACT_DIR="$TMP_DIR/repository"
echo "Downloading the public GitHub repository ($BRANCH)…"
curl -fLsS "$REPO_URL/archive/refs/heads/$BRANCH.zip" -o "$ARCHIVE"
mkdir -p "$EXTRACT_DIR"
unzip -q "$ARCHIVE" -d "$EXTRACT_DIR"

COMPOSE_FILE="$(find "$EXTRACT_DIR" -type f -name docker-compose.yml -print -quit || true)"
PROJECT_DIR=""
if [[ -n "$COMPOSE_FILE" ]]; then
  PROJECT_DIR="$(dirname "$COMPOSE_FILE")"
else
  PROJECT_ZIP="$(find "$EXTRACT_DIR" -type f -iname '*.zip' -print -quit || true)"
  if [[ -z "$PROJECT_ZIP" ]]; then
    echo "No docker-compose.yml or project ZIP found in the GitHub repository." >&2
    exit 1
  fi
  NESTED_DIR="$TMP_DIR/nested-project"
  mkdir -p "$NESTED_DIR"
  unzip -q "$PROJECT_ZIP" -d "$NESTED_DIR"
  COMPOSE_FILE="$(find "$NESTED_DIR" -type f -name docker-compose.yml -print -quit || true)"
  [[ -n "$COMPOSE_FILE" ]] || { echo "The project ZIP does not contain docker-compose.yml." >&2; exit 1; }
  PROJECT_DIR="$(dirname "$COMPOSE_FILE")"
fi

for required in app.py supervisor.py Dockerfile docker-compose.yml requirements.txt; do
  [[ -f "$PROJECT_DIR/$required" ]] || { echo "Project file missing: $required" >&2; exit 1; }
done

mkdir -p "$INSTALL_DIR"
for item in app.py supervisor.py Dockerfile docker-compose.yml requirements.txt README.md run.bat .env.example install.ps1 install.sh; do
  [[ -f "$PROJECT_DIR/$item" ]] && cp -f "$PROJECT_DIR/$item" "$INSTALL_DIR/$item"
done
mkdir -p "$INSTALL_DIR/data"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  echo
  echo "Enter the Telegram credentials. They will be saved locally to $INSTALL_DIR/.env (not uploaded to GitHub)."
  read -r -s -p 'BotFather token: ' BOT_TOKEN; echo
  read -r -p 'Telegram API ID: ' TELEGRAM_API_ID
  read -r -s -p 'Telegram API Hash: ' TELEGRAM_API_HASH; echo
  read -r -p 'Your numeric Telegram user ID: ' ADMIN_IDS
  if [[ -z "$BOT_TOKEN" || -z "$TELEGRAM_API_ID" || -z "$TELEGRAM_API_HASH" || -z "$ADMIN_IDS" ]]; then
    echo "All four values are required." >&2
    exit 1
  fi
  cat > "$INSTALL_DIR/.env" <<EOF
BOT_TOKEN=$BOT_TOKEN
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
ADMIN_IDS=$ADMIN_IDS
PUBLIC_BASE_URL=http://localhost:8000
MAX_FILE_GB=3
DATA_DIR=/app/data
LOG_LEVEL=INFO
EOF
  chmod 600 "$INSTALL_DIR/.env"
  unset BOT_TOKEN TELEGRAM_API_HASH
fi

cd "$INSTALL_DIR"
echo
echo "Starting the bot from $INSTALL_DIR. Stop it with Ctrl+C."
echo "The default localhost download link is reachable only from this computer."
docker compose up --build
