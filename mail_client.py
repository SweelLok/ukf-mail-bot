"""
POP3-клиент для почты UKF (сервер studentmail.ukf.sk, Dovecot).

Сервер университета отдаёт только POP3 SSL (порт 995) — IMAP закрыт.
POP3 видит только папку «Входящие»; это ограничение протокола.
Дедупликация — по стабильным UIDL-идентификаторам сообщений.

Логин:  MAIL_USER     = номер студенческого билета (číslo študentskej karty)
        MAIL_PASSWORD = пароль от webmail (родné číslo bez lomítka)
"""

import email
import poplib
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

HOST = "studentmail.ukf.sk"
PORT = 995
FOLDER = "INBOX"  # у POP3 нет папок — только «Входящие»


def decode_str(value: str) -> str:
    """Декодирует MIME-заголовок (=?UTF-8?...?=) в читаемый текст."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def get_text_body(msg: email.message.Message) -> str:
    """Достаёт текстовое тело письма (text/plain), игнорируя вложения."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        return payload.decode(charset, errors="replace")
                    except (LookupError, TypeError):
                        return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


class MailClient:
    """POP3-клиент: подключается, читает письма, дедуплицирует по UIDL."""

    def __init__(self, user: str, password: str, host: str = HOST, port: int = PORT):
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self._pop: poplib.POP3_SSL | None = None

    # --- подключение -------------------------------------------------

    def connect(self) -> None:
        self._pop = poplib.POP3_SSL(self.host, self.port)
        self._pop.user(self.user)
        self._pop.pass_(self.password)

    def disconnect(self) -> None:
        if self._pop is not None:
            try:
                self._pop.quit()
            except Exception:
                try:
                    self._pop.close()
                except Exception:
                    pass
            self._pop = None

    def _ensure(self) -> poplib.POP3_SSL:
        if self._pop is None:
            self.connect()
        return self._pop

    # --- чтение писем --------------------------------------------------

    def _uidl_map(self) -> dict[int, str]:
        """Возвращает {номер_сообщения: uidl} для всех писем."""
        pop = self._ensure()
        _, lines, _ = pop.uidl()
        mapping = {}
        for line in lines:
            parts = line.decode().split()
            if len(parts) == 2:
                mapping[int(parts[0])] = parts[1]
        return mapping

    def _parse(self, raw_lines: list[bytes], uid: str, folder: str = FOLDER) -> dict:
        msg = email.message_from_bytes(b"\r\n".join(raw_lines))
        date_raw = msg.get("Date", "")
        try:
            dt = parsedate_to_datetime(date_raw)
            date_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            date_str = date_raw
        return {
            "uid": uid,
            "folder": folder,
            "from": decode_str(msg.get("From", "")),
            "subject": decode_str(msg.get("Subject", "(без темы)")),
            "date": date_str,
            "body": get_text_body(msg).strip(),
        }

    def fetch_messages(self, limit: int = 100) -> list[dict]:
        """Читает последние `limit` писем. Новые — первыми."""
        pop = self._ensure()
        uidl_map = self._uidl_map()
        if not uidl_map:
            return []
        nums = sorted(uidl_map.keys())
        nums = nums[-limit:] if limit else nums
        messages = []
        for num in reversed(nums):  # новые первыми
            uid = uidl_map[num]
            _, lines, _ = pop.retr(num)
            try:
                messages.append(self._parse(lines, uid))
            except Exception:
                continue  # битое письмо — пропускаем
        return messages

    def fetch_all(self, limit: int = 200) -> list[dict]:
        """Читает все письма из Входящих (POP3 больше ничего не видит)."""
        return self.fetch_messages(limit=limit)
