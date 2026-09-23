"""Релевантность и ранжирование.

Источники отдают много шума: широкое слово «аналитик» ловит и senior-позиции,
и вакансии вроде «аналитик отдела продаж». Фильтр строится на трёх осях:
роль, уровень (стажировка/junior) и явные стоп-сигналы.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .models import Vacancy

# «#» и «+» сохраняются: иначе ключи «c#» и «c++» схлопнулись бы в «c»
# и совпадали бы с любым словом на эту букву.
_NON_WORD = re.compile(r"[^a-zа-я0-9+#]+")


def normalize(text: str | None) -> str:
    """«BI-аналитик (Junior)» -> « bi аналитик junior ».

    Обрамляющие пробелы позволяют искать ключ как подстроку, не боясь склейки слов.
    """
    if not text:
        return " "
    text = text.lower().replace("ё", "е")
    text = _NON_WORD.sub(" ", text)
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def _contains(haystack: str, keyword: str) -> bool:
    """Совпадение по началу слова: «аналитик» ловит «аналитика/аналитику».
    Хвост слова свободен намеренно — иначе русские падежи пришлось бы
    перечислять руками.

    Исключение — очень короткие ключи («qa», «hr», «1с»): у них требуется
    совпадение целым словом. Иначе двухбуквенный ключ цеплялся бы к любому
    слову с таким началом, а это ложные срабатывания на ровном месте.
    """
    needle = normalize(keyword).strip()
    if not needle:
        return False
    if len(needle) <= 2:
        return f" {needle} " in haystack
    return f" {needle}" in haystack


def _matches(haystack: str, keywords) -> str | None:
    """Первый совпавший ключ.

    Принимает и список, и словарь «ключ: вес» — тогда перебираются ключи.
    """
    for keyword in keywords or []:
        if _contains(haystack, keyword):
            return keyword
    return None


def _best_match(haystack: str, weighted: dict) -> tuple[str | None, int]:
    """Лучшее совпадение по весу.

    «Младший бизнес-аналитик» матчит и широкий якорь «аналитик», и точную
    «бизнес аналитик» — засчитываем вторую, иначе профильная вакансия
    получила бы тот же балл, что и случайная.
    """
    best_key, best_weight = None, 0
    for keyword, weight in (weighted or {}).items():
        if weight > best_weight and _contains(haystack, keyword):
            best_key, best_weight = keyword, weight
    return best_key, best_weight


def _sum_weights(haystack: str, weighted: dict, cap: int | None = None) -> tuple[int, list[str]]:
    """Сумма весов всех совпавших ключей (с потолком, чтобы длинное
    описание не перевешивало всё остальное)."""
    total = 0
    hits: list[str] = []
    for keyword, weight in (weighted or {}).items():
        if _contains(haystack, keyword):
            total += int(weight)
            hits.append(keyword)
    if cap is not None:
        total = max(-cap, min(cap, total))
    return total, hits


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

    req_stop = _matches(body, search_cfg.get("requirement_stopwords", []))
    if req_stop:
        return False, 0, f"требование не по профилю: {req_stop}"

    role_keywords = search_cfg.get("role_keywords", {})

    # Роль обязана быть именно в названии. Поиск по всему описанию даёт
    # мусор вроде «Стажёр по работе с клиентами», где слово «аналитика»
    # встречается один раз в списке обязанностей.
    role, role_weight = _best_match(title, role_keywords)
    if not role:
        return False, 0, "не найдена целевая роль в названии"

    # Стажировка и junior — разные вещи: при занятости 20–30 ч/нед джуниор
    # на полный день чаще всего не подходит, поэтому веса разведены.
    intern_keywords = search_cfg.get("internship_keywords", [])
    junior_keywords = search_cfg.get("junior_keywords", [])

    intern_in_title = _matches(title, intern_keywords)
    intern_in_body = intern_in_title or _matches(body, intern_keywords)
    junior_in_title = _matches(title, junior_keywords)
    junior_in_body = junior_in_title or _matches(body, junior_keywords)

    level_in_body = intern_in_body or junior_in_body
    if not level_in_body and not vacancy.level_prefiltered:
        return False, 0, "нет признаков стажировки/junior"

    score = role_weight
    if intern_in_title:
        score += int(search_cfg.get("internship_weight", 8))
    elif intern_in_body:
        score += int(search_cfg.get("internship_weight", 8)) // 2
    elif junior_in_title:
        score += int(search_cfg.get("junior_weight", 3))
    elif junior_in_body:
        score += 1
    else:
        score += 1  # уровень гарантирован только фильтром источника

    # Площадка могла подтвердить тип занятости фильтром, минуя текст.
    score += vacancy.source_bonus

    # Совпадения со стеком из резюме поднимают вакансию, чужой стек — опускает.
    # Потолок не даёт длинному описанию перевесить роль и уровень.
    skill_bonus, _ = _sum_weights(body, search_cfg.get("skill_keywords", {}), cap=6)
    gap_penalty, _ = _sum_weights(body, search_cfg.get("skill_gaps", {}), cap=6)
    score += skill_bonus + gap_penalty

    # График, совместимый с учёбой. Отсечения нет намеренно: RSS-фид hh
    # график не отдаёт вообще, и жёсткий фильтр вырезал бы главный источник.
    schedule_text = normalize(" ".join(filter(None, [vacancy.schedule, vacancy.employment])))
    schedule_bonus, _ = _sum_weights(schedule_text, search_cfg.get("schedule_bonus", {}), cap=5)
    score += schedule_bonus

    if vacancy.salary:
        score += 1
    if vacancy.requirements:
        score += 1
    score += _freshness_bonus(vacancy.published_at)

    min_score = int(search_cfg.get("min_score", 0))
    if score < min_score:
        return False, score, f"низкий балл соответствия: {score} < {min_score}"

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
