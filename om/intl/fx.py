"""International FX for S8: monthly rates, period-end vs period-average translation and devaluation flags.

Data: `om/intl/data/fx/egp_usd_monthly.csv` (IMF IFS, Egypt, month-end and monthly-average EGP per USD, see its header).
SAR, AED, QAR, BHD, OMR and USD come from the pegs in `om.fx.PEGS_PER_USD`. EUR, GBP and other ECB currencies are read
from the existing `om.fx` cache file (`fx_per_usd.json`) when a cache dir is given and the file exists; this module never
touches the network.

All rates are units of currency per 1 USD. Rules: balance-sheet stocks at the period-end rate, flows at the period
average, per-share data is not scaled (EPS is a flow per share, so it is translated at the average).
"""
from __future__ import annotations

import calendar
import copy
import csv
import json
from datetime import date, timedelta
from pathlib import Path

from ..fx import PEGS_PER_USD
from ..statements import LINES

DEFAULT_RATES = Path(__file__).parent / "data" / "fx" / "egp_usd_monthly.csv"

# x.* keys that are balance-sheet stocks (everything else under x. is a flow)
X_STOCK = {"x.rou_assets", "x.lease_liabilities_current", "x.lease_liabilities_noncurrent", "x.eosb",
           "x.investment_property", "x.provisions", "x.retained_earnings", "x.share_capital", "x.nci_equity",
           "x.noncurrent_assets", "x.noncurrent_liabilities", "x.cash_beginning", "x.cash_end"}
# lines that are per-share or share counts: shares stay unchanged, EPS goes at the average
UNCHANGED = {"diluted_shares"}
PER_SHARE_FLOW = {"eps_diluted", "x.eps_basic"}


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _prev_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def kind_of(key: str) -> str | None:
    """'i' stock, 'd' flow, 'u' unchanged (share counts), None unknown."""
    if key in UNCHANGED:
        return "u"
    if key in LINES:
        return LINES[key][1]
    if key.startswith("x."):
        return "i" if key in X_STOCK else "d"
    return None


class IntlFX:
    """Units of currency per 1 USD, monthly. `rate` is a period-end rate, `average` a day-weighted monthly average."""

    def __init__(self, rates_path: str | Path | None = None, fx_cache_dir: str | Path | None = None):
        self.path = Path(rates_path) if rates_path else DEFAULT_RATES
        # ccy -> {(year, month): (end, avg)}
        self.monthly: dict[str, dict[tuple[int, int], tuple[float, float]]] = {}
        self.sources: dict[str, str] = {}
        self._load_csv(self.path)
        if fx_cache_dir is not None:
            self._load_ecb_cache(Path(fx_cache_dir))

    def _load_csv(self, path: Path) -> None:
        with open(path, newline="") as fh:
            rows = csv.DictReader(r for r in fh if r.strip() and not r.startswith("#"))
            for r in rows:
                y, m = int(r["month"][:4]), int(r["month"][5:7])
                self.monthly.setdefault(r["ccy"], {})[(y, m)] = (float(r["end"]), float(r["avg"]))
                self.sources[r["ccy"]] = r.get("source") or path.name

    def _load_ecb_cache(self, cache_dir: Path) -> None:
        f = cache_dir / "fx_per_usd.json"
        if not f.exists():
            return
        daily = json.loads(f.read_text())
        by: dict[str, dict[tuple[int, int], list]] = {}
        for d in sorted(daily):
            y, m = int(d[:4]), int(d[5:7])
            for ccy, v in daily[d].items():
                if ccy in self.monthly or ccy in PEGS_PER_USD:
                    continue
                by.setdefault(ccy, {}).setdefault((y, m), []).append(v)
        for ccy, months in by.items():
            self.monthly[ccy] = {k: (v[-1], sum(v) / len(v)) for k, v in months.items()}
            self.sources[ccy] = "ECB reference rates via om.fx cache"

    def covers(self, ccy: str) -> bool:
        return ccy in PEGS_PER_USD or ccy in self.monthly

    def _month(self, ccy: str, y: int, m: int):
        if ccy in PEGS_PER_USD:
            p = PEGS_PER_USD[ccy]
            return (p, p)
        return self.monthly.get(ccy, {}).get((y, m))

    def rate(self, ccy: str, day: date) -> float | None:
        """Period-end rate: the month-end rate of `day` if `day` is a month end, else the nearest prior month end."""
        y, m = day.year, day.month
        if day != month_end(y, m):
            y, m = _prev_month(y, m)
        row = self._month(ccy, y, m)
        return row[0] if row else None

    def average(self, ccy: str, start: date, end: date) -> float | None:
        """Average of the monthly averages weighted by the days of [start, end] in each month. None if a month is missing."""
        if end < start:
            return None
        tot = wsum = 0.0
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            lo, hi = max(start, date(y, m, 1)), min(end, month_end(y, m))
            days = (hi - lo).days + 1
            row = self._month(ccy, y, m)
            if row is None:
                return None
            tot += row[1] * days
            wsum += days
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return tot / wsum if wsum else None

    def devaluation_flags(self, ccy: str, start: date, end: date, threshold: float = 0.15) -> list[dict]:
        """Month-end to month-end moves in the window where the currency weakens against USD.

        pct_move = per-USD rate(m) / per-USD rate(m-1) - 1, i.e. how much more local currency one dollar buys.
        A flag is raised when pct_move >= threshold.
        """
        out: list[dict] = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            cur, py_m = self._month(ccy, y, m), _prev_month(y, m)
            prev = self._month(ccy, *py_m)
            if cur and prev and prev[0] > 0:
                move = cur[0] / prev[0] - 1
                if move >= threshold:
                    out.append({"flag": "devaluation", "ccy": ccy, "date": month_end(y, m),
                                "from_rate": prev[0], "to_rate": cur[0], "pct_move": move})
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return out


