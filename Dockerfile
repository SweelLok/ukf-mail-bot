# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Зависимости ставятся до копирования кода — лучше кэширование слоёв
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py mail_client.py seen_store.py ./

# Постоянный том: seen.json, exports, chat_id, логи
RUN mkdir -p /data/logs /data/exports

ENV DATA_DIR=/data

# Публичных портов нет: бот работает только на исходящих соединениях
# (Telegram long polling + POP3), открывать наружу ничего не нужно.
CMD ["python", "bot.py"]
