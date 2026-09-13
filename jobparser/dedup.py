"""Хранилище уже отправленных вакансий, чтобы дайджест не повторялся.

Состояние — обычный JSON в репозитории: workflow коммитит его обратно,
поэтому история переживает пересоздание раннера.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Vacancy

log = logging.getLogger(__name__)


class SeenStore:
    def __init__(self, path: str | Path, ttl_days: int = 60):
        self.path = Path(path)
        self.ttl_days = ttl_days
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("не удалось прочитать %s (%s) — начинаем с пустого состояния", self.path, exc)
            self._data = {}

    def is_new(self, vacancy: Vacancy) -> bool:
        return vacancy.key not in self._data and vacancy.fuzzy_key not in self._data

    def filter_new(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        return [v for v in vacancies if self.is_new(v)]

    def mark_sent(self, vacancies: list[Vacancy]) -> None:
        today = date.today().isoformat()
        for vacancy in vacancies:
            self._data[vacancy.key] = today
            self._data[vacancy.fuzzy_key] = today

    def prune(self) -> int:
        """Удаляет записи старше ttl_days. Возвращает число удалённых."""
        cutoff = date.today() - timedelta(days=self.ttl_days)
        stale = []
        for key, value in self._data.items():
            try:
                seen_date = datetime.fromisoformat(value).date()
            except (ValueError, TypeError):
                continue
            if seen_date < cutoff:
                stale.append(key)
        for key in stale:
            del self._data[key]
        return len(stale)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, indent=1, sort_keys=True)
        self.path.write_text(payload + "\n", encoding="utf-8")

    def __len__(self) -> int:
        return len(self._data)
