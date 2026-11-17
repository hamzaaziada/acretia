#!/usr/bin/env python3
"""S2.4b gate: Excel MCP daemon wiring.

Proves that src/harness/mcp/excel_server.py recalculates workbooks through om.recalc.compare and reports the
state of the recalculation engines honestly, including when LibreOffice is not usable.

Written from docs/gates/s2.4b-gate-spec.md by a worker who did not write the implementation and did not read
tests/test_mcp_excel_daemon.py. Offline; never calls a live model. Exits non-zero on any failure.
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# The gate writes its workbook into a private root; the server confines every path to ACRETIA_MCP_ROOT.
_TMP = tempfile.mkdtemp(prefix="acretia-s2-4b-gate-")
os.environ["ACRETIA_MCP_ROOT"] = _TMP

RESULTS: list[tuple[str, str, str]] = []   # (status, name, detail)
_ENGINE_NOTES: list[str] = []              # assertion 23: per-engine exercised/skipped lines


def check(name):
    """Run one assertion. PASS on return, FAIL on any exception, SKIPPED on _Skip."""
    def deco(fn):
        try:
            detail = str(fn() or "")
            RESULTS.append(("PASS", name, detail))
        except _Skip as e:
            RESULTS.append(("SKIPPED", name, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append(("FAIL", name, f"{type(e).__name__}: {e}"[:400]))
            if os.environ.get("VERIFY_DEBUG"):
                traceback.print_exc()
        return fn
    return deco


class _Skip(Exception):
    """Raised when an assertion cannot be earned on this machine; never counts as a pass."""


def expect_tool_failure(fn, contains=None):
    """Call fn; it must raise ToolFailure (a tool ran and failed), not crash the server."""
    from src.harness.mcp.server import ToolFailure
    try:
        fn()
    except ToolFailure as e:
        if contains and contains.lower() not in str(e).lower():
            raise AssertionError(f"ToolFailure {e!r} lacks {contains!r}")
        return str(e)
    except Exception as e:  # noqa: BLE001
        raise AssertionError(f"expected ToolFailure, got {type(e).__name__}: {e}") from None
    raise AssertionError("expected ToolFailure, nothing raised")


# --------------------------------------------------------------------------- fixtures
def _model_bytes() -> bytes:
    """The standard synthetic model, built with circ=0 so every cell is comparable (D-006)."""
    from om import model3
    from om import statements as stm
    from tests.test_model3 import synthetic_companyfacts
    data, _meta = model3.build(stm.build(synthetic_companyfacts(), "TEST"), circ=0)
    return data


def _planted() -> tuple[bytes, str, float]:
    """A real model with one formula cell's cached value moved by +1.0. Returns (bytes, cell ref, delta)."""
    from om import model3
    from om import statements as stm
    from om.xlsx import col_letter
    from tests.test_model3 import synthetic_companyfacts
    wb, _meta = model3.build_workbook(stm.build(synthetic_companyfacts(), "TEST"), circ=0)
    target = None
    for sh in wb.sheets:
        for (r, c), cell in sh.cells.items():
            if (isinstance(cell.value, str) and cell.value.startswith("=")
                    and isinstance(cell.cached, (int, float)) and not isinstance(cell.cached, bool)):
                target = (sh.name, r, c, cell.cached)
                break
        if target:
            break
    if target is None:
        raise AssertionError("no numeric formula cell found in the model to plant a divergence in")
    sh, r, c, cached = target
    wb[sh].cells[(r, c)].cached = cached + 1.0
    ref = f"{sh}!{col_letter(c)}{r}"
    return wb.to_bytes(), ref, 1.0


def _write(name: str, data: bytes) -> str:
    path = os.path.join(_TMP, name)
    with open(path, "wb") as fh:
        fh.write(data)
    return name  # relative to ACRETIA_MCP_ROOT


def _uno_available() -> bool:
    try:
        import uno  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


