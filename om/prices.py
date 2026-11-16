"""Price providers. Prices are the one input with no free commercial licence (see README).

- CsvPrices: your own licensed end-of-day file. Columns: ticker,date,close,currency[,ordinary_per_unit]
  ordinary_per_unit = ordinary shares represented by one traded unit (ADR ratio); default 1.
- TwelveDataPrices: business-tier key. Their Venture plan allows public display of *derived*
  metrics with attribution; confirm in writing before publishing.
Personal-use feeds (Yahoo/yfinance, Alpha Vantage free, Tiingo Starter, Stooq) are deliberately not wired in.
"""
from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class Quote:
    ticker: str
    close: float
    currency: str
    on: date
    source: str
    ordinary_per_unit: float = 1.0


class CsvPrices:
    def __init__(self, path: Path):
        self.rows: dict[str, list[Quote]] = {}
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                q = Quote(r["ticker"].upper(), float(r["close"]), (r.get("currency") or "USD").upper(),
                          date.fromisoformat(r["date"]), f"csv:{Path(path).name}",
                          float(r.get("ordinary_per_unit") or 1))
                self.rows.setdefault(q.ticker, []).append(q)

    def get(self, ticker: str, as_of: date | None = None) -> Quote | None:
        qs = [q for q in self.rows.get(ticker.upper(), []) if as_of is None or q.on <= as_of]
        return max(qs, key=lambda q: q.on) if qs else None


class TwelveDataPrices:
    URL = "https://api.twelvedata.com/eod?{q}"

    def __init__(self, api_key: str):
        self.key = api_key

    def get(self, ticker: str, as_of: date | None = None) -> Quote | None:
        params = {"symbol": ticker, "apikey": self.key}
        if as_of:
            params["date"] = as_of.isoformat()
        with urllib.request.urlopen(self.URL.format(q=urllib.parse.urlencode(params)), timeout=30) as r:
            j = json.loads(r.read())
        if "close" not in j:
            return None
        return Quote(ticker.upper(), float(j["close"]), j.get("currency", "USD").upper(),
                     date.fromisoformat(j["datetime"][:10]), "twelvedata")
