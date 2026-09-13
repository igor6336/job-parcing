"""getmatch.ru — внутренний JSON-эндпоинт каталога вакансий.

Официальной документации нет, схема может измениться без предупреждения.
Поиска по тексту в API нет, поэтому выкачиваем каталог по городу и фильтруем
локально. Площадка ориентирована на middle/senior, junior-позиции там редки —
источник скорее дополняющий, чем основной.
"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urljoin

from ..models import Vacancy
from ..utils import clean_html, format_salary, get_json, truncate
from .base import BaseSource

log = logging.getLogger(__name__)

BASE = "https://getmatch.ru"
API_URL = f"{BASE}/api/offers"

FORMAT_LABELS = {
    "remote": "Удалённо",
    "hybrid": "Гибрид",
    "office": "Офис",
    "onsite": "Офис",
}


class GetmatchSource(BaseSource):
    name = "getmatch.ru"

    def fetch(self) -> list[Vacancy]:
        vacancies: list[Vacancy] = []
        per_page = int(self.cfg.get("per_page", 100))
        max_pages = int(self.cfg.get("max_pages", 4))
        location = self.cfg.get("location", "moscow")

        seen_ids: set[int] = set()
        for page in range(max_pages):
            # Параметр page эндпоинт игнорирует — листается только offset.
            params = {"l": location, "limit": per_page, "offset": page * per_page}
            data = get_json(self.session, API_URL, params=params)
            if not isinstance(data, dict):
                break

            offers = data.get("offers") or []
            if not offers:
                break

            new_on_page = 0
            for offer in offers:
                if offer.get("id") in seen_ids:
                    continue
                seen_ids.add(offer.get("id"))
                new_on_page += 1
                parsed = self._parse(offer)
                if parsed:
                    vacancies.append(parsed)

            # Защита от эндпоинта, который перестал листаться и отдаёт то же самое.
            if new_on_page == 0:
                break
            if len(seen_ids) >= int((data.get("meta") or {}).get("total", 0) or 0):
                break

        return vacancies

    def _parse(self, offer: dict) -> Vacancy | None:
        try:
            if offer.get("is_active") is False:
                return None

            company = offer.get("company") or {}
            company_name = company.get("name") if isinstance(company, dict) else str(company)

            published_at = None
            if offer.get("published_at"):
                try:
                    published_at = datetime.fromisoformat(offer["published_at"])
                except ValueError:
                    published_at = None

            salary = None
            if not offer.get("salary_hidden"):
                salary = format_salary(
                    offer.get("salary_display_from"),
                    offer.get("salary_display_to"),
                    offer.get("salary_currency") or "RUB",
                    gross=offer.get("salary_taxes") == "gross",
                )

            cities, formats = self._locations(offer)
            skills = ", ".join(
                s.get("name", "")
                for s in (offer.get("skills_objects") or [])
                if isinstance(s, dict)
            ).strip(", ")
            description = clean_html(offer.get("offer_description"))

            return Vacancy(
                source=self.name,
                external_id=str(offer["id"]),
                title=(offer.get("position") or "").strip(),
                company=(company_name or "—").strip(),
                url=urljoin(BASE, offer.get("url", "")),
                salary=salary,
                schedule=" · ".join(formats) or None,
                employment=None,
                requirements=truncate(skills or description, 220) or None,
                area=", ".join(cities) or None,
                published_at=published_at,
                raw_text=" ".join(filter(None, [skills, description])),
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("getmatch: пропущена вакансия %s: %s", offer.get("id"), exc)
            return None

    @staticmethod
    def _locations(offer: dict) -> tuple[list[str], list[str]]:
        cities: list[str] = []
        formats: list[str] = []
        for item in offer.get("location_requirements") or []:
            if not isinstance(item, dict) or item.get("exclude"):
                continue
            city = item.get("city")
            if city and city not in cities:
                cities.append(city)
            label = FORMAT_LABELS.get(item.get("format", ""))
            if label and label not in formats:
                formats.append(label)
        return cities, formats