# --------------------------------------------------------------------------- A. the wiring is real
@check("1. xlsx_recalc on a real model returns available:true and a report with agree/engines/divergences/compared_cells")
def _():
    from src.harness.mcp import excel_server as E
    name = _write("model.xlsx", _model_bytes())
    out = E.xlsx_recalc(name)
    assert out.get("available") is True, f"available is {out.get('available')!r}: {out.get('reason')!r}"
    rep = out["result"]
    for key in ("agree", "engines", "divergences", "compared_cells"):
        assert key in rep, f"report lacks {key!r}; keys={sorted(rep)}"
    assert isinstance(rep["agree"], bool), f"agree is {type(rep['agree']).__name__}"
    assert isinstance(rep["divergences"], list), f"divergences is {type(rep['divergences']).__name__}"
    return f"available=True, agree={rep['agree']}, compared_cells={rep['compared_cells']}"


@check("2. compared_cells > 500 for the standard synthetic model (not a trivially empty report)")
def _():
    from src.harness.mcp import excel_server as E
    name = _write("model.xlsx", _model_bytes())
    n = E.xlsx_recalc(name)["result"]["compared_cells"]
    assert n > 500, f"compared_cells={n}, expected > 500"
    return f"compared_cells={n} > 500"


@check("3. report engines keys are exactly om.recalc.DEFAULT_ENGINES; a missing engine is a key with available:false and a reason")
def _():
    from om import recalc
    from src.harness.mcp import excel_server as E
    name = _write("model.xlsx", _model_bytes())
    engines = E.xlsx_recalc(name)["result"]["engines"]
    assert set(engines) == set(recalc.DEFAULT_ENGINES), \
        f"engines keys {sorted(engines)} != DEFAULT_ENGINES {sorted(recalc.DEFAULT_ENGINES)}"
    for k, info in engines.items():
        assert "available" in info, f"engine {k!r} has no 'available'"
        if info["available"] is False:
            assert info.get("reason"), f"engine {k!r} is unavailable with an empty reason"
    missing = [k for k, v in engines.items() if v["available"] is False]
    return f"keys={sorted(engines)}; unavailable={missing or 'none'} (each with a reason)"


@check("4. ADVERSARIAL: a planted wrong cached value is reported in divergences with the planted delta")
def _():
    from src.harness.mcp import excel_server as E
    data, ref, delta = _planted()
    name = _write("planted.xlsx", data)
    rep = E.xlsx_recalc(name)["result"]
    assert rep["agree"] is False, "tool reported agree:true on a workbook with a planted wrong cached value"
    hit = next((d for d in rep["divergences"] if d.get("cell") == ref), None)
    assert hit is not None, f"planted cell {ref} not in divergences: {[d.get('cell') for d in rep['divergences']][:10]}"
    vals = hit["values"]
    assert "cached" in vals, f"divergence for {ref} has no 'cached' value: {vals}"
    others = [v for k, v in vals.items() if k != "cached" and isinstance(v, (int, float))]
    assert others, f"divergence for {ref} has no numeric non-cached value to compare: {vals}"
    got = abs(vals["cached"] - others[0])
    assert abs(got - delta) <= 1e-6 * max(1.0, abs(vals["cached"])), \
        f"planted delta {delta} not reported; cached={vals['cached']} vs {others[0]} (delta {got})"
    return f"{ref} reported, cached={vals['cached']} vs {others[0]} (delta {got})"


@check("5. ADVERSARIAL: engines=['cached','om'] compares only those two and still finds the planted divergence")
def _():
    from src.harness.mcp import excel_server as E
    data, ref, _delta = _planted()
    name = _write("planted.xlsx", data)
    rep = E.xlsx_recalc(name, engines=["cached", "om"])["result"]
    assert set(rep["engines"]) == {"cached", "om"}, f"engines argument ignored: keys={sorted(rep['engines'])}"
    assert rep["agree"] is False, "engines=['cached','om'] reported agree:true on the planted workbook"
    assert any(d.get("cell") == ref for d in rep["divergences"]), \
        f"planted cell {ref} not found with engines=['cached','om']"
    return f"keys={sorted(rep['engines'])}, {ref} still divergent"


@check("6. ADVERSARIAL: an unknown engine name raises a tool failure, not silently dropped")
def _():
    from src.harness.mcp import excel_server as E
    name = _write("model.xlsx", _model_bytes())
    msg = expect_tool_failure(lambda: E.xlsx_recalc(name, engines=["bogus"]), contains="bogus")
    return f"ToolFailure: {msg[:120]}"


