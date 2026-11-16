"""Number, unit and period-header parsing for English and Arabic financial reports.

Public API (docs/s8/contract.md):

* ``normalise_digits(s)``: Eastern Arabic and Persian digits to ASCII, Arabic
  separators and minus signs to ASCII, exotic spaces to a plain space, bidi
  control marks removed.
* ``parse_number(token, *, decimal=None, context=None) -> ParsedNumber``
* ``detect_unit(text) -> (currency | None, scale | None)``
* ``parse_period_header(text) -> date | None``

Conventions
-----------
* ``ParsedNumber.value`` is the signed printed number (no unit scaling).
  Nil dashes give ``value == 0.0`` with ``is_nil=True``.
* Note references, years and text never carry a value (``value is None``).
* ``context`` lets the caller say where the cell sits: ``"note"`` (a note
  column: small integers and lists like ``5,6`` are note refs), ``"header"``
  (a column header: a four-digit year is a year) or ``"value"`` (a statement
  body cell: a bare four-digit integer such as ``2024`` is a number, not a
  year). Without a context a bare integer from 1990 to 2100 is classed as a
  year, because that is the safer error in a statement table.
* ``decimal`` is ``"."`` or ``","`` and overrides the pattern decision for a
  token with a single ambiguous separator.
* Percents give the printed number (``12.5%`` -> 12.5, kind ``percent``).
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
import calendar

__all__ = ["ParsedNumber", "normalise_digits", "parse_number", "detect_unit",
           "parse_period_header", "normalise_arabic_text"]

# ----------------------------------------------------------------- digits
_DIGIT_MAP = {}
for _i in range(10):
    _DIGIT_MAP[0x0660 + _i] = str(_i)      # Arabic-Indic
    _DIGIT_MAP[0x06F0 + _i] = str(_i)      # Extended Arabic-Indic (Persian)
_SEP_MAP = {
    0x066C: ",",   # Arabic thousands separator
    0x066B: ".",   # Arabic decimal separator
    0x060C: ",",   # Arabic comma
    0x066A: "%",   # Arabic percent sign
    0x2212: "-",   # minus sign
    0x207B: "-",   # superscript minus
    0xFE63: "-",   # small hyphen-minus
    0xFF0D: "-",   # fullwidth hyphen-minus
    0x2010: "-", 0x2011: "-", 0x2012: "-",   # hyphens, figure dash
    0x02D7: "-",   # modifier letter minus
    0x066D: "*",
}
_SPACES = {0x00A0, 0x202F, 0x2009, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008,
           0x200A, 0x205F, 0x3000, 0x2001}
_STRIP = {0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
          0x2066, 0x2067, 0x2068, 0x2069, 0x200B, 0x200C, 0x200D, 0xFEFF, 0x0640}
_TRANS = {}
_TRANS.update(_DIGIT_MAP)
_TRANS.update(_SEP_MAP)
for _c in _SPACES:
    _TRANS[_c] = " "
for _c in _STRIP:
    _TRANS[_c] = None

_DASHES = "-–—―−"   # hyphen, en dash, em dash, horizontal bar, minus


def normalise_digits(s):
    """ASCII-fold digits, separators and minus signs; drop bidi marks; fold exotic spaces."""
    if s is None:
        return ""
    return str(s).translate(_TRANS)


def normalise_arabic_text(s):
    """Fold Arabic letters for matching: strip diacritics/tatweel, unify alef, yaa, taa marbuta."""
    s = normalise_digits(s)
    s = unicodedata.normalize("NFKC", s)
    s = "".join(ch for ch in s if not unicodedata.category(ch) == "Mn")
    for a in "أإآٱ":
        s = s.replace(a, "ا")
    return s.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")


# ----------------------------------------------------------------- numbers
@dataclass
class ParsedNumber:
    value: float | None
    is_nil: bool = False
    negative: bool = False
    kind: str = "text"          # number | nil | note_ref | year | percent | text


_NIL_WORDS = {"nil", "n/a", "na", "none", "-nil-", "لا شيء", "لا يوجد", "لاشيء", "صفر"}
_NOTE_WORD = re.compile(r"^(?:notes?|ref|إيضاح|ايضاح|إيضاحات|ايضاحات|اﻹيضاح|الإيضاح|الايضاح)\s*\.?\s*\(?\s*\d{1,3}\s*\)?(?:\s*[,،-]\s*\d{1,3})*$",
                        re.I)
_NOTE_SUFFIX = re.compile(r"^\d{1,3}\s*\(\s*[A-Za-z]\s*\)$")
_CORE = re.compile(r"^\d[\d.,' ]*$|^[.,]\d+$")


def _strip_parens(s):
    if len(s) >= 2 and s[0] == "(" and s[-1] == ")":
        return s[1:-1].strip(), True
    return s, False


def _decide_decimal(core, decimal):
    """Return a float for a digit string with optional , and . separators, or None."""
    core = core.replace(" ", "").replace("'", "")
    if not core or not re.fullmatch(r"[\d.,]+", core):
        return None
    has_c, has_d = "," in core, "." in core
    if not has_c and not has_d:
        return float(core)
    if has_c and has_d:
        last_c, last_d = core.rfind(","), core.rfind(".")
        dec = "," if last_c > last_d else "."
        if decimal in (".", ","):
            dec = decimal
        th = "." if dec == "," else ","
        head, _, tail = core.rpartition(dec)
        if dec in head or not tail.isdigit():
            return None
        if not re.fullmatch(r"\d{1,3}(?:%s\d{3})*" % re.escape(th), head):
            return None
        return float(head.replace(th, "") + "." + tail)
    sep = "," if has_c else "."
    other = "." if has_c else ","
    parts = core.split(sep)
    if any(p == "" for p in parts[1:]) or core.startswith(sep) and len(parts) > 2:
        return None
    if core.startswith(sep):
        # ".5" / ",5": decimal fraction only
        return float("0." + parts[1]) if len(parts) == 2 else None
    if len(parts) > 2:
        # repeated separator: thousands unless every group but the first is 3 digits, else bad
        if decimal == sep:
            return None
        if all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
            return float("".join(parts))
        return None
    left, right = parts
    if decimal == sep:
        return float(left + "." + right)
    if decimal == other:
        return float(left + right) if len(right) == 3 else None
    # single ambiguous separator, decide by pattern
    if sep == ",":
        if len(right) == 3 and 1 <= len(left) <= 3 and not left.startswith("0"):
            return float(left + right)             # 1,234 -> thousands
        return float(left + "." + right)            # 12,5 / 1234,56 / 0,123 -> decimal comma
    return float(left + "." + right)                # 12.5 / 1.234 -> decimal point (English default)


def parse_number(token, *, decimal=None, context=None):
    """Parse one printed cell. See module docstring for the conventions."""
    raw = "" if token is None else str(token)
    s = normalise_digits(raw).strip()
    if not s:
        return ParsedNumber(None, False, False, "text")
    low = s.lower().strip(" .")
    if low in _NIL_WORDS or re.fullmatch(r"[%s_]+" % re.escape(_DASHES), s):
        return ParsedNumber(0.0, True, False, "nil")
    if s in ("(-)", "(–)", "(—)", "( - )"):
        return ParsedNumber(0.0, True, False, "nil")
    if _NOTE_WORD.match(s) or _NOTE_SUFFIX.match(s):
        return ParsedNumber(None, False, False, "note_ref")
    if context == "note":
        return ParsedNumber(None, False, False, "note_ref") if re.fullmatch(r"[\d\s,\-\(\)a-zA-Z]+", s) \
            and re.search(r"\d", s) else ParsedNumber(None, False, False, "text")

    work = s
    negative = False
    pct = False
    if work.endswith("%"):
        pct, work = True, work[:-1].strip()
    elif work.startswith("%"):
        pct, work = True, work[1:].strip()
    # brackets (possibly with a minus inside)
    inner, br = _strip_parens(work)
    if br:
        negative, work = True, inner
    # sign: leading/trailing minus of any dash type
    changed = True
    while changed and work:
        changed = False
        if work[0] in _DASHES and len(work) > 1:
            negative, work, changed = True, work[1:].strip(), True
        elif work[-1] in _DASHES and len(work) > 1:
            negative, work, changed = True, work[:-1].strip(), True
        elif work[0] == "+":
            work, changed = work[1:].strip(), True
    inner, br2 = _strip_parens(work)
    if br2:
        negative, work = True, inner
    # tolerate a lone unmatched bracket from OCR
    work = work.strip()
    if work.startswith("(") and work[1:].strip().replace(",", "").replace(".", "").isdigit():
        negative, work = True, work[1:].strip()
    elif work.endswith(")") and work[:-1].strip().replace(",", "").replace(".", "").isdigit():
        negative, work = True, work[:-1].strip()
    # strip currency noise glued to the number
    work = re.sub(r"^(?:US\$|\$|SAR|SR|EGP|AED|USD|E£|£E|LE)\s*", "", work, flags=re.I)

    if not _CORE.match(work):
        return ParsedNumber(None, False, False, "text")
    core = work.strip()
    # spaces as thousands separator ("1 234 567")
    if " " in core:
        if re.fullmatch(r"\d{1,3}(?: \d{3})+(?:[.,]\d+)?", core):
            core = core.replace(" ", "")
        else:
            return ParsedNumber(None, False, False, "text")
    # apostrophe thousands ("1'234'567")
    if "'" in core:
        if re.fullmatch(r"\d{1,3}(?:'\d{3})+(?:[.,]\d+)?", core):
            core = core.replace("'", "")
        else:
            return ParsedNumber(None, False, False, "text")
    if pct:
        v = _decide_decimal(core, decimal)
        if v is None:
            return ParsedNumber(None, False, False, "text")
        return ParsedNumber(-v if negative else v, False, negative, "percent")

    plain_int = re.fullmatch(r"\d+", core) is not None
    if plain_int and not negative:
        n = int(core)
        if context == "header" and 1990 <= n <= 2100 and len(core) == 4:
            return ParsedNumber(None, False, False, "year")
        if context is None and len(core) == 4 and 1990 <= n <= 2100:
            return ParsedNumber(None, False, False, "year")
    v = _decide_decimal(core, decimal)
    if v is None:
        return ParsedNumber(None, False, False, "text")
    if v == 0 and negative:
        negative = False
    return ParsedNumber(-v if negative else v, False, negative, "number")


# ------------------------------------------------------------------- units
_AR = "ء-ي"
_UNIT_CURRENCIES = [
    # (ISO, regex over lower-cased normalised text); more specific first
    ("USD", r"\bus\s?\$|\busd\b|us\s+dollars?|\bdollars?\b|دولار"),
    ("SAR", r"\bsar\b|\bsr\b|saudi\s+riyals?|ريال\s+سعودي|(?<![ء-ي])ر\s?\.\s?س\b|(?<![ء-ي])ر\s?\.\s?س\s?\.?"),
    ("EGP", r"\begp\b|egyptian\s+pounds?|جنيه\s+مصري|جنيهات\s+مصريه|جنيه|(?<![ء-ي])ج\s?\.\s?م\b|(?<![ء-ي])ج\s?\.\s?م\s?\.?|\be£|£\s?e\b|\bl\.\s?e\b"),
    ("AED", r"\baed\b|uae\s+dirhams?|\bdirhams?\b|درهم|د\s?\.\s?ا\b"),
    ("QAR", r"\bqar\b|qatari\s+riyals?|ريال\s+قطري"),
    ("OMR", r"\bomr\b|omani\s+rials?|ريال\s+عماني"),
    ("KWD", r"\bkwd\b|kuwaiti\s+dinars?|دينار\s+كويتي"),
    ("BHD", r"\bbhd\b|bahraini\s+dinars?|دينار\s+بحريني"),
    ("JOD", r"\bjod\b|jordanian\s+dinars?|دينار\s+اردني"),
    ("EUR", r"\beur\b|\beuros?\b|€|يورو"),
    ("GBP", r"\bgbp\b|pounds?\s+sterling|£\s?(?!e)|جنيه\s+استرليني"),
]
_UNIT_SCALES = [
    (1e9, r"\bbillions?\b|\bbn\b|(?<![ء-ي])(?:بال|ال|ب)?(?:مليار|مليارات|بليون)(?![ء-ي])"),
    (1e6, r"\bmillions?\b|\bmn\b|\bmio\b|(?<![ء-ي])(?:بال|ال|ب)?(?:مليون|ملايين)(?![ء-ي])"),
    (1e3, r"['’‘`´]\s?000(?!\d)|\b000['’‘]s\b|\bthousands?\b|\bin\s+000s?\b|\(\s?000s?\s?\)|(?<![ء-ي])(?:بال|ال|ب)?(?:الف|الاف|آلاف)(?![ء-ي])"),
]


def detect_unit(text):
    """Find the reporting currency and printed scale in a header phrase.

    Returns ``(currency | None, scale | None)``; scale is 1e3, 1e6 or 1e9, or
    ``None`` when the phrase names no unit.
    """
    if not text:
        return None, None
    t = normalise_arabic_text(text).lower()
    t = t.replace("‘", "'").replace("’", "'")
    cur = None
    best = None
    for iso, pat in _UNIT_CURRENCIES:
        m = re.search(pat, t)
        if m and (best is None or m.start() < best):
            # a pound sterling / dollar phrase inside an Egyptian pound phrase must not win
            if iso == "USD" and re.search(r"جنيه|egyptian|ريال|درهم", t) and not re.search(r"us\s?\$|usd|us\s+dollar", t):
                continue
            cur, best = iso, m.start()
    scale = None
    for sc, pat in _UNIT_SCALES:
        if re.search(pat, t):
            scale = sc
            break
    return cur, scale


# ----------------------------------------------------------------- periods
_MONTHS_EN = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTHS_AR = {
    # Egyptian / Gulf (Gregorian transliterations)
    "يناير": 1, "فبراير": 2, "مارس": 3, "ابريل": 4, "أبريل": 4, "مايو": 5, "ماي": 5,
    "يونيو": 6, "يونيه": 6, "يونيوه": 6, "يوليو": 7, "يوليه": 7, "يوليوز": 7,
    "اغسطس": 8, "أغسطس": 8, "غشت": 8, "سبتمبر": 9, "اكتوبر": 10, "أكتوبر": 10,
    "نوفمبر": 11, "ديسمبر": 12,
    # Levantine / Iraqi
    "كانون الثاني": 1, "كانون الثانيه": 1, "شباط": 2, "اذار": 3, "نيسان": 4, "ايار": 5,
    "حزيران": 6, "تموز": 7, "اب": 8, "ايلول": 9, "تشرين الاول": 10, "تشرين الثاني": 11,
    "كانون الاول": 12,
}
_MONTHS_AR = {normalise_arabic_text(k): v for k, v in _MONTHS_AR.items()}


def _month_alt():
    en = sorted(_MONTHS_EN, key=len, reverse=True)
    ar = sorted(_MONTHS_AR, key=len, reverse=True)
    return "|".join(re.escape(x) for x in en + ar)


_M = _month_alt()
_RE_DMY = re.compile(r"(?<![\d])(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:of\s+|من\s+)?(%s)\b\.?,?\s*(?:سنه\s+|لعام\s+|عام\s+)?(\d{4})(?!\d)" % _M)
_RE_MDY = re.compile(r"\b(%s)\b\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(\d{4})(?!\d)" % _M)
_RE_YMD_AR = re.compile(r"(?<!\d)(\d{4})\s*(?:م\s*)?(%s)\s*(\d{1,2})(?!\d)" % _M)
_RE_MY = re.compile(r"\b(%s)\b\.?,?\s*(\d{4})(?!\d)" % _M)
_RE_NUM = re.compile(r"(?<![\d.])(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})(?![\d])")
_RE_ISO = re.compile(r"(?<!\d)(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})(?!\d)")


def _month_no(word):
    w = word.lower()
    return _MONTHS_EN.get(w) or _MONTHS_AR.get(w)


def _mk(y, m, d):
    try:
        if not 1900 <= y <= 2200:
            return None
        return date(y, m, d)
    except ValueError:
        return None


def parse_period_header(text):
    """Return the first period-end date named in a header, or ``None``.

    Handles ``31 December 2024``, ``June 30, 2024``, ``As at 31/12/2024``,
    ``2024-12-31``, Arabic and Eastern-Arabic-digit forms, a month and year
    without a day (month end), and RTL-reversed ``2024 ديسمبر 31``.
    """
    if not text:
        return None
    t = normalise_arabic_text(text).lower()
    t = re.sub(r"\s+", " ", t)
    best = None   # (position, date)

    def keep(pos, d):
        nonlocal best
        if d is not None and (best is None or pos < best[0]):
            best = (pos, d)

    for m in _RE_DMY.finditer(t):
        mo = _month_no(m.group(2))
        keep(m.start(), _mk(int(m.group(3)), mo, int(m.group(1))))
    for m in _RE_MDY.finditer(t):
        mo = _month_no(m.group(1))
        keep(m.start(), _mk(int(m.group(3)), mo, int(m.group(2))))
    for m in _RE_YMD_AR.finditer(t):
        mo = _month_no(m.group(2))
        keep(m.start(), _mk(int(m.group(1)), mo, int(m.group(3))))
    for m in _RE_ISO.finditer(t):
        keep(m.start(), _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _RE_NUM.finditer(t):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = _mk(y, b, a) if b <= 12 else _mk(y, a, b)      # day first unless impossible
        keep(m.start(), d)
    if best is None:
        for m in _RE_MY.finditer(t):
            mo = _month_no(m.group(1))
            y = int(m.group(2))
            if mo and 1900 <= y <= 2200:
                keep(m.start(), date(y, mo, calendar.monthrange(y, mo)[1]))
    return best[1] if best else None
