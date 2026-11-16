"""Icon library: original line icons on a 24-unit grid (2-unit stroke, round caps), drawn as native PowerPoint
vector shapes (DrawingML custom geometry), so they stay sharp, recolour with the theme and need no images.

Any SVG made of path / circle / ellipse / rect / line / polyline / polygon elements converts, so a larger
open-source set (e.g. Lucide, ISC licence) can be added to ICONS as-is.
"""
from __future__ import annotations

import math
import re
from xml.etree import ElementTree as ET

# name -> SVG inner markup (24 x 24 grid). Elements with fill="1" are solid; everything else is stroked.
ICONS: dict[str, str] = {
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5"/><circle cx="17" cy="8.5" r="2.5"/><path d="M16.5 13.6c2.9.3 5 2.8 5 5.9"/>',
    "dollar": '<path d="M12 2v20"/><path d="M17 6.5C16.2 5 14.3 4 12 4 9.2 4 7 5.6 7 7.8c0 4.9 10 2.6 10 7.6 0 2.2-2.2 3.6-5 3.6-2.5 0-4.4-1.1-5.2-2.8"/>',
    "coins": '<ellipse cx="9" cy="6" rx="6" ry="3"/><path d="M3 6v4c0 1.7 2.7 3 6 3s6-1.3 6-3V6"/><path d="M3 10v4c0 1.7 2.7 3 6 3 .9 0 1.7-.1 2.5-.3"/><ellipse cx="16" cy="15" rx="5" ry="2.5"/><path d="M11 15v3.5c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5V15"/>',
    "bank": '<path d="M12 3l9 5H3z"/><path d="M3 21h18"/><path d="M5 10v8M9.7 10v8M14.3 10v8M19 10v8"/>',
    "bar-chart": '<path d="M3 21h18"/><path d="M6 21v-6M11 21V9M16 21v-9M21 21V4"/>',
    "trending-up": '<polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/>',
    "trending-down": '<polyline points="3 7 9 13 13 9 21 17"/><polyline points="15 17 21 17 21 11"/>',
    "pie-chart": '<path d="M20.5 15A9 9 0 1 1 9 3.5"/><path d="M12 3a9 9 0 0 1 9 9h-9z"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3" fill="1"/>',
    "factory": '<path d="M3 21V10l6 4v-4l6 4V5h5v16z"/><path d="M7 18h2M12 18h2M17 18h1"/>',
    "truck": '<path d="M2 6h11v10H2z"/><path d="M13 9h4.5l3.5 3.5V16h-8"/><circle cx="6" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
    "building": '<rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2"/><path d="M11 21v-3h2v3"/>',
    "store": '<path d="M4 10v11h16V10"/><path d="M3 4h18l-1 6H4z"/><path d="M10 21v-6h4v6"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/>',
    "shield-check": '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><polyline points="8.5 12 11 14.5 15.5 10"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><polyline points="8 12.5 11 15.5 16.5 9.5"/>',
    "x-circle": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "alert": '<path d="M12 3l10 18H2z"/><path d="M12 10v4.5"/><circle cx="12" cy="17.6" r="1" fill="1"/>',
    "document": '<path d="M6 2h8l5 5v15H6z"/><path d="M14 2v5h5"/><path d="M9 13h7M9 17h7"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5L16 16"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>',
    "cloud": '<path d="M7 19h10a4.5 4.5 0 0 0 .7-8.9A6 6 0 0 0 6.2 10 4.5 4.5 0 0 0 7 19z"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "chip": '<rect x="7" y="7" width="10" height="10" rx="1"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
    "cart": '<path d="M2.5 4h2.4l2.4 11h11.2l2-8H6"/><circle cx="9" cy="19.5" r="1.5"/><circle cx="17" cy="19.5" r="1.5"/>',
    "leaf": '<path d="M5 20C5 11 11 5 20 4c0 9-6 15-15 16z"/><path d="M5 20l8.5-8.5"/>',
    "energy": '<polygon points="13 2 4 14 11.5 14 10.5 22 20 10 12.5 10"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/><path d="M3 13h18"/>',
    "rocket": '<path d="M9.5 14.5C10.5 9 14 4.5 20 4c-.5 6-5 9.5-10.5 10.5z"/><path d="M9.5 14.5l-3.5-.8 2.6-3.3h3.2M9.5 14.5l.8 3.5 3.3-2.6v-3.2"/><path d="M5.5 16.5c-1.3 1-1.8 2.8-2 4 1.2-.2 3-.7 4-2"/>',
    "flag": '<path d="M5 21V4"/><path d="M5 4h13l-2.5 4.5L18 13H5"/>',
    "map-pin": '<path d="M12 21s-7-6.3-7-11a7 7 0 0 1 14 0c0 4.7-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><polyline points="3 7 12 13 21 7"/>',
    "mobile": '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    "scale": '<path d="M12 3v17M7 21h10M4 7h16"/><path d="M6 7l-3 7a3 3 0 0 0 6 0z"/><path d="M18 7l-3 7a3 3 0 0 0 6 0z"/>',
    "percent": '<path d="M19 5L5 19"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/>',
    "arrow-right": '<path d="M4 12h16M14 6l6 6-6 6"/>',
    "arrow-up": '<path d="M12 20V4M6 10l6-6 6 6"/>',
    "arrow-down": '<path d="M12 4v16M6 14l6 6 6-6"/>',
    "layers": '<polygon points="12 3 21 8 12 13 3 8"/><polyline points="3 12 12 17 21 12"/><polyline points="3 16 12 21 21 16"/>',
    "filter": '<polygon points="3 4 21 4 14 12.5 14 20 10 18 10 12.5"/>',
    "trophy": '<path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H5a3 3 0 0 0 3 4.5M16 6h3a3 3 0 0 1-3 4.5"/><path d="M12 13v4M8.5 21h7M10 17h4v4h-4z"/>',
    "spark": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16v4M17 18h4"/>',
    "robot": '<rect x="5" y="8" width="14" height="11" rx="2"/><path d="M12 4.5V8"/><circle cx="12" cy="3.5" r="1"/><circle cx="9.5" cy="13" r="1.2" fill="1"/><circle cx="14.5" cy="13" r="1.2" fill="1"/><path d="M9.5 16.5h5M3 12v3M21 12v3"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><polyline points="20 4 20 9 15 9"/>',
    "hierarchy": '<rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4M6 16v-4h12v4"/>',
    "checklist": '<path d="M10 6h11M10 12h11M10 18h11"/><polyline points="3 6 4.5 7.5 7 5"/><polyline points="3 12 4.5 13.5 7 11"/><polyline points="3 18 4.5 19.5 7 17"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "home": '<path d="M3 11l9-8 9 8"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
    "tools": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 0 0 5.2-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    "health": '<path d="M12 20s-8-5-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 9c0 6-8 11-8 11z"/><path d="M8 11.5h2.5l1-2 2 4 1-2H16"/>',
    "education": '<polygon points="12 4 22 9 12 14 2 9"/><path d="M6 11v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5"/><path d="M22 9v6"/>',
    "handshake-deal": '<path d="M3 12l4-4 4 2 3-2 7 5-3 3"/><path d="M8 15l3 3 3-2 2 2"/><path d="M3 12l3 3"/>',
    "plane": '<path d="M2.5 13.5l7-1.5 5-7.5c.6-.9 2-.9 2.4.2.3.7.1 1.4-.4 2L13 12l2.5 6.5-1.5 1-4-5.5-4.5 1-1.5 2-1.5-.5.5-2.5z"/>',
    "wallet": '<path d="M3 7a2 2 0 0 1 2-2h13v4"/><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M16 13.5h2"/>',
    "receipt": '<path d="M6 2h12v20l-3-2-3 2-3-2-3 2z"/><path d="M9 7h6M9 11h6M9 15h4"/>',
    "lightbulb-off": '<circle cx="12" cy="12" r="0.1"/>',
}
del ICONS["lightbulb-off"]       # no lightbulbs: a stock cliché

