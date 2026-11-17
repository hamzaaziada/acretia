"""GLEIF LEI connector (S8.5); logic in om.intl.sources.gleif."""
from __future__ import annotations

from om.intl.sources.gleif import GleifSource

from . import base
from .intl_common import SourceConnector


class GleifConnector(SourceConnector):
    name = "gleif"

    def __init__(self, replay=False, data_dir=None, fetcher=None, leis=None, min_interval=None, clock=None, sleep=None, urlopen=None):
        super().__init__(GleifSource(replay=replay, data_dir=data_dir, fetcher=fetcher, leis=leis, min_interval=min_interval, clock=clock,
                          sleep=sleep, urlopen=urlopen))


base.register("gleif", GleifConnector)
