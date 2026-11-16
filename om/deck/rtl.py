"""RTL helpers: detection, measurement shaping, geometry mirroring, digit conversion.

Key decision (D-S3-rtl-digits): finance decks keep Latin digits in Arabic text (Gulf banking
convention); `digits(..., "arabic-indic")` is available but never applied by default.
"""
from __future__ import annotations

import copy
import re
from typing import Any

CANVAS_W = 13.333
_RTL_RE = re.compile(r"[֐-׿؀-ۿݐ-ݿࢠ-ࣿיִ-﷿ﹰ-﻿]")
_LATIN_RE = re.compile(r"[A-Za-zÀ-ɏͰ-ϿЀ-ӿ]")


def is_rtl(text: str) -> bool:
    """True if more than 30 % of letters are Arabic/Hebrew."""
    rtl = len(_RTL_RE.findall(text))
    other = len(_LATIN_RE.findall(text))
    return rtl + other > 0 and rtl / (rtl + other) > 0.30


def shape(text: str) -> str:
    """Reshape Arabic into presentation forms. For measurement only, never written to pptx."""
    try:
        import arabic_reshaper
        return arabic_reshaper.reshape(text)
    except Exception:
        return text


def mirror_x(x: float, w: float, canvas_w: float = CANVAS_W) -> float:
    return round(canvas_w - x - w, 2)


_AI = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
_LAT = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def digits(text: str, style: str = "latin") -> str:
    """Convert digits to 'latin' (default, finance convention) or 'arabic-indic'."""
    if style == "arabic-indic":
        return text.translate(_AI)
    if style == "latin":
        return text.translate(_LAT)
    raise ValueError(f"unknown digit style {style!r}")


def _get(o: Any, k: str, default: Any = None) -> Any:
    return o.get(k, default) if isinstance(o, dict) else getattr(o, k, default)


def _set(o: Any, k: str, v: Any) -> None:
    if isinstance(o, dict):
        o[k] = v
    else:
        setattr(o, k, v)


_FLIP = {"l": "r", "r": "l"}


def _mirror_element(e: Any, canvas_w: float) -> None:
    x, w = _get(e, "x"), _get(e, "w")
    if x is not None and w is not None:
        _set(e, "x", mirror_x(x, w, canvas_w))
    t = _get(e, "text")
    if t is not None:
        for p in _get(t, "paras", []) or []:
            a = _get(p, "align", "l")
            _set(p, "align", _FLIP.get(a, a))
    for k in ("chart", "table"):
        d = _get(e, k)
        if isinstance(d, dict):
            d["rtl"] = True


def mirror(slide: Any, canvas_w: float = CANVAS_W) -> Any:
    """Return a mirrored deep copy: x' = W - x - w, rtl=True, aligns l<->r, chart/table rtl flags."""
    s = copy.deepcopy(slide)
    _set(s, "rtl", True)
    for e in _get(s, "elements", []) or []:
        _mirror_element(e, canvas_w)
    return s