KEYWORDS: dict[str, str] = {
    "user": "person customer employee member", "users": "people team customers workforce talent headcount",
    "dollar": "money cash price revenue cost", "coins": "money savings returns dividend capital", "bank": "bank finance lender debt treasury",
    "bar-chart": "ranking comparison data analytics", "trending-up": "growth increase upside", "trending-down": "decline decrease downside",
    "pie-chart": "share mix portion market share", "target": "goal objective aim kpi", "factory": "manufacturing production plant operations",
    "truck": "logistics delivery supply chain distribution", "globe": "global international markets world", "building": "company office headquarters real estate",
    "store": "retail shop warehouse club branch", "shield": "risk protection security compliance", "shield-check": "risk mitigated safe approved",
    "clock": "time speed timing deadline", "calendar": "schedule date plan timeline", "check-circle": "done approved yes complete",
    "x-circle": "no rejected stop fail", "alert": "warning risk issue caution", "document": "report filing contract policy",
    "search": "research diligence analysis review", "lock": "secure private locked covenant", "cloud": "cloud software saas",
    "database": "data storage records", "chip": "technology semiconductor hardware ai compute", "cart": "ecommerce purchase shopping consumer",
    "leaf": "esg sustainability environment green", "energy": "power electricity energy fast", "link": "integration partnership connection",
    "briefcase": "business deal m&a professional", "rocket": "launch growth scale startup", "flag": "milestone start priority",
    "map-pin": "location site geography", "mail": "communication email outreach", "mobile": "app digital phone",
    "scale": "balance trade-off legal fairness", "percent": "rate yield margin percentage", "arrow-right": "next step flow",
    "arrow-up": "increase up", "arrow-down": "decrease down", "layers": "stack platform layers segments", "filter": "funnel screen pipeline",
    "trophy": "winner best leadership award", "spark": "new innovation idea insight", "robot": "automation ai robot",
    "refresh": "cycle renewal recurring loop", "hierarchy": "organisation structure org chart governance", "checklist": "plan actions tasks process",
    "eye": "visibility monitoring view", "home": "housing residential home", "tools": "operations maintenance fix build",
    "health": "healthcare medical wellbeing", "education": "training education talent skills", "handshake-deal": "agreement partnership deal",
    "plane": "travel aviation expansion", "wallet": "spend consumer payments wallet", "receipt": "invoice billing transaction cost",
}

