"""Shared adapter for the international connectors (S8.5).

`om.intl.sources.<name>` holds the logic; this module wraps a source as a `Connector`, converts errors, and makes the
connector names reachable through `base.get(...)` even though base.py's `_LAZY` table cannot list them: importing
this module (every `intl_*.py` does) extends `_LAZY` at runtime. Bootstrap with either of

    import src.harness.connectors.intl_common            # then base.get("egx"), base.get("esef"), ...
    from src.harness.connectors.intl_common import load_all; load_all()

Sources never return report bytes to anyone but the caller, and only write under data/raw/intl/<source>/."""
from __future__ import annotations

import importlib

from om.intl.sources.common import NotConfigured, SourceError  # noqa: F401  (re-exported)

from . import base
from .base import Connector, ConnectorError, ConnectorItem

NAMES = {"egx": "intl_egx", "tadawul": "intl_tadawul", "esef": "intl_esef", "companies_house": "intl_companies_house",
         "kvk": "intl_kvk", "inpi": "intl_inpi", "bronnoysund": "intl_bronnoysund", "cro": "intl_cro", "gleif": "intl_gleif",
         "pappers": "intl_paid", "north_data": "intl_paid", "bigdata": "intl_paid", "third_bridge": "intl_paid",
         "arbolus": "intl_paid"}
base._LAZY.update({k: v for k, v in NAMES.items() if k not in base._LAZY})


def load_all() -> list[str]:
    for mod in sorted(set(NAMES.values())):
        importlib.import_module(f"{__package__}.{mod}")
    return sorted(NAMES)


class SourceConnector(Connector):
    """Adapts an `om.intl.sources` object (list_items / fetch) to the Connector interface."""
    fragile = False

    def __init__(self, source):
        self._src = source

    @property
    def min_interval(self) -> float:
        return self._src.fetcher.min_interval if hasattr(self._src, "fetcher") else 0.0

    @property
    def source(self):
        return self._src

    def __getattr__(self, attr):      # source-specific helpers: resolve(), statements(), officers(), psc(), list_bulk() ...
        if attr.startswith("_"):
            raise AttributeError(attr)
        return getattr(self.__dict__["_src"], attr)

    def list(self):
        try:
            for d in self._src.list_items():
                yield ConnectorItem(id=str(d["id"]), name=d.get("name") or str(d["id"]), size=int(d.get("size", 0)),
                                    version=d.get("version", ""), meta=dict(d.get("meta", {})))
        except NotConfigured:
            raise
        except SourceError as e:
            raise ConnectorError(str(e)) from e

    def fetch(self, item_id: str):
        try:
            body, meta = self._src.fetch(item_id)
        except NotConfigured:
            raise
        except SourceError as e:
            raise ConnectorError(str(e)) from e
        meta.setdefault("name", item_id)
        meta.setdefault("source", self.name)
        return body, meta
