"""Хранилище просмотренных UID'ов, чтобы бот присылал только новые письма."""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# На хостинге с эфемерной ФС (Fly.io) состояние живёт на смонтированном томе.
STORE_PATH = os.path.join(os.environ.get("DATA_DIR", BASE_DIR), "seen.json")


class SeenStore:
    def __init__(self, path: str = STORE_PATH):
        self.path = path
        self._seen: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._seen = {k: set(v) for k, v in raw.items()}
            except Exception:
                self._seen = {}

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({k: sorted(v) for k, v in self._seen.items()}, f)

    def is_new(self, folder: str, uid: str) -> bool:
        return uid not in self._seen.get(folder, set())

    def is_first_run(self, folder: str) -> bool:
        """True, если по этой папке ещё нет записей — первый запуск бота."""
        return folder not in self._seen

    def mark(self, folder: str, uid: str) -> None:
        self._seen.setdefault(folder, set()).add(uid)

    def mark_many(self, messages: list[dict]) -> None:
        for m in messages:
            self.mark(m["folder"], m["uid"])
