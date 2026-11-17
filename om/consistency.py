"""Inconsistency checker: every number in a deck, spreadsheet or document becomes a *fact*
(metric, company, period, value, displayed precision, where it came from), then the facts are checked.

Checks
  conflict    the same metric for the same company and period shows different values
              (across slides, or across documents in a data room)
  aggregate   a Total / Median / Mean / High / Low row doesn't match the rows above it
  math        stated margins and growth rates don't follow from the stated amounts
  source      a deck number doesn't match the company's SEC filings (LTM or fiscal year)
  units       one metric shown in different units across a deck ($m on one slide, $bn on another)

Precision rules, so it doesn't cry wolf: values are compared at the precision they're displayed
(84.2 vs 84.23 is fine), different periods are never compared, numbers with no clear metric are
ignored, and "% of revenue", "top 10", increments ("add $6m") and dates are skipped.
"""
from __future__ import annotations

import io
import re
import statistics
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# --------------------------------------------------------------------------- metrics
# (canonical, kind, pattern) — phrases before their sub-phrases: the first alternative that matches at a position wins
METRICS = [
    ("adj_ebitda_margin", "pct", r"adj(?:usted|\.)?\s+ebitda\s+margins?"),
    ("ebitda_margin", "pct", r"ebitda\s+margins?"),
    ("gross_margin", "pct", r"gross\s+margins?"),
    ("ebit_margin", "pct", r"(?:ebit|operating)\s+margins?"),
    ("net_margin", "pct", r"net\s+(?:income\s+)?margins?"),
    ("fcf_margin", "pct", r"(?:fcf|free\s+cash\s+flow)\s+margins?"),
    ("adj_ebitda_growth", "pct", r"adj(?:usted|\.)?\s+ebitda\s+growth"),
    ("ebitda_growth", "pct", r"ebitda\s+growth"),
    ("revenue_growth", "pct", r"(?:revenue|sales|top[- ]line)\s+growth|growth\s+in\s+(?:revenue|sales)"),
    ("nrr", "pct", r"net\s+(?:revenue|dollar)\s+retention|\bnrr\b|\bndr\b"),
    ("grr", "pct", r"gross\s+(?:revenue\s+|dollar\s+)?retention|\bgrr\b"),
    ("ev_revenue", "mult", r"ev\s*/\s*(?:ltm\s+|ntm\s+)?(?:revenue|sales)|ev\s+to\s+(?:revenue|sales)"),
    ("ev_ebitda", "mult", r"ev\s*/\s*(?:ltm\s+|ntm\s+)?ebitda|ev\s+to\s+ebitda"),
    ("pe", "mult", r"\bp\s*/\s*e\b|price\s*/\s*earnings|price[- ]to[- ]earnings"),
    ("adj_ebitda", "money", r"adj(?:usted|\.)?\s+ebitda"),
    ("ebitda", "money", r"\bebitda\b"),
    ("ebit", "money", r"\bebit\b|operating\s+income|operating\s+profit"),
    ("gross_profit", "money", r"gross\s+profit"),
    ("net_income", "money", r"net\s+income|net\s+profit|net\s+earnings"),
    ("eps", "money", r"\beps\b|earnings\s+per\s+share"),
    ("ocf", "money", r"operating\s+cash\s+flows?|\bocf\b|cash\s+(?:flow\s+)?from\s+operations"),
    ("fcf", "money", r"\bfcf\b|free\s+cash\s+flows?"),
    ("capex", "money", r"\bcapex\b|capital\s+expenditures?"),
    ("arr", "money", r"\barr\b|annual(?:ized)?\s+recurring\s+revenue"),
    ("revenue", "money", r"\brevenues?\b|net\s+sales|\bsales\b|\bturnover\b|top[- ]line"),
    ("net_debt", "money", r"net\s+debt"),
    ("debt", "money", r"total\s+debt|\bdebt\b|\bborrowings\b"),
    ("cash", "money", r"\bcash\b(?!\s+flow)(?:\s+(?:and|&)\s+(?:cash\s+)?equivalents)?"),
    ("ev", "money", r"enterprise\s+value|\bev\b(?!\s*/)"),
    ("equity_value", "money", r"equity\s+value|market\s+cap(?:italization)?"),
    ("customers", "count", r"\bcustomers\b|\bclients\b|\blogos\b"),
    ("employees", "count", r"\bemployees\b|\bheadcount\b|\bftes?\b"),
    ("wacc", "pct", r"\bwacc\b"),
    ("~growth", "pct", r"\bgrowth\b|\bgrower\b|\bgrew\b|\bgrowing\b|\byoy\b|year[- ]over[- ]year|\bup\b"),
    ("~margin", "pct", r"\bmargins?\b"),
]
KIND = {m: k for m, k, _ in METRICS}
METRIC_RE = re.compile("|".join(f"(?P<m{i}>{p})" for i, (_, _, p) in enumerate(METRICS)), re.I)
MARGIN_OF = {"ebitda": "ebitda_margin", "adj_ebitda": "adj_ebitda_margin", "gross_profit": "gross_margin", "ebit": "ebit_margin",
             "net_income": "net_margin", "fcf": "fcf_margin"}
GROWTH_OF = {"revenue": "revenue_growth", "ebitda": "ebitda_growth", "adj_ebitda": "adj_ebitda_growth", "arr": "arr_growth"}
for _m in ("arr_growth",):
    KIND[_m] = "pct"
POINT_IN_TIME = {"customers", "employees", "arr", "nrr", "grr", "cash", "debt", "net_debt", "ev", "equity_value", "wacc"}
LABEL = {"revenue": "Revenue", "revenue_growth": "Revenue growth", "gross_margin": "Gross margin", "ebitda": "EBITDA",
         "ebitda_margin": "EBITDA margin", "adj_ebitda": "Adjusted EBITDA", "adj_ebitda_margin": "Adjusted EBITDA margin",
         "ebit": "EBIT", "ebit_margin": "EBIT margin", "net_income": "Net income", "net_margin": "Net margin", "fcf": "Free cash flow",
         "fcf_margin": "FCF margin", "capex": "Capex", "arr": "ARR", "nrr": "Net revenue retention", "grr": "Gross retention",
         "customers": "Customers", "employees": "Employees", "ev": "Enterprise value", "equity_value": "Equity value",
         "ev_revenue": "EV / Revenue", "ev_ebitda": "EV / EBITDA", "pe": "P / E", "eps": "EPS", "cash": "Cash", "debt": "Debt",
         "net_debt": "Net debt", "gross_profit": "Gross profit", "wacc": "WACC", "ebitda_growth": "EBITDA growth",
         "adj_ebitda_growth": "Adj. EBITDA growth", "arr_growth": "ARR growth", "ocf": "Operating cash flow"}


def metric_mentions(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in METRIC_RE.finditer(text):
        i = int(next(k for k, v in m.groupdict().items() if v is not None)[1:])
        out.append((m.start(), m.end(), METRICS[i][0]))
    return out


LABEL_FILLER = {"total", "reported", "consolidated", "group", "company", "annual", "full", "year", "full-year", "in", "m", "bn", "mm",
                "k", "usd", "eur", "gbp", "millions", "billions", "thousands", "us", "of", "the", "and", "a", "x", "yoy", "y", "o"}


def canon_metric(label: str) -> str | None:
    """A table header / row label -> canonical metric, only when the label is essentially that metric."""
    ms = [x for x in metric_mentions(label) if not x[2].startswith("~")]
    if not ms:
        return None
    s, e, m = ms[0]
    if len(ms) > 1 and ms[1][2] != m:
        # "EBITDA margin" is one mention; "Revenue / EBITDA" is two different metrics -> ambiguous
        return None
    rest = label[:s] + " " + label[e:]
    rest = re.sub(r"\([^)]*\)", " ", rest)                       # ($m), (%), (FY2025)
    rest = PERIOD_TOKENS.sub(" ", rest)
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]*", rest.lower()) if w not in LABEL_FILLER]
    if words:
        return None                                              # "Long-term debt", "Debt and leases", "Revenue per store"
    return m


