"""Paid sources: interfaces only. Pappers, North Data, Bigdata.com (and the partnerships Third Bridge and Arbolus) need
the user's approval and a commercial agreement. Nothing here holds a credential, makes a request or buys anything."""
from __future__ import annotations

from .common import NotConfigured

MESSAGE = "requires user approval and a commercial agreement"


class PaidSource:
    vendor = ""
    kind = "data"

    def __init__(self):
        pass

    def _refuse(self):
        raise NotConfigured(f"{self.vendor}: {MESSAGE}")

    def list_items(self):
        self._refuse()
        yield {}

    def fetch(self, item_id: str):
        self._refuse()


class Pappers(PaidSource):
    vendor, source = "Pappers (FR private-company financials)", "pappers"


class NorthData(PaidSource):
    vendor, source = "North Data (DE private-company financials)", "north_data"


class Bigdata(PaidSource):
    vendor, source = "Bigdata.com (transcripts, news, filings)", "bigdata"


class ThirdBridge(PaidSource):
    vendor, source, kind = "Third Bridge (expert-interview transcripts)", "third_bridge", "partnership"


class Arbolus(PaidSource):
    vendor, source, kind = "Arbolus (expert-interview transcripts)", "arbolus", "partnership"


PAID = {c.source: c for c in (Pappers, NorthData, Bigdata, ThirdBridge, Arbolus)}
