"""Connector interface and registry (S2.5).

A Connector lists items and fetches their bytes. Everything it returns is untrusted data: callers must treat file
names and content as data, never instructions. Concrete connectors live in sibling modules and register themselves
lazily so importing this package never touches the network or an optional dependency."""
from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Iterator


@dataclass(frozen=True)
class ConnectorItem:
    id: str                      # stable identifier passed back to fetch()
    name: str                    # relative display path (untrusted; sanitise before writing to disk)
    size: int = 0
    version: str = ""            # etag / mtime:size, for incremental sync
    meta: dict = field(default_factory=dict)


class ConnectorError(RuntimeError):
    pass


class Connector(ABC):
    name: str = "connector"

    @abstractmethod
    def list(self) -> Iterator[ConnectorItem]:
        """Yield every item the connector can fetch."""

    @abstractmethod
    def fetch(self, item_id: str) -> tuple[bytes, dict]:
        """Return (content, meta). meta always carries at least `name` and `source`."""


_FACTORIES: dict[str, Callable[..., Connector]] = {}
# connector name -> module that registers it (imported lazily on first use)
_LAZY = {
    "local_room": "rooms", "s3_room": "rooms", "archive_room": "rooms",
    "sec": "sec", "web": "web",
    "synced_folder": "drive", "sharepoint": "drive", "box": "drive", "dropbox": "drive",
}


def register(name: str, factory: Callable[..., Connector] | None = None):
    """register("x", factory) or @register("x") on a class/factory."""
    def deco(f):
        _FACTORIES[name] = f
        return f
    return deco(factory) if factory is not None else deco


def get(name: str, **cfg) -> Connector:
    if name not in _FACTORIES and name in _LAZY:
        importlib.import_module(f"{__package__}.{_LAZY[name]}")
    if name not in _FACTORIES:
        raise ConnectorError(f"unknown connector {name!r}; available: {', '.join(available())}")
    return _FACTORIES[name](**cfg)


def available() -> list[str]:
    return sorted(set(_FACTORIES) | set(_LAZY))
