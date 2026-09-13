"""Загрузка config.yaml и секретов из окружения."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass
class Secrets:
    telegram_token: str | None
    telegram_chat_id: str | None
    superjob_key: str | None

    @classmethod
    def from_env(cls) -> "Secrets":
        return cls(
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            superjob_key=os.getenv("SUPERJOB_API_KEY") or None,
        )

    @property
    def telegram_chat_ids(self) -> list[str]:
        """Получателей может быть несколько: TELEGRAM_CHAT_ID принимает
        список через запятую, пробел или точку с запятой.

        Каждый получатель должен сам написать боту хотя бы раз — иначе
        Telegram запрещает отправку и возвращает «chat not found».
        """
        raw = self.telegram_chat_id or ""
        ids = [part.strip() for part in re.split(r"[,;\s]+", raw) if part.strip()]
        # Один и тот же чат в списке дважды означал бы дубль сообщения.
        return list(dict.fromkeys(ids))


class Config:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        path = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(path, encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh) or {})

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def search(self) -> dict[str, Any]:
        return self.get("search", default={}) or {}

    def source(self, name: str) -> dict[str, Any]:
        return self.get("sources", name, default={}) or {}

    @property
    def telegram(self) -> dict[str, Any]:
        return self.get("telegram", default={}) or {}

    @property
    def dedup(self) -> dict[str, Any]:
        return self.get("dedup", default={}) or {}