# --------------------------------------------------------------------------- periods
MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
PERIOD_RES = [
    (re.compile(r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b"), lambda m: (f"{m.group(1)}-{m.group(2)}-{m.group(3)}", False)),
    (re.compile(r"\b(\d{1,2})\s+" + MONTHS + r"\s+((?:19|20)\d{2})\b", re.I), lambda m: (_date(m.group(0)), False)),
    (re.compile(r"\b" + MONTHS + r"\s+(\d{1,2}),?\s+((?:19|20)\d{2})\b", re.I), lambda m: (_date(m.group(0)), False)),
    (re.compile(r"\b(?:ltm|ttm|last\s+twelve\s+months)\b", re.I), lambda m: ("LTM", False)),
    (re.compile(r"\bntm\b", re.I), lambda m: ("NTM", True)),
    (re.compile(r"\bq([1-4])\s*(?:fy|cy)?\s*'?((?:19|20)?\d{2})\b", re.I), lambda m: (f"Q{m.group(1)} {_yr(m.group(2))}", False)),
    (re.compile(r"\b([1-4])q\s*'?((?:19|20)?\d{2})\b", re.I), lambda m: (f"Q{m.group(1)} {_yr(m.group(2))}", False)),
    (re.compile(r"\b(h[12])\s*'?((?:19|20)?\d{2})\b", re.I), lambda m: (f"{m.group(1).upper()} {_yr(m.group(2))}", False)),
    (re.compile(r"\b(?:fy|cy|fiscal(?:\s+year)?)\s*'?((?:19|20)?\d{2})\s*([ae])?\b", re.I),
     lambda m: (f"FY{_yr(m.group(1))}", (m.group(2) or "").lower() == "e")),
    (re.compile(r"\b((?:19|20)\d{2})\s*([ae])\b", re.I), lambda m: (f"FY{m.group(1)}", m.group(2).lower() == "e")),
    (re.compile(r"\bfy\s*-\s*([12])\b", re.I), lambda m: (f"FY-{m.group(1)}", False)),
    (re.compile(r"\bfy\b(?!\s*[-\d'])", re.I), lambda m: ("FY", False)),
    (re.compile(r"(?<![\d.,$])\b((?:19|20)\d{2})\b(?![\d.,]*\s*(?:%|x\b|million|billion|bn\b|m\b))", re.I), lambda m: (f"FY{m.group(1)}", False)),
]
PROJECTION = re.compile(r"\b(?:intention|intends?|planned|target(?:s|ed)?|forecasts?|projected|projections?|expects?|expected|budget(?:ed)?|guidance|plan(?:ned)?|"
                        r"outlook|estimated?|pro\s+forma)\b", re.I)


def _date(text: str) -> str:
    import datetime as _dt
    t = re.sub(r",", "", text.strip())
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y", "%d %b. %Y", "%b. %d %Y"):
        try:
            return _dt.datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    return t


def _yr(y: str) -> str:
    return y if len(y) == 4 else f"20{y}"


def find_periods(text: str) -> list[tuple[int, int, str, bool]]:
    taken, out = [], []
    for rx, fn in PERIOD_RES:
        for m in rx.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            if rx is PERIOD_RES[-1][0] and re.search(MONTHS + r"\s+\d{1,2},?\s*$", text[:m.start()], re.I):
                continue            # "March 31, 2027" is a date, not a fiscal year
            p, proj = fn(m)
            taken.append((m.start(), m.end()))
            out.append((m.start(), m.end(), p, proj))
    return sorted(out)


def canon_period(label: str) -> tuple[str | None, bool]:
    ps = find_periods(label)
    proj = bool(PROJECTION.search(label)) or any(x[3] for x in ps)
    return (ps[0][2] if ps else None), proj


# --------------------------------------------------------------------------- numbers
SCALE_WORDS = {"k": 1e3, "thousand": 1e3, "thousands": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6, "millions": 1e6,
               "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9, "t": 1e12, "tn": 1e12, "trillion": 1e12}
NUM_RE = re.compile(
    r"(?<![\w.$€£])(?P<neg>\(|-|−|–)?\s?(?P<cur>US\$|\$|€|£|USD\s?|EUR\s?|GBP\s?)?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?\)?"
    r"(?:\s?(?P<unit>%|x(?![a-z])|×|bn\b|billions?\b|b\b|mm\b|mn\b|m\b|millions?\b|k\b|thousands?\b|tn\b|trillions?\b))?\)?(?![\d-]*[A-Za-z]{1,2}\d)",
    re.I)
HEADER_SCALE = re.compile(r"\(\s*(?:in\s+)?(?P<cur>\$|€|£|us\$|usd|eur|gbp)?\s*(?:in\s+)?(?P<sc>k|000s|thousands?|m|mm|mn|millions?|b|bn|billions?)?\s*(?P<pct>%)?\s*\)"
                          r"|\b(?P<cur2>\$|€|£)\s*(?P<sc2>k|m|mm|bn|b)\b|\bin\s+(?P<sc3>thousands|millions|billions)\b", re.I)
EMPTY = re.compile(r"^\s*(?:n/?a|nm|n\.m\.|—|–|-|\s*)\s*$", re.I)


@dataclass
class Num:
    value: float          # as written (before scale)
    decimals: int
    kind: str | None      # money | pct | mult | None (bare)
    scale: float          # 1, 1e3, 1e6, 1e9
    raw: str
    start: int = 0
    end: int = 0


FOOTNOTE_MARK = re.compile(r"(\d(?:[.,]\d+)?\s?(?:%|x|bn|B|M|m|k|million|billion))([1-9])(?=[\s,.;:)]|$)")


def parse_numbers(text: str, accounting: bool = True) -> list[Num]:
    """accounting=True: (1,234) is negative (tables). In prose, brackets are asides: "(66.4%)"."""
    text = FOOTNOTE_MARK.sub(lambda m: m.group(1) + " ", text)   # "$9.38B1" (footnote 1) -> "$9.38B " (same length)
    out = []
    for m in NUM_RE.finditer(text):
        ip, dp, unit, cur = m.group("int"), m.group("dec") or "", (m.group("unit") or "").lower(), m.group("cur")
        v = float(ip.replace(",", "") + dp)
        neg = m.group("neg")
        if neg == "(" and (not accounting or not m.group(0).rstrip().endswith(")")):
            neg = None
        if neg:
            v = -v
        kind = "pct" if unit == "%" else "mult" if unit in ("x", "×") else "money" if cur else None
        scale = SCALE_WORDS.get(unit, 1.0) if unit not in ("%", "x", "×") else 1.0
        if unit in ("b", "m", "k", "t") and not cur:
            scale = 1.0 if unit == "b" else scale     # a bare "b" is too ambiguous without a currency
        raw = m.group(0).strip()
        if not neg and raw.startswith("(") != raw.endswith(")"):
            raw = raw.strip("()")
        out.append(Num(v, len(dp) - 1 if dp else 0, kind, scale, raw, m.start(), m.end()))
    return out


def header_scale(label: str) -> tuple[str | None, float | None]:
    """'Revenue LTM ($m)' -> ('money', 1e6); 'Gross margin (%)' -> ('pct', None)."""
    m = HEADER_SCALE.search(label or "")
    if not m:
        return (None, None)
    if m.group("pct"):
        return ("pct", None)
    sc = (m.group("sc") or m.group("sc2") or m.group("sc3") or "").lower()
    cur = m.group("cur") or m.group("cur2")
    scale = {"k": 1e3, "000s": 1e3, "thousand": 1e3, "thousands": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6,
             "millions": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9}.get(sc)
    if cur or scale:
        return ("money", scale or 1.0)
    return (None, None)


def scale_label(kind: str, scale: float) -> str:
    if kind == "pct":
        return "%"
    if kind == "mult":
        return "x"
    if kind == "money":
        return {1e3: "$k", 1e6: "$m", 1e9: "$bn", 1e12: "$tn"}.get(scale, "$")
    return ""


# --------------------------------------------------------------------------- entities
SUFFIX = re.compile(r"\b(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|lp|holdings?|group|n\s?v|s\s?a|ag|se|the|class\s+[ab])\b")
SUMMARY = {"median": "__median__", "peer median": "__median__", "mean": "__mean__", "average": "__mean__", "peer average": "__mean__",
           "peer mean": "__mean__", "total": "__total__", "sum": "__total__", "high": "__max__", "max": "__max__", "maximum": "__max__",
           "low": "__min__", "min": "__min__", "minimum": "__min__"}

TEXT_SUMMARY = {"median": "__median__", "peer median": "__median__", "peer average": "__mean__", "peer mean": "__mean__",
                "average of the peers": "__mean__"}


def norm_entity(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " "))
    s = SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


class Entities:
    """Aliases (names, tickers) -> one key per company; summary rows map to __median__ etc."""

    def __init__(self):
        self.alias: dict[str, str] = {}
        self.ticker: dict[str, str] = {}      # key -> ticker
        self.display: dict[str, str] = {}

    def add(self, name: str, ticker: str | None = None) -> str:
        key = self.resolve(name) or self.resolve(ticker or "") or norm_entity(name) or (ticker or "").upper()
        if not key:
            return ""
        self.display.setdefault(key, name.strip() or ticker)
        if norm_entity(name):
            self.alias[norm_entity(name)] = key
        if ticker and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", ticker.strip()):
            self.alias[ticker.strip().upper()] = key
            self.ticker[key] = ticker.strip().upper()
        return key

    def resolve(self, label: str) -> str | None:
        if not label:
            return None
        lab = label.strip()
        low = re.sub(r"\s+", " ", lab.lower()).strip(" :")
        if low in SUMMARY:
            return SUMMARY[low]
        if lab.upper() in self.alias and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", lab):
            return self.alias[lab.upper()]
        return self.alias.get(norm_entity(lab))

    def find_in(self, text: str) -> list[tuple[int, str]]:
        """Entity mentions in free text: (position, key)."""
        out = []
        low = text.lower()
        for k, v in TEXT_SUMMARY.items():
            for m in re.finditer(rf"\b{re.escape(k)}\b", low):
                out.append((m.start(), v))
        for alias, key in self.alias.items():
            if alias.isupper():
                for m in re.finditer(rf"\b{re.escape(alias)}\b", text):
                    out.append((m.start(), key))
            elif len(alias) >= 3:
                for m in re.finditer(rf"\b{re.escape(alias)}\b", re.sub(r"[^a-z0-9 ]", " ", low)):
                    out.append((m.start(), key))
        return sorted(out)


# --------------------------------------------------------------------------- facts
@dataclass
class Fact:
    metric: str
    kind: str
    value: float              # normalized: dollars, percent points, x, count
    ulp: float                # displayed precision in normalized units
    raw: str                  # as displayed
    entity: str | None
    period: str | None
    projection: bool
    source: str               # document label
    where: str                # human location
    quote: str
    origin: str               # table | chart | text | sheet | model
    unit: str = ""            # $m, $bn, %, x
    slide: int | None = None
    page: int | None = None
    doc_id: int | None = None
    period_inferred: bool = False

    def lo(self):
        return self.value - self.ulp / 2

    def hi(self):
        return self.value + self.ulp / 2


def _ulp(decimals: int, scale: float) -> float:
    return 10 ** (-decimals) * scale


def make_fact(num: Num, metric: str, *, kind_hint: str | None, scale_hint: float | None, **kw) -> Fact | None:
    mkind = KIND.get(metric)
    kind = num.kind or kind_hint or mkind
    if mkind and kind != mkind and not (mkind == "count" and kind is None):
        return None                       # "41% of revenue" is not revenue
    kind = mkind or kind
    scale = num.scale if num.scale != 1.0 else (scale_hint or 1.0)
    if kind == "money" and num.kind != "money" and not scale_hint and num.scale == 1.0 and metric != "eps":
        return None                       # bare "84" next to "revenue": unit unknown
    if kind == "count":
        scale = num.scale
    if kind == "pct" and num.kind is None and scale_hint is None and kind_hint != "pct" and abs(num.value) <= 1.5 and num.decimals >= 2:
        num = Num(num.value * 100, max(num.decimals - 2, 0), "pct", 1.0, num.raw)   # 0.78 stored as a fraction
    return Fact(metric=metric, kind=kind, value=num.value * scale, ulp=_ulp(num.decimals, scale), raw=num.raw,
                unit=scale_label(kind, scale), **kw)


# --------------------------------------------------------------------------- text facts
SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\"“])|\n+")
CLAUSE_SPLIT = re.compile(r",\s+|;\s+|\s+(?:vs\.?|versus|compared\s+(?:with|to)|while|whereas)\s+", re.I)
SKIP_BEFORE = re.compile(r"(?:\btop|\bbottom|#|\bno\.|\bitem|\bnote|\bpage|\bp\.|\bsection|\bstep|\bphase|\btier|\bclass|\bseries)\s*$", re.I)
INCREMENT_BEFORE = re.compile(r"\b(?:add(?:s|ed|ing)?|additional|incremental|extra|another|(?:increase|decrease|grow|grew|rise|rose|fell|decline)[a-z]*\s+(?:by|of))\s*(?:about|approximately|~|c\.)?\s*$", re.I)
SCENARIO = re.compile(r"\b(?:leaves?|leaving|left\s+with|would|could|after\s+(?:the|a|an)\b|pro\s+forma|remaining|falls?\s+to|rises?\s+to|"
                      r"drops?\s+to|reduces?\s+(?:cash\s+)?to|below|above|if\b|scenario|case\b|option)", re.I)
BALANCES = {"cash", "debt", "net_debt"}
SCENARIO_COL = re.compile(r"\b(?:pre|post|pro\s+forma|case|scenario|option|downside|upside|base|bull|bear|sensitivity|illustrative)\b", re.I)
BALANCE_QUAL = re.compile(r"\b(?:clos(?:e|es|ing)|ending|end|opening|starting|beginning|pro\s+forma|post|pre|residual|remaining|"
                          r"path|paced|pace|minimum|buffer|floor)\b", re.I)
AFTER_LINK = re.compile(r"^\s*(?:of\s+|in\s+)?(?:(?:the|its|our|total|annual|annualized|reported|adjusted|net|gross|group|company)\s+)*$", re.I)
BEFORE_LINK = re.compile(r"^\s*(?:\(\s*)?(?:(?:was|were|is|are|of|at|to|by|:|=|–|—|-|totall?ed|totaling|totalling|reached|stood\s+at|came\s+in\s+at|"
                         r"rose|fell|grew|increased|decreased|declined|amounted|amounting|equal(?:s|led)?|reported|reports|"
                         r"would\s+be|will\s+be|of\s+about|approximately|about|roughly|around|nearly|almost|over|under|"
                         r"an?|the|just|only|some|c\.|~)\s*)*$", re.I)
PERIOD_TOKENS = re.compile(r"\b(?:ltm|ttm|ntm|fy\s*'?\d{2,4}[ae]?|fiscal(?:\s+year)?\s+\d{2,4}|cy\s*\d{2,4}|q[1-4]\s*(?:fy)?\s*'?\d{2,4}|[1-4]q\s*'?\d{2,4}|h[12]\s*'?\d{2,4}|"
                           r"(?:19|20)\d{2}[ae]?|in|for|during)\b", re.I)


def _strip_periods(gap: str) -> str:
    return PERIOD_TOKENS.sub(" ", gap)


PARTIAL_BEFORE = re.compile(r"\b(?:months?|weeks?|days?|quarters?|half|portion|part|share|fraction|multiple|percent|%|times)\s+of\s+(?:the\s+|its\s+|our\s+)?"
                            r"(?:fy\s*'?\d{2,4}\s+|fiscal\s+\d{4}\s+)?$", re.I)
MODIFIER_BEFORE = re.compile(r"\b(?:after|before|less|excluding|ex|net\s+of|minus|plus|including|vs\.?|versus|against|over|covers?|"
                             r"covering|above|below|than|exceeds?|funds?|funding)\s+(?:the\s+|its\s+|our\s+)?(?:fy\s*'?\d{2,4}\s+)?$", re.I)
POLICY_AFTER = re.compile(r"^\s*(?:buffer|floor|minimum|requirement|target|cushion|headroom|threshold|hurdle|covenant|limit|ceiling|"
                          r"per\s+(?:share|store|warehouse|unit|customer)|margin)\b", re.I)
SHARE_AFTER = re.compile(r"^\s*(?:%\s*)?(?:of\s+(?:total\s+|our\s+|its\s+|net\s+)?(?:revenue|sales|customers|total|the)|share)\b", re.I)


def text_facts(text: str, ents: Entities | None, *, source: str, where: str, origin: str = "text", slide=None, page=None,
               doc_id=None, default_entity: str | None = None, carry_period: str | None = None,
               carry: bool = True) -> tuple[list[Fact], str | None]:
    """Facts from prose. Returns (facts, last period seen) so a following passage can inherit the period."""
    facts = []
    last_period = carry_period
    for sent in SENT_SPLIT.split(text):
        sent = sent.strip()
        if not sent or not re.search(r"\d", sent):
            ps = find_periods(sent)
            if ps and carry:
                last_period = ps[-1][2]
            continue
        sent_periods = find_periods(sent)
        sent_proj = bool(PROJECTION.search(sent)) or any(p[3] for p in sent_periods)
        mentions = metric_mentions(sent)
        ent_mentions = ents.find_in(sent) if ents else []
        nums = parse_numbers(sent, accounting=False)
        # clause boundaries
        bounds, pos = [], 0
        for m in CLAUSE_SPLIT.finditer(sent):
            bounds.append((pos, m.start()))
            pos = m.end()
        bounds.append((pos, len(sent)))
        inherited = False
        used: set = set()
        prev_fact = None
        for n in nums:
            if any(ps <= n.start < pe for ps, pe, _, _ in sent_periods):
                continue                                             # part of "FY2025"
            if re.fullmatch(r"(?:19|20)\d{2}", n.raw) and n.kind is None:
                continue
            before, after = sent[:n.start], sent[n.end:]
            if SKIP_BEFORE.search(before) or SHARE_AFTER.match(after) or re.search(MONTHS + r"\s*$", before, re.I):
                continue
            cs, ce = next(((a, b) for a, b in bounds if a <= n.start < b), (0, len(sent)))
            # metric must sit next to the number: "412 customers", "$6.43B of capex", "free cash flow was $9.39B",
            # "capex of $6.43B", "a margin of 22%", "up 31%". Period words between them are allowed.
            m_after = [x for x in mentions if x[0] >= n.end and AFTER_LINK.match(_strip_periods(sent[n.end:x[0]])) and not x[2].startswith("~")]
            m_before = [x for x in mentions if x[1] <= n.start and x[0] >= cs and BEFORE_LINK.match(_strip_periods(sent[x[1]:n.start]))]
            cand = m_after[:1] or m_before[-1:]
            if cand and (cand[0] in used or PARTIAL_BEFORE.search(sent[:cand[0][0]]) or POLICY_AFTER.match(sent[cand[0][1]:])
                         or (cand[0] in m_before and MODIFIER_BEFORE.search(sent[:cand[0][0]]))):
                cand = []
            metric = cand[0][2] if cand else None
            if cand:
                used.add(cand[0])
            if metric is None and prev_fact is not None and ent_mentions:
                # "83.4% LTM vs. a peer median of 17.9%", "66.4%; peer median 59.4%": a comparison inherits the metric
                between = [e for p_, e in ent_mentions if prev_fact[1] <= p_ < n.start]
                if between and between[-1] != prev_fact[0].entity:
                    metric = prev_fact[0].metric
            if metric is None:
                continue
            if metric.startswith("~"):
                prev = [x[2] for x in mentions if x[0] < n.start and not x[2].startswith("~") and KIND.get(x[2]) == "money"]
                near = [x[2] for x in mentions if x[1] <= n.start and not x[2].startswith("~")]   # whole sentence: "revenue was $84m, up 31%"
                if metric == "~margin":
                    metric = MARGIN_OF.get(near[-1]) if near else None
                else:
                    word = sent[cand[0][0]:cand[0][1]].lower() if cand else ""
                    metric = ((GROWTH_OF.get(near[-1]) or f"{near[-1]}_growth") if near and KIND.get(near[-1]) in ("money", "count")
                              else "revenue_growth" if not near and word in ("grower", "growth") else None)
                    if n.kind != "pct" or re.search(r"\b(?:a\s+year|per\s+year|annually|cagr|compound)\b", sent[n.end:n.end + 40], re.I):
                        metric = None                                # CAGRs over several years are a different measure
                    if metric:
                        KIND.setdefault(metric, "pct")
                if not metric:
                    continue
            if INCREMENT_BEFORE.search(before) and KIND.get(metric) in ("money", "count"):
                continue
            if metric in BALANCES and (SCENARIO.search(sent) or BALANCE_QUAL.search(sent[max(cs, n.start - 30):n.start])
                                       or not any(cs <= p[0] < ce for p in sent_periods)):
                continue                       # undated or scenario balances ("leaves $15.5B of cash", "closing cash on the paced path")
            # period: in the clause, else in the sentence, else carried from the previous sentence
            usable = [p for p in sent_periods if metric in POINT_IN_TIME or not re.match(r"\d{4}-\d{2}-\d{2}$", p[2])]
            cp = [p for p in usable if cs <= p[0] < ce]
            period = (min(cp, key=lambda p: abs(p[0] - n.start))[2] if cp else
                      min(usable, key=lambda p: abs(p[0] - n.start))[2] if usable else
                      (last_period if not sent_periods else None))
            if period and re.match(r"\d{4}-\d{2}-\d{2}$", period) and metric not in POINT_IN_TIME:
                period = None
            inferred = not cp and not usable and period is not None
            # entity: nearest mention before the number (in the sentence), else the default
            eb = [e for p, e in ent_mentions if p < n.start]
            entity = eb[-1] if eb else (ent_mentions[0][1] if ent_mentions else default_entity)
            f = make_fact(n, metric, kind_hint=None, scale_hint=None, entity=entity, period=period, projection=sent_proj,
                          source=source, where=where, quote=sent[:300], origin=origin, slide=slide, page=page, doc_id=doc_id,
                          period_inferred=inferred)
            if f:
                if prev_fact is not None and f.metric == prev_fact[0].metric and f.period is None and prev_fact[0].period:
                    f.period = prev_fact[0].period
                facts.append(f)
                prev_fact = (f, n.end)
                inherited = inherited or inferred
        if sent_periods and carry:
            last_period = sent_periods[-1][2]
        elif not carry:
            last_period = None
    return facts, last_period


# --------------------------------------------------------------------------- table facts
def table_facts(rows: list[list[str]], ents: Entities | None, *, source: str, where: str, origin: str = "table", slide=None,
                page=None, doc_id=None, default_entity: str | None = None, table_ref: dict | None = None,
                default_scale: float | None = None) -> list[Fact]:
    """rows[0] is the header. Works for both layouts: companies down the side (comps) or metrics down the side (P&L)."""
    rows = [[(c or "").strip() for c in r] for r in rows if any((c or "").strip() for c in r)]
    if len(rows) < 2:
        return []
    # find the header: the first row with 2+ period labels (P&L layout) or the first row (comps layout)
    hdr_i = next((i for i, r in enumerate(rows[:6]) if sum(1 for c in r[1:] if canon_period(c)[0]) >= 2), 0)
    header, body = rows[hdr_i], rows[hdr_i + 1:]
    labels = [r[0] for r in body]
    period_cols = sum(1 for c in header[1:] if canon_period(c)[0])
    metric_rows = period_cols >= 2 or sum(1 for lab in labels if canon_metric(lab)) >= max(1, len(labels) / 2)
    facts: list[Fact] = []
    if table_ref is not None:
        table_ref.update(header=header, body=body, metric_rows=metric_rows)
    if metric_rows:
        for r in body:
            metric = canon_metric(r[0])
            if not metric:
                continue
            kh, sh = header_scale(r[0])
            if sh is None and KIND.get(metric) == "money" and default_scale:
                sh = default_scale
            for j, cell in enumerate(r[1:], start=1):
                if j >= len(header) or EMPTY.match(cell):
                    continue
                period, proj = canon_period(header[j])
                if SCENARIO_COL.search(header[j]):
                    continue                  # pre-/post-transaction, case and option columns are not reported figures
                if period is None and sum(1 for c in header[1:] if c) > 1:
                    continue                  # an unlabelled column in a multi-period table: skip
                nums = parse_numbers(cell)
                if len(nums) != 1:
                    continue
                f = make_fact(nums[0], metric, kind_hint=kh, scale_hint=sh, entity=default_entity, period=period, projection=proj,
                              source=source, where=f"{where} · {r[0]} × {header[j] or 'value'}", quote=f"{r[0]}: {cell}",
                              origin=origin, slide=slide, page=page, doc_id=doc_id)
                if f:
                    facts.append(f)
        return facts
    # companies (or other entities) down the side, metrics across the top
    tick_col = next((j for j, h in enumerate(header) if re.fullmatch(r"\s*(?:ticker|symbol)\s*", h, re.I)), None)
    for r in body:
        name = r[0]
        if not name:
            continue
        tick = r[tick_col] if tick_col is not None and tick_col < len(r) else None
        key = ents.resolve(name) if ents else None
        if key is None and ents is not None:
            key = ents.add(name, tick)
        for j, h in enumerate(header):
            if j == 0 or j == tick_col or j >= len(r) or EMPTY.match(r[j]):
                continue
            metric = canon_metric(h)
            if not metric:
                continue
            period, proj = canon_period(h)
            kh, sh = header_scale(h)
            nums = parse_numbers(r[j])
            if len(nums) != 1:
                continue
            f = make_fact(nums[0], metric, kind_hint=kh, scale_hint=sh, entity=key, period=period, projection=proj, source=source,
                          where=f"{where} · {name} × {h}", quote=f"{name} — {h}: {r[j]}", origin=origin, slide=slide, page=page,
                          doc_id=doc_id)
            if f:
                facts.append(f)
    return facts


# --------------------------------------------------------------------------- PowerPoint reader
def _texts(el) -> str:
    return "".join(t.text or "" for t in el.iter(f"{A}t"))


def read_pptx(data: bytes) -> list[dict]:
    """-> [{n, title, texts: [shape text], tables: [rows], charts: [{title, series: [{name, cats, vals, fmt}]}], notes}]"""
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())

    def rels(part: str) -> dict:
        p = PurePosixPath(part)
        rp = str(p.parent / "_rels" / (p.name + ".rels"))
        if rp not in names:
            return {}
        out = {}
        for r in ET.fromstring(z.read(rp)).iter(f"{PR}Relationship"):
            tgt = r.get("Target")
            out[r.get("Id")] = str(PurePosixPath(p.parent, tgt)) if not tgt.startswith("/") else tgt.lstrip("/")
        return out

    def norm(path: str) -> str:
        parts = []
        for seg in path.split("/"):
            if seg == "..":
                parts and parts.pop()
            elif seg and seg != ".":
                parts.append(seg)
        return "/".join(parts)

    order = []
    if "ppt/presentation.xml" in names:
        prels = rels("ppt/presentation.xml")
        for sid in ET.fromstring(z.read("ppt/presentation.xml")).iter(f"{P}sldId"):
            t = prels.get(sid.get(f"{R}id"))
            if t:
                order.append(norm(t))
    if not order:
        order = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
    slides = []
    for i, part in enumerate(order, start=1):
        if part not in names:
            continue
        root = ET.fromstring(z.read(part))
        srels = {k: norm(v) for k, v in rels(part).items()}
        title, texts, tables, charts = "", [], [], []
        for sp in root.iter(f"{P}sp"):
            ph = sp.find(f".//{P}nvPr/{P}ph")
            paras = [_texts(p) for p in sp.iter(f"{A}p")]
            txt = "\n".join(x for x in paras if x.strip())
            if not txt.strip():
                continue
            if ph is not None and ph.get("type") in ("title", "ctrTitle") and not title:
                title = txt.replace("\n", " ")
            else:
                texts.append(txt)
        inside = {id(x) for el in list(root.iter(f"{P}sp")) + list(root.iter(f"{P}graphicFrame")) for x in el.iter(f"{A}p")}
        loose = [_texts(x) for x in root.iter(f"{A}p") if id(x) not in inside]
        if any(t.strip() for t in loose):
            texts.append("\n".join(t for t in loose if t.strip()))   # text outside any shape (some generators do this)
        for gf in root.iter(f"{P}graphicFrame"):
            tbl = gf.find(f".//{A}tbl")
            if tbl is not None:
                tables.append([[" ".join(_texts(p) for p in tc.iter(f"{A}p")).strip() for tc in tr.findall(f"{A}tc")]
                               for tr in tbl.findall(f"{A}tr")])
                continue
            ch = gf.find(f".//{C}chart")
            if ch is not None and srels.get(ch.get(f"{R}id")) in names:
                charts.append(read_chart(z.read(srels[ch.get(f"{R}id")])))
        if not title and texts:
            first, _, rest = texts.pop(0).partition("\n")
            title = first
            if rest.strip():
                texts.insert(0, rest)
        notes = ""
        for k, v in srels.items():
            if "notesSlide" in v and v in names:
                notes = "\n".join(x for x in (_texts(p) for p in ET.fromstring(z.read(v)).iter(f"{A}p")) if x.strip() and not x.strip().isdigit())
        slides.append({"n": i, "title": title, "texts": texts, "tables": tables, "charts": charts, "notes": notes})
    return slides


