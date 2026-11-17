"""FX from ECB reference rates (free for commercial reuse, cite "Source: ECB statistics").

Primary: Frankfurter v1 API (serves ECB reference rates, no key, no quota).
Fallback: ECB's own eurofxref-hist.zip.
Pegs (not in ECB): SAR 3.75, AED 3.6725, QAR 3.64, BHD 0.376, OMR 0.3845 per USD.
Rules: balance-sheet stocks at the period-end rate, flows at the period-average rate,
market values at the price-date rate.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

from .net import fetch_bytes

PEGS_PER_USD = {"USD": 1.0, "SAR": 3.75, "AED": 3.6725, "QAR": 3.64, "BHD": 0.376, "OMR": 0.3845}
FRANKFURTER = "https://api.frankfurter.dev/v1/{start}..{end}?base=USD"
ECB_HIST = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"


class FX:
    """Units of currency per 1 USD, by day."""

    def __init__(self, cache_dir: Path):
        self.path = Path(cache_dir) / "fx_per_usd.json"
        self.rates: dict[str, dict[str, float]] = {}
        if self.path.exists():
            self.rates = json.loads(self.path.read_text())
        self.source = "ECB reference rates via Frankfurter"

    def ensure(self, start: date, end: date) -> None:
        have = sorted(self.rates)
        if have and have[0] <= (start + timedelta(days=7)).isoformat() and have[-1] >= (end - timedelta(days=5)).isoformat():
            return
        try:
            url = FRANKFURTER.format(start=start.isoformat(), end=end.isoformat())
            data = json.loads(fetch_bytes(url, {"User-Agent": "Acretia/0.1"}))
            for d, row in data["rates"].items():
                self.rates.setdefault(d, {}).update(row)
        except Exception:
            try:
                self._from_ecb()
            except Exception as e:  # no FX available: USD twins stay null, ratios are unaffected
                print(f"  ! FX unavailable ({e!r:.80}); USD conversions skipped")
                return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.rates))

    def _from_ecb(self) -> None:
        z = zipfile.ZipFile(io.BytesIO(fetch_bytes(ECB_HIST, {"User-Agent": "Acretia/0.1"}, timeout=120)))
        rows = csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode()))
        for row in rows:
            usd = row.get("USD", "").strip()
            if not usd or usd == "N/A":
                continue
            per_eur_usd = float(usd)
            day = {}
            for k, v in row.items():
                k = (k or "").strip()
                v = (v or "").strip()
                if len(k) == 3 and v and v != "N/A":
                    day[k] = float(v) / per_eur_usd
            day["EUR"] = 1 / per_eur_usd
            self.rates[row["Date"]] = day
        self.source = "ECB reference rates (eurofxref-hist)"

    def per_usd(self, ccy: str, on: date) -> float | None:
        if ccy in PEGS_PER_USD:
            return PEGS_PER_USD[ccy]
        self.ensure(on - timedelta(days=10), on)
        for back in range(0, 10):  # weekends/holidays: use the previous fixing
            d = (on - timedelta(days=back)).isoformat()
            if d in self.rates and ccy in self.rates[d]:
                return self.rates[d][ccy]
        return None

    def avg_per_usd(self, ccy: str, start: date, end: date) -> float | None:
        if ccy in PEGS_PER_USD:
            return PEGS_PER_USD[ccy]
        self.ensure(start, end)
        vals = [r[ccy] for d, r in self.rates.items() if start.isoformat() <= d <= end.isoformat() and ccy in r]
        return sum(vals) / len(vals) if vals else None
