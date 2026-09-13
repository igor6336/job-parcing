"""LinkedIn — гостевой эндпоинт выдачи вакансий (без авторизации).

Честно о том, что это даёт:

1. Эндпоинт `jobs-guest/jobs/api/seeMoreJobPostings` отдаёт публичные карточки
   без логина. Официальным API он не является: LinkedIn не документирует его
   и в пользовательском соглашении запрещает автоматизированный сбор данных.
   Формально это серая зона — решение о применении за владельцем репозитория.
2. По Москве выдача тонкая (десятки вакансий на запрос, а не тысячи):
   LinkedIn заблокирован в РФ с 2016 года, российские компании публикуются
   в основном на hh. Почти всё, что есть, — международные компании.
3. Карточка не содержит требований, а зарплату указывают редко.

LinkedIn склонен отдавать 429 при частых запросах, поэтому между страницами
выдерживается пауза.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Vacancy
from ..utils import clean_html, get_text
from .base import BaseSource

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
PAGE_SIZE = 25


class LinkedInSource(BaseSource):
    name = "linkedin.com"

    def fetch(self) -> list[Vacancy]:
        vacancies: list[Vacancy] = []
        max_pages = int(self.cfg.get("max_pages", 2))
        location = self.cfg.get("location", "Moscow, Russia")
        pause = float(self.cfg.get("pause_seconds", 1.5))

        seen_ids: set[str] = set()
        for query in self.cfg.get("queries", []):
            for page in range(max_pages):
                params = {
                    "keywords": query,
                    "location": location,
                    "start": page * PAGE_SIZE,
                    "f_TPR": f"r{int(self.search_cfg.get('period_days', 3)) * 86400}",
                }
                body = get_text(self.session, SEARCH_URL, params=params)
                if not body:
                    break

                items = self._parse(body)
                if not items:
                    break

                new_on_page = 0
                for vacancy in items:
                    if vacancy.external_id in seen_ids:
                        continue
                    seen_ids.add(vacancy.external_id)
                    new_on_page += 1
                    vacancies.append(vacancy)

                if new_on_page == 0:
                    break
                time.sleep(pause)

        return vacancies

    def _parse(self, body: str) -> list[Vacancy]:
        soup = BeautifulSoup(body, "lxml")
        result: list[Vacancy] = []

        for card in soup.select(".base-search-card, .job-search-card"):
            title_node = card.select_one(".base-search-card__title")
            link_node = card.select_one("a.base-card__full-link") or card.select_one("a")
            if not title_node or not link_node:
                continue

            urn = card.get("data-entity-urn", "")
            match = re.search(r"jobPosting:(\d+)", urn)
            url = self._clean_url(link_node.get("href", ""))
            external_id = match.group(1) if match else url
            if not external_id:
                continue

            company_node = card.select_one(".base-search-card__subtitle")
            location_node = card.select_one(".job-search-card__location")
            salary_node = card.select_one(".job-search-card__salary-info")
            date_node = card.select_one("time")

            result.append(
                Vacancy(
                    source=self.name,
                    external_id=str(external_id),
                    title=clean_html(title_node.get_text(" ")),
                    company=clean_html(company_node.get_text(" ")) if company_node else "—",
                    url=url,
                    salary=clean_html(salary_node.get_text(" ")) if salary_node else None,
                    schedule=None,
                    employment=None,
                    # Требований в карточке нет — они только на странице вакансии.
                    requirements=None,
                    area=clean_html(location_node.get_text(" ")) if location_node else None,
                    published_at=self._parse_date(date_node),
                    raw_text=clean_html(card.get_text(" ")),
                )
            )
        return result

    @staticmethod
    def _clean_url(href: str) -> str:
        """Ссылки приходят с хвостом трекинга — он ломает дедупликацию."""
        if not href:
            return ""
        parts = urlsplit(href)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    @staticmethod
    def _parse_date(node) -> datetime | None:
        if node is None:
            return None
        raw = node.get("datetime")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