def read_chart(xml: bytes) -> dict:
    root = ET.fromstring(xml)
    t = root.find(f"{C}chart/{C}title")
    out = {"title": _texts(t) if t is not None else "", "series": []}
    for ser in root.iter(f"{C}ser"):
        tx = ser.find(f"{C}tx")
        name = ""
        if tx is not None:
            v = tx.find(f".//{C}v")
            name = v.text if v is not None else _texts(tx)

        def pts(tag):
            el = ser.find(f"{C}{tag}")
            if el is None:
                return {}, None
            fmt = el.find(f".//{C}formatCode")
            return {int(p.get("idx")): (p.find(f"{C}v").text or "") for p in el.iter(f"{C}pt") if p.find(f"{C}v") is not None}, \
                (fmt.text if fmt is not None else None)
        cats, _ = pts("cat")
        vals, fmt = pts("val")
        hidden = ser.find(f"{C}spPr/{A}noFill") is not None
        n = max(list(cats) + list(vals) + [-1]) + 1
        out["series"].append({"name": name or "", "cats": [cats.get(i, "") for i in range(n)],
                              "vals": [vals.get(i) for i in range(n)], "fmt": fmt, "hidden": hidden})
    return out


def chart_facts(chart: dict, ents: Entities | None, *, source: str, where: str, slide=None, doc_id=None,
                default_entity: str | None = None) -> list[Fact]:
    facts = []
    for s in chart["series"]:
        if s.get("hidden"):
            continue
        label = s["name"] or chart.get("title", "")
        metric = canon_metric(label) or canon_metric(chart.get("title", ""))
        if not metric:
            continue
        kh, sh = header_scale(label)
        if kh is None and s.get("fmt") and "%" in s["fmt"]:
            kh = "pct"
        sp, sproj = canon_period(label)
        for cat, v in zip(s["cats"], s["vals"]):
            if v in (None, ""):
                continue
            try:
                val = float(v)
            except ValueError:
                continue
            key = ents.resolve(cat) if ents else None
            cp, cproj = canon_period(cat)
            if key is None and cp is None:
                continue                      # category is neither a company nor a period
            dec = len(f"{round(val, 6)}".rstrip("0").split(".")[1]) if "." in f"{round(val, 6)}".rstrip("0") else 0
            num = Num(val, min(dec, 6), None, 1.0, f"{v}")
            f = make_fact(num, metric, kind_hint=kh or KIND.get(metric), scale_hint=sh, entity=key or default_entity,
                          period=cp or sp, projection=sproj or cproj, source=source, where=f"{where} · chart “{label}” · {cat}",
                          quote=f"{label} — {cat}: {v}", origin="chart", slide=slide, doc_id=doc_id)
            if f:
                f.raw = _fmt_value(f)
                facts.append(f)
    return facts


