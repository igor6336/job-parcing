"""hh.ru — официальный публичный API, ключ не нужен.

Документация: https://api.hh.ru/openapi/redoc
Самый полный источник по российскому рынку, поэтому он же — основной.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..models import Vacancy
from ..utils import clean_html, format_salary, get_json
from .base import BaseSource

log = logging.getLogger(__name__)

API_URL = "https://api.hh.ru/vacancies"


class HHSource(BaseSource):
    name = "hh.ru"

    def fetch(self) -> list[Vacancy]:
        vacancies: list[Vacancy] = []
        period = int(self.search_cfg.get("period_days", 3))
        experience = self.cfg.get("experience") or []
        per_page = int(self.cfg.get("per_page", 100))
        max_pages = int(self.cfg.get("max_pages", 3))

        requests_made = 0
        for query in self.cfg.get("queries", []):
            for page in range(max_pages):
                requests_made += 1
                params = {
                    "text": query,
                    "area": self.cfg.get("area", 1),
                    "per_page": per_page,
                    "page": page,
                    "period": period,
                    "order_by": "publication_time",
                }
                if experience:
                    params["experience"] = experience

                data = get_json(self.session, API_URL, params=params)
                if not isinstance(data, dict):
                    break

                items = data.get("items") or []
                for item in items:
                    parsed = self._parse(item, bool(experience))
                    if parsed:
                        vacancies.append(parsed)

                if page + 1 >= int(data.get("pages", 0)):
                    break

        if requests_made and not vacancies:
            log.error(
                "hh.ru не вернул ни одной вакансии. Самая частая причина — HTTP 403: "
                "API блокирует IP зарубежных дата-центров, включая раннеры GitHub "
                "Actions. Задайте JOBPARSER_PROXY с российским адресом или запускайте "
                "парсер на VPS в РФ (см. README, раздел «Ограничение hh.ru»)."
            )

        return vacancies

    def _parse(self, item: dict, level_prefiltered: bool) -> Vacancy | None:
        try:
            salary = item.get("salary") or {}
            snippet = item.get("snippet") or {}
            requirement = clean_html(snippet.get("requirement"))
            responsibility = clean_html(snippet.get("responsibility"))

            published_at = None
            if item.get("published_at"):
                published_at = datetime.fromisoformat(item["published_at"])

            return Vacancy(
                source=self.name,
                external_id=str(item["id"]),
                title=item.get("name", "").strip(),
                company=(item.get("employer") or {}).get("name", "").strip(),
                url=item.get("alternate_url", ""),
                salary=format_salary(
                    salary.get("from"),
                    salary.get("to"),
                    salary.get("currency"),
                    salary.get("gross"),
                ),
                schedule=(item.get("schedule") or {}).get("name"),
                employment=(item.get("employment") or {}).get("name"),
                requirements=requirement or responsibility or None,
                area=(item.get("area") or {}).get("name"),
                published_at=published_at,
                raw_text=" ".join(filter(None, [requirement, responsibility])),
                level_prefiltered=level_prefiltered,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("hh: пропущена вакансия %s: %s", item.get("id"), exc)
            return None
