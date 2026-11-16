"""SEC adapter (S2.5): edgartools (MIT) first, existing om.sec/om.statements as the fallback.

* Identity: `SEC_USER_AGENT` from the environment is mandatory; without it nothing runs (SEC fair-access policy).
* `company_facts(ticker)` -> SEC companyfacts JSON; `filings(ticker, form, n)` -> list of dicts;
  `financial_statements(ticker)` -> om.statements.Statements-based dict (same line items either way, so models
  do not change when the source does). edgartools supplies identity, throttling, CIK resolution and the HTTP
  layer; the XBRL line mapping stays in om.statements (deterministic, already graded)."""
from __future__ import annotations

import os
from pathlib import Path

from .base import Connector, ConnectorError, ConnectorItem, register

try:  # optional dependency, see D-018
    import edgar as _edgar
except Exception:  # ImportError or a broken install
    _edgar = None

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


class SecIdentityError(ConnectorError):
    pass


def identity(env=None) -> str:
    ua = (env if env is not None else os.environ).get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise SecIdentityError("SEC_USER_AGENT is not set; refusing to contact the SEC "
                               "(set it to '<name or org> <contact email>').")
    return ua


class SecAdapter:
    def __init__(self, prefer: str = "auto", edgar_module=None, om_client=None, cache_dir: str | Path = "data/raw/sec",
                 env=None):
        """prefer: 'auto' (edgartools if importable), 'edgartools', 'om'. edgar_module/om_client are test seams."""
        self.ua = identity(env)
        self._edgar = edgar_module if edgar_module is not None else _edgar
        if prefer == "edgartools" and self._edgar is None:
            raise ConnectorError("edgartools is not installed (pip install edgartools)")
        self.backend = "om" if (prefer == "om" or self._edgar is None) else "edgartools"
        self._om = om_client
        self._cache = Path(cache_dir)
        if self.backend == "edgartools":
            self._edgar.set_identity(self.ua)

    # ---------------------------------------------------------------- om fallback
    def _om_client(self):
        if self._om is None:
            from om.sec import SecClient
            self._om = SecClient(self.ua, self._cache)
        return self._om

    def _om_cik(self, ticker: str) -> int:
        t = ticker.upper().replace(".", "-")
        for row in self._om_client().tickers():
            if str(row.get("ticker", "")).upper() == t:
                return int(row["cik"])
        raise ConnectorError(f"unknown ticker {ticker!r}")

    # ---------------------------------------------------------------- public API
    def cik(self, ticker: str) -> int:
        if self.backend == "edgartools":
            return int(self._edgar.Company(ticker).cik)
        return self._om_cik(ticker)

    def company_facts(self, ticker: str) -> dict:
        cik = self.cik(ticker)
        if self.backend == "edgartools":
            dl = getattr(self._edgar, "download_json", None)
            if dl is None:
                from edgar.httprequests import download_json as dl  # edgartools' throttled, identity-aware client
            return dl(FACTS_URL.format(cik=cik))
        return self._om_client().companyfacts(cik)

    def filings(self, ticker: str, form: str = "10-K", n: int = 5) -> list[dict]:
        if self.backend == "edgartools":
            out = []
            for f in self._edgar.Company(ticker).get_filings(form=form)[:n]:
                out.append({"form": f.form, "filed": str(f.filing_date), "accession": f.accession_no,
                            "url": getattr(f, "filing_url", None) or "", "source": "edgartools"})
            return out
        sub = self._om_client().submissions(self._om_cik(ticker))
        r = sub.get("filings", {}).get("recent", {})
        cik = int(sub.get("cik", 0))
        out = []
        for i, f in enumerate(r.get("form", [])):
            if f == form:
                acc = r["accessionNumber"][i]
                doc = r.get("primaryDocument", [""] * (i + 1))[i]
                out.append({"form": f, "filed": r["filingDate"][i], "accession": acc, "source": "om.sec",
                            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"})
                if len(out) >= n:
                    break
        return out

    def financial_statements(self, ticker: str, years: int = 5) -> dict:
        from om import statements as stm
        s = stm.build(self.company_facts(ticker), ticker.upper(), years=years)
        return statements_to_dict(s, source=self.backend)


def statements_to_dict(s, source: str = "") -> dict:
    """om.statements.Statements -> plain dict {"years","data":{key:[$m or None]},...}; input for fintk."""
    return {"ticker": s.ticker, "name": s.name, "cik": s.cik, "currency": s.currency,
            "years": [d.isoformat() for d in s.years],
            "data": {k: [it.value for it in items] for k, items in s.data.items()},
            "filings": s.filings, "warnings": list(s.warnings), "financial_format": s.financial_format,
            "source": source}


_default: SecAdapter | None = None


def _adapter(**kw) -> SecAdapter:
    global _default
    if kw:
        return SecAdapter(**kw)
    if _default is None:
        _default = SecAdapter()
    return _default


def company_facts(ticker: str, **kw) -> dict:
    return _adapter(**kw).company_facts(ticker)


def filings(ticker: str, form: str = "10-K", n: int = 5, **kw) -> list[dict]:
    return _adapter(**kw).filings(ticker, form, n)


def financial_statements(ticker: str, **kw) -> dict:
    return _adapter(**kw).financial_statements(ticker)


@register("sec")
class SecConnector(Connector):
    """Lists recent filings for a ticker; fetch(accession-url) returns the filing document bytes via edgartools/om.sec."""
    name = "sec"

    def __init__(self, ticker: str, form: str = "10-K", n: int = 5, adapter: SecAdapter | None = None):
        self.ticker, self.form, self.n = ticker, form, n
        self.adapter = adapter or SecAdapter()
        self._by_id: dict = {}

    def list(self):
        for f in self.adapter.filings(self.ticker, self.form, self.n):
            self._by_id[f["accession"]] = f
            yield ConnectorItem(f["accession"], f"{self.ticker}-{f['form']}-{f['filed']}.htm", 0, f["accession"], f)

    def fetch(self, item_id: str):
        f = self._by_id.get(item_id)
        if not f or not f.get("url", "").startswith("https://www.sec.gov/"):
            raise ConnectorError(f"unknown filing {item_id!r} (call list() first)")
        if self.adapter.backend == "edgartools":
            dt = getattr(self._edgar, "download_text", None)
            if dt is None:
                from edgar.httprequests import download_text as dt
            body = dt(f["url"]).encode("utf-8")
        else:
            body = self.adapter._om_client().get_text(f["url"], f"harness/{item_id}").encode("utf-8")
        return body, {"name": f"{item_id}.htm", "source": "sec", **f}