_K = 0.5522847498            # circle-to-bezier constant


def _gear(cx=12.0, cy=12.0, r_out=9.5, r_in=7.2, teeth=8) -> str:
    pts = []
    for k in range(teeth * 2):
        a0 = math.pi * 2 * k / (teeth * 2)
        a1 = math.pi * 2 * (k + 1) / (teeth * 2)
        r = r_out if k % 2 == 0 else r_in
        pts += [(cx + r * math.cos(a0 + 0.12), cy + r * math.sin(a0 + 0.12)), (cx + r * math.cos(a1 - 0.12), cy + r * math.sin(a1 - 0.12))]
    d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + "Z"
    return f'<path d="{d}"/><circle cx="12" cy="12" r="3"/>'


ICONS["gear"] = _gear()
KEYWORDS["gear"] = "settings operations process engine"


# --------------------------------------------------------------------------- SVG -> DrawingML
def _tokens(d: str):
    for m in re.finditer(r"[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?", d):
        yield m.group(0)


def _arc_to_beziers(x1, y1, rx, ry, phi, fa, fs, x2, y2):
    """SVG endpoint arc -> cubic Béziers (W3C F.6.5)."""
    if rx == 0 or ry == 0:
        return [("L", (x2, y2))]
    cp, sp = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    rx, ry = abs(rx), abs(ry)
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if fa == fs:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not fs and dt > 0:
        dt -= 2 * math.pi
    elif fs and dt < 0:
        dt += 2 * math.pi
    n = max(1, int(math.ceil(abs(dt) / (math.pi / 2) - 1e-9)))
    seg = dt / n
    out = []
    for k in range(n):
        a, b = t1 + k * seg, t1 + (k + 1) * seg
        al = 4 / 3 * math.tan((b - a) / 4)
        p = []
        for (ux, uy) in ((math.cos(a) - al * math.sin(a), math.sin(a) + al * math.cos(a)),
                         (math.cos(b) + al * math.sin(b), math.sin(b) - al * math.cos(b)),
                         (math.cos(b), math.sin(b))):
            x, y = rx * ux, ry * uy
            p.append((cp * x - sp * y + cx, sp * x + cp * y + cy))
        out.append(("C", tuple(p)))
    return out


