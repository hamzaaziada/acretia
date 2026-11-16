"""Hard delivery gate: a workbook is delivered only if every deterministic check passes.

Order: grade, validate_xlsx, recalc comparison, master check, manifest. ``deliver`` writes nothing unless all pass.
"""
from __future__ import annotations

import json
import os

from . import manifest as mf
from . import xlsx


class DeliveryBlocked(Exception):
    def __init__(self, report: dict):
        self.report = report
        bad = [s["name"] for s in report.get("steps", []) if not s["passed"]]
        super().__init__("delivery blocked: " + ", ".join(bad))


def _step(name, fn):
    try:
        ok, detail, extra = fn()
    except Exception as e:  # a gate that cannot run is a failed gate
        ok, detail, extra = False, f"{type(e).__name__}: {e}", None
    return {"name": name, "passed": bool(ok), "detail": detail}, extra


def _grade(data):
    from . import modelcheck
    g = modelcheck.grade(data)
    bad = [x.get("id") or x.get("title") for x in g["graders"] if x.get("critical") and x.get("passed") is False]
    return not bad, (f"score {g['score']}" if not bad else "critical graders failed: " + ", ".join(map(str, bad))), None


def _validate(data):
    from . import validate_xlsx
    r = validate_xlsx.validate(data)
    ok = bool(r.get("passed"))
    f = r.get("findings") or []
    return ok, "passed" if ok else f"{len(f)} findings; first: {f[0] if f else None}", None


def _recalc(data, require):
    from . import recalc
    r = recalc.compare(data)
    engines = r.get("engines", {})
    missing = [e for e in require if not (engines.get(e) or {}).get("available")]
    if missing:
        return False, "required engine unavailable: " + ", ".join(f"{e} ({(engines.get(e) or {}).get('reason', 'not reported')})" for e in missing), None
    ok = bool(r.get("agree"))
    d = r.get("divergences") or []
    return ok, (f"{r.get('compared_cells', 0)} cells agree" if ok else f"{len(d)} divergences; first: {d[0] if d else None}"), None


def _master(data, meta):
    grid = xlsx.read(data).sheets.get("Checks")
    if grid is None:
        return False, "no Checks sheet", None
    r = ((meta.get("rows") or {}).get("Checks") or {}).get("master")
    cell = grid.get((r, 3)) if r else None
    if cell is None:
        for (rr, cc), c in sorted(grid.items()):
            if cc == 1 and isinstance(c.value, str) and "master" in c.value.lower():
                cell = grid.get((rr, 3))
                break
    if cell is None:
        return False, "master check cell not found", None
    return cell.value == "OK", f"master check reads {cell.value!r}", None


def _manifest(data, meta):
    man, values = mf.export_with_values(data, meta)
    book = xlsx.read(data)
    problems = []
    if not man.outputs:
        problems.append("no outputs")
    hist = mf.historical_ids(data, meta)
    for o in man.outputs:
        cell = book.sheets.get(o.sheet, {}).get(xlsx.split_ref(o.ref.replace("$", "").split(":")[0]))
        v = values.get(o.id)
        if cell is None:
            problems.append(f"{o.id}: cell {o.sheet}!{o.ref} does not exist")
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            problems.append(f"{o.id}: {o.sheet}!{o.ref} has no numeric cached value ({v!r})")
        if o.id in hist and not o.citations:
            problems.append(f"{o.id}: no citation")
    return not problems, ("; ".join(problems[:5]) if problems else f"{len(man.outputs)} outputs, all cited"), (man, values)


def gate(data: bytes, meta: dict, *, circ0_data: bytes | None = None, require_engines=("om",)) -> dict:
    steps, man = [], None
    for name, fn in (("modelcheck.grade", lambda: _grade(data)),
                     ("validate_xlsx", lambda: _validate(data)),
                     ("recalc.compare", lambda: _recalc(circ0_data or data, require_engines)),
                     ("master_check", lambda: _master(data, meta)),
                     ("manifest", lambda: _manifest(data, meta))):
        s, extra = _step(name, fn)
        steps.append(s)
        if name == "manifest" and extra:
            man = extra
    out = {"passed": all(s["passed"] for s in steps), "steps": steps, "manifest": man[0].to_dict() if man else None}
    if man:
        out["values"] = man[1]
    return out


def deliver(data: bytes, meta: dict, out_dir, *, name: str, circ0_data: bytes | None = None) -> dict:
    report = gate(data, meta, circ0_data=circ0_data)
    if not report["passed"]:
        raise DeliveryBlocked(report)
    man = mf.export(data, meta)
    files = {"xlsx": (f"{name}.xlsx", data), "manifest": (f"{name}.manifest.json", mf.to_json(man).encode()),
             "report": (f"{name}.report.json", json.dumps(report, sort_keys=True, indent=2, default=str).encode())}
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for k, (fn, blob) in files.items():
        p = os.path.join(out_dir, fn)
        with open(p + ".tmp", "wb") as f:
            f.write(blob)
        paths[k] = p
    for p in paths.values():
        os.replace(p + ".tmp", p)
    return paths