def fy_start(fy_end: date) -> date:
    """First day of the 12-month fiscal year ending on fy_end."""
    y, m = fy_end.year - 1, fy_end.month
    nxt = month_end(y, m) + timedelta(days=1)
    return nxt


def translate(statements, to_ccy: str, fx: IntlFX, threshold: float = 0.15):
    """Return a translated copy of an om.statements.Statements (or IntlStatements).

    Stocks (kind "i") at the period-end rate, flows (kind "d") at the average over the fiscal year, share counts
    unchanged, EPS at the average. A line with no rate stays None. Flags (also in `.warnings`) go to `.fx_flags`
    and, when present, `.basis_flags["fx_translation"]`.
    """
    src = statements.currency
    out = copy.copy(statements)
    out.data = {}
    out.warnings = list(statements.warnings)
    flags: list[dict] = []

    for i, fy_end in enumerate(statements.years):
        start = fy_start(fy_end)
        end_from, end_to = fx.rate(src, fy_end), fx.rate(to_ccy, fy_end)
        avg_from, avg_to = fx.average(src, start, fy_end), fx.average(to_ccy, start, fy_end)
        for f in fx.devaluation_flags(src, start, fy_end, threshold):
            f = dict(f, period_end=fy_end)
            flags.append(f)
            out.warnings.append(f"devaluation: {src} lost {f['pct_move']:.0%} vs USD in {f['date']:%b %Y} "
                                f"({f['from_rate']:.2f} to {f['to_rate']:.2f} per USD), FY ending {fy_end}")
        if None in (end_from, end_to, avg_from, avg_to):
            flags.append({"flag": "fx_rate_missing", "ccy": src if None in (end_from, avg_from) else to_ccy, "period_end": fy_end})
            out.warnings.append(f"fx_rate_missing for FY ending {fy_end}: lines left untranslated (None)")
    for key, items in statements.data.items():
        k = kind_of(key)
        new = []
        for i, it in enumerate(items):
            fy_end = statements.years[i]
            start = fy_start(fy_end)
            if k == "u":
                f = 1.0
            elif k == "i":
                a, b = fx.rate(src, fy_end), fx.rate(to_ccy, fy_end)
                f = b / a if a and b else None
            elif k == "d" or key in PER_SHARE_FLOW:
                a, b = fx.average(src, start, fy_end), fx.average(to_ccy, start, fy_end)
                f = b / a if a and b else None
            else:
                f = None
            c = copy.copy(it)
            c.value = None if it.value is None or f is None else it.value * f
            new.append(c)
        out.data[key] = new
    out.currency = to_ccy
    out.fx_flags = flags
    bf = getattr(out, "basis_flags", None)
    if isinstance(bf, dict):
        out.basis_flags = dict(bf, fx_translation=f"{src}->{to_ccy}: BS period-end, flows fiscal-year average")
    return out
