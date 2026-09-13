"""Реестр источников. Новый источник добавляется одной строкой в SOURCES."""

from __future__ import annotations

from .base import BaseSource
from .getmatch import GetmatchSource
from .habr import HabrSource
from .hh import HHSource
from .linkedin import LinkedInSource
from .superjob import SuperJobSource
from .trudvsem import TrudvsemSource

# Ключ должен совпадать с именем секции в config.yaml -> sources.
SOURCES: dict[str, type[BaseSource]] = {
    "hh": HHSource,
    "trudvsem": TrudvsemSource,
    "habr": HabrSource,
    "getmatch": GetmatchSource,
    "linkedin": LinkedInSource,
    "superjob": SuperJobSource,
}

__all__ = ["SOURCES", "BaseSource"]
