"""«Работа России» (trudvsem.ru) — открытые госданные, без ключа и без лимитов.

Документация: https://trudvsem.ru/opendata/api
Даёт то, чего почти нет на hh: стажировки в госструктурах, ЦБ, крупных ГК.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..models import Vacancy
from ..utils import clean_html, format_salary, get_json, truncate
from .base import BaseSource

log = logging.getLogger(__name__)

API_URL = "https://opendata.trudvsem.ru/api/v1/vacancies/region/{region}"


class TrudvsemSource(BaseSource):
    name = "trudvsem"

    def fetch(self) -> list[Vacancy]:
        vacancies: list[Vacancy] = []
        region = self.cfg.get("region_code", "7700000000000")
        per_page = int(self.cfg.get("per_page", 100))
        max_pages = int(self.cfg.get("max_pages", 2))
        url = API_URL.format(region=region)

        for query in self.cfg.get("queries", []):
            for page in range(max_pages):
                params = {"text": query, "limit": per_page, "offset": page}
                data = get_json(self.session, url, params=params)
                if not isinstance(data, dict):
                    break

                items = ((data.get("results") or {}).get("vacancies")) or []
                if not items:
                    break

                for wrapper in items:
                    parsed = self._parse(wrapper.get("vacancy") or {})
                    if parsed:
                        vacancies.append(parsed)

                if len(items) < per_page:
                    break

        return vacancies

    def _parse(self, item: dict) -> Vacancy | None:
        try:
            if not item.get("id"):
                return None

            requirement = item.get("requirement") or {}
            education = requirement.get("education") or ""
            experience = requirement.get("experience")
            duty = clean_html(item.get("duty"))

            try:
                experience_years = int(experience) if experience not in (None, "") else None
            except (TypeError, ValueError):
                experience_years = None

            req_parts = []
            if education:
                req_parts.append(f"образование: {education}")
            if experience_years:
                req_parts.append(f"опыт: {experience_years} г.")
            if duty:
                req_parts.append(truncate(duty, 200))

            published_at = None
            raw_date = item.get("creation-date")
            if raw_date:
                try:
                    published_at = datetime.fromisoformat(raw_date)
                except ValueError:
                    published_at = None

            return Vacancy(
                source=self.name,
                external_id=str(item["id"]),
                title=(item.get("job-name") or "").strip(),
                company=((item.get("company") or {}).get("name") or "").strip(),
                url=item.get("vac_url", ""),
                salary=format_salary(
                    item.get("salary_min"),
                    item.get("salary_max"),
                    item.get("currency") or "RUR",
                ),
                schedule=item.get("schedule"),
                employment=item.get("employment"),
                requirements="; ".join(req_parts) or None,
                area=((item.get("region") or {}).get("name")),
                published_at=published_at,
                raw_text=" ".join([duty, education]),
                # API отдаёт опыт числом, но не фильтрует по нему — уровень проверяем сами.
                level_prefiltered=False,
                experience_years=experience_years,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("trudvsem: пропущена вакансия %s: %s", item.get("id"), exc)
            return None
