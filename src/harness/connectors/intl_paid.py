"""Paid-source interfaces (S8.5): Pappers, North Data, Bigdata.com, Third Bridge, Arbolus. Each raises NotConfigured
("requires user approval and a commercial agreement") from list() and fetch(). No credentials, no calls, no purchase."""
from __future__ import annotations

from om.intl.sources.paid import PAID, MESSAGE  # noqa: F401

from . import base
from .intl_common import NotConfigured, SourceConnector  # noqa: F401  (NotConfigured re-exported for callers)


def _make(key, cls):
    class _Paid(SourceConnector):
        name = key

        def __init__(self):
            super().__init__(cls())

    _Paid.__name__ = _Paid.__qualname__ = f"{cls.__name__}Connector"
    return _Paid


for _key, _cls in PAID.items():
    base.register(_key, _make(_key, _cls))
