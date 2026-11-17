"""Bilingual (EN/AR) line-item label dictionary and matcher (S8.2).

`match(label, statement=None)` maps a printed line-item label to a canonical key: one of `om.statements.LINES`
or an `x.` key in `EXTRA_KEYS`. The dictionary lives in `om/intl/data/labels/*.yaml` (variants as printed in
Egyptian EAS, Saudi SOCPA/IFRS, UAE and IFRS annual reports).

Rules the matcher keeps:
  * an exact normalised hit has confidence 1.0 (0.95 when a statement hint re-routes it, 0.75 when the same text
    exists under two keys and no hint resolves it, 0.4 when it is genuinely ambiguous);
  * fuzzy token matching needs a clear margin over the runner-up; a candidate that is a total/subtotal key must
    cover every content word of the query, so a component ("Other current assets") never lands on a total;
  * unknown labels return None or confidence < 0.5.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).parent / "data" / "labels"

_TASHKEEL = re.compile("[ً-ٰٟۖ-ۭـ]")  # harakat, superscript alef, Quranic marks, tatweel
_AR_LETTER = re.compile("[ء-يٮ-ۓ]")
_LATIN = re.compile("[A-Za-z]")
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})
_AR_CHAR_MAP = {ord(a): b for a, b in {
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ی": "ي", "ې": "ي", "ة": "ه", "ہ": "ه", "ھ": "ه",
    "ؤ": "و", "ئ": "ي", "ک": "ك", "ء": "", "ٔ": "", "ٕ": "",
}.items()}

# trailing section markers such as "(A)", "(I+II)", "(أ+ب)", "(1)"
_MARKER = re.compile(r"\(\s*(?:[a-z]|[ا-ي]|[ivx]+|\d+)(?:\s*[+&,،]\s*(?:[a-z]|[ا-ي]|[ivx]+|\d+))*\s*\)\s*$")

_AR_NOTE_PAREN = re.compile(r"[(\[]\s*(?:ايضاح(?:ات)?|note|notes)\s*(?:رقم)?\s*[\d\s,،و\-–]*[)\]]")
_AR_NOTE_BARE = re.compile(r"(?:^|\s)ايضاح(?:ات)?\s*(?:رقم)?\s*\d+(?:\s*[و,،\-–]\s*\d+)*")
_AR_RESTATED = re.compile(r"[(\[]\s*(?:معدل\w*|معاد\s+\w+(?:\s+\w+)?|بعد\s+التعديل)\s*[)\]]")
_AR_YEAR_END = re.compile(r"\s*(?:لل|عن\s+|ل|ال)?(?:سنه|عام|فتره)\s+(?:ال)?منتهي\w*.*$")
_EN_NOTE_PAREN = re.compile(r"[(\[]\s*notes?\s*[\d\s,&and\-–]*[)\]]")
_EN_NOTE_BARE = re.compile(r"\bnotes?\s*\d+(?:\s*(?:,|and|&|-|–)\s*\d+)*")
_EN_RESTATED = re.compile(r"[(\[]\s*(?:as\s+)?(?:restated|re-?presented|reclassified|revised|re-?stated|audited|unaudited)\s*[)\]]")
_EN_YEAR_END = re.compile(r"\bfor the (?:financial |fiscal )?(?:year|period|twelve months|six months|quarter|nine months)\s+ended\b.*$")
_EN_FOR_YEAR = re.compile(r"\b(?:for|during) the (?:financial |fiscal )?(?:year|period)\b")
_EN_CANON = [("non current", "noncurrent"), ("non controlling", "noncontrolling"), ("long term", "longterm"),
             ("short term", "shortterm"), ("right of use", "rightofuse"), ("pre tax", "pretax"),
             ("write off", "writeoff"), ("work in progress", "workinprogress"), ("by products", "byproducts")]
_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_WS = re.compile(r"\s+")


def normalise_digits(s: str) -> str:
    return s.translate(_DIGIT_MAP)


def normalise_ar(s: str) -> str:
    """Arabic label key for matching only: no diacritics/tatweel, one alef, ى->ي, ة->ه, ؤ->و, ئ->ي, ASCII digits,
    punctuation and note references ("(إيضاح ١٢)") and restated tags removed, whitespace collapsed."""
    s = unicodedata.normalize("NFKC", s or "")
    s = _TASHKEEL.sub("", s)
    s = s.translate(_DIGIT_MAP).translate(_AR_CHAR_MAP).lower()
    s = _AR_NOTE_PAREN.sub(" ", s)
    s = _AR_NOTE_BARE.sub(" ", s)
    s = _AR_RESTATED.sub(" ", s)
    s = _AR_YEAR_END.sub("", s)
    s = _MARKER.sub("", s.strip())
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def normalise_label(s: str) -> str:
    """English label key: lower case, "&"->"and", no punctuation, "the", "for the year/period [ended ...]", note
    references, "(restated)" tags and section markers; hyphen compounds unified (non-current -> noncurrent)."""
    s = unicodedata.normalize("NFKC", s or "").translate(_DIGIT_MAP).lower()
    s = s.replace("&", " and ").replace("’", "'").replace("`", "'")
    s = _EN_NOTE_PAREN.sub(" ", s)
    s = _EN_NOTE_BARE.sub(" ", s)
    s = _EN_RESTATED.sub(" ", s)
    s = _EN_YEAR_END.sub("", s)
    s = _MARKER.sub("", s.strip())
    s = _EN_FOR_YEAR.sub(" ", s)
    s = s.replace("'", "")
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    s = re.sub(r"\bthe\b", " ", s)
    s = _WS.sub(" ", s).strip()
    for a, b in _EN_CANON:
        s = re.sub(rf"\b{a}\b", b, s)
    return s


def detect_lang(s: str) -> str:
    ar, la = len(_AR_LETTER.findall(s or "")), len(_LATIN.findall(s or ""))
    if ar == 0 and la == 0:
        return "en"
    return "ar" if ar >= la else "en"


def _norm(s: str, lang: str) -> str:
    return normalise_ar(s) if lang == "ar" else normalise_label(s)


# ---------------------------------------------------------------------------------------------------- dictionary
@dataclass(frozen=True)
class Entry:
    key: str
    label: str
    norm: str
    lang: str
    statement: str
    is_total: bool
    sign_hint: int


@dataclass(frozen=True)
class LabelMatch:
    key: str
    confidence: float
    sign_hint: int
    lang: str
    is_total: bool
    statement: str = ""
    method: str = "exact"          # exact | alias | fuzzy | ambiguous | bilingual
    norm: str = ""


_KEYS: dict[str, dict] = {}
_ENTRIES: list[Entry] = []
_EXACT: dict[str, list[Entry]] = {}
_TOKENS: dict[Entry, frozenset] = {}
_INVERTED: dict[str, list[Entry]] = {}
_LOADED = False
_STATEMENT_ORDER = {"IS": 0, "BS": 1, "CF": 2, "OCI": 3, "EQ": 4}

_EN_STOP = frozenset("and of the for to in on at from by a an with its is total sum aggregate grand".split())
_AR_STOP = frozenset("و في من على الى عن او مع اجمالي مجموع جمله".split())
_AR_SYN = {"الموجودات": "الاصول", "موجودات": "اصول", "المطلوبات": "الالتزامات", "مطلوبات": "التزامات",
           "الخصوم": "الالتزامات", "خصوم": "التزامات", "مصاريف": "مصروفات", "المصاريف": "المصروفات",
           "الجاريه": "المتداوله", "جاريه": "متداوله", "الارباح": "الربح", "ارباح": "ربح", "الاقليه": "غير المسيطره"}


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    keys = _read(DATA_DIR / "keys.yaml")["keys"]
    _KEYS.update({k: {"statement": v["statement"], "total": bool(v["total"])} for k, v in keys.items()})
    seen: set = set()
    for path in sorted(DATA_DIR.glob("*.yaml")):
        if path.name == "keys.yaml":
            continue
        doc = _read(path)
        lang = doc.get("lang", "en")
        for key, groups in (doc.get("labels") or {}).items():
            if key not in _KEYS:
                raise ValueError(f"{path.name}: unknown key {key!r}")
            for sign_name, sign in (("pos", 1), ("neg", -1)):
                for raw in (groups.get(sign_name) or "").splitlines():
                    raw = raw.strip()
                    if not raw:
                        continue
                    norm = _norm(raw, lang)
                    if not norm or (key, norm, sign) in seen:
                        continue
                    seen.add((key, norm, sign))
                    e = Entry(key, raw, norm, lang, _KEYS[key]["statement"], _KEYS[key]["total"], sign)
                    _ENTRIES.append(e)
                    _EXACT.setdefault(norm, []).append(e)
    for e in _ENTRIES:
        toks = frozenset(_tokens(e.norm, e.lang))
        _TOKENS[e] = toks
        for t in toks:
            _INVERTED.setdefault(t, []).append(e)
    _LOADED = True


def _stem_en(t: str) -> str:
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def _stem_ar(t: str) -> str:
    t = _AR_SYN.get(t, t)
    for p in ("وال", "بال", "لل", "ال"):
        if t.startswith(p) and len(t) > len(p) + 2:
            t = t[len(p):]
            break
    return _AR_SYN.get(t, t)


def _tokens(norm: str, lang: str) -> list:
    out = []
    for t in norm.split():
        if t.isdigit():
            continue
        if lang == "ar":
            if t in _AR_STOP:
                continue
            t = _stem_ar(t)
        else:
            if t in _EN_STOP:
                continue
            t = _stem_en(t)
        out.append(t)
    return out


def _build_keys() -> tuple:
    _load()
    return tuple(k for k in _KEYS if k.startswith("x."))


EXTRA_KEYS: tuple = _build_keys()

# when the printed statement differs from the key's home statement, a label of key K printed in statement S
# really denotes key ALIASES[(K, S)]
ALIASES = {
    ("net_income", "CF"): "cf_net_income", ("cf_net_income", "IS"): "net_income",
    ("x.nci_equity", "IS"): "x.nci_profit", ("x.nci_profit", "BS"): "x.nci_equity",
    ("tax", "CF"): "x.tax_paid", ("x.zakat", "CF"): "x.tax_paid",
    ("interest_expense", "CF"): "x.interest_paid", ("x.finance_costs_net", "CF"): "x.interest_paid",
    ("x.depreciation", "CF"): "da", ("x.amortisation", "CF"): "da",
    ("x.rou_depreciation", "CF"): "x.rou_depreciation",
    ("x.lease_liabilities_noncurrent", "CF"): "x.lease_payments",
    ("x.eps_basic", "IS"): "x.eps_basic",
}


def key_info(key: str) -> dict:
    _load()
    return _KEYS[key]


def all_keys() -> tuple:
    _load()
    return tuple(_KEYS)


def entries(key: str | None = None, lang: str | None = None) -> list:
    _load()
    return [e for e in _ENTRIES if (key is None or e.key == key) and (lang is None or e.lang == lang)]


def label_counts() -> dict:
    _load()
    out = {"en": set(), "ar": set()}
    for e in _ENTRIES:
        out[e.lang].add(e.norm)
    return {k: len(v) for k, v in out.items()}


def exact_collisions() -> dict:
    """norm -> keys, for normalised texts printed under more than one key (resolved by statement hint)."""
    _load()
    return {n: sorted({e.key for e in es}) for n, es in _EXACT.items() if len({e.key for e in es}) > 1}


# ---------------------------------------------------------------------------------------------------- matching
def _mk(e: Entry, conf: float, method: str, key: str | None = None) -> LabelMatch:
    k = key or e.key
    info = _KEYS[k]
    return LabelMatch(k, round(conf, 3), e.sign_hint, e.lang, info["total"], info["statement"], method, e.norm)


def _exact(norm: str, statement: str | None) -> LabelMatch | None:
    es = _EXACT.get(norm)
    if not es:
        return None
    keys = {e.key for e in es}
    # prefer the sign carried by the entries (a text is never both profit and loss under one key)
    if len(keys) == 1:
        e = es[0]
        if statement and e.statement != statement and (e.key, statement) in ALIASES:
            return _mk(e, 0.95, "alias", ALIASES[(e.key, statement)])
        return _mk(e, 1.0, "exact")
    if statement:
        hit = [e for e in es if e.statement == statement]
        if len({e.key for e in hit}) == 1:
            return _mk(hit[0], 1.0, "exact")
        if len({e.key for e in hit}) > 1:
            return _mk(hit[0], 0.4, "ambiguous")
    best = min(es, key=lambda e: (_STATEMENT_ORDER.get(e.statement, 9), list(_KEYS).index(e.key)))
    return _mk(best, 0.4 if statement else 0.75, "ambiguous" if statement else "exact")


def _fuzzy(norm: str, lang: str, statement: str | None) -> LabelMatch | None:
    q = frozenset(_tokens(norm, lang))
    if not q:
        return None
    cands: dict = {}
    seen: set = set()
    for t in q:
        for e in _INVERTED.get(t, ()):
            if e.lang != lang or e in seen:
                continue
            seen.add(e)
            toks = _TOKENS[e]
            inter = len(q & toks)
            score = inter / len(q | toks)
            if e.is_total and not q <= toks:
                continue                      # a total must cover every content word: components never map to totals
            if statement and e.statement != statement:
                score *= 0.93
            prev = cands.get(e.key)
            if prev is None or score > prev[0]:
                cands[e.key] = (score, e)
    if not cands:
        return None
    ranked = sorted(cands.values(), key=lambda x: -x[0])
    best_score, best = ranked[0]
    if best_score < 0.6:
        return None
    runner = ranked[1][0] if len(ranked) > 1 else 0.0
    if best_score - runner < 0.15:
        return _mk(best, 0.4, "ambiguous")
    return _mk(best, 0.6 + 0.3 * (best_score - 0.6) / 0.4, "fuzzy")


def _match_one(text: str, lang: str, statement: str | None) -> LabelMatch | None:
    norm = _norm(text, lang)
    if not norm:
        return None
    m = _exact(norm, statement)
    if m is not None:
        return m
    return _fuzzy(norm, lang, statement)


def _script_parts(label: str) -> tuple:
    ar = " ".join(re.findall(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿][؀-ۿݐ-ݿً-ٟ0-9٠-٩\s/()\-,،.]*", label))
    en = " ".join(re.findall(r"[A-Za-z][A-Za-z0-9&'’\s/()\-,.]*", label))
    return ar.strip(), en.strip()


def match(label: str, *, statement: str | None = None) -> LabelMatch | None:
    """Map a printed label to a canonical key. See the module docstring for the confidence rules."""
    _load()
    if not label or not label.strip():
        return None
    if statement:
        statement = statement.upper()
    lang = detect_lang(label)
    if _AR_LETTER.search(label) and _LATIN.search(label):
        ar_text, en_text = _script_parts(label)
        ms = [m for m in (_match_one(ar_text, "ar", statement) if ar_text else None,
                          _match_one(en_text, "en", statement) if en_text else None) if m]
        if not ms:
            return None
        if len(ms) == 2:
            if ms[0].key == ms[1].key:
                return LabelMatch(ms[0].key, max(m.confidence for m in ms), ms[0].sign_hint, "bi", ms[0].is_total,
                                  ms[0].statement, "bilingual", ms[0].norm)
            lo = min(ms, key=lambda m: m.confidence)
            hi = max(ms, key=lambda m: m.confidence)
            return LabelMatch(hi.key, min(0.4, hi.confidence), hi.sign_hint, "bi", hi.is_total, hi.statement,
                              "ambiguous", hi.norm) if lo.confidence >= 0.5 else hi
        return ms[0]
    m = _match_one(label, lang, statement)
    if m is not None and m.confidence < 0.5 and m.method == "fuzzy":
        return None
    return m