# --------------------------------------------------------------------------- Excel reader (cell grid, % formats)
def read_xlsx(data: bytes) -> list[tuple[str, list[list[str]]]]:
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{S}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
    pct_styles = set()
    if "xl/styles.xml" in names:
        st = ET.fromstring(z.read("xl/styles.xml"))
        custom_pct = {nf.get("numFmtId") for nf in st.iter(f"{S}numFmt") if "%" in (nf.get("formatCode") or "")}
        xfs = st.find(f"{S}cellXfs")
        for i, xf in enumerate(xfs.findall(f"{S}xf") if xfs is not None else []):
            if xf.get("numFmtId") in {"9", "10"} | custom_pct:
                pct_styles.add(str(i))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    wrels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{PR}Relationship"):
            wrels[r.get("Id")] = "xl/" + r.get("Target").lstrip("/").removeprefix("xl/")
    out = []
    for i, sh in enumerate(wb.iter(f"{S}sheet")):
        part = wrels.get(sh.get(f"{R}id")) or f"xl/worksheets/sheet{i + 1}.xml"
        if part not in names:
            continue
        grid: dict[tuple[int, int], str] = {}
        for c in ET.fromstring(z.read(part)).iter(f"{S}c"):
            ref = c.get("r") or ""
            m = re.match(r"([A-Z]+)(\d+)", ref)
            if not m:
                continue
            col = 0
            for ch in m.group(1):
                col = col * 26 + ord(ch) - 64
            v, t = c.find(f"{S}v"), c.get("t")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{S}t"))
            elif t == "e" and v is not None:
                val = v.text or "#VALUE!"
            elif v is not None and v.text is not None:
                val = v.text
                if c.get("s") in pct_styles:
                    try:
                        val = f"{round(float(val) * 100, 6):g}%"
                    except ValueError:
                        pass
                elif t is None:
                    try:
                        val = f"{round(float(val), 6):g}"      # drop float noise (0.30000000000000004)
                    except ValueError:
                        pass
            else:
                continue
            grid[(int(m.group(2)), col)] = val
        if grid:
            nr, nc = max(r for r, _ in grid), max(c for _, c in grid)
            rows = [[grid.get((r, c), "") for c in range(1, nc + 1)] for r in range(1, min(nr, 2000) + 1)]
            out.append((sh.get("name") or f"Sheet{i + 1}", rows))
    return out


