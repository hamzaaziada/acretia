"""Real glyph metrics for text fitting (fontTools cmap + hmtx), PowerPoint-style greedy wrap.

Measurement only: fonts are metric-compatible proxies (Arial->Liberation Sans, Calibri->Carlito,
Cambria->Caladea/Liberation Serif, Arabic->Noto Sans Arabic); on macOS/Windows the real Arial, Calibri,
Cambria etc. are found by file name. Missing fonts fall back to DejaVu, then to a constant-width
estimate, with a warning, never a crash. ACRETIA_FONT_DIRS overrides the search roots. Line breaking stays in logical order; python-bidi is not used.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

SAFETY = 0.97          # 3 % width safety margin
LINE_FACTOR = 1.2      # line height = 1.2 x size x line_spacing
HOUSE_FONTS = {"major": "Cambria", "minor": "Arial"}
_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")

# Search roots, in order. ACRETIA_FONT_DIRS (os.pathsep-separated) replaces the list and disables
# fc-match, so a macOS or Windows layout can be simulated on Linux.
_DEFAULT_DIRS = [
    "/usr/share/fonts", "/usr/local/share/fonts", "~/.fonts", "~/.local/share/fonts",   # Linux
    "/System/Library/Fonts/Supplemental", "/System/Library/Fonts", "/Library/Fonts", "~/Library/Fonts",  # macOS
    "C:/Windows/Fonts",                                                                  # Windows
]
# key -> (fc-match proxy, ((regular files...), (bold files...))); real fonts and proxies, first hit wins
_PROXY = {
    "arial": ("Liberation Sans", (
        ("LiberationSans-Regular.ttf", "Arial.ttf", "arial.ttf"),
        ("LiberationSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"))),
    "calibri": ("Carlito", (
        ("Carlito-Regular.ttf", "Calibri.ttf", "calibri.ttf"),
        ("Carlito-Bold.ttf", "Calibri Bold.ttf", "calibrib.ttf"))),
    "cambria": ("Caladea", (
        ("Caladea-Regular.ttf", "Cambria.ttf", "cambria.ttc", "LiberationSerif-Regular.ttf", "Times New Roman.ttf", "times.ttf"),
        ("Caladea-Bold.ttf", "Cambria Bold.ttf", "cambriab.ttf", "LiberationSerif-Bold.ttf", "Times New Roman Bold.ttf", "timesbd.ttf"))),
    "arabic": ("Noto Sans Arabic", (
        ("NotoSansArabic-Regular.ttf", "NotoSansArabic[wdth,wght].ttf", "NotoSansArabic.ttf", "Arial.ttf", "arial.ttf",
         "GeezaPro.ttc", "Geeza Pro.ttc", "Tahoma.ttf", "tahoma.ttf", "DejaVuSans.ttf"),
        ("NotoSansArabic-Bold.ttf", "NotoSansArabic[wdth,wght].ttf", "NotoSansArabic.ttf", "Arial Bold.ttf", "arialbd.ttf",
         "GeezaPro.ttc", "Geeza Pro.ttc", "Tahoma Bold.ttf", "tahomabd.ttf", "DejaVuSans-Bold.ttf"))),
    "dejavu": ("DejaVu Sans", (("DejaVuSans.ttf",), ("DejaVuSans-Bold.ttf",))),
}


def _dirs() -> list[str]:
    env = os.environ.get("ACRETIA_FONT_DIRS")
    raw = [d for d in env.split(os.pathsep) if d] if env is not None else _DEFAULT_DIRS
    return [os.path.expanduser(d) for d in raw]


@lru_cache(maxsize=None)
def _index(dirs: tuple[str, ...]) -> dict[str, str]:
    """Lower-cased basename -> path over all font roots (earlier roots win)."""
    out: dict[str, str] = {}
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for n in files:
                out.setdefault(n.lower(), os.path.join(root, n))
    return out


@dataclass
class Theme:
    """Minimal theme stand-in: only the fonts dict is used here."""
    fonts: dict[str, str]


@dataclass
class Measure:
    lines: int
    height_in: float
    widest_in: float
    line_texts: list[str]


def _find_file(names: tuple[str, ...]) -> str | None:
    idx = _index(tuple(_dirs()))
    for n in names:
        if n.lower() in idx:
            return idx[n.lower()]
    return None


def _fc_match(proxy: str, bold: bool) -> str | None:
    if os.environ.get("ACRETIA_FONT_DIRS") is not None or not shutil.which("fc-match"):
        return None
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}|%{family}", f"{proxy}:{'bold' if bold else 'regular'}"],
                             capture_output=True, text=True, timeout=5).stdout
        path, _, fam = out.partition("|")
        if path and os.path.exists(path) and proxy.split()[0].lower() in fam.lower():
            return path
    except Exception:
        pass
    return None


@lru_cache(maxsize=None)
def _resolve(family: str, bold: bool) -> str | None:
    """Exact resolution only (no fallback): fc-match proxy, then known file names in the search roots."""
    key = family.lower()
    if key in ("major", "minor"):
        key = HOUSE_FONTS[key].lower()
    if key in _PROXY:
        proxy, (reg, bld) = _PROXY[key]
        return _fc_match(proxy, bold) or _find_file(bld if bold else reg)
    base = family.strip()
    return _find_file((f"{base} Bold.ttf", f"{base}.ttf") if bold else (f"{base}.ttf",))


_WARNED: set[str] = set()


def font_path(font: str, bold: bool = False, arabic: bool = False) -> str | None:
    """Path of the font file used to measure `font` (real font, else metric proxy, else DejaVu), or None."""
    fam = "arabic" if arabic else font
    path = _resolve(fam, bold)
    if path is None:
        path = _resolve("dejavu", bold)
        if f"{fam}|{path}" not in _WARNED:
            _WARNED.add(f"{fam}|{path}")
            warnings.warn(f"font {fam!r} not found; falling back to DejaVu Sans", stacklevel=3)
    return path


def available() -> dict:
    """Which proxies were found: {key: {"regular": path|None, "bold": path|None}}."""
    return {k: {"regular": _resolve(k, False), "bold": _resolve(k, True)} for k in _PROXY}


def _pick_face(path: str, bold: bool) -> int:
    """Index of the upright regular/bold face inside a .ttc collection (0 when none matches)."""
    from fontTools.ttLib import TTCollection
    coll = TTCollection(path)
    try:
        for i, f in enumerate(coll.fonts):
            sub = (f["name"].getDebugName(2) or "").lower()
            if "italic" not in sub and "oblique" not in sub and ("bold" in sub) == bold:
                return i
        return 0
    finally:
        coll.close()


@lru_cache(maxsize=None)
def _load(path: str, bold: bool = False) -> tuple[dict[int, str], dict[str, int], int]:
    from fontTools.ttLib import TTFont
    if path.lower().endswith((".ttc", ".otc")):
        f = TTFont(path, fontNumber=_pick_face(path, bold))
    else:
        f = TTFont(path)
    try:
        adv = {g: m[0] for g, m in f["hmtx"].metrics.items()}
        return f.getBestCmap(), adv, f["head"].unitsPerEm
    finally:
        f.close()


@lru_cache(maxsize=None)
def _font(family: str, bold: bool) -> tuple[dict[int, str], dict[str, int], int]:
    path = font_path(family, bold)
    if path is not None:
        try:
            return _load(path, bold)
        except Exception as e:   # unreadable font file: degrade, never crash
            warnings.warn(f"font file {path} unreadable ({e}); using constant-width estimate", stacklevel=3)
    else:
        warnings.warn("no usable fonts found; using constant-width estimate", stacklevel=3)
    return {}, {}, 2   # every glyph 0.5 em, the same estimate used for unmapped characters


def family_for(font: str, theme: Theme | None = None) -> str:
    if font in ("major", "minor"):
        return (theme.fonts.get(font) if theme else None) or HOUSE_FONTS[font]
    return font


def _adv(text: str, family: str, bold: bool) -> float:
    cmap, hmtx, upm = _font(family, bold)
    total = 0
    for ch in text:
        g = cmap.get(ord(ch))
        total += hmtx[g] if g else upm // 2
    return total / upm


def _prep(text: str, family: str, bold: bool) -> tuple[str, str]:
    """Return (text to measure, family). Arabic is shaped and uses the Arabic proxy font."""
    if _ARABIC_RE.search(text):
        from .rtl import shape
        cmap = _font("arabic", bold)[0]
        shaped = shape(text)
        ok = sum(1 for c in shaped if c.isspace() or ord(c) in cmap)
        return (shaped if ok >= 0.95 * len(shaped) else text), "arabic"   # else base chars (conservative)
    return text, family


def _w(text: str, size_pt: float, bold: bool, fam: str) -> float:
    t, f = _prep(text, fam, bold)
    return _adv(t, f, bold) * size_pt / 72.0


def text_width(text: str, size_pt: float, *, bold: bool = False, font: str = "minor",
               theme: Theme | None = None) -> float:
    """Single-line width in inches (no safety margin)."""
    return _w(text, size_pt, bold, family_for(font, theme))


def _wrap(text: str, size_pt: float, limit: float, bold: bool, fam: str) -> list[str]:
    lines: list[str] = []
    for hard in text.split("\n"):
        cur = ""
        for w in hard.split(" "):
            cand = w if not cur else cur + " " + w
            if _w(cand, size_pt, bold, fam) <= limit:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            cur = ""
            while _w(w, size_pt, bold, fam) > limit and len(w) > 1:   # break by characters
                n = len(w)
                while n > 1 and _w(w[:n], size_pt, bold, fam) > limit:
                    n -= 1
                lines.append(w[:n])
                w = w[n:]
            cur = w
        lines.append(cur)
    return lines


def measure(text: str, size_pt: float, width_in: float, *, bold: bool = False, font: str = "minor",
            rtl: bool | None = None, line_spacing: float = 1.0, theme: Theme | None = None) -> Measure:
    """Wrap `text` greedily into `width_in` (minus 3 %) and return line count and height.
    `rtl` is accepted for API symmetry; wrapping is in logical order so width is unaffected."""
    fam = family_for(font, theme)
    lines = _wrap(text, size_pt, max(width_in * SAFETY, 0.01), bold, fam)
    widest = max((_w(l, size_pt, bold, fam) for l in lines), default=0.0)
    return Measure(len(lines), len(lines) * LINE_FACTOR * size_pt * line_spacing / 72.0, widest, lines)


def _wrap_runs(p: Any, size_pt: float, limit: float, fam: str) -> int:
    """Line count for a Para with mixed bold/regular runs."""
    words = [(w, bool(getattr(r, "b", False))) for r in p.runs for w in r.t.split(" ")]
    lines, cur = 1, 0.0
    for word, b in words:
        ww = _w(word, size_pt, b, fam)
        add = ww if cur == 0.0 else _w(" ", size_pt, b, fam) + ww
        if cur + add <= limit:
            cur += add
            continue
        if cur != 0.0:
            lines += 1
        extra = int(ww // limit) if ww > limit else 0
        lines += extra
        cur = ww - extra * limit
    return lines


def para_height(paras: list[Any], width_in: float, size_pt: float, *, font: str = "minor",
                line_spacing: float = 1.0, space_after_pt: float | None = None,
                bullet_indent_in: float = 0.25, theme: Theme | None = None) -> float:
    """Height in inches of a multi-paragraph block. Bold runs are measured bold; levels and
    bullets indent the wrap width. `space_after_pt` overrides each Para.space_after when given."""
    fam = family_for(font, theme)
    total = 0.0
    for p in paras:
        indent = bullet_indent_in * (getattr(p, "level", 0) + (1 if getattr(p, "bullet", False) else 0))
        n = _wrap_runs(p, size_pt, max(width_in - indent, 0.1) * SAFETY, fam)
        total += n * LINE_FACTOR * size_pt * line_spacing / 72.0
        sa = space_after_pt if space_after_pt is not None else getattr(p, "space_after", 0)
        total += sa / 72.0
    return total
