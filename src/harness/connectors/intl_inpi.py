"""France INPI RNE connector (S8.5); logic in om.intl.sources.inpi."""
from __future__ import annotations

from om.intl.sources.inpi import InpiSource

from . import base
from .intl_common import SourceConnector


class InpiConnector(SourceConnector):
    name = "inpi"

    def __init__(self, replay=False, data_dir=None, fetcher=None, sirens=None, min_interval=None, clock=None, sleep=None, urlopen=None):
        super().__init__(InpiSource(replay=replay, data_dir=data_dir, fetcher=fetcher, sirens=sirens, min_interval=min_interval, clock=clock,
                          sleep=sleep, urlopen=urlopen))


base.register("inpi", InpiConnector)
