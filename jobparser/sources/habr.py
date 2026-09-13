"""Хабр Карьера — публичного API нет, разбираем HTML выдачи.

Единственный хрупкий источник в наборе: при редизайне сайта селекторы сломаются.
Поэтому каждый селектор задан списком кандидатов, а провал парсинга логируется
предупреждением и не роняет остальные источники.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Vacancy
from ..utils import clean_html, get_text, truncate
from .base import BaseSource

log = logging.getLogger(__name__)

BASE = "https://career.habr.com"
SEARCH_URL = f"{BASE}/vacancies"

CARD_SELECTORS = [".vacancy-card", "section.vacancy-card"]
TITLE_SELECTORS = [".vacancy-card__title a", "a.vacancy-card__title-link"]
COMPANY_SELECTORS = [".vacancy-card__company-title a", ".vacancy-card__company a"]
SALARY_SELECTORS = [".vacancy-card__salary", ".basic-salary"]
SKILL_SELECTORS = [".vacancy-card__skills"]
META_SELECTORS = [".vacancy-card__meta"]
DATE_SELECTORS = [".vacancy-card__date", ".vacancy-card__date time"]

# Чипы в карточке смешивают три разные сущности, разделяем их по словарю.
SENIOR_CHIPS = {"senior", "lead", "teamlead", "техлид", "тимлид"}
JUNIOR_CHIPS = {"стажёр", "стажер", "intern", "junior", "джуниор"}
LEVEL_CHIPS = SENIOR_CHIPS | JUNIOR_CHIPS | {"middle", "миддл"}
FORMAT_CHIPS = {
    "можно удалённо",
    "можно удаленно",
    "только удалённо",
    "только удаленно",
    "полный рабочий день",
    "неполный рабочий день",
    "частичная занятость",
    "полная занятость",
    "гибкий график",
    "можно в офисе",
    "гибрид",
}

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def _first(node, selectors: list[str]):
    for selector in selectors:
        found = node.select_one(selector)
        if found is not None:
            return found
    return None


class HabrSource(BaseSource):
    name = "career.habr.com"

    def fetch(self) -> list[Vacancy]:
        vacancies: list[Vacancy] = []
        max_pages = int(self.cfg.get("max_pages", 2))
        city_id = self.cfg.get("city_id")

        for query in self.cfg.get("queries", []):
            for page in range(1, max_pages + 1):
                params: dict[str, object] = {"q": query, "type": "all", "page": page}
                if city_id:
                    params["city_ids[]"] = city_id

                html = get_text(self.session, SEARCH_URL, params=params)
                if not html:
                    break

                page_items = self._parse_page(html, first_page=page == 1)
                if not page_items:
                    break
                vacancies.extend(page_items)

        return vacancies

    def _parse_page(self, html: str, first_page: bool) -> list[Vacancy]:
        soup = BeautifulSoup(html, "lxml")

        cards = []
        for selector in CARD_SELECTORS:
            cards = soup.select(selector)
            if cards:
                break
        if not cards:
            # На последней странице выдачи карточек просто нет — это не поломка.
            if first_page:
                log.warning("habr: карточки не найдены — вероятно, изменилась вёрстка")
            return []

        result: list[Vacancy] = []
        for card in cards:
            vacancy = self._parse_card(card)
            if vacancy:
                result.append(vacancy)
        return result

    def _parse_card(self, card) -> Vacancy | None:
        title_node = _first(card, TITLE_SELECTORS)
        if not title_node:
            return None

        href = title_node.get("href", "")
        url = urljoin(BASE, href)
        match = re.search(r"/vacancies/(\d+)", href)
        external_id = match.group(1) if match else url

        levels, formats, locations = self._split_chips(card)
        # Грейд в карточке надёжнее, чем угадывание по названию: «Аналитик BI»
        # с чипом Senior не должен попадать в дайджест для стажировок.
        if levels & SENIOR_CHIPS:
            return None

        company_node = _first(card, COMPANY_SELECTORS)
        skills_node = _first(card, SKILL_SELECTORS)
        skills = clean_html(skills_node.get_text(", ")) if skills_node else ""

        return Vacancy(
            source=self.name,
            external_id=str(external_id),
            title=clean_html(title_node.get_text(" ")),
            company=clean_html(company_node.get_text(" ")) if company_node else "—",
            url=url,
            salary=self._clean_salary(card),
            schedule=" · ".join(sorted(formats)) or None,
            # Грейд (Junior/Intern) — не график работы, в карточку дайджеста
            # он не идёт, но остаётся в raw_text для фильтра уровня.
            employment=None,
            requirements=truncate(skills, 220) or None,
            area=", ".join(sorted(locations)) or None,
            published_at=self._parse_date(card),
            # Чипы грейда кладём в текст, чтобы сработал общий фильтр уровня.
            raw_text=" ".join([skills, " ".join(levels), " ".join(formats)]),
        )

    @staticmethod
    def _split_chips(card) -> tuple[set[str], set[str], set[str]]:
        """Чипы карточки → (грейды, форматы работы, города)."""
        meta = _first(card, META_SELECTORS)
        levels: set[str] = set()
        formats: set[str] = set()
        locations: set[str] = set()
        if not meta:
            return levels, formats, locations

        for chip in meta.select(".chip-with-icon__text, .basic-chip__text, .basic-chip"):
            text = clean_html(chip.get_text(" "))
            if not text:
                continue
            lowered = text.lower().replace("ё", "е")
            if any(lowered == level.replace("ё", "е") for level in LEVEL_CHIPS):
                levels.add(lowered)
            elif any(lowered == fmt.replace("ё", "е") for fmt in FORMAT_CHIPS):
                formats.add(text)
            else:
                locations.add(text)
        return levels, formats, locations

    @staticmethod
    def _clean_salary(card) -> str | None:
        """В блоке зарплаты соседствуют оффер и подсказка «Похожие специалисты
        получают N — M ₽». Прогноз — не зарплата работодателя, вырезаем его."""
        node = _first(card, SALARY_SELECTORS)
        if node is None:
            return None

        node = node.__copy__()
        for predicted in node.select(".predicted-salary, .tooltip"):
            predicted.decompose()

        text = clean_html(node.get_text(" "))
        if not text or "не указана" in text.lower():
            return None
        return text

    @staticmethod
    def _parse_date(card) -> datetime | None:
        """«12 сентября» / «вчера» → datetime. Нужно только для ранжирования."""
        node = _first(card, DATE_SELECTORS)
        if node is None:
            return None

        raw = clean_html(node.get_text(" ")).lower()
        now = datetime.now(timezone.utc)
        if "сегодня" in raw:
            return now
        if "вчера" in raw:
            return now - timedelta(days=1)

        match = re.search(r"(\d{1,2})\s+([а-яё]+)", raw)
        if not match:
            return None
        month = MONTHS.get(match.group(2))
        if not month:
            return None

        try:
            parsed = datetime(now.year, month, int(match.group(1)), tzinfo=timezone.utc)
        except ValueError:
            return None
        # Декабрьская вакансия, увиденная в январе, относится к прошлому году.
        if parsed > now + timedelta(days=1):
            parsed = parsed.replace(year=now.year - 1)
        return parsed