def sheet_facts(rows: list[list[str]], *, source: str, where: str, doc_id=None, ents: Entities | None = None) -> list[Fact]:
    """A worksheet may hold a period table (P&L), key-value rows (KPIs) and written answers; handle all three."""
    title = " ".join(c for r in rows[:3] for c in r if c)
    _, sheet_scale = header_scale(title) if re.search(r"\$\s*(?:k|m|mm|bn|b)\b|\(\$|in\s+(?:thousands|millions|billions)", title, re.I) else (None, None)
    if sheet_scale is None:
        m = re.search(r"[,(]\s*\$\s*(k|m|mm|bn|b)\b", title, re.I)
        sheet_scale = {"k": 1e3, "m": 1e6, "mm": 1e6, "bn": 1e9, "b": 1e9}.get(m.group(1).lower()) if m else None
    facts = table_facts(rows, ents, source=source, where=where, origin="sheet", doc_id=doc_id, default_scale=sheet_scale)
    for r in rows:
        for c in r:
            if len(c) > 80 and re.search(r"\d", c) and " " in c:
                fs, _ = text_facts(c, ents, source=source, where=f"{where} · text", doc_id=doc_id, carry=False)
                facts += fs
    covered = {f.where.split(" · ")[-1].split(" × ")[0] for f in facts}
    for r in rows:
        cells = [c for c in r if c.strip()]
        if len(cells) == 2 and cells[0] not in covered:
            metric = canon_metric(cells[0])
            nums = parse_numbers(cells[1])
            if metric and len(nums) == 1:
                kh, sh = header_scale(cells[0])
                period, proj = canon_period(cells[0])
                f = make_fact(nums[0], metric, kind_hint=kh, scale_hint=sh, entity=None, period=period, projection=proj, source=source,
                              where=f"{where} · {cells[0]}", quote=f"{cells[0]}: {cells[1]}", origin="sheet", doc_id=doc_id)
                if f:
                    facts.append(f)
    return facts


# --------------------------------------------------------------------------- comparison
def _fmt_value(f: Fact) -> str:
    if f.kind == "pct":
        return f"{f.value:.{_dec(f.ulp)}f}%"
    if f.kind == "mult":
        return f"{f.value:.{_dec(f.ulp)}f}x"
    if f.kind == "money":
        for sc, lab in ((1e12, "tn"), (1e9, "bn"), (1e6, "m"), (1e3, "k")):
            if abs(f.value) >= sc:
                d = max(0, min(2, _dec(f.ulp / sc)))
                return f"${f.value / sc:,.{d}f}{lab}"
        return f"${f.value:,.2f}"
    return f"{f.value:,.{_dec(f.ulp)}f}"


def _disp(f: Fact) -> str:
    """As the document writes it when that's self-explanatory ("$9.39B", "15.1%"), else normalized."""
    if f.origin in ("text", "table") and re.search(r"[$€£%x×]|bn|million|billion", f.raw, re.I):
        return f.raw.strip("() ")
    return _fmt_value(f)


def _dec(ulp: float) -> int:
    d = 0
    while ulp < 0.999 and d < 6:
        ulp *= 10
        d += 1
    return d


def agree(a: Fact, b: Fact) -> bool:
    """Same displayed precision: must be identical ($9.39B vs $9.38B is a visible inconsistency).
    Different precision: the finer one must round to the coarser (84.23 vs 84.2 is fine)."""
    eps = 1e-9 * max(abs(a.value), abs(b.value), 1)
    if abs(a.ulp - b.ulp) <= 1e-9 * max(a.ulp, b.ulp):
        return abs(a.value - b.value) <= eps
    return abs(a.value - b.value) <= max(a.ulp, b.ulp) / 2 * 1.0001 + eps


def one_step(a: Fact, b: Fact) -> bool:
    """Same precision, one rounding step apart ($9.39B vs $9.38B)."""
    same = abs(a.ulp - b.ulp) <= 1e-9 * max(a.ulp, b.ulp)
    return same and abs(a.value - b.value) <= a.ulp * 1.0001


def _clusters(facts: list[Fact]) -> list[list[Fact]]:
    groups: list[list[Fact]] = []
    for f in sorted(facts, key=lambda x: x.ulp):            # most precise first
        for g in groups:
            if agree(g[0], f):
                g.append(f)
                break
        else:
            groups.append([f])
    return groups


def _item(f: Fact, **extra) -> dict:
    d = {"value": f.raw if f.origin != "chart" else _fmt_value(f), "where": f.where, "source": f.source, "quote": f.quote,
         "slide": f.slide, "page": f.page, "doc_id": f.doc_id, "origin": f.origin, "projection": f.projection,
         "period": f.period, "period_inferred": f.period_inferred}
    d.update(extra)
    return d


def _subject(f: Fact, ents: Entities | None) -> str:
    if not f.entity:
        return ""
    names = {"__median__": "Median", "__mean__": "Mean", "__total__": "Total", "__max__": "High", "__min__": "Low"}
    return names.get(f.entity) or (ents.display.get(f.entity) if ents else None) or f.entity


def find_conflicts(facts: list[Fact], ents: Entities | None, *, scope: str) -> list[dict]:
    """scope: 'deck' (one document, many slides) or 'room' (many documents)."""
    issues = []
    by_key: dict[tuple, list[Fact]] = {}
    for f in facts:
        by_key.setdefault((f.entity or "", f.metric), []).append(f)
    for (ent, metric), fs in by_key.items():
        periods = {f.period for f in fs if f.period}
        for per in sorted(periods):
            group = [f for f in fs if f.period == per]
            cl = _clusters(group)
            if len(cl) < 2:
                continue
            if scope == "room" and len({f.source for f in group}) < 2 and not any(f.origin != "text" for f in group):
                pass
            proj = any(f.projection for f in group) and not all(f.projection for f in group)
            inferred = any(f.period_inferred for f in group)
            rounding = all(one_step(cl[0][0], c[0]) for c in cl[1:])
            sev = "medium" if (proj or inferred or rounding) else "high"
            subj = _subject(group[0], ents)
            title = f"{subj + ' — ' if subj else ''}{LABEL.get(metric, metric)} ({per}) differs: " + " vs ".join(_disp(c[0]) for c in cl)
            note = []
            if rounding:
                note.append("The figures differ by one rounding step; show the same figure everywhere.")
            if proj:
                note.append("One side is a projection or target; check whether the actual has been updated.")
            if inferred:
                note.append("The period of at least one figure was inferred from the surrounding text.")
            issues.append({"type": "conflict", "severity": sev, "title": title, "metric": metric, "period": per, "entity": subj,
                           "detail": " ".join(note), "groups": [[_item(f) for f in c] for c in cl]})
        # figures without a stated period: fine if they match *some* period; flag if they match none
        loose = [f for f in fs if not f.period and (f.origin in ("table", "chart", "sheet") or scope == "room")]
        if loose:
            dated = [f for f in fs if f.period]
            for c in _clusters(loose):
                f0 = c[0]
                if dated and not any(agree(f0, d) for d in dated):
                    if scope == "room" and metric not in POINT_IN_TIME:
                        continue
                    subj = _subject(f0, ents)
                    d0 = _clusters(dated)[0][0]
                    issues.append({"type": "conflict", "severity": "medium", "metric": metric, "period": None, "entity": subj,
                                   "title": f"{subj + ' — ' if subj else ''}{LABEL.get(metric, metric)} is {_disp(f0)} in {f0.where.split(' · ')[0]} "
                                            f"but {_disp(d0)} ({d0.period}) in {d0.where.split(' · ')[0]}",
                                   "detail": "Dated figures: " + ", ".join(f"{_fmt_value(d)} ({d.period})" for d in _clusters(dated) for d in d[:1]),
                                   "groups": [[_item(f) for f in c], [_item(d) for d in dated]]})
            if not dated:
                cl = _clusters(loose)
                if len(cl) > 1 and (scope == "deck" or metric in POINT_IN_TIME):
                    subj = _subject(cl[0][0], ents)
                    issues.append({"type": "conflict", "severity": "medium" if scope == "deck" else "high", "metric": metric,
                                   "period": None, "entity": subj,
                                   "title": f"{subj + ' — ' if subj else ''}{LABEL.get(metric, metric)} differs: " + " vs ".join(_disp(c[0]) for c in cl),
                                   "detail": "No period is stated, so these may be different dates; confirm they should match.",
                                   "groups": [[_item(f) for f in c] for c in cl]})
    return issues


def unit_mix(facts: list[Fact]) -> list[dict]:
    out = []
    by_metric: dict[str, dict[str, list[Fact]]] = {}
    for f in facts:
        if f.kind == "money" and f.origin in ("table", "text", "chart"):
            by_metric.setdefault(f.metric, {}).setdefault(f.unit, []).append(f)
    for metric, units in by_metric.items():
        if len(units) > 1:
            parts = [f"{u} on slide{'s' if len({f.slide for f in fs}) > 1 else ''} {', '.join(str(s) for s in sorted({f.slide for f in fs if f.slide}))}"
                     for u, fs in units.items()]
            out.append({"type": "units", "severity": "low", "metric": metric, "title": f"{LABEL.get(metric, metric)} shown in different units: " + "; ".join(parts),
                        "detail": "Pick one unit per metric across the deck (a footnote can carry the other).",
                        "groups": [[_item(fs[0])] for fs in units.values()]})
    return out


AGG = {"__median__": ("Median", statistics.median), "__mean__": ("Mean", statistics.fmean), "__total__": ("Total", sum),
       "__max__": ("High", max), "__min__": ("Low", min)}


def aggregate_checks(tables: list[dict], ents: Entities) -> list[dict]:
    """tables: [{rows, where, slide, source}] — recompute summary rows from the rows above them."""
    issues = []
    for t in tables:
        rows = [[(c or "").strip() for c in r] for r in t["rows"]]
        if len(rows) < 3:
            continue
        header = rows[0]
        data_rows, summaries = [], []
        for r in rows[1:]:
            key = SUMMARY.get(re.sub(r"\s+", " ", (r[0] if r else "").lower()).strip(" :"))
            (summaries if key else data_rows).append((key, r))
        if not summaries or len(data_rows) < 2:
            continue
        for key, srow in summaries:
            name, fn = AGG[key]
            for j in range(1, len(header)):
                if j >= len(srow) or EMPTY.match(srow[j]):
                    continue
                shown = parse_numbers(srow[j])
                vals = [parse_numbers(r[j]) for _, r in data_rows if j < len(r) and not EMPTY.match(r[j])]
                vals = [v[0] for v in vals if len(v) == 1]
                if len(shown) != 1 or len(vals) < 2:
                    continue
                s = shown[0]
                comp = fn([v.value for v in vals])
                ulp_rows = max(_ulp(v.decimals, 1) for v in vals)
                tol = _ulp(s.decimals, 1) / 2 + (ulp_rows / 2 * len(vals) if key == "__total__" else ulp_rows / 2) + 1e-9
                if abs(comp - s.value) > tol:
                    d = max(s.decimals, 1)
                    issues.append({"type": "aggregate", "severity": "high", "metric": canon_metric(header[j]) or header[j],
                                   "title": f"{name} of “{header[j]}” shows {s.raw} but the {len(vals)} rows above give {comp:,.{d}f}",
                                   "detail": f"{t['where']}. Rows used: " + ", ".join(v.raw for v in vals) +
                                             (". If the summary deliberately excludes some rows, say so in a footnote." if key in ("__median__", "__mean__") else ""),
                                   "groups": [[{"value": s.raw, "where": f"{t['where']} · {srow[0]} × {header[j]}", "slide": t.get("slide"),
                                                "source": t.get("source"), "quote": " | ".join(srow), "origin": "table"}]]})
    return issues


