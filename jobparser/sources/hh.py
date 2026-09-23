"""hh.ru — через RSS-выдачу поиска.

Почему не API: в апреле 2026 hh закрыл публичный `GET /vacancies` — метод
отдаёт 403 всем неавторизованным клиентам, откуда бы запрос ни шёл. Ключи
выдаются работодателям после модерации, соискателю его не получить.
Справочники (/areas, /dictionaries, /suggests) остались открытыми, но вакансий
там нет.

RSS (`hh.ru/search/vacancy/rss`) — штатная функция самого сайта: ссылка на неё
есть на странице поиска. Это не обход блокировки и не парсинг HTML, который
правила hh запрещают отдельным пунктом.

Цена решения: фид отдаёт только компанию, регион, зарплату и дату — графика
работы и требований в нём нет, они остаются за ссылкой.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from xml.etree import ElementTree

from ..models import Vacancy
from ..utils import get_text
from .base import BaseSource

log = logging.getLogger(__name__)

RSS_URL = "https://hh.ru/search/vacancy/rss"

# Описание в фиде — четыре фиксированных абзаца.
COMPANY_RE = re.compile(r"Вакансия компании:\s*(.+?)\s*</p>", re.S)
REGION_RE = re.compile(r"Регион:\s*(.+?)\s*</p>", re.S)
SALARY_RE = re.compile(r"уровень месячного дохода:\s*(.+?)\s*</p>", re.S)


def _unescape(text: str) -> str:
    """В заголовках фида встречается двойное экранирование: «&amp;mdash;»."""
    return html.unescape(html.unescape(text or "")).strip()


class HHSource(BaseSource):
    name = "hh.ru"

    def fetch(self) -> list[Vacancy]:
        vacancies: list[Vacancy] = []
        max_pages = int(self.cfg.get("max_pages", 3))
        area = self.cfg.get("area", 1)
        # search_field=name резко чистит выдачу: RSS игнорирует часть фильтров,
        # и без него в фид попадает всё, где ключевое слово встретилось в тексте.
        search_field = self.cfg.get("search_field", "name")
        period = int(self.search_cfg.get("period_days", 3))

        # Режимы поиска. Фид уважает employment и schedule (в отличие от
        # experience, который он игнорирует), поэтому стажировки и гибкий
        # график можно запросить напрямую, а не вылавливать по названию.
        # bonus — прибавка к баллу: площадка подтвердила тип занятости,
        # даже если в заголовке слова «стажировка» нет.
        profiles = self.cfg.get("query_profiles") or [{"params": {}, "bonus": 0}]

        seen_ids: set[str] = set()
        for profile in profiles:
            extra = profile.get("params") or {}
            bonus = int(profile.get("bonus", 0))
            note = profile.get("note", "")

            for query in self.cfg.get("queries", []):
                for page in range(max_pages):
                    params = {
                        "text": query,
                        "area": area,
                        "page": page,
                        "period": period,
                        "order_by": "publication_time",
                    }
                    if search_field:
                        params["search_field"] = search_field
                    params.update(extra)

                    body = get_text(self.session, RSS_URL, params=params)
                    if not body:
                        break

                    items = self._parse_feed(body)
                    if not items:
                        break

                    new_on_page = 0
                    for vacancy in items:
                        if vacancy.external_id in seen_ids:
                            continue
                        seen_ids.add(vacancy.external_id)
                        new_on_page += 1
                        vacancy.source_bonus = bonus
                        vacancy.source_note = note
                        if bonus > 0:
                            # Режим уже гарантирует нужный тип занятости,
                            # поэтому слово «стажёр» в тексте не обязательно.
                            vacancy.level_prefiltered = True
                        vacancies.append(vacancy)

                    # Фид отдаёт ровно 20 записей; когда страницы кончились,
                    # hh повторяет последнюю вместо пустого ответа.
                    if new_on_page == 0:
                        break

        if not vacancies:
            log.warning(
                "hh.ru: RSS не вернул вакансий. Если в логе выше есть HTTP 403 — "
                "проверьте, не закрыли ли и RSS (см. README, раздел «hh.ru»)."
            )
        return vacancies

    def _parse_feed(self, body: str) -> list[Vacancy]:
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as exc:
            log.warning("hh.ru: не разобрался RSS (%s)", exc)
            return []

        result: list[Vacancy] = []
        for item in root.iterfind(".//item"):
            vacancy = self._parse_item(item)
            if vacancy:
                result.append(vacancy)
        return result

    def _parse_item(self, item) -> Vacancy | None:
        link = (item.findtext("link") or "").strip()
        title = _unescape(item.findtext("title") or "")
        if not link or not title:
            return None

        match = re.search(r"/vacancy/(\d+)", link)
        external_id = match.group(1) if match else link

        description = item.findtext("description") or ""
        company = self._extract(COMPANY_RE, description) or "—"
        region = self._extract(REGION_RE, description)
        salary = self._extract(SALARY_RE, description)
        if salary and "не указан" in salary.lower():
            salary = None

        published_at = None
        raw_date = (item.findtext("pubDate") or "").strip()
        if raw_date:
            try:
                published_at = datetime.fromisoformat(raw_date)
            except ValueError:
                published_at = None

        return Vacancy(
            source=self.name,
            external_id=str(external_id),
            title=title,
            company=company,
            url=link,
            salary=salary,
            # Графика и требований в фиде нет — они видны только на странице вакансии.
            schedule=None,
            employment=None,
            requirements=None,
            area=region,
            published_at=published_at,
            raw_text=title,
        )

    @staticmethod
    def _extract(pattern: re.Pattern, text: str) -> str | None:
        match = pattern.search(text)
        return _unescape(match.group(1)) if match else None
