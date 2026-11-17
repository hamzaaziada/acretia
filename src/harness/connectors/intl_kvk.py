"""Netherlands KvK open dataset connector (S8.5); logic in om.intl.sources.kvk."""
from __future__ import annotations

from om.intl.sources.kvk import KvkSource

from . import base
from .intl_common import SourceConnector


class KvkConnector(SourceConnector):
    name = "kvk"

    def __init__(self, replay=False, data_dir=None, fetcher=None, min_interval=None, clock=None, sleep=None, urlopen=None):
        super().__init__(KvkSource(replay=replay, data_dir=data_dir, fetcher=fetcher, min_interval=min_interval, clock=clock,
                          sleep=sleep, urlopen=urlopen))


base.register("kvk", KvkConnector)