def math_checks(facts: list[Fact], ents: Entities | None) -> list[dict]:
    """Stated margin vs amount / revenue, stated growth vs this year / last year — interval arithmetic at displayed precision."""
    issues = []
    idx: dict[tuple, list[Fact]] = {}
    for f in facts:
        idx.setdefault((f.entity or "", f.metric, f.period), []).append(f)

    def ratio_interval(num: Fact, den: Fact):
        if den.lo() <= 0:
            return None
        lo, hi = num.lo() / den.hi(), num.hi() / den.lo()
        return min(lo, hi) * 100, max(lo, hi) * 100
    seen = set()
    for (ent, metric, per), fs in list(idx.items()):
        if per is None:
            continue
        inv = {v: k for k, v in MARGIN_OF.items()}
        if metric in inv:
            nums, revs = idx.get((ent, inv[metric], per), []), idx.get((ent, "revenue", per), [])
            for m in fs:
                for a in nums[:1]:
                    for r in revs[:1]:
                        iv = ratio_interval(a, r)
                        if iv and not (m.lo() <= iv[1] + 1e-9 and m.hi() >= iv[0] - 1e-9) and (ent, metric, per) not in seen:
                            seen.add((ent, metric, per))
                            subj = _subject(m, ents)
                            issues.append({"type": "math", "severity": "high", "metric": metric, "period": per, "entity": subj,
                                           "title": f"{subj + ' — ' if subj else ''}{LABEL.get(metric, metric)} ({per}) is stated as {_fmt_value(m)}, "
                                                    f"but {LABEL.get(inv[metric], inv[metric])} / Revenue = {(a.value / r.value * 100):.1f}%",
                                           "detail": f"{_fmt_value(a)} / {_fmt_value(r)}.",
                                           "groups": [[_item(m)], [_item(a)], [_item(r)]]})
        if metric.endswith("_growth") and per.startswith("FY") and per[2:].isdigit():
            base = {v: k for k, v in GROWTH_OF.items()}.get(metric)
            cur, prev = idx.get((ent, base, per), []), idx.get((ent, base, f"FY{int(per[2:]) - 1}"), [])
            for g in fs:
                for c in cur[:1]:
                    for p in prev[:1]:
                        iv = ratio_interval(c, p)
                        if not iv:
                            continue
                        iv = (iv[0] - 100, iv[1] - 100)
                        if not (g.lo() <= iv[1] + 1e-9 and g.hi() >= iv[0] - 1e-9) and (ent, metric, per) not in seen:
                            seen.add((ent, metric, per))
                            subj = _subject(g, ents)
                            issues.append({"type": "math", "severity": "high", "metric": metric, "period": per, "entity": subj,
                                           "title": f"{subj + ' — ' if subj else ''}{LABEL.get(metric, metric)} ({per}) is stated as {_fmt_value(g)}, "
                                                    f"but {_fmt_value(c)} vs {_fmt_value(p)} is {(c.value / p.value - 1) * 100:.1f}%",
                                           "detail": "", "groups": [[_item(g)], [_item(c)], [_item(p)]]})
    return issues


# --------------------------------------------------------------------------- arithmetic written in the prose
OP_GAP = [("-", re.compile(r"^\s*(?:[a-z0-9 ]{0,40}?\s)?(?:less|minus|net\s+of|after\s+deducting|deduct(?:ing)?)\s+(?:the\s+|a\s+|an\s+)?$", re.I)),
          ("+", re.compile(r"^\s*(?:[a-z0-9 ]{0,40}?\s)?(?:plus|\+|together\s+with)\s+(?:the\s+|a\s+|an\s+)?$", re.I)),
          ("*", re.compile(r"^\s*(?:times|×|\*|multiplied\s+by)\s*$", re.I)),
          ("/", re.compile(r"^\s*(?:/|÷|divided\s+by)\s*$", re.I))]
EQ_GAP = re.compile(r"^\s*(?:[a-z0-9 ]{0,40}?\s)?(?:=|equals?|left|leaves?|leaving|gives?|totals?|totalling|totaling|comes\s+to|is|are|was|were)\s+"
                    r"(?:of\s+|a\s+|an\s+|the\s+|about\s+|approximately\s+|~)?$|^\s*\(\s*$", re.I)


def _norm_num(n: Num, as_fraction: bool = False) -> tuple[float, float]:
    if n.kind == "pct" and as_fraction:
        return n.value / 100, _ulp(n.decimals, 1) / 100
    return n.value * n.scale, _ulp(n.decimals, n.scale)


def _eval(vals: list[float], ops: list[str]) -> float | None:
    # × and ÷ first, then + and −
    v, o = list(vals), list(ops)
    i = 0
    while i < len(o):
        if o[i] in "*/":
            if o[i] == "/" and v[i + 1] == 0:
                return None
            v[i] = v[i] * v[i + 1] if o[i] == "*" else v[i] / v[i + 1]
            del v[i + 1], o[i]
        else:
            i += 1
    r = v[0]
    for x, op in zip(v[1:], o):
        r = r + x if op == "+" else r - x
    return r


def arithmetic_checks(text: str, *, source: str, where: str, slide=None, page=None, doc_id=None) -> list[dict]:
    """'$15.82B less $6.43B capex left $9.38B'  /  '$1B / 443.1M = $2.26'  /  '$9.39B ($15.82B less $6.43B)'"""
    issues = []
    for sent in SENT_SPLIT.split(text):
        nums = [n for n in parse_numbers(sent, accounting=False) if not (re.fullmatch(r"(?:19|20)\d{2}", n.raw) and n.kind is None)]
        if len(nums) < 3:
            continue
        gaps = []
        for a, b in zip(nums, nums[1:]):
            g = sent[a.end:b.start]
            op = next((o for o, rx in OP_GAP if rx.match(g)), None)
            gaps.append(op or ("=" if EQ_GAP.match(g) else None))
        # maximal runs of connected numbers
        i = 0
        while i < len(gaps):
            if gaps[i] is None:
                i += 1
                continue
            j = i
            while j < len(gaps) and gaps[j] is not None:
                j += 1
            run, rg = nums[i:j + 1], gaps[i:j]
            i = j
            if rg.count("=") != 1 or len(rg) < 2:
                continue
            k = rg.index("=")
            if k == len(rg) - 1:
                operands, ops, result = run[:-1], rg[:-1], run[-1]
            elif k == 0:
                operands, ops, result = run[1:], rg[1:], run[0]
            else:
                continue
            if "=" in ops or None in ops:
                continue
            kinds = {n.kind for n in operands + [result]} - {None}
            if "pct" in kinds and ops and set(ops) <= {"+", "-"} and kinds != {"pct"}:
                continue                                  # "$X plus 3%" is not arithmetic we can check
            pct_ops = any(n.kind == "pct" for n in operands)
            vals = [_norm_num(n, as_fraction=set(ops) & {"*", "/"} != set()) for n in operands]
            res = _eval([v for v, _ in vals], ops)
            if res is None:
                continue
            if result.kind == "pct" and not pct_ops:
                res *= 100                                   # 2.7M ÷ 443.1M = 0.61%
            elif result.kind == "pct" and pct_ops and set(ops) & {"*", "/"}:
                res *= 100
            shown, ulp = _norm_num(result)
            if abs(res - shown) <= ulp / 2 * 1.0001 + 1e-9 * max(abs(res), 1):
                continue
            # could the inputs' own rounding explain it?
            lo_hi = []
            for signs in range(2 ** len(vals)):
                vs = [v + (u / 2 if signs >> t & 1 else -u / 2) for t, (v, u) in enumerate(vals)]
                r = _eval(vs, ops)
                if r is not None:
                    lo_hi.append(r * (100 if result.kind == "pct" and (not pct_ops or set(ops) & {"*", "/"}) else 1))
            rounding = bool(lo_hi) and min(lo_hi) - ulp / 2 <= shown <= max(lo_hi) + ulp / 2
            expr = " ".join(x for pair in zip([n.raw for n in operands], [{"-": "−", "+": "+", "*": "×", "/": "÷"}[o] for o in ops] + [""]) for x in pair if x)
            dec = max(result.decimals, 0)
            cur = re.match(r"^\(?\s*(US\$|\$|€|£)", result.raw)
            cur = cur.group(1) if cur else ""
            issues.append({"type": "arithmetic", "severity": "medium" if rounding else "high",
                           "title": f"{expr} = {cur}{res / result.scale:,.{dec}f}{_unit_suffix(result)}, but the text says {result.raw}",
                           "detail": ("Within rounding of the inputs, but a reader redoing the sum on the page gets a different answer; "
                                      "show the figures so they add." if rounding else "The stated result doesn't follow from the stated inputs."),
                           "groups": [[{"value": result.raw, "where": where, "source": source, "quote": sent[:300], "slide": slide,
                                        "page": page, "doc_id": doc_id, "origin": "text"}]]})
    return issues


def _unit_suffix(n: Num) -> str:
    unit = {1e3: "k", 1e6: "M", 1e9: "B", 1e12: "T"}.get(n.scale, "")
    m = re.search(r"(bn|billion|b|mm|mn|m|million|k|thousand)\b", n.raw, re.I)
    if m:
        unit = m.group(1)
    if n.kind == "pct":
        unit = "%"
    if n.kind == "mult":
        unit = "x"
    return unit


# --------------------------------------------------------------------------- bridges / waterfalls
SUBTOTAL = re.compile(r"\b(?:clos(?:e|ing)|end(?:ing)?|year[- ]end|total|sub-?total|residual|remaining|balance|net|free\s+cash|fcf|"
                      r"available)\b", re.I)


def bridge_checks(chart: dict, *, source: str, where: str, slide=None) -> list[dict]:
    issues = []
    if any(s.get("hidden") for s in chart["series"]):
        return issues                                    # stacked waterfall with an invisible base: signs unknown
    for s in chart["series"]:
        vals = [float(v) if v not in (None, "") else None for v in s["vals"]]
        cats = s["cats"]
        if len(vals) < 3 or None in vals or not any(v < 0 for v in vals):
            continue
        subs = [i for i, c in enumerate(cats) if i > 0 and SUBTOTAL.search(c or "")]
        if not subs:
            continue
        dec = max((len(f"{v:g}".split(".")[1]) if "." in f"{v:g}" else 0) for v in vals)
        tol = 10 ** -dec * (len(vals)) / 2 + 1e-9
        running = vals[0]
        for i in range(1, len(vals)):
            if i in subs:
                if abs(running - vals[i]) > tol:
                    issues.append({"type": "bridge", "severity": "high",
                                   "title": f"Bridge doesn't foot: “{cats[i]}” shows {vals[i]:,.{dec}f} but the bars before it sum to {running:,.{dec}f}",
                                   "detail": f"{where}, chart “{s['name'] or chart.get('title', '')}”: " + ", ".join(f"{c} {v:,.{dec}f}" for c, v in zip(cats, vals)),
                                   "groups": [[{"value": f"{vals[i]:,.{dec}f}", "where": f"{where} · {cats[i]}", "source": source, "slide": slide,
                                                "quote": "", "origin": "chart"}]]})
                running = vals[i]
            else:
                running += vals[i]
    return issues


