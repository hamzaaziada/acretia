"""Archetype registry: `register` decorator, BuildContext, auto-discovery of sibling modules."""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable

from om.deck.theme import Theme


@dataclass
class BuildContext:
    theme: Theme
    index: int
    total: int
    deck_title: str
    rtl: bool = False
    lang: str = "en"
    gap: float = 0.3
    visual: dict | None = None
    manifest: dict | None = None
    dense: bool = False


@dataclass
class Archetype:
    id: str
    schema: dict
    visual_type: str
    data: bool
    build: Callable[[dict, BuildContext], Any]


REGISTRY: dict[str, Archetype] = {}


def register(id: str, schema: dict, visual_type: str, data: bool = False):
    def deco(fn):
        if id in REGISTRY:
            raise ValueError(f"archetype {id!r} registered twice")
        REGISTRY[id] = Archetype(id, schema, visual_type, data, fn)
        return fn
    return deco


def get(id: str) -> Archetype:
    try:
        return REGISTRY[id]
    except KeyError:
        raise KeyError(f"unknown archetype {id!r}; known: {sorted(REGISTRY)}") from None


for _m in pkgutil.iter_modules(__path__):
    if _m.name != "base" and not _m.name.startswith("_"):
        importlib.import_module(f"{__name__}.{_m.name}")
