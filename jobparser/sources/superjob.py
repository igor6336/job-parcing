"""SuperJob — официальный API, нужен бесплатный ключ (https://api.superjob.ru/register).

Без секрета SUPERJOB_API_KEY источник молча пропускается: остальной дайджест
должен работать и без него.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..models import Vacancy
from ..utils import clean_html, format_salary, get_json, truncate
from .base import BaseSource

log = logging.getLogger(__name__)

API_URL = "https://api.superjob.ru/2.0/vacancies/"


class SuperJobSource(BaseSource):
    name = "superjob.ru"

    @property
    def enabled(self) -> bool:
        if not super().enabled:
            return False
        if not (self.secrets and self.secrets.superjob_key):
            log.info("[superjob] нет SUPERJOB_API_KEY — источник пропущен")
            return False
        return True

    def fetch(self) -> list[Vacancy]:
        vacancies: list[Vacancy] = []
        headers = {"X-Api-App-Id": self.secrets.superjob_key}
        per_page = min(int(self.cfg.get("per_page", 100)), 100)
        max_pages = int(self.cfg.get("max_pages", 2))
        experience = self.cfg.get("experience") or []
        period_days = int(self.search_cfg.get("period_days", 3))

        for query in self.cfg.get("queries", []):
            for page in range(max_pages):
                params: dict[str, object] = {
                    "keyword": query,
                    "town": self.cfg.get("town", 4),
                    "count": per_page,
                    "page": page,
                    "order_field": "date",
                    "order_direction": "desc",
                    "period": period_days,
                }
                if experience:
                    params["experience"] = experience

                data = get_json(self.session, API_URL, params=params, headers=headers)
                if not isinstance(data, dict):
                    break

                for item in data.get("objects") or []:
                    parsed = self._parse(item, bool(experience))
                    if parsed:
                        vacancies.append(parsed)

                if not data.get("more"):
                    break

        return vacancies

    def _parse(self, item: dict, level_prefiltered: bool) -> Vacancy | None:
        try:
            published_at = None
            if item.get("date_published"):
                published_at = datetime.fromtimestamp(
                    int(item["date_published"]), tz=timezone.utc
                )

            candidate = clean_html(item.get("candidat"))
            work = clean_html(item.get("work"))

            return Vacancy(
                source=self.name,
                external_id=str(item["id"]),
                title=(item.get("profession") or "").strip(),
                company=((item.get("client") or {}).get("title") or item.get("firm_name") or "").strip(),
                url=item.get("link", ""),
                salary=format_salary(
                    item.get("payment_from"),
                    item.get("payment_to"),
                    item.get("currency", "rub"),
                ),
                schedule=(item.get("type_of_work") or {}).get("title"),
                employment=(item.get("place_of_work") or {}).get("title"),
                requirements=truncate(candidate or work, 220) or None,
                area=(item.get("town") or {}).get("title"),
                published_at=published_at,
                raw_text=" ".join(filter(None, [candidate, work])),
                level_prefiltered=level_prefiltered,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("superjob: пропущена вакансия %s: %s", item.get("id"), exc)
            return None
