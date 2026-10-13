#!/usr/bin/env bash
# Установка UKF Mail Bot на чистую Ubuntu VM (Oracle Cloud / любой VPS).
# Запуск на сервере от своего пользователя: bash setup-oracle.sh
set -euo pipefail

APP_DIR="$HOME/ukf-mail-bot"
SERVICE_NAME="ukf-mail-bot"

echo "==> 1. Обновление пакетов и установка зависимостей"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip git

echo "==> 2. Клонирование репозитория"
if [ -d "$APP_DIR/.git" ]; then
    echo "    Каталог уже есть — делаю git pull"
    git -C "$APP_DIR" pull --ff-only
else
    git clone https://github.com/SweelLok/ukf-mail-bot.git "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> 3. Виртуальное окружение и пакеты"
if [ ! -d venv ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

echo "==> 4. Настройка .env"
if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo "    Создан .env из шаблона. ОТКРОЙ ЕГО И ЗАПОЛНИ ЗНАЧЕНИЯ:"
    echo "    nano $APP_DIR/.env"
else
    echo "    .env уже существует — не трогаю"
fi

mkdir -p logs exports

echo "==> 5. Установка systemd-сервиса"
# В юните подставляем реальный путь пользователя
sed "s|/home/vadim|$HOME|g" deploy/ukf-mail-bot.service > /tmp/ukf-mail-bot.service
sudo cp /tmp/ukf-mail-bot.service "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload

echo "==> 6. Автозапуск и запуск бота"
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sleep 3
sudo systemctl --no-pager status "$SERVICE_NAME" || true

cat <<'EOF'

ГОТОВО. Полезные команды на сервере:

  sudo systemctl status ukf-mail-bot     # статус
  sudo journalctl -u ukf-mail-bot -f     # живые логи
  sudo systemctl restart ukf-mail-bot    # перезапуск после правок
  tail -f ~/ukf-mail-bot/logs/bot.log    # лог бота (chat_id, ошибки)

ВАЖНО: в чате Telegram отправь боту /start — chat_id сохранится
в .env автоматически, и бот начнёт присылать новые письма.

ПОВЕДЕНИЕ БОТА:
  - Проверяет почту каждые 10 минут; письма приходят ТОЛЬКО если они есть.
  - Раз в сутки пишет heartbeat "Бот жив" со статусом почты.
  - Доступ только по твоему Telegram user_id (TELEGRAM_ADMIN_ID в .env).
    Узнать ID: напиши боту @userinfobot в Telegram — пришлёт число.
EOF
