"""Релевантность и ранжирование.

Источники отдают много шума: широкое слово «аналитик» ловит и senior-позиции,
и вакансии вроде «аналитик отдела продаж». Фильтр строится на трёх осях:
роль, уровень (стажировка/junior) и явные стоп-сигналы.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .models import Vacancy

_NON_WORD = re.compile(r"[^a-zа-я0-9+]+")


def normalize(text: str | None) -> str:
    """«BI-аналитик (Junior)» -> « bi аналитик junior ».

    Обрамляющие пробелы позволяют искать ключ как подстроку, не боясь склейки слов.
    """
    if not text:
        return " "
    text = text.lower().replace("ё", "е")
    text = _NON_WORD.sub(" ", text)
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def _matches(haystack: str, keywords: list[str]) -> str | None:
    """Совпадение по началу слова: «аналитик» ловит «аналитика/аналитику»,
    но «bi» не срабатывает внутри «combi». Хвост слова свободен намеренно —
    иначе русские падежи пришлось бы перечислять руками."""
    for keyword in keywords or []:
        needle = normalize(keyword).rstrip()  # оставляем ведущий пробел
        if needle.strip() and needle in haystack:
            return keyword
    return None


def is_relevant(vacancy: Vacancy, search_cfg: dict) -> tuple[bool, int, str]:
    """Возвращает (подходит, score, причина отказа)."""
    title = normalize(vacancy.title)
    body = normalize(vacancy.search_text)

    stopword = _matches(title, search_cfg.get("title_stopwords", []))
    if stopword:
        return False, 0, f"стоп-слово в названии: {stopword}"

    max_years = int(search_cfg.get("max_experience_years", 2))
    if vacancy.experience_years is not None and vacancy.experience_years > max_years:
        return False, 0, f"требуемый опыт: {vacancy.experience_years} г."

    exp_stop = _matches(body, search_cfg.get("experience_stopwords", []))
    if exp_stop:
        return False, 0, f"требуемый опыт: {exp_stop}"

    if vacancy.area:
        area = normalize(vacancy.area)
        if not _matches(area, search_cfg.get("city_aliases", [])):
            return False, 0, f"другой регион: {vacancy.area}"

    role_keywords = search_cfg.get("role_keywords", [])
    level_keywords = search_cfg.get("level_keywords", [])

    # Роль обязана быть именно в названии. Поиск по всему описанию даёт
    # мусор вроде «Стажёр по работе с клиентами», где слово «аналитика»
    # встречается один раз в списке обязанностей.
    if not _matches(title, role_keywords):
        return False, 0, "не найдена целевая роль в названии"

    level_in_title = _matches(title, level_keywords)
    level_in_body = level_in_title or _matches(body, level_keywords)

    if not level_in_body and not vacancy.level_prefiltered:
        return False, 0, "нет признаков стажировки/junior"

    score = 4
    if level_in_title:
        score += 4
    elif level_in_body:
        score += 2
    else:
        score += 1  # уровень гарантирован только фильтром источника

    if vacancy.salary:
        score += 1
    if vacancy.requirements:
        score += 1
    score += _freshness_bonus(vacancy.published_at)

    return True, score, ""


def _freshness_bonus(published_at: datetime | None) -> int:
    if not published_at:
        return 0
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age = now - published_at
    if age <= timedelta(days=1):
        return 3
    if age <= timedelta(days=3):
        return 1
    return 0


def apply_filters(vacancies: list[Vacancy], search_cfg: dict) -> list[Vacancy]:
    """Фильтрует, проставляет score и убирает кросс-источниковые дубли."""
    kept: list[Vacancy] = []
    for vacancy in vacancies:
        ok, score, _reason = is_relevant(vacancy, search_cfg)
        if not ok:
            continue
        vacancy.score = score
        kept.append(vacancy)

    kept.sort(key=lambda v: (-v.score, v.company.lower()))

    seen: set[str] = set()
    unique: list[Vacancy] = []
    for vacancy in kept:
        if vacancy.fuzzy_key in seen:
            continue
        seen.add(vacancy.fuzzy_key)
        unique.append(vacancy)
    return unique