def _path_cmds(d: str) -> list[list]:
    """-> list of subpaths, each [("M",(x,y)), ("L",(x,y)) | ("C",((x,y),(x,y),(x,y))) | ("Q",…) | ("Z",None)]"""
    toks = list(_tokens(d))
    i, cmd = 0, None
    x = y = sx = sy = 0.0
    lc = lq = None
    subs, cur = [], None

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v
    while i < len(toks):
        if re.fullmatch(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                if cur is not None:
                    cur.append(("Z", None))
                x, y = sx, sy
                lc = lq = None
                continue
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            sx, sy = x, y
            cur = [("M", (x, y))]
            subs.append(cur)
            cmd = "l" if rel else "L"
            lc = lq = None
        elif c in "LHV":
            if c == "L":
                nx, ny = num(), num()
                x, y = (x + nx, y + ny) if rel else (nx, ny)
            elif c == "H":
                v = num()
                x = x + v if rel else v
            else:
                v = num()
                y = y + v if rel else v
            cur.append(("L", (x, y)))
            lc = lq = None
        elif c in "CS":
            if c == "C":
                p1 = (num(), num())
            else:
                p1 = (2 * x - lc[0], 2 * y - lc[1]) if lc else (x, y)
                p1 = (p1[0] - x, p1[1] - y) if rel else p1
            p2, p3 = (num(), num()), (num(), num())
            if rel:
                p1 = (x + p1[0], y + p1[1]) if c == "C" else (x + p1[0], y + p1[1])
                p2, p3 = (x + p2[0], y + p2[1]), (x + p3[0], y + p3[1])
            cur.append(("C", (p1, p2, p3)))
            lc, lq = p2, None
            x, y = p3
        elif c in "QT":
            if c == "Q":
                p1 = (num(), num())
                if rel:
                    p1 = (x + p1[0], y + p1[1])
            else:
                p1 = (2 * x - lq[0], 2 * y - lq[1]) if lq else (x, y)
            p2 = (num(), num())
            if rel:
                p2 = (x + p2[0], y + p2[1])
            cur.append(("Q", (p1, p2)))
            lq, lc = p1, None
            x, y = p2
        elif c == "A":
            rx, ry, phi, fa, fs, nx, ny = num(), num(), num(), num(), num(), num(), num()
            if rel:
                nx, ny = x + nx, y + ny
            cur.extend(_arc_to_beziers(x, y, rx, ry, phi, int(fa), int(fs), nx, ny))
            x, y = nx, ny
            lc = lq = None
        else:
            i += 1
    return subs


def _ellipse(cx, cy, rx, ry):
    kx, ky = rx * _K, ry * _K
    return [[("M", (cx + rx, cy)),
             ("C", ((cx + rx, cy + ky), (cx + kx, cy + ry), (cx, cy + ry))),
             ("C", ((cx - kx, cy + ry), (cx - rx, cy + ky), (cx - rx, cy))),
             ("C", ((cx - rx, cy - ky), (cx - kx, cy - ry), (cx, cy - ry))),
             ("C", ((cx + kx, cy - ry), (cx + rx, cy - ky), (cx + rx, cy))), ("Z", None)]]


def _rect(x, y, w, h, r):
    if r <= 0:
        return [[("M", (x, y)), ("L", (x + w, y)), ("L", (x + w, y + h)), ("L", (x, y + h)), ("Z", None)]]
    r = min(r, w / 2, h / 2)
    k = r * _K
    return [[("M", (x + r, y)), ("L", (x + w - r, y)), ("C", ((x + w - r + k, y), (x + w, y + r - k), (x + w, y + r))),
             ("L", (x + w, y + h - r)), ("C", ((x + w, y + h - r + k), (x + w - r + k, y + h), (x + w - r, y + h))),
             ("L", (x + r, y + h)), ("C", ((x + r - k, y + h), (x, y + h - r + k), (x, y + h - r))),
             ("L", (x, y + r)), ("C", ((x, y + r - k), (x + r - k, y), (x + r, y))), ("Z", None)]]


def _points(s: str):
    v = [float(t) for t in re.findall(r"-?(?:\d+\.?\d*|\.\d+)", s)]
    return list(zip(v[0::2], v[1::2]))


def parse(markup: str) -> list[tuple[list, bool]]:
    """SVG inner markup -> [(subpath, filled)]"""
    root = ET.fromstring(f"<svg>{markup}</svg>")
    out = []
    for el in root:
        tag = el.tag.split("}")[-1]
        a = el.attrib
        filled = a.get("fill") not in (None, "none", "0")
        f = lambda k, d=0.0: float(a.get(k, d))  # noqa: E731
        if tag == "path":
            subs = _path_cmds(a.get("d", ""))
        elif tag == "circle":
            subs = _ellipse(f("cx"), f("cy"), f("r"), f("r"))
        elif tag == "ellipse":
            subs = _ellipse(f("cx"), f("cy"), f("rx"), f("ry"))
        elif tag == "rect":
            subs = _rect(f("x"), f("y"), f("width"), f("height"), f("rx", a.get("ry", 0)))
        elif tag == "line":
            subs = [[("M", (f("x1"), f("y1"))), ("L", (f("x2"), f("y2")))]]
        elif tag in ("polyline", "polygon"):
            pts = _points(a.get("points", ""))
            if not pts:
                continue
            sub = [("M", pts[0])] + [("L", p) for p in pts[1:]] + ([("Z", None)] if tag == "polygon" else [])
            subs = [sub]
        else:
            continue
        out += [(s, filled) for s in subs]
    return out


def custgeom(name: str, scale: int = 1000) -> str:
    """DrawingML <a:custGeom> for an icon: stroked subpaths (fill none) and solid ones (stroke off)."""
    if name not in ICONS:
        raise KeyError(f"unknown icon {name!r}")
    S = 24 * scale

    def pt(p):
        return f'<a:pt x="{int(round(p[0] * scale))}" y="{int(round(p[1] * scale))}"/>'
    paths = []
    for sub, filled in parse(ICONS[name]):
        cmds = []
        for op, arg in sub:
            if op == "M":
                cmds.append(f"<a:moveTo>{pt(arg)}</a:moveTo>")
            elif op == "L":
                cmds.append(f"<a:lnTo>{pt(arg)}</a:lnTo>")
            elif op == "C":
                cmds.append(f"<a:cubicBezTo>{''.join(pt(p) for p in arg)}</a:cubicBezTo>")
            elif op == "Q":
                cmds.append(f"<a:quadBezTo>{''.join(pt(p) for p in arg)}</a:quadBezTo>")
            elif op == "Z":
                cmds.append("<a:close/>")
        attrs = ' fill="norm" stroke="0"' if filled else ' fill="none"'
        paths.append(f'<a:path w="{S}" h="{S}"{attrs}>{"".join(cmds)}</a:path>')
    return (f'<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/>'
            f'<a:pathLst>{"".join(paths)}</a:pathLst></a:custGeom>')


def find(query: str, n: int = 5) -> list[str]:
    """Best icon names for a word or phrase."""
    q = set(re.findall(r"[a-z&]+", query.lower()))
    scored = []
    for name, kw in KEYWORDS.items():
        words = set(kw.split()) | set(name.split("-"))
        s = len(q & words) * 2 + sum(1 for w in q for k in words if len(w) > 4 and len(k) > 4 and (w.startswith(k) or k.startswith(w)))
        if s:
            scored.append((s, name))
    return [n_ for _, n_ in sorted(scored, key=lambda t: (-t[0], t[1]))[:n]]


def catalogue() -> str:
    return ", ".join(sorted(ICONS))
