"""Anti-slop text rules (S3.6): banned filler, dash and emoji bans, exclamation marks, all caps, title full stops.

`lint_text` works on one string; `lint_spec` walks a DeckSpec dict and reports JSON paths. No LLM, no network.
"""
from __future__ import annotations

import re
from typing import Any

BANNED: tuple[str, ...] = (
    "delve", "delves", "delving", "unlock", "unlocks", "unlocking", "game-changer", "game changer", "game-changing",
    "seamless", "seamlessly", "robust", "in today's fast-paced", "in today’s fast-paced", "synergy", "synergies",
    "cutting-edge", "cutting edge", "best-in-class", "best in class", "world-class", "world class", "holistic",
    "paradigm", "revolutionize", "revolutionise", "revolutionary", "empower", "empowers", "empowering", "journey",
    "it's important to note", "it’s important to note", "dive into", "deep dive into", "at the end of the day",
    "evolving landscape", "changing landscape", "shifting landscape", "dynamic landscape", "ever-changing landscape",
    "digital landscape",
    # Arabic generic filler
    "نقلة نوعية", "حلول مبتكرة", "في عالم اليوم سريع الخطى", "في عالم اليوم سريع التغير", "رائد في مجاله", "رحلة",
)
# "leverage" is only slop as a verb; "financial leverage", "net leverage" and "leveraged buyout" stay legal.
_LEVERAGE_VERB = re.compile(
    r"\b(?:to|we|will|can|could|would|should|may|might|must|you|they|and|or|that|which|how)\s+leverag(?:e|es|ed|ing)\b"
    r"|\bleveraging\b(?!\s+(?:ratio|multiple))", re.I)
_BANNED_RE = [(b, re.compile(r"(?<!\w)" + re.escape(b) + r"(?!\w)", re.I)) for b in BANNED]

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⭐⭕⬛⬜⌀-⏿️‍]")
_ENDASH_DASH = re.compile(r"\s–\s")
_CAPS = re.compile(r"(?<![A-Za-z0-9&/])[A-Z]{6,}(?![A-Za-z0-9])")
FINANCE_ACRONYMS = frozenset({
    "EBITDA", "EBITDAR", "NASDAQ", "SHARIA", "WACC", "CAGR", "GAAP", "IFRS", "LIBOR", "SOFR", "EURIBOR", "NOPAT",
    "EBITDA", "ROIC", "TTM", "LTM", "NTM", "SAFE", "ESOP", "SPAC", "REIT", "ETF", "EGX", "TADAWUL", "SUKUK", "FINRA",
    "BASEL", "CAMELS", "ICAAP", "ILAAP", "CRYPTO", "NYSE", "EURONEXT", "MSCI", "FTSE", "STOXX", "CBE", "ADQ", "SAIBOR",
})
_SKIP_KEYS = {"id", "archetype", "deck_id", "lang", "as_of", "theme", "art_direction", "kind", "binding", "manifest_id",
              "format", "type", "color", "alt"}


def lint_text(text: str, *, kind: str = "text") -> list[tuple[str, str]]:
    """Return (rule, message) pairs. rule is `banned_phrase` or `punctuation`. kind='title' adds the full-stop rule."""
    out: list[tuple[str, str]] = []
    if not text:
        return out
    for phrase, rx in _BANNED_RE:
        if rx.search(text):
            out.append(("banned_phrase", f"banned filler \"{phrase}\""))
    if _LEVERAGE_VERB.search(text):
        out.append(("banned_phrase", "banned filler \"leverage\" used as a verb"))
    if "—" in text:
        out.append(("punctuation", "em dash; use a comma, colon or full stop"))
    if _ENDASH_DASH.search(text):
        out.append(("punctuation", "en dash used as a dash between spaces"))
    if _EMOJI.search(text):
        out.append(("punctuation", "emoji"))
    if "!" in text or "！" in text:
        out.append(("punctuation", "exclamation mark"))
    for m in _CAPS.finditer(text):
        if m.group(0) not in FINANCE_ACRONYMS:
            out.append(("punctuation", f"all-caps word \"{m.group(0)}\""))
    if kind == "title" and text.rstrip().endswith((".", "。", "۔")):
        out.append(("punctuation", "title ends with a full stop"))
    return out


def lint_spec(spec: Any) -> list[dict]:
    """Walk a DeckSpec dict; every string is linted. Finding.shape_name carries the JSON path."""
    out: list[dict] = []

    def walk(node: Any, path: str, slide: int | None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _SKIP_KEYS:
                    continue
                walk(v, f"{path}.{k}" if path else str(k), slide)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                s = slide
                if path == "slides":
                    s = i + 1
                walk(v, f"{path}[{i}]", s)
        elif isinstance(node, str):
            is_title = bool(re.fullmatch(r"slides\[\d+\]\.title", path)) or path == "title"
            for rule, msg in lint_text(node, kind="title" if is_title else "text"):
                out.append({"severity": "critical", "rule": rule, "slide": slide or 0, "shape_id": None,
                            "shape_name": path, "message": f"{msg} at {path}"})

    walk(spec, "", None)
    return out
