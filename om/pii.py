"""Reversible PII masking for outbound LLM prompts (stdlib only).

`Masker.mask(text)` swaps emails, phone numbers, IBANs (mod-97), payment cards (Luhn), US SSNs, UK NINOs and any
supplied person names for placeholders such as `[EMAIL_1]`. The same value always gets the same placeholder within one
Masker (= one job). `unmask` restores the originals. Ordinary financial text (1,234.5, FY2024, $12.3bn, ISO dates,
10-digit CIKs) is left alone: every digit pattern is either validated (Luhn / mod-97) or needs phone/SSN punctuation.
"""
from __future__ import annotations

import re
import threading
import unicodedata

_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_IBAN = re.compile(r"\b[A-Za-z]{2}\d{2}(?: ?[A-Za-z0-9]{2,4}){3,8}\b")
_CARD = re.compile(r"(?<![\w.,-])(?:\d[ -]?){12,18}\d(?![\w.,]?\d)")
_SSN = re.compile(r"(?<![\w-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\w-])")
_NINO = re.compile(r"\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z] ?\d{2} ?\d{2} ?\d{2} ?[A-D]\b")
_PHONE_INTL = re.compile(r"(?<![\w+])\+\d{1,3}(?:[\s.-]?\(?\d{1,4}\)?){2,5}(?!\w|[\s.-]\d)")
_PHONE_US = re.compile(r"(?<![\w.,/-])(?:\+?1[-.\s])?(?:\(\d{3}\)\s?|\d{3}[-.\s])\d{3}[-.\s]\d{4}(?![\w-]|[.,]\d)")


_DASHES = {c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"}


def _fold(text: str) -> tuple[str, list[int]]:
    """NFKC-fold a copy of `text` for detection (fullwidth '@' and digits, NBSP / thin / narrow spaces, unicode
    dashes) and return it with, for each folded char, the index of the original char it came from (+ a sentinel)."""
    out, idx = [], []
    for i, ch in enumerate(text):
        f = unicodedata.normalize("NFKC", ch).translate(_DASHES)
        if f and f.isspace() and f != " ":
            f = " "
        out.append(f)
        idx.extend([i] * len(f))
    idx.append(len(text))
    return "".join(out), idx


def _sub(rx: re.Pattern, fn, text: str) -> str:
    """Like rx.sub but detects on the folded copy and replaces in the ORIGINAL text. `fn(match, original_span)`
    gets the folded match and the original substring; return the replacement for the original span."""
    folded, idx = _fold(text)
    out, last = [], 0
    for m in rx.finditer(folded):
        a, b = idx[m.start()], idx[m.end()]
        if a < last:
            continue
        out.append(text[last:a])
        out.append(fn(m, text[a:b]))
        last = b
    out.append(text[last:])
    return "".join(out)


def luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return total % 10 == 0


def iban_ok(s: str) -> bool:
    s = s.replace(" ", "").upper()
    if not 15 <= len(s) <= 34 or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", s):
        return False
    moved = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


class Masker:
    """Stateful per job: same value -> same placeholder. Thread-safe."""

    def __init__(self, names: list[str] | tuple[str, ...] = ()):
        self.names = sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True)
        self._by_value: dict[tuple[str, str], str] = {}
        self.mapping: dict[str, str] = {}          # placeholder -> original
        self._count: dict[str, int] = {}
        self._lock = threading.Lock()

    def _ph(self, kind: str, value: str) -> str:
        key = (kind, re.sub(r"\W", "", value).lower() if kind in ("PHONE", "CARD", "IBAN", "NINO", "SSN") else value.lower())
        if key not in self._by_value:
            self._count[kind] = self._count.get(kind, 0) + 1
            ph = f"[{kind}_{self._count[kind]}]"
            self._by_value[key] = ph
            self.mapping[ph] = value
        return self._by_value[key]

    def mask(self, text: str) -> tuple[str, dict[str, str]]:
        if not text:
            return text, dict(self.mapping)
        with self._lock:
            out = _sub(_EMAIL, lambda m, o: self._ph("EMAIL", o), text)
            out = _sub(_IBAN, self._iban, out)
            out = _sub(_CARD, lambda m, o: self._ph("CARD", o) if luhn_ok(re.sub(r"[ -]", "", m.group())) else o, out)
            out = _sub(_SSN, lambda m, o: self._ph("SSN", o), out)
            out = _sub(_NINO, lambda m, o: self._ph("NINO", o), out)
            out = _sub(_PHONE_INTL, self._phone, out)
            out = _sub(_PHONE_US, self._phone, out)
            for name in self.names:
                out = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", lambda m: self._ph("PERSON", m.group()), out, flags=re.I)
            return out, dict(self.mapping)

    def _iban(self, m, orig):
        toks = m.group().split(" ")
        while len(toks) > 1 and not iban_ok("".join(toks)):
            toks.pop()
        cand = " ".join(toks)
        if not iban_ok(cand):
            return orig
        # the original span may use odd spaces: cut it where the folded candidate ends
        _, idx = _fold(orig)
        cut = idx[len(cand)] if len(cand) < len(idx) else len(orig)
        return self._ph("IBAN", orig[:cut]) + orig[cut:]

    def _phone(self, m, orig):
        digits = re.sub(r"\D", "", m.group())
        return self._ph("PHONE", orig) if 10 <= len(digits) <= 15 else orig

    def mask_obj(self, obj, skip_keys=("role", "type", "id", "tool_call_id", "model")):
        """Mask every string value in a JSON-like message structure (content parts, tool_calls arguments, names,
        tool results...). Keys in `skip_keys` and `data:` URLs are structural and left alone."""
        if isinstance(obj, str):
            return self.mask(obj)[0] if not obj.startswith("data:") else obj
        if isinstance(obj, list):
            return [self.mask_obj(x, skip_keys) for x in obj]
        if isinstance(obj, dict):
            return {k: (v if k in skip_keys and isinstance(v, str) else self.mask_obj(v, skip_keys)) for k, v in obj.items()}
        return obj

    def unmask(self, text: str, mapping: dict[str, str] | None = None) -> str:
        return unmask(text, mapping if mapping is not None else self.mapping)


_PH = re.compile(r"\[[A-Z]+_\d+\]")


def unmask(text: str, mapping: dict[str, str]) -> str:
    if not text or not mapping:
        return text
    return _PH.sub(lambda m: mapping.get(m.group(), m.group()), text)


def unmask_obj(obj, mapping: dict[str, str]):
    """Unmask every string value (and key) in a JSON-like structure."""
    if isinstance(obj, str):
        return unmask(obj, mapping)
    if isinstance(obj, list):
        return [unmask_obj(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {unmask(k, mapping) if isinstance(k, str) else k: unmask_obj(v, mapping) for k, v in obj.items()}
    return obj
