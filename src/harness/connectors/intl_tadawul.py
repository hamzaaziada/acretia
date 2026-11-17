"""Saudi Exchange (Tadawul) financial statements connector (S8.5); logic in om.intl.sources.tadawul."""
from __future__ import annotations

from om.intl.sources.tadawul import TadawulSource

from . import base
from .intl_common import SourceConnector


class TadawulConnector(SourceConnector):
    name = "tadawul"

    def __init__(self, replay=False, data_dir=None, fetcher=None, pages=None, min_interval=None, clock=None, sleep=None, urlopen=None):
        super().__init__(TadawulSource(replay=replay, data_dir=data_dir, fetcher=fetcher, pages=pages, min_interval=min_interval, clock=clock,
                          sleep=sleep, urlopen=urlopen))


base.register("tadawul", TadawulConnector)
