"""Deterministic variety rules: no consecutive repeats, enough distinct visual types, and a templated-deck detector."""
from __future__ import annotations

import math

GRID_IN = .25
NON_CONTENT = {"cover", "divider", "closing", "agenda"}


def _g(o, *names, default=None):
    for n in names:
        v = o.get(n) if isinstance(o, dict) else getattr(o, n, None)
        if v is not None:
            return v
    return default


def _elements(slide) -> list:
    return list(_g(slide, "elements", default=[]) or [])


def _box(e):
    b = _g(e, "box")
    if b is not None and not isinstance(b, (int, float)):
        b = tuple(b) if not isinstance(b, dict) else (b.get("x"), b.get("y"), b.get("w"), b.get("h"))
        if len(b) == 4:
            return b
    vals = tuple(_g(e, k) for k in ("x", "y", "w", "h"))
    return vals if all(isinstance(v, (int, float)) for v in vals) else None


def _q(v: float) -> int:
    return round(v / GRID_IN)


def _vtype(slide):
    return _g(slide, "visual_type", default=None) or _g(_g(slide, "spec", default={}) or {}, "visual_type")


def _arch(slide):
    return _g(slide, "archetype", default=None) or _g(_g(slide, "spec", default={}) or {}, "archetype")


def signature(slide) -> frozenset:
    cells = set()
    for e in _elements(slide):
        b = _box(e)
        if b:
            cells.add(("box", str(_g(e, "role", "kind", default="")), _q(b[0]), _q(b[1]), _q(b[2]), _q(b[3])))
    cells.add(("arch", _arch(slide)))
    cells.add(("vt", _vtype(slide)))
    return frozenset(cells)


def similarity(a, b) -> float:
    sa, sb = (a if isinstance(a, frozenset) else signature(a)), (b if isinstance(b, frozenset) else signature(b))
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0


def _f(rule, slide, msg):
    return {"severity": "major", "rule": rule, "slide": slide, "shape_id": None, "shape_name": None, "message": msg}


def check(slides, *, templated_ratio: float = .30, templated_sim: float = .85) -> list[dict]:
    slides = list(slides)
    n, out = len(slides), []
    nums = [_g(s, "number", "index", default=i + 1) for i, s in enumerate(slides)]
    arch, vt = [_arch(s) for s in slides], [_vtype(s) for s in slides]
    for i in range(1, n):
        if arch[i] is not None and arch[i] == arch[i - 1] and vt[i] == vt[i - 1]:
            out.append(_f("variety", nums[i], f"slides {nums[i - 1]} and {nums[i]} repeat archetype {arch[i]!r} with visual type {vt[i]!r}"))
    if n >= 2:
        w = min(10, n)
        need = 5 if n >= 10 else math.ceil(n / 2)
        for i in range(n - w + 1):
            d = len(set(vt[i:i + w]))
            if d < need:
                out.append(_f("variety", nums[i], f"slides {nums[i]}-{nums[i + w - 1]} use only {d} distinct visual types (need {need})"))
                break
    content = [i for i in range(n) if arch[i] not in NON_CONTENT]
    sigs = {i: signature(slides[i]) for i in content}
    pairs = [(similarity(sigs[a], sigs[b]), a, b) for k, a in enumerate(content) for b in content[k + 1:]]
    if pairs:
        hot = sum(1 for s, _, _ in pairs if s > templated_sim)
        if hot / len(pairs) > templated_ratio:
            s, a, b = max(pairs)
            out.append(_f("templated", nums[b], f"{hot}/{len(pairs)} content-slide pairs are near-identical in layout (>{templated_sim:.2f}); "
                                                f"worst: slides {nums[a]} and {nums[b]} ({s:.2f})"))
    return out