# --------------------------------------------------------------------------- tie-out to SEC filings
TIE = {"revenue": ("revenue", 1e6), "ebitda": ("ebitda", 1e6), "ebit": ("ebit", 1e6), "net_income": ("net_income", 1e6),
       "gross_profit": ("gross_profit", 1e6), "fcf": ("fcf", 1e6), "gross_margin": ("margin_gross", 1), "ebitda_margin": ("margin_ebitda", 1),
       "ebit_margin": ("margin_ebit", 1), "net_margin": ("margin_net", 1), "fcf_margin": ("margin_fcf", 1)}
TIE_GROWTH = {"revenue_growth": "revenue_growth", "ebitda_growth": "ebitda_growth"}


def tie_out(facts: list[Fact], ents: Entities, data_service, universe: dict[str, str] | None = None, log=None) -> tuple[list[dict], dict]:
    """Compare deck numbers to the company's SEC figures. Returns (issues, stats)."""
    issues, stats = [], {"checked": 0, "matched": 0, "companies": 0, "skipped": 0}
    rows: dict[str, tuple[dict, dict] | None] = {}
    for f in facts:
        if not f.entity or f.entity.startswith("__") or (f.metric not in TIE and f.metric not in TIE_GROWTH):
            continue
        tick = ents.ticker.get(f.entity) or (universe or {}).get(f.entity)
        if not tick:
            continue
        if tick not in rows:
            try:
                rows[tick] = data_service.comps_row(tick)
                stats["companies"] += 1
            except Exception as e:  # unknown ticker / offline
                rows[tick] = None
                if log:
                    log(f"{tick}: {e}")
        if rows[tick] is None:
            stats["skipped"] += 1
            continue
        row, prov = rows[tick]
        if row.get("is_financial_format") and f.metric in ("ebitda", "ebitda_margin", "gross_margin", "gross_profit"):
            continue
        cands = []
        if f.metric in TIE:
            base, mult = TIE[f.metric]
            per = {"LTM": ["ltm"], "FY": ["fy"], "FY-1": ["fy_minus1"]}.get(f.period or "", None)
            if per is None and f.period and f.period.startswith("FY") and row.get("last_fy_end"):
                fy = int(str(row["last_fy_end"])[:4])
                yr = int(f.period[2:]) if f.period[2:].isdigit() else None
                per = ["fy"] if yr == fy else ["fy_minus1"] if yr == fy - 1 else []
            if per is None:
                per = ["ltm", "fy"]
            for p in per:
                v = row.get(f"{base}_{p}")
                if v is not None:
                    cands.append((p.upper().replace("_MINUS1", "-1"), v * mult))
        else:
            base = TIE_GROWTH[f.metric]
            for p, k in (("LTM", f"{base}_ltm_yoy"), ("FY", f"{base}_fy")):
                if f.period in (None, p) and row.get(k) is not None:
                    cands.append((p, row[k]))
        if not cands:
            continue
        stats["checked"] += 1
        tol = f.ulp / 2 * 1.0001 + 1e-9 * abs(f.value)
        if any(abs(f.value - v) <= tol for _, v in cands):
            stats["matched"] += 1
            continue
        filing = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={row.get('cik')}&type=10-K" if row.get("cik") else None)
        shown = ", ".join(f"{p}: {_fmt_value(Fact(f.metric, f.kind, v, f.ulp, '', None, None, False, '', '', '', ''))}" for p, v in cands)
        issues.append({"type": "source", "severity": "high" if f.period else "medium", "metric": f.metric, "period": f.period,
                       "entity": _subject(f, ents),
                       "title": f"{_subject(f, ents)} — {LABEL.get(f.metric, f.metric)}{' (' + f.period + ')' if f.period else ''} shows {f.raw}; SEC filings give {shown}",
                       "detail": f"From {tick}'s 10-K/10-Q XBRL data (LTM ending {row.get('ltm_end') or '?'}, fiscal year ending {row.get('last_fy_end') or '?'})."
                                 + ("" if f.period else " The deck doesn't state the period, so both LTM and fiscal year were tried."),
                       "groups": [[_item(f)], [{"value": shown, "where": f"SEC EDGAR · {tick}", "source": "SEC filings", "quote": "",
                                                "origin": "source", "link": filing}]]})
    return issues, stats


# --------------------------------------------------------------------------- deck
def deck_facts(data: bytes, source: str = "deck", notes: bool = False) -> tuple[list[Fact], Entities, list[dict], list[dict]]:
    slides = read_pptx(data)
    if not notes:
        for sl in slides:
            sl["notes"] = ""          # speaker notes aren't shown to the reader (and often hold drafting comments)
    ents = Entities()
    facts, tables = [], []
    # tables first: they name the companies (and tickers) that text and charts refer to
    for s in slides:
        for ti, rows in enumerate(s["tables"], start=1):
            where = f"Slide {s['n']} · table{' ' + str(ti) if len(s['tables']) > 1 else ''}"
            facts += table_facts(rows, ents, source=source, where=where, slide=s["n"])
            tables.append({"rows": rows, "where": where, "slide": s["n"], "source": source})
    for s in slides:
        for ci, ch in enumerate(s["charts"], start=1):
            facts += chart_facts(ch, ents, source=source, where=f"Slide {s['n']}", slide=s["n"])
        carry = None
        for txt in s["texts"] + ([s["notes"]] if s["notes"] else []):
            if re.match(r"^(?:source|sources|note|notes)s?\b[:.]", txt.strip(), re.I):
                continue                          # footnotes describe methods, not figures
            fs, _ = text_facts(txt, ents, source=source, where=f"Slide {s['n']} · text", slide=s["n"], carry=False)
            facts += fs
    return facts, ents, slides, tables


def check_deck(data: bytes, *, name: str = "deck", data_service=None, universe: dict[str, str] | None = None, tie: bool = True,
               extra_facts: list[Fact] | None = None, notes: bool = False, log=None) -> dict:
    facts, ents, slides, tables = deck_facts(data, source=name, notes=notes)
    issues = find_conflicts(facts + (extra_facts or []), ents, scope="deck" if not extra_facts else "room")
    issues += aggregate_checks(tables, ents)
    issues += math_checks(facts, ents)
    issues += unit_mix(facts)
    for sl in slides:
        for txt in sl["texts"] + ([sl["notes"]] if sl["notes"] else []) + [sl["title"]]:
            issues += arithmetic_checks(txt, source=name, where=f"Slide {sl['n']}", slide=sl["n"])
        for ch in sl["charts"]:
            issues += bridge_checks(ch, source=name, where=f"Slide {sl['n']}", slide=sl["n"])
    tie_stats = None
    if tie and data_service is not None:
        ti, tie_stats = tie_out(facts, ents, data_service, universe, log=log)
        issues += ti
    return _report(issues, facts, {"slides": len(slides), "tables": len(tables), "tie_out": tie_stats,
                                   "companies": sorted(ents.display.get(k, k) for k in set(ents.alias.values()) if not k.startswith("__"))})


def _report(issues: list[dict], facts: list[Fact], extra: dict) -> dict:
    rank = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: (rank[i["severity"]], i["type"], i["title"]))
    for n, i in enumerate(issues, start=1):
        i["id"] = n
    by = {}
    for f in facts:
        by[f.origin] = by.get(f.origin, 0) + 1
    return {"issues": issues, "counts": {s: sum(1 for i in issues if i["severity"] == s) for s in ("high", "medium", "low")},
            "facts": len(facts), "facts_by_origin": by, **extra}


# --------------------------------------------------------------------------- data room
def room_facts(index, rooms, room_id: int, log=None) -> list[Fact]:
    facts: list[Fact] = []
    for d in rooms.documents(room_id):
        label = d["path"].split("/", 1)[-1] if "/" in d["path"] else d["path"]
        ext = Path(d["path"]).suffix.lower()
        fp = rooms.file_path(d["doc_id"])
        try:
            if ext == ".xlsx" and fp and fp.exists():
                for sheet, rows in read_xlsx(fp.read_bytes()):
                    facts += sheet_facts(rows, source=label, where=f"{label} · sheet {sheet}", doc_id=d["doc_id"])
                continue
            if ext == ".pptx" and fp and fp.exists():
                for s in read_pptx(fp.read_bytes()):
                    for rows in s["tables"]:
                        facts += table_facts(rows, None, source=label, where=f"{label} · slide {s['n']} table", slide=s["n"], doc_id=d["doc_id"])
                    for ch in s["charts"]:
                        facts += chart_facts(ch, None, source=label, where=f"{label} · slide {s['n']}", slide=s["n"], doc_id=d["doc_id"])
                    for txt in [s["title"]] + s["texts"] + ([s["notes"]] if s["notes"] else []):
                        fs, _ = text_facts(txt, None, source=label, where=f"{label} · slide {s['n']}", slide=s["n"], doc_id=d["doc_id"])
                        facts += fs
                continue
        except Exception as e:  # unreadable original: fall back to the indexed text
            if log:
                log(f"{label}: {e}")
        carry = None
        for c in index.db.execute("SELECT text, section FROM chunks WHERE doc_id=? ORDER BY ord", (d["doc_id"],)):
            m = re.match(r"p\.(\d+)", c["section"] or "")
            page = int(m.group(1)) if m else None
            fs, carry = text_facts(c["text"], None, source=label, where=f"{label}{' · p.' + str(page) if page else ''}", page=page,
                                   doc_id=d["doc_id"], carry_period=carry)
            facts += fs
    return facts


LLM_SCHEMA = {
    "type": "object", "required": ["facts"],
    "properties": {"facts": {"type": "array", "items": {
        "type": "object", "required": ["metric", "value", "unit", "period", "quote"],
        "properties": {
            "metric": {"type": "string", "enum": sorted(m for m in KIND if not m.startswith("~")) + ["other"]},
            "label": {"type": "string"}, "value": {"type": "number"},
            "unit": {"type": "string", "enum": ["usd", "usd_thousands", "usd_millions", "usd_billions", "percent", "multiple", "count"]},
            "period": {"type": "string"}, "projection": {"type": "boolean"}, "quote": {"type": "string"}}}}}}
