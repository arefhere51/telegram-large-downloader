FROM aiogram/telegram-bot-api:latest AS local_bot_api

FROM python:3.12-alpine
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    TELEGRAM_API_LISTEN_HOST=127.0.0.1 \
    TELEGRAM_API_PORT=8081
RUN apk add --no-cache ca-certificates libstdc++ openssl
COPY --from=local_bot_api /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py supervisor.py ./
RUN mkdir -p /app/data /tmp/telegram-bot-api
EXPOSE 8000
CMD ["python", "supervisor.py"]