@check("7. ADVERSARIAL: a path outside ACRETIA_MCP_ROOT is refused; a missing file raises a tool failure")
def _():
    from src.harness.mcp import excel_server as E
    outside = expect_tool_failure(lambda: E.xlsx_recalc("/etc/hosts"), contains="root")
    missing = expect_tool_failure(lambda: E.xlsx_recalc("does-not-exist.xlsx"))
    return f"outside -> {outside[:60]!r}; missing -> {missing[:60]!r}"


# --------------------------------------------------------------------------- B. the old bug is gone
@check("8. om.recalc exposes none of recalc_file / recalculate / three_engine / check")
def _():
    from om import recalc
    ghosts = [n for n in ("recalc_file", "recalculate", "three_engine", "check") if hasattr(recalc, n)]
    assert not ghosts, f"om.recalc exposes guessed entry point(s) {ghosts}"
    return "none of the four guessed entry points exist"


@check("9. xlsx_recalc source does not contain 'exposes no recalc entry point' (dead branch cannot return)")
def _():
    from src.harness.mcp import excel_server as E
    src = inspect.getsource(E.xlsx_recalc)
    assert "exposes no recalc entry point" not in src, "the dead branch string is back in xlsx_recalc"
    return "dead-branch string absent from xlsx_recalc source"


# --------------------------------------------------------------------------- C. engine status is honest
@check("10. xlsx_engine_status returns every DEFAULT_ENGINES key with available and reason on each")
def _():
    from om import recalc
    from src.harness.mcp import excel_server as E
    out = E.xlsx_engine_status()
    assert out.get("available") is True, f"available is {out.get('available')!r}: {out.get('reason')!r}"
    engines = out["result"]["engines"]
    assert set(engines) == set(recalc.DEFAULT_ENGINES), \
        f"status keys {sorted(engines)} != DEFAULT_ENGINES {sorted(recalc.DEFAULT_ENGINES)}"
    for k, info in engines.items():
        assert "available" in info, f"engine {k!r} has no 'available'"
        assert "reason" in info, f"engine {k!r} has no 'reason'"
    return f"keys={sorted(engines)}, each with available+reason"


@check("11. om and cached are always available:true")
def _():
    from src.harness.mcp import excel_server as E
    engines = E.xlsx_engine_status()["result"]["engines"]
    for k in ("om", "cached"):
        assert engines[k]["available"] is True, f"engine {k!r} reports available={engines[k]['available']!r}"
    return "om and cached both available:true"


@check("12. ready is true exactly when at least two engines are available")
def _():
    from src.harness.mcp import excel_server as E
    res = E.xlsx_engine_status()["result"]
    n = sum(1 for e in res["engines"].values() if e["available"])
    assert res["ready"] is (n >= 2), f"ready={res['ready']!r} but {n} engines available"
    return f"ready={res['ready']} with {n} engines available"


@check("13. every unavailable engine has a non-empty reason naming its dependency (uno / soffice / formulon)")
def _():
    from src.harness.mcp import excel_server as E
    engines = E.xlsx_engine_status()["result"]["engines"]
    checked = []
    for k, info in engines.items():
        if info["available"]:
            continue
        reason = info.get("reason") or ""
        assert reason.strip(), f"engine {k!r} is unavailable with an empty reason"
        low = reason.lower()
        assert any(d in low for d in ("uno", "soffice", "formulon")), \
            f"engine {k!r} reason {reason!r} names no dependency (uno/soffice/formulon)"
        checked.append(f"{k}: {reason[:70]}")
    return "; ".join(checked) if checked else "no engine unavailable"


@check("14. ADVERSARIAL: xlsx_engine_status does not increase recalc.daemon().starts (no process spawned)")
def _():
    from om import recalc
    from src.harness.mcp import excel_server as E
    before = recalc.daemon().starts
    E.xlsx_engine_status()
    E.xlsx_engine_status()
    after = recalc.daemon().starts
    assert after == before, f"daemon().starts went {before} -> {after} while only asking for status"
    return f"daemon().starts unchanged at {after} across two status calls"