UNIT = {"usd": ("money", 1.0), "usd_thousands": ("money", 1e3), "usd_millions": ("money", 1e6), "usd_billions": ("money", 1e9),
        "percent": ("pct", 1.0), "multiple": ("mult", 1.0), "count": ("count", 1.0)}


def llm_room_facts(router, index, rooms, room_id: int, log=None, max_passages: int = 120) -> list[Fact]:
    """Model-extracted facts for what the rules miss. Every fact must quote its passage verbatim (checked here)."""
    from .llm import Part
    facts = []
    passages = []
    for d in rooms.documents(room_id):
        for c in index.db.execute("SELECT text, section FROM chunks WHERE doc_id=? ORDER BY ord", (d["doc_id"],)):
            if re.search(r"\d", c["text"]) and metric_mentions(c["text"]):
                passages.append((d, c["section"], c["text"]))
    system = ("You extract financial and operating figures from data-room documents for a consistency check. Return only figures "
              "stated about the company itself (not customers, competitors or markets). Use the canonical metric names given; use "
              "'other' if none fits. period: FY2025, Q3 2025, LTM, or '' if not stated. Never compute or infer values; copy the "
              "quote verbatim from the passage.")
    for d, sec, text in passages[:max_passages]:
        label = d["path"].split("/", 1)[-1]
        try:
            res = router.complete_json("check", system, [Part(f"Document: {label} ({sec})\n\n{text}")], LLM_SCHEMA)
        except Exception as e:
            if log:
                log(f"model extraction failed for {label}: {e}")
            continue
        flat = re.sub(r"\s+", " ", text)
        for x in res.data.get("facts", []):
            q = re.sub(r"\s+", " ", x.get("quote") or "").strip()
            if x["metric"] == "other" or not q or q not in flat:
                continue                                  # ungrounded: drop
            kind, scale = UNIT[x["unit"]]
            if KIND.get(x["metric"]) not in (kind, None) and not (KIND.get(x["metric"]) == "count" and kind == "count"):
                continue
            per, proj = canon_period(x.get("period") or "")
            v = float(x["value"])
            dec = len(str(v).split(".")[1].rstrip("0")) if "." in str(v) else 0
            m = re.match(r"p\.(\d+)", sec or "")
            facts.append(Fact(metric=x["metric"], kind=kind, value=v * scale, ulp=_ulp(dec, scale), raw=str(x.get("label") or v),
                              entity=None, period=per, projection=bool(x.get("projection")) or proj, source=label,
                              where=f"{label}{' · ' + sec if sec else ''}", quote=q[:300], origin="model",
                              unit=scale_label(kind, scale), page=int(m.group(1)) if m else None, doc_id=d["doc_id"]))
    return facts


def _dedupe(facts: list[Fact]) -> list[Fact]:
    seen, out = set(), []
    for f in facts:
        k = (f.source, f.metric, f.period, round(f.value, 6))
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def adjudicate(router, issues: list[dict], log=None, limit: int = 25) -> None:
    """Ask the model whether each numeric conflict really compares like with like; downgrade if not."""
    from .llm import Part
    schema = {"type": "object", "required": ["same_measure", "explanation"],
              "properties": {"same_measure": {"type": "boolean"}, "explanation": {"type": "string"}}}
    for i in [x for x in issues if x["type"] == "conflict"][:limit]:
        quotes = "\n".join(f"- [{it['source']}, {it['where']}] {it['quote']}" for g in i["groups"] for it in g[:2])
        try:
            r = router.complete_json("check", "You review possible inconsistencies between deal documents. Decide whether the figures "
                                     "below measure the same thing for the same period (same definition: e.g. reported vs adjusted, "
                                     "gross vs net, pro forma, segment vs total, different dates). Be brief.",
                                     [Part(f"Possible inconsistency: {i['title']}\n\nQuotes:\n{quotes}")], schema)
        except Exception as e:
            if log:
                log(f"adjudication failed: {e}")
            return
        i["review"] = r.data["explanation"]
        if not r.data["same_measure"]:
            i["severity"] = "low"
            i["title"] += " (likely different definitions)"


def check_room(index, rooms, room_id: int, *, router=None, deck: bytes | None = None, deck_name: str = "deck", log=None) -> dict:
    facts = room_facts(index, rooms, room_id, log=log)
    used_model = False
    if router is not None and router.available("check"):
        facts += llm_room_facts(router, index, rooms, room_id, log=log)
        used_model = True
    facts = _dedupe(facts)
    extra = {}
    if deck:
        dfacts, ents, slides, tables = deck_facts(deck, source=deck_name)
        # a deck about the target: rows/metrics without a company belong to the subject; keep company rows apart
        facts += [f for f in dfacts if not f.entity]
        extra["deck_slides"] = len(slides)
    issues = find_conflicts(facts, None, scope="room")
    issues += math_checks(facts, None)
    for d in rooms.documents(room_id):
        label = d["path"].split("/", 1)[-1]
        for c in index.db.execute("SELECT text, section FROM chunks WHERE doc_id=? ORDER BY ord", (d["doc_id"],)):
            m = re.match(r"p\.(\d+)", c["section"] or "")
            issues += arithmetic_checks(c["text"], source=label, where=f"{label}{' · ' + c['section'] if c['section'] else ''}",
                                        page=int(m.group(1)) if m else None, doc_id=d["doc_id"])
    if used_model and issues:
        adjudicate(router, issues, log=log)
    docs = rooms.documents(room_id)
    return _report(issues, facts, {"documents": len(docs), "model": used_model,
                                   "metrics": sorted({LABEL.get(f.metric, f.metric) for f in facts}), **extra})


def load_universe(path: Path) -> dict[str, str]:
    """normalized company name -> ticker, for tying decks that show names without tickers."""
    import csv
    out = {}
    if path.exists():
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                k = norm_entity(r.get("name") or "")
                if k and k not in out:
                    out[k] = r.get("ticker")
    return out


def facts_table(facts: list[Fact]) -> list[dict]:
    return [asdict(f) for f in facts]


# --------------------------------------------------------------------------- Excel workbook
ERR = re.compile(r"^#(?:N/A|DIV/0!|REF!|VALUE!|NAME\?|NUM!|NULL!|SPILL!|CALC!)$")
CHECK_BAD = re.compile(r"^\s*(?:error|fail(?:ed)?|false|not\s+ok|check|x|✗|mismatch|break)\s*$", re.I)


def uncalculated(data: bytes) -> int:
    """Formula cells saved without a cached value (files written by code and never opened in Excel)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    n = 0
    for name in z.namelist():
        if re.match(r"xl/worksheets/sheet\d+\.xml$", name):
            for c in ET.fromstring(z.read(name)).iter(f"{S}c"):
                if c.find(f"{S}f") is not None and (c.find(f"{S}v") is None or c.find(f"{S}v").text in (None, "")):
                    n += 1
    return n


_LO_ALWAYS_RECALC = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>
"""


def recalc(data: bytes) -> bytes | None:
    """Recalculate with LibreOffice (headless) if it's installed; None otherwise."""
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("soffice") or shutil.which("libreoffice") or next(
        (x for x in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",) if Path(x).exists()), None)
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "in.xlsx", Path(d) / "out"
        src.write_bytes(data)
        out.mkdir()
        # A fresh profile that tells LibreOffice to recalculate every formula on load. Without it, simple
        # references such as =Filings!C9 keep whatever value the file cached, so a wrong stored value survives.
        (Path(d) / "profile" / "user").mkdir(parents=True)
        (Path(d) / "profile" / "user" / "registrymodifications.xcu").write_text(_LO_ALWAYS_RECALC, encoding="utf-8")
        try:
            subprocess.run([exe, "--headless", "--norestore", f"-env:UserInstallation=file://{d}/profile", "--convert-to", "xlsx",
                            "--outdir", str(out), str(src)], capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return None
        res = out / "in.xlsx"
        return res.read_bytes() if res.exists() else None


def check_workbook(data: bytes, *, name: str = "workbook", allow_recalc: bool = True) -> dict:
    """Error cells, failing rows on a Checks tab, and the same metric/period disagreeing across sheets."""
    issues, facts = [], []
    missing = uncalculated(data)
    recalculated = False
    if missing and allow_recalc:
        fresh = recalc(data)
        if fresh and uncalculated(fresh) < missing:
            data, recalculated = fresh, True
    if missing and not recalculated:
        issues.append({"type": "not_calculated", "severity": "medium", "title": f"{missing} formula cells have no calculated values",
                       "detail": "The file was saved without calculating (typical of files written by code). Open and save it in Excel, "
                                 "or install LibreOffice so the checker can recalculate it; until then formula results can't be checked.",
                       "groups": []})
    sheets = read_xlsx(data)
    for sheet, rows in sheets:
        errs = [(r, c, v) for r, row in enumerate(rows, 1) for c, v in enumerate(row, 1) if ERR.match(v.strip())]
        if errs:
            refs = ", ".join(f"{_col(c)}{r}" for r, c, _ in errs[:12]) + (f" (+{len(errs) - 12} more)" if len(errs) > 12 else "")
            issues.append({"type": "error_cells", "severity": "high", "title": f"{sheet}: {len(errs)} cell{'s' if len(errs) > 1 else ''} show "
                           f"{', '.join(sorted({v for _, _, v in errs}))}", "detail": f"Cells: {refs}. A shared model must calculate cleanly.",
                           "groups": [[{"value": v, "where": f"{sheet}!{_col(c)}{r}", "source": name, "quote": "", "origin": "sheet"} for r, c, v in errs[:5]]]})
        if re.search(r"check", sheet, re.I):
            bad = [(r, row) for r, row in enumerate(rows, 1) if any(CHECK_BAD.match(v) for v in row[1:]) and row and row[0].strip()]
            if bad:
                issues.append({"type": "checks", "severity": "high", "title": f"{sheet}: {len(bad)} check{'s' if len(bad) > 1 else ''} failing",
                               "detail": "; ".join(" | ".join(x for x in row if x.strip())[:140] for _, row in bad[:6]),
                               "groups": [[{"value": " | ".join(x for x in row if x.strip())[:80], "where": f"{sheet} row {r}", "source": name,
                                            "quote": "", "origin": "sheet"} for r, row in bad[:5]]]})
        facts += sheet_facts(rows, source=name, where=f"{sheet}", doc_id=None)
    for f in facts:
        f.source = f.where.split(" · ")[0]            # compare across sheets
    issues += find_conflicts(facts, None, scope="room")
    issues += math_checks(facts, None)
    return _report(issues, facts, {"sheets": [s for s, _ in sheets], "recalculated": recalculated, "uncalculated": missing})


def _col(c: int) -> str:
    out = ""
    while c:
        c, r = divmod(c - 1, 26)
        out = chr(65 + r) + out
    return out
