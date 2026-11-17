"""ESEF filings (filings.xbrl.org) connector (S8.5); logic in om.intl.sources.esef."""
from __future__ import annotations

from om.intl.sources.esef import EsefSource

from . import base
from .intl_common import SourceConnector


class EsefConnector(SourceConnector):
    name = "esef"

    def __init__(self, replay=False, data_dir=None, fetcher=None, country=None, lei=None, period_end=None, limit=20, min_interval=None, clock=None, sleep=None, urlopen=None):
        super().__init__(EsefSource(replay=replay, data_dir=data_dir, fetcher=fetcher, country=country, lei=lei, period_end=period_end, limit=limit, min_interval=min_interval, clock=clock,
                          sleep=sleep, urlopen=urlopen))


base.register("esef", EsefConnector)
