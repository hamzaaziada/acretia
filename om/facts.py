"""Turn SEC companyfacts JSON into point-in-time values: FY, LTM, and balance-sheet snapshots.

Rules (documented in METHODOLOGY.md):
- Periods are picked by their real start/end dates, never by the fy/fp labels.
- Several filings can report the same period. 'latest' = most recently filed (restated) value;
  'first' = as first reported. Under --as-of, only facts filed on or before that date are visible.
- FY: duration 350-380 days.  LTM at end E = FY_last + YTD(E) - YTD(E - 1 year); LTM = FY when the
  latest report is the annual one; LTM = FY (basis fy_only) when no interim exists.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from .concepts import DURATION, INSTANT, UNIT_KIND


@dataclass(frozen=True)
class Fact:
    val: float
    end: date
    start: date | None
    filed: date
    form: str
    accn: str
    concept: str
    taxonomy: str
    unit: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1 if self.start else 0

    def ref(self) -> dict:
        return {"concept": f"{self.taxonomy}:{self.concept}", "value": self.val, "unit": self.unit,
                "start": self.start.isoformat() if self.start else None, "end": self.end.isoformat(),
                "form": self.form, "accn": self.accn, "filed": self.filed.isoformat()}


@dataclass
class Value:
    """A derived number plus the facts it came from."""
    val: float | None
    basis: str = ""
    sources: list = field(default_factory=list)
    end: date | None = None

    def prov(self) -> dict:
        return {"basis": self.basis, "end": self.end.isoformat() if self.end else None,
                "facts": [f.ref() for f in self.sources]}


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


ANNUAL = (350, 380)
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT"}


class Company:
    def __init__(self, cf: dict, as_of: date | None = None, reporting_ccy: str | None = None):
        self.cik = int(cf.get("cik", 0))
        self.name = cf.get("entityName")
        self.as_of = as_of
        self.raw = cf.get("facts", {})
        self.ccy = reporting_ccy or self._detect_currency()
        self._cache: dict[str, dict] = {}

    # ------------------------------------------------------------ currency
    def _detect_currency(self) -> str:
        counts: Counter = Counter()
        for tax, concept in DURATION["revenue"] + DURATION["net_income"]:
            for unit, rows in self.raw.get(tax, {}).get(concept, {}).get("units", {}).items():
                if len(unit) == 3 and unit.isalpha() and unit.isupper():
                    counts[unit] += len(rows)
        return counts.most_common(1)[0][0] if counts else "USD"

    def _unit_ok(self, metric: str, unit: str) -> bool:
        kind = UNIT_KIND.get(metric, "money")
        if kind == "shares":
            return unit == "shares"
        if kind == "per_share":
            return unit == f"{self.ccy}/shares"
        return unit == self.ccy

    # ------------------------------------------------------------ fact selection
    def concepts_present(self, metric: str) -> list[tuple[str, str]]:
        chain = DURATION.get(metric) or INSTANT.get(metric)
        return [(t, c) for t, c in chain if c in self.raw.get(t, {})]

    def facts(self, metric: str, version: str = "latest", only: tuple[str, str] | None = None) -> dict:
        """period_key -> Fact. Duration key = (start, end); instant key = end."""
        ck = f"{metric}:{version}:{only}"
        if ck in self._cache:
            return self._cache[ck]
        chain = [only] if only else (DURATION.get(metric) or INSTANT.get(metric))
        is_duration = metric in DURATION
        out: dict = {}
        for tax, concept in chain:
            node = self.raw.get(tax, {}).get(concept)
            if not node:
                continue
            per_concept: dict = {}
            for unit, rows in node.get("units", {}).items():
                if not self._unit_ok(metric, unit):
                    continue
                for r in rows:
                    filed = _d(r.get("filed"))
                    if self.as_of and filed and filed > self.as_of:
                        continue
                    f = Fact(float(r["val"]), _d(r["end"]), _d(r.get("start")), filed, r.get("form", ""),
                             r.get("accn", ""), concept, tax, unit)
                    if is_duration and not f.start:
                        continue
                    key = (f.start, f.end) if is_duration else f.end
                    cur = per_concept.get(key)
                    if cur is None or (version == "latest" and f.filed > cur.filed) or \
                            (version == "first" and f.filed < cur.filed):
                        per_concept[key] = f
            for key, f in per_concept.items():
                out.setdefault(key, f)  # earlier concept in the chain wins for this period
        self._cache[ck] = out
        return out

    # ------------------------------------------------------------ periods
    def annuals(self, metric: str, only: tuple[str, str] | None = None) -> list[Fact]:
        fs = [f for (s, e), f in self.facts(metric, only=only).items() if ANNUAL[0] <= f.days <= ANNUAL[1]]
        return sorted(fs, key=lambda f: f.end)

    def fy(self, metric: str, offset: int = 0, anchor: date | None = None) -> Value:
        """offset 0 = latest fiscal year (ending on/before anchor), -1 = the year before."""
        ann = [f for f in self.annuals(metric) if anchor is None or f.end <= anchor]
        if len(ann) < 1 - offset:
            return Value(None, "missing")
        f = ann[offset - 1]
        return Value(f.val, "fy", [f], f.end)

    def latest_end(self) -> date | None:
        ends = [k[1] for m in ("revenue", "net_income") for k in self.facts(m)]
        return max(ends) if ends else None

    def ltm(self, metric: str, at: date | None = None) -> Value:
        """Prefer one tag across FY + YTD + prior YTD; mix tags only if no single tag covers all three."""
        at = at or self.latest_end()
        if at is None:
            return Value(None, "missing")
        fallback = None
        for only in self.concepts_present(metric):
            v = self._ltm(metric, at, only)
            if v.val is not None and v.basis not in ("fy_only",):
                return v
            if fallback is None and v.val is not None:
                fallback = v
        merged = self._ltm(metric, at, None)
        if merged.val is not None and merged.basis != "fy_only":
            merged.basis += "(mixed_tags)"
            return merged
        return fallback or merged

    def _ltm(self, metric: str, at: date, only) -> Value:
        facts = self.facts(metric, only=only)
        if not facts:
            return Value(None, "missing")
        ann = [f for f in self.annuals(metric, only) if f.end <= at + timedelta(days=3)]
        if not ann:
            return Value(None, "no_annual")
        fy_last = ann[-1]
        if abs((fy_last.end - at).days) <= 3:
            return Value(fy_last.val, "fy", [fy_last], fy_last.end)
        ytd_start = fy_last.end + timedelta(days=1)
        cur = _ytd(facts, ytd_start, at)
        if cur is None:
            return Value(fy_last.val, "fy_only", [fy_last], fy_last.end)
        # prior-year YTD: same window shifted back one fiscal year
        prev_fy = [f for f in ann if abs((f.end - (fy_last.end - timedelta(days=364))).days) <= 10]
        prior_start = (prev_fy[-1].end + timedelta(days=1)) if prev_fy else ytd_start - timedelta(days=364)
        prior = _ytd(facts, prior_start, at - timedelta(days=364), tol_end=10)
        if prior is None:
            return Value(fy_last.val, "fy_only", [fy_last], fy_last.end)
        basis = "fy+ytd-ytd_prior" if len(cur.sources) == 1 and len(prior.sources) == 1 else "fy+ytd-ytd_prior(quarter_sum)"
        return Value(fy_last.val + cur.val - prior.val, basis, [fy_last] + cur.sources + prior.sources, at)

    def ltm_prior_year(self, metric: str) -> Value:
        at = self.latest_end()
        if at is None:
            return Value(None, "missing")
        target = at - timedelta(days=364)
        ends = sorted({k[1] for k in self.facts(metric)}, key=lambda e: abs((e - target).days))
        if not ends or abs((ends[0] - target).days) > 10:
            return Value(None, "missing")
        return self.ltm(metric, ends[0])

    def balance_date(self) -> date | None:
        ends = list(self.facts("total_assets"))
        return max(ends) if ends else None

    def instant(self, metric: str, at: date | None = None) -> Value:
        facts = self.facts(metric)
        if not facts:
            return Value(None, "missing")
        if at is not None:
            f = facts.get(at)
            return Value(f.val, "balance_sheet", [f], f.end) if f else Value(None, "missing_at_date", end=at)
        end = max(facts)
        return Value(facts[end].val, "latest", [facts[end]], end)


QUARTER = (80, 100)


def _ytd(facts: dict, start: date, end: date, tol_end: int = 3) -> Value | None:
    """Year-to-date value for [start, end]: a single YTD fact, else a chain of contiguous quarters."""
    direct = _find(facts, end=end, start=start, tol_end=tol_end)
    if direct is not None:
        return Value(direct.val, "ytd", [direct], direct.end)
    quarters = sorted((f for f in facts.values() if QUARTER[0] <= f.days <= QUARTER[1]), key=lambda f: f.start)
    chain, cursor = [], start
    while True:
        nxt = next((q for q in quarters if abs((q.start - cursor).days) <= 7), None)
        if nxt is None:
            return None
        chain.append(nxt)
        if abs((nxt.end - end).days) <= tol_end:
            return Value(sum(q.val for q in chain), "quarter_sum", chain, nxt.end)
        if nxt.end > end + timedelta(days=tol_end):
            return None
        cursor = nxt.end + timedelta(days=1)


def _find(facts: dict, end: date, start: date, tol: int = 10, tol_end: int = 3):
    best = None
    for (s, e), f in facts.items():
        if abs((e - end).days) <= tol_end and abs((s - start).days) <= tol:
            if best is None or abs((s - start).days) < abs((best.start - start).days):
                best = f
    return best