# --------------------------------------------------------------------------- D. restart is safe
@check("15. xlsx_engine_restart returns a status and xlsx_recalc still works afterwards")
def _():
    from src.harness.mcp import excel_server as E
    out = E.xlsx_engine_restart()
    assert out.get("available") is True, f"restart available is {out.get('available')!r}: {out.get('reason')!r}"
    assert "engines" in out["result"], f"restart result has no engines: {sorted(out['result'])}"
    name = _write("model.xlsx", _model_bytes())
    rep = E.xlsx_recalc(name)["result"]
    assert rep["agree"] is True, f"recalc after restart does not agree: {rep['divergences'][:3]}"
    assert rep["compared_cells"] > 500, f"recalc after restart compared only {rep['compared_cells']} cells"
    return f"restart ok; recalc after restart agrees over {rep['compared_cells']} cells"


@check("16. when LibreOffice is unavailable, restart still returns available:true with the reason recorded, not raise")
def _():
    from src.harness.mcp import excel_server as E
    if _uno_available():
        raise _Skip("uno bridge is importable on this machine; the unavailable path cannot be exercised here")
    out = E.xlsx_engine_restart()
    assert out.get("available") is True, f"restart raised/failed instead of reporting: {out.get('reason')!r}"
    lo = out["result"]["engines"]["libreoffice"]
    assert lo["available"] is False, f"libreoffice reports available={lo['available']!r} without the uno bridge"
    assert (lo.get("reason") or "").strip(), "libreoffice unavailable with an empty reason"
    assert "uno" in lo["reason"].lower(), f"reason {lo['reason']!r} does not name uno"
    return f"available=True, libreoffice reason={lo['reason'][:70]!r}"


@check("17. when LibreOffice IS available, restart changes the daemon pid and recalculation still agrees")
def _():
    from om import recalc
    from src.harness.mcp import excel_server as E
    if not _uno_available():
        raise _Skip("uno bridge not importable: LibreOffice daemon cannot start on this machine")
    before = recalc.daemon().pid
    out = E.xlsx_engine_restart()
    after = recalc.daemon().pid
    assert out.get("available") is True, f"restart failed: {out.get('reason')!r}"
    assert after is not None, "no daemon pid after restart"
    assert after != before, f"daemon pid unchanged ({before} -> {after})"
    name = _write("model.xlsx", _model_bytes())
    rep = E.xlsx_recalc(name)["result"]
    assert rep["agree"] is True, f"recalc after restart does not agree: {rep['divergences'][:3]}"
    return f"pid {before} -> {after}; recalc agrees over {rep['compared_cells']} cells"


# --------------------------------------------------------------------------- E. the protocol layer
@check("18. tools/list returns all five tools, each with an inputSchema")
def _():
    from src.harness.mcp import excel_server as E
    srv = E.make_server()
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = resp["result"]["tools"]
    names = sorted(t["name"] for t in tools)
    expected = sorted(["xlsx_evaluate", "xlsx_grade", "xlsx_recalc", "xlsx_engine_status", "xlsx_engine_restart"])
    assert names == expected, f"tools/list returned {names}, expected {expected}"
    for t in tools:
        assert isinstance(t.get("inputSchema"), dict), f"tool {t['name']!r} has no inputSchema object"
    return f"{len(tools)} tools, each with an inputSchema"


@check("19. xlsx_engine_status schema has required: [] so it can be called with no arguments")
def _():
    from src.harness.mcp import excel_server as E
    srv = E.make_server()
    tools = {t["name"]: t for t in srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    schema = tools["xlsx_engine_status"]["inputSchema"]
    assert schema.get("required") == [], f"required is {schema.get('required')!r}, expected []"
    resp = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "xlsx_engine_status", "arguments": {}}})
    assert resp["result"]["isError"] is False, f"no-argument call failed: {resp['result']}"
    return "required=[] and a no-argument tools/call succeeds"


