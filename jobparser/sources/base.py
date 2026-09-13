"""Базовый интерфейс источника вакансий."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests

from ..models import Vacancy

log = logging.getLogger(__name__)


class BaseSource(ABC):
    """Чтобы добавить площадку: наследуйтесь, реализуйте fetch(), зарегистрируйте
    класс в sources/__init__.py и добавьте секцию в config.yaml."""

    name: str = "base"

    def __init__(self, cfg: dict, search_cfg: dict, session: requests.Session, secrets=None):
        self.cfg = cfg or {}
        self.search_cfg = search_cfg or {}
        self.session = session
        self.secrets = secrets

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", False))

    @abstractmethod
    def fetch(self) -> list[Vacancy]:
        """Вернуть сырые вакансии. Фильтрация — снаружи, в filters.py."""

    def safe_fetch(self) -> list[Vacancy]:
        """Источник никогда не должен ронять весь запуск."""
        if not self.enabled:
            log.info("[%s] отключён в конфиге", self.name)
            return []
        try:
            vacancies = self.fetch()
            log.info("[%s] получено %d вакансий", self.name, len(vacancies))
            return vacancies
        except Exception as exc:  # noqa: BLE001
            log.error("[%s] источник упал: %s", self.name, exc, exc_info=True)
            return []
