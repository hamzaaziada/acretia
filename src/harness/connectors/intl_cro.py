"""Ireland CRO open data connector (S8.5); logic in om.intl.sources.cro."""
from __future__ import annotations

from om.intl.sources.cro import CroSource

from . import base
from .intl_common import SourceConnector


class CroConnector(SourceConnector):
    name = "cro"

    def __init__(self, replay=False, data_dir=None, fetcher=None, query=None, min_interval=None, clock=None, sleep=None, urlopen=None):
        super().__init__(CroSource(replay=replay, data_dir=data_dir, fetcher=fetcher, query=query, min_interval=min_interval, clock=clock,
                          sleep=sleep, urlopen=urlopen))


base.register("cro", CroConnector)