@check("20. xlsx_recalc schema includes the optional engines array")
def _():
    from src.harness.mcp import excel_server as E
    srv = E.make_server()
    tools = {t["name"]: t for t in srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    schema = tools["xlsx_recalc"]["inputSchema"]
    props = schema.get("properties", {})
    assert "engines" in props, f"xlsx_recalc schema has no 'engines': {sorted(props)}"
    assert props["engines"].get("type") == "array", f"engines is {props['engines'].get('type')!r}, expected array"
    assert "engines" not in (schema.get("required") or []), "engines must be optional, not required"
    return "engines present as an optional array"


@check("21. a tools/call for xlsx_recalc returns a JSON payload whose result.compared_cells > 500")
def _():
    from src.harness.mcp import excel_server as E
    name = _write("model.xlsx", _model_bytes())
    srv = E.make_server()
    resp = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "xlsx_recalc", "arguments": {"path": name}}})
    res = resp["result"]
    assert res["isError"] is False, f"tools/call reported an error: {res}"
    payload = json.loads(res["content"][0]["text"])
    assert payload.get("available") is True, f"payload available is {payload.get('available')!r}"
    n = payload["result"]["compared_cells"]
    assert n > 500, f"result.compared_cells={n}, expected > 500"
    return f"tools/call payload result.compared_cells={n} > 500"


# --------------------------------------------------------------------------- F. no regression
@check("22. python3 -m unittest tests.test_recalc -q is green (or skips only for a missing engine)")
def _():
    proc = subprocess.run([sys.executable, "-m", "unittest", "tests.test_recalc", "-q"],
                          cwd=ROOT, capture_output=True, text=True, timeout=900)
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    summary = " | ".join(tail[-4:]) if tail else "(no output)"
    assert proc.returncode == 0, f"tests.test_recalc exited {proc.returncode}: {summary}"
    return summary[:200]


@check("23. the gate prints, per engine, whether it was exercised or skipped and why")
def _():
    from om import recalc
    from src.harness.mcp import excel_server as E
    name = _write("model.xlsx", _model_bytes())
    rep = E.xlsx_recalc(name)["result"]
    status = E.xlsx_engine_status()["result"]["engines"]
    lines = []
    for eng in recalc.DEFAULT_ENGINES:
        info = rep["engines"].get(eng, {})
        if info.get("available"):
            lines.append(f"{eng}: EXERCISED ({info.get('cells', 0)} cells)")
        else:
            why = (info.get("reason") or status.get(eng, {}).get("reason") or "unavailable").strip()
            lines.append(f"{eng}: SKIPPED ({why})")
    # The daemon-level status is reported separately: the UNO daemon can be unavailable while compare() still
    # gets LibreOffice values through the one-shot soffice fallback, and the gate must say which is which.
    lo_daemon = status["libreoffice"]
    lines.append(f"libreoffice daemon: {'AVAILABLE' if lo_daemon['available'] else 'UNAVAILABLE'} "
                 f"({(lo_daemon.get('reason') or 'ok').strip()})")
    _ENGINE_NOTES.extend(lines)
    # Every engine must appear, and a skipped engine must name its dependency. A gate that silently skips an
    # engine and prints PASS is not acceptable.
    assert len(lines) >= len(recalc.DEFAULT_ENGINES), f"only {len(lines)} engine lines printed"
    for line in lines:
        if line.startswith("libreoffice daemon:"):
            continue
        eng = line.split(":", 1)[0]
        assert eng in recalc.DEFAULT_ENGINES, f"unexpected engine line {line!r}"
        if "SKIPPED" in line:
            low = line.lower()
            assert any(d in low for d in ("uno", "soffice", "formulon")), \
                f"skipped engine line names no dependency: {line!r}"
    if not _uno_available():
        assert lo_daemon["available"] is False, "uno is missing but the daemon status claims libreoffice is available"
        assert "uno" in (lo_daemon.get("reason") or "").lower(), \
            f"libreoffice daemon unavailable without naming uno: {lo_daemon.get('reason')!r}"
    return "; ".join(lines)


def main() -> int:
    width = max(len(n) for _, n, _ in RESULTS)
    fails = 0
    for status, name, detail in RESULTS:
        fails += status == "FAIL"
        print(f"{status.ljust(7)}  {name.ljust(width)}  {detail}")
    print("\nEngine exercise (assertion 23):")
    for line in _ENGINE_NOTES:
        print(f"  {line}")
    passed = sum(1 for s, _, _ in RESULTS if s == "PASS")
    skipped = sum(1 for s, _, _ in RESULTS if s == "SKIPPED")
    print(f"\nS2.4b gate: {passed}/{len(RESULTS)} passed, {skipped} skipped, {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())