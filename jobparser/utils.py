"""Вспомогательные функции: HTTP-сессия с ретраями, чистка текста, зарплата."""

from __future__ import annotations

import html
import logging
import os
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

USER_AGENT = (
    "job-digest-bot/1.0 (personal daily job digest; "
    "+https://github.com/igor6336/job-parcing)"
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def make_session(timeout: int = 20) -> requests.Session:
    """Сессия с экспоненциальными ретраями на сетевые ошибки и 5xx/429.

    JOBPARSER_PROXY (например, http://user:pass@host:port) направляет запросы
    через прокси — на случай, если площадки недоступны из текущей сети.
    """
    session = requests.Session()

    proxy = os.getenv("JOBPARSER_PROXY")
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
        log.info("запросы идут через прокси %s", re.sub(r"//[^@]+@", "//***@", proxy))

    retry = Retry(
        total=4,
        backoff_factor=2,  # 2s, 4s, 8s, 16s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"})
    session.request_timeout = timeout  # type: ignore[attr-defined]
    return session


def get_json(session: requests.Session, url: str, **kwargs) -> dict | list | None:
    """GET с логированием ошибок вместо исключения.

    Падение одного источника не должно ронять весь дайджест.
    """
    timeout = kwargs.pop("timeout", getattr(session, "request_timeout", 20))
    try:
        response = session.get(url, timeout=timeout, **kwargs)
        if response.status_code != 200:
            log.warning("GET %s -> HTTP %s", url, response.status_code)
            return None
        return response.json()
    except Exception as exc:  # noqa: BLE001 - источник не должен ронять запуск
        log.warning("GET %s failed: %s", url, exc)
        return None


def get_text(session: requests.Session, url: str, **kwargs) -> str | None:
    timeout = kwargs.pop("timeout", getattr(session, "request_timeout", 20))
    try:
        response = session.get(url, timeout=timeout, **kwargs)
        if response.status_code != 200:
            log.warning("GET %s -> HTTP %s", url, response.status_code)
            return None
        return response.text
    except Exception as exc:  # noqa: BLE001
        log.warning("GET %s failed: %s", url, exc)
        return None


def clean_html(text: str | None) -> str:
    """Убирает теги (в т.ч. hh-шные <highlighttext>) и схлопывает пробелы."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:—-") + "…"


# Источники пишут валюту как угодно: hh — "RUR", trudvsem — "руб.", SuperJob — "rub".
_CURRENCY = {
    "RUR": "₽",
    "RUB": "₽",
    "РУБ": "₽",
    "РУБ.": "₽",
    "РУБЛЬ": "₽",
    "USD": "$",
    "EUR": "€",
    "KZT": "₸",
    "BYR": "Br",
}


def format_salary(
    salary_from: int | float | None,
    salary_to: int | float | None,
    currency: str | None = "RUR",
    gross: bool | None = None,
) -> str | None:
    """Приводит разнобой источников к строке вида «от 80 000 до 120 000 ₽ (на руки)»."""

    def money(value: int | float) -> str:
        return f"{int(value):,}".replace(",", " ")

    salary_from = salary_from or None
    salary_to = salary_to or None
    if not salary_from and not salary_to:
        return None

    # trudvsem присылает валюту буквально как «руб.» — вместе с кавычками-ёлочками.
    key = (currency or "RUR").upper().strip().strip("«»\"'")
    sign = _CURRENCY.get(key, _CURRENCY.get(key.rstrip("."), key or ""))
    if salary_from and salary_to and salary_from != salary_to:
        body = f"{money(salary_from)}–{money(salary_to)}"
    elif salary_from and salary_to and salary_from == salary_to:
        body = money(salary_from)
    elif salary_from:
        body = f"от {money(salary_from)}"
    else:
        body = f"до {money(salary_to)}"

    result = f"{body} {sign}".strip()
    if gross is True:
        result += " (до вычета НДФЛ)"
    elif gross is False:
        result += " (на руки)"
    return result
