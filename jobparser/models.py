"""Единая модель вакансии, к которой приводятся все источники."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime


def _norm_for_key(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", text)


@dataclass
class Vacancy:
    source: str
    external_id: str
    title: str
    company: str
    url: str
    salary: str | None = None
    schedule: str | None = None
    employment: str | None = None
    requirements: str | None = None
    area: str | None = None
    published_at: datetime | None = None
    score: int = 0
    raw_text: str = field(default="", repr=False)

    # True, если сам источник уже отфильтровал выдачу по «без опыта / до 3 лет».
    # Тогда отсутствие слова «junior/стажёр» в тексте не считается дисквалификацией.
    level_prefiltered: bool = False

    # Требуемый опыт в годах, если источник отдаёт его отдельным полем.
    experience_years: int | None = None

    @property
    def key(self) -> str:
        """Ключ дедупликации между запусками."""
        return f"{self.source}:{self.external_id}"

    @property
    def fuzzy_key(self) -> str:
        """Ключ дедупликации между источниками в рамках одного запуска.

        Одна и та же вакансия часто дублируется на hh и, например, на SuperJob
        с разными id, но совпадающей парой «компания + должность».
        """
        digest = _norm_for_key(self.company) + "|" + _norm_for_key(self.title)
        return hashlib.sha1(digest.encode("utf-8")).hexdigest()[:16]

    @property
    def search_text(self) -> str:
        parts = [self.title, self.company, self.requirements or "", self.raw_text]
        return " ".join(p for p in parts if p)
