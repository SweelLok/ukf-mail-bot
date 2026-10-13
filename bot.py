"""
UKF Mail Bot — телеграм-бот для университетской почты UKF.

Почта: сервер studentmail.ukf.sk (POP3). POP3 видит только «Входящие» —
Спам и Корзина недоступны (ограничение протокола сервера UKF).
"""

import asyncio
import html
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from mail_client import MailClient
from seen_store import SeenStore

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MAIL_USER = os.getenv("MAIL_USER", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# На Fly.io (и любом хостинге с эфемерной ФС) секреты приходят через
# переменные окружения (fly secrets set), а постоянные данные —
# на смонтированный том DATA_DIR (по умолчанию /data).
DATA_DIR = os.environ.get("DATA_DIR")
if DATA_DIR:
    DATA_DIR = os.path.abspath(DATA_DIR)
    os.makedirs(DATA_DIR, exist_ok=True)

# Постоянное хранилище: seen.json, exports, chat_id, логи.
STORE_DIR = DATA_DIR or BASE_DIR
os.makedirs(os.path.join(STORE_DIR, "logs"), exist_ok=True)
os.makedirs(os.path.join(STORE_DIR, "exports"), exist_ok=True)

EXPORTS_DIR = os.path.join(STORE_DIR, "exports")

# chat_id: из переменной окружения (fly secrets), из файла на томе,
# или локально из .env (подставится после /start).
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_chat_id_file = os.path.join(STORE_DIR, "chat_id")
if not CHAT_ID and os.path.exists(_chat_id_file):
    with open(_chat_id_file, "r", encoding="utf-8") as _f:
        CHAT_ID = _f.read().strip()

CHECK_INTERVAL_MINUTES = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(STORE_DIR, "logs", "bot.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ukf-bot")

seen = SeenStore()


def _fmt_message(m: dict) -> str:
    # Текст письма может содержать <, >, & — экранируем, иначе
    # Telegram отвергает сообщение как некорректный HTML.
    esc = html.escape
    body = m["body"]
    if len(body) > 3000:
        body = body[:3000] + "…"
    return (
        f"📧 <b>Новое письмо</b>\n"
        f"👤 От: {esc(str(m['from']))}\n"
        f"📌 Тема: {esc(str(m['subject']))}\n"
        f"🕐 Дата: {esc(str(m['date']))}\n"
        f"📁 Папка: {esc(str(m['folder']))}\n\n"
        f"{esc(body)}"
    )


def _scan_inbox() -> list[dict]:
    """Возвращает новые письма из Входящих. При первом запуске только
    запоминает уже существующие письма (чтобы не присылать всю историю)."""
    client = MailClient(MAIL_USER, MAIL_PASSWORD)
    client.connect()
    try:
        messages = client.fetch_messages(limit=100)
        if seen.is_first_run("INBOX"):
            # baseline: старые письма не присылаем
            seen.mark_many(messages)
            seen.save()
            return []
        return [m for m in messages if seen.is_new("INBOX", m["uid"])]
    finally:
        client.disconnect()


async def send_new_messages(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверка почты: рассылает новые письма или сообщает, что всё тихо."""
    if not CHAT_ID:
        return
    try:
        new = await asyncio.to_thread(_scan_inbox)
    except Exception as e:
        log.exception("Ошибка при проверке почты")
        await context.bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Ошибка доступа к почте: {e}")
        return
    if new:
        for m in new:
            try:
                await context.bot.send_message(
                    chat_id=CHAT_ID, text=_fmt_message(m), parse_mode="HTML"
                )
                seen.mark("INBOX", m["uid"])  # помечаем только после успешной отправки
            except Exception:
                log.exception("Не удалось отправить письмо в Telegram")
        seen.save()
    else:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"✅ Новых писем пока нет. Проверю снова через {CHECK_INTERVAL_MINUTES} мин.",
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global CHAT_ID
    if not CHAT_ID:
        CHAT_ID = str(update.effective_chat.id)
        _persist_chat_id(CHAT_ID)
    text = (
        "👋 <b>UKF Mail Bot</b>\n\n"
        "Я слежу за твоей университетской почтой и присылаю новые письма.\n\n"
        "Команды:\n"
        "/getmail — выгрузить все письма в один TXT-файл\n"
        "/check — проверить почту прямо сейчас\n"
        "/status — состояние бота"
    )
    await update.message.reply_text(text, parse_mode="HTML")


def _persist_chat_id(chat_id: str) -> None:
    """Сохраняет chat_id, чтобы переживал перезапуск.

    На Fly.io пишем в файл на постоянном томе (DATA_DIR).
    Локально — в .env (старое поведение)."""
    if DATA_DIR:
        with open(_chat_id_file, "w", encoding="utf-8") as f:
            f.write(chat_id)
        log.info("chat_id %s сохранён в %s", chat_id, _chat_id_file)
        return
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    key = "TELEGRAM_CHAT_ID"
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={chat_id}\n"
            break
    else:
        lines.append(f"{key}={chat_id}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log.info("chat_id %s сохранён в .env", chat_id)


def _collect_all_mail() -> list[dict]:
    client = MailClient(MAIL_USER, MAIL_PASSWORD)
    client.connect()
    try:
        return client.fetch_all(limit=200)
    finally:
        client.disconnect()


async def cmd_getmail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("📥 Читаю все письма с почты, подожди немного…")
    try:
        messages = await asyncio.to_thread(_collect_all_mail)
    except Exception as e:
        log.exception("Ошибка выгрузки почты")
        await msg.edit_text(f"⚠️ Не смог получить доступ к почте: {e}")
        return
    if not messages:
        await msg.edit_text("📭 На почте нет писем.")
        return

    filename = f"ukf_mail_{datetime.now():%Y%m%d_%H%M}.txt"
    path = os.path.join(EXPORTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write("Выгрузка писем UKF\n")
        f.write(f"Сгенерировано: {datetime.now():%d.%m.%Y %H:%M}\n")
        f.write(f"Всего писем: {len(messages)}\n")
        f.write("=" * 70 + "\n\n")
        for m in messages:
            f.write(f"От:     {m['from']}\n")
            f.write(f"Тема:   {m['subject']}\n")
            f.write(f"Дата:   {m['date']}\n")
            f.write(f"Папка:  {m['folder']}\n")
            f.write("-" * 70 + "\n")
            f.write(m["body"] or "(пустое письмо)\n")
            f.write("\n" + "=" * 70 + "\n\n")

    with open(path, "rb") as f:
        await update.message.reply_document(
            document=InputFile(f, filename=filename),
            caption=f"📄 Все письма с почты ({len(messages)} шт.)",
        )
    await msg.edit_text(f"✅ Готово: {len(messages)} писем в файле {filename}")


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global CHAT_ID
    if not CHAT_ID:
        CHAT_ID = str(update.effective_chat.id)
        _persist_chat_id(CHAT_ID)
    await update.message.reply_text("🔍 Проверяю почту…")
    await send_new_messages(context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await asyncio.to_thread(MailClient(MAIL_USER, MAIL_PASSWORD).connect)
        mail_ok = "✅ подключение к почте работает"
    except Exception as e:
        mail_ok = f"❌ почта недоступна: {e}"
    text = (
        "📊 <b>Статус бота</b>\n\n"
        f"📬 {mail_ok}\n"
        f"👤 Почта: {MAIL_USER}\n"
        f"⏱ Автопроверка: каждые {CHECK_INTERVAL_MINUTES} мин."
    )
    await update.message.reply_text(text, parse_mode="HTML")


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан в .env")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("getmail", cmd_getmail))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("status", cmd_status))

    job_queue = app.job_queue
    job_queue.run_repeating(send_new_messages, interval=CHECK_INTERVAL_MINUTES * 60, first=10)

    log.info("Бот запущен. Автопроверка каждые %d м.", CHECK_INTERVAL_MINUTES)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
