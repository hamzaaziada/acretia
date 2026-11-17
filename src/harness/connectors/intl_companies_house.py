"""UK Companies House connector (S8.5): REST API (key from COMPANIES_HOUSE_API_KEY only) plus free bulk iXBRL accounts;
logic in om.intl.sources.companies_house. `list_bulk()` / `fetch("bulk:<zip>")` need no key; `list()` and API fetches do."""
from __future__ import annotations

from om.intl.sources.companies_house import CompaniesHouseSource

from . import base
from .intl_common import ConnectorItem, SourceConnector


class CompaniesHouseConnector(SourceConnector):
    name = "companies_house"

    def __init__(self, replay=False, data_dir=None, fetcher=None, api_key=None, company_numbers=None, min_interval=None,
                 clock=None, sleep=None, urlopen=None):
        super().__init__(CompaniesHouseSource(replay=replay, data_dir=data_dir, fetcher=fetcher, api_key=api_key,
                                              company_numbers=company_numbers, min_interval=min_interval, clock=clock,
                                              sleep=sleep, urlopen=urlopen))

    def list_bulk(self):
        for d in self._src.list_bulk():
            yield ConnectorItem(id=d["id"], name=d["name"], meta=d["meta"])


base.register("companies_house", CompaniesHouseConnector)
