"""Market data for the comps builder (decision D-S4-01): a price is never invented.

Preferred: a real quote the caller supplies (om.prices.Quote / CsvPrices). Fallback: a public-float proxy computed
from the 10-K cover page, price = dei:EntityPublicFloat / dei:EntityCommonStockSharesOutstanding. The float excludes
shares held by affiliates and is measured at the end of the second fiscal quarter, so the proxy understates and lags
the market price; it is labelled as such in `source` and `basis`. No price at all returns None.
"""
from __future__ import annotations

from datetime import date

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"}


def _rows(cf: dict, concept: str, unit: str) -> list[dict]:
    node = (cf.get("facts") or {}).get("dei", {}).get(concept) or {}
    return [r for r in (node.get("units") or {}).get(unit, []) if r.get("val") is not None and r.get("end")]


def from_companyfacts(cf: dict) -> dict | None:
    """Public-float proxy from the latest 10-K cover: {"price", "as_of", "source", "basis": "public_float"} or None."""
    floats = [r for r in _rows(cf, "EntityPublicFloat", "USD") if r.get("form") in ANNUAL_FORMS and float(r["val"]) > 0]
    shares = [r for r in _rows(cf, "EntityCommonStockSharesOutstanding", "shares") if float(r["val"]) > 0]
    if not floats or not shares:
        return None
    fl = max(floats, key=lambda r: (r.get("filed") or "", r["end"]))
    same = [r for r in shares if r.get("accn") and r.get("accn") == fl.get("accn")]
    pool = same or [r for r in shares if r.get("form") in ANNUAL_FORMS] or shares
    latest = max(pool, key=lambda r: (r.get("filed") or "", r["end"]))
    # several share classes can sit on one cover (same accession and date): the cover total is their sum
    vals = {float(r["val"]) for r in pool if r.get("accn") == latest.get("accn") and r["end"] == latest["end"]}
    n = sum(vals)
    if n <= 0:
        return None
    try:
        as_of = date.fromisoformat(fl["end"]).isoformat()
    except ValueError:
        return None
    price = float(fl["val"]) / n
    src = (f"PROXY, not a quote: dei:EntityPublicFloat {float(fl['val']):,.0f} USD (as of {fl['end']}, {fl.get('form', '')} "
           f"filed {fl.get('filed', '')}, accn {fl.get('accn', '')}) / dei:EntityCommonStockSharesOutstanding {n:,.0f} shares "
           f"(cover date {latest['end']}, accn {latest.get('accn', '')}). Public float excludes affiliates' shares and is "
           "measured at mid-year, so this understates the market price; supply a real quote when you have one.")
    return {"price": price, "as_of": as_of, "source": src, "basis": "public_float"}


def from_quote(q) -> dict:
    """A real quote (om.prices.Quote). Price is per ordinary share (ADR ratio applied)."""
    per = q.ordinary_per_unit or 1.0
    return {"price": float(q.close) / per, "as_of": q.on.isoformat(),
            "source": f"quote {q.ticker} {q.close:,.4f} {q.currency} on {q.on.isoformat()} ({q.source})"
                      + (f", {per:g} ordinary shares per unit" if per != 1.0 else ""),
            "basis": "quote", "currency": q.currency}


def resolve(ticker: str, cf: dict, quotes=None) -> dict | None:
    """A supplied quote wins; else the public-float proxy; else None. `quotes`: a Quote, {ticker: Quote} or CsvPrices-like."""
    q = None
    if quotes is not None:
        if hasattr(quotes, "close") and hasattr(quotes, "on"):
            q = quotes
        elif isinstance(quotes, dict):
            q = quotes.get(ticker) or quotes.get(ticker.upper())
        elif hasattr(quotes, "get"):
            q = quotes.get(ticker)
    if q is not None and getattr(q, "close", None):
        return from_quote(q)
    return from_companyfacts(cf)
