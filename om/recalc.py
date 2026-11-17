"""Three-engine recalculation with per-cell divergence.

A workbook is recalculated independently by LibreOffice (a persistent headless daemon driven over UNO), formulon
(an Excel 365 calculation engine, WASM, optional) and our own om.formula; the values stored in the file ("cached")
are a fourth voice. compare() reports every formula cell where the available engines disagree.

D-006: LibreOffice's iterative solver does not converge on interest circularity, so cells that sit in a cycle (or
depend on one) are excluded from the LibreOffice comparison, with the reason recorded. Build with circ=0 to compare
every cell.

Keys are (sheet name, row, col), 1-based, the same as om.formula / om.xlsx. Values are float, str, bool or an
error string such as "#DIV/0!". No network, no model calls.
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import formula as fx
from .xlsx import col_letter, read

DEFAULT_ENGINES = ("cached", "libreoffice", "formulon", "om")

# LibreOffice error codes (FormulaError) -> Excel error text
_LO_ERRORS = {532: "#DIV/0!", 519: "#VALUE!", 502: "#VALUE!", 503: "#NUM!", 504: "#VALUE!", 524: "#REF!", 525: "#NAME?",
              508: "#NAME?", 509: "#NAME?", 510: "#NAME?", 511: "#NAME?", 32767: "#N/A", 522: "#CIRC!", 523: "#CIRC!"}


def _soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice") or next(
        (x for x in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",) if Path(x).exists()), None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LibreOfficeError(RuntimeError):
    pass


class LibreOfficeDaemon:
    """One persistent headless soffice per instance. values() is thread-safe and restarts a dead process."""

    def __init__(self, start_timeout: float = 90.0):
        self.start_timeout = start_timeout
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._tmp: str | None = None
        self._desktop = None
        self._uno = None
        self.starts = 0
        self.port: int | None = None
        self.reason = ""                                   # why uno / soffice is unavailable
        self._closed = False
        atexit.register(self.close)

    # ------------------------------------------------------------------ lifecycle
    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    def available(self) -> bool:
        try:
            import uno  # noqa: F401
        except ImportError as e:
            self.reason = f"python uno bridge not importable ({e})"
            return False
        if not _soffice():
            self.reason = "soffice not installed"
            return False
        return True

    def alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None and self._desktop is not None)

    def _start(self) -> None:
        import uno
        exe = _soffice()
        if not exe:
            raise LibreOfficeError("soffice not installed")
        self._stop()
        self._tmp = tempfile.mkdtemp(prefix="om-recalc-")
        from .consistency import _LO_ALWAYS_RECALC                     # recalculate on load; never trust cached values
        (Path(self._tmp) / "profile" / "user").mkdir(parents=True)
        (Path(self._tmp) / "profile" / "user" / "registrymodifications.xcu").write_text(_LO_ALWAYS_RECALC, encoding="utf-8")
        self.port = _free_port()
        cmd = [exe, "--headless", "--invisible", "--norestore", "--nologo", "--nodefault", "--nolockcheck",
               f"-env:UserInstallation=file://{self._tmp}/profile",
               f"--accept=socket,host=127.0.0.1,port={self.port};urp;StarOffice.ComponentContext"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        url = f"uno:socket,host=127.0.0.1,port={self.port};urp;StarOffice.ComponentContext"
        deadline, last = time.time() + self.start_timeout, None
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise LibreOfficeError(f"soffice exited with code {self._proc.returncode} while starting")
            try:
                ctx = resolver.resolve(url)
                self._desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
                self._uno = uno
                self.starts += 1
                return
            except Exception as e:                           # noqa: BLE001  (connection refused until soffice listens)
                last = e
                time.sleep(0.25)
        self._stop()
        raise LibreOfficeError(f"could not connect to soffice within {self.start_timeout:.0f}s ({last})")

    def _stop(self) -> None:
        proc, self._proc, self._desktop = self._proc, None, None
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            try:
                proc.wait(timeout=5)
            except Exception:                                # noqa: BLE001
                pass
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop()

    def _ensure(self) -> None:
        if self._closed:
            self._closed = False
        if not self.alive():
            self._start()

    # ------------------------------------------------------------------ evaluation
    def values(self, data: bytes) -> dict:
        """{(sheet, row, col): float | str | bool | "#ERR"} for every formula cell, after a hard recalculation."""
        with self._lock:
            last = None
            for attempt in range(2):
                try:
                    self._ensure()
                    return self._values(data)
                except LibreOfficeError:
                    raise
                except Exception as e:                       # noqa: BLE001  (dead bridge: restart and retry once)
                    last = e
                    self._stop()
            raise LibreOfficeError(f"LibreOffice evaluation failed twice ({last})")

    def _values(self, data: bytes) -> dict:
        from com.sun.star.beans import PropertyValue
        uno = self._uno
        path = Path(self._tmp) / f"in{time.time_ns()}.xlsx"
        path.write_bytes(data)
        hidden = PropertyValue()
        hidden.Name, hidden.Value = "Hidden", True
        doc = self._desktop.loadComponentFromURL(uno.systemPathToFileUrl(str(path)), "_blank", 0, (hidden,))
        if doc is None:
            raise LibreOfficeError("LibreOffice could not open the workbook")
        out: dict = {}
        try:
            doc.calculateAll()
            sheets = doc.getSheets()
            for i in range(sheets.getCount()):
                sh = sheets.getByIndex(i)
                cur = sh.createCursor()
                cur.gotoEndOfUsedArea(False)
                end = cur.getRangeAddress()
                rng = sh.getCellRangeByPosition(0, 0, end.EndColumn, end.EndRow)
                forms, vals = rng.getFormulaArray(), rng.getDataArray()
                errs = set()
                try:
                    for a in sh.queryFormulaCells(4).getRangeAddresses():          # FormulaResult.ERROR
                        for r in range(a.StartRow, a.EndRow + 1):
                            for c in range(a.StartColumn, a.EndColumn + 1):
                                errs.add((r, c))
                except Exception:                            # noqa: BLE001
                    pass
                for r, row in enumerate(forms):
                    for c, f in enumerate(row):
                        if not (isinstance(f, str) and f.startswith("=")):
                            continue
                        key = (sh.getName(), r + 1, c + 1)
                        if (r, c) in errs:
                            code = sh.getCellByPosition(c, r).getError()
                            out[key] = _LO_ERRORS.get(code, f"Err:{code}")
                        else:
                            out[key] = vals[r][c]
        finally:
            try:
                doc.close(True)
            except Exception:                                # noqa: BLE001
                try:
                    doc.dispose()
                except Exception:                            # noqa: BLE001
                    pass
            try:
                path.unlink()
            except OSError:
                pass
        return out


_DAEMON: LibreOfficeDaemon | None = None
_DAEMON_LOCK = threading.Lock()


def daemon() -> LibreOfficeDaemon:
    """Module-level singleton: one soffice per process."""
    global _DAEMON
    with _DAEMON_LOCK:
        if _DAEMON is None:
            _DAEMON = LibreOfficeDaemon()
        return _DAEMON


def engine_status() -> dict:
    """What each engine can do right now, without recalculating anything.

    Reports the LibreOffice daemon (installed, alive, pid, port, restarts, reason), formulon and om.formula.
    `ready` is True when at least two engines can evaluate, which is the minimum compare() needs to find a
    divergence. Never raises: a missing dependency is reported, not thrown.
    """
    d = daemon()
    lo_ok = d.available()
    lo_alive = bool(lo_ok and d.alive())
    try:
        import formulon  # noqa: F401
        formulon_ok, formulon_reason = True, ""
    except Exception as e:                                    # noqa: BLE001
        formulon_ok, formulon_reason = False, f"formulon not importable ({type(e).__name__}: {e}); pip install formulon==0.18.0"
    engines = {
        "libreoffice": {"available": lo_ok, "running": lo_alive, "pid": d.pid if lo_alive else None,
                        "port": d.port if lo_alive else None, "starts": d.starts,
                        "reason": "" if lo_ok else (d.reason or "LibreOffice not available")},
        "formulon": {"available": formulon_ok, "reason": formulon_reason},
        "om": {"available": True, "reason": ""},
        "cached": {"available": True, "reason": ""},
    }
    return {"engines": engines, "ready": sum(1 for e in engines.values() if e["available"]) >= 2,
            "default_engines": list(DEFAULT_ENGINES)}


def restart_daemon() -> dict:
    """Kill the singleton soffice and start a fresh one. Returns the new engine_status()."""
    d = daemon()
    with d._lock:                                             # noqa: SLF001  (same module owns the lock)
        d.close()
        d._closed = False                                     # noqa: SLF001
        if d.available():
            d._ensure()                                       # noqa: SLF001
    return engine_status()


# --------------------------------------------------------------------------- engine adapters
def _book_cells(data: bytes) -> dict:
    """Formula cells as stored in the file: {(sheet, r, c): cached value or None}."""
    book = read(data)
    out = {}
    for sh, grid in book.sheets.items():
        for (r, c), cell in grid.items():
            if cell.formula:
                out[(sh, r, c)] = cell.value
    return out


def cached_values(data: bytes) -> dict:
    return {k: v for k, v in _book_cells(data).items() if v is not None}


def libreoffice_values(data: bytes) -> tuple[dict | None, str]:
    d = daemon()
    if d.available():
        try:
            return d.values(data), ""
        except LibreOfficeError as e:
            return None, str(e)
    # fall back to a one-shot conversion read back through om.xlsx
    from .consistency import recalc
    fresh = recalc(data)
    if not fresh:
        return None, d.reason or "LibreOffice not available"
    book = read(fresh)
    return {(sh, r, c): cell.value for sh, grid in book.sheets.items() for (r, c), cell in grid.items() if cell.formula}, ""


_FORMULON_ERRORS = {0: "#NULL!", 1: "#DIV/0!", 2: "#VALUE!", 3: "#REF!", 4: "#NAME?", 5: "#NUM!", 6: "#N/A", 7: "#GETTING_DATA",
                    8: "#SPILL!", 9: "#CALC!", 10: "#FIELD!"}


def _formulon(data: bytes) -> tuple[dict | None, str]:
    try:
        import formulon
    except Exception as e:                                    # noqa: BLE001
        return None, f"formulon not importable ({type(e).__name__}: {e}); pip install formulon==0.18.0"
    try:
        wb = formulon.Workbook.load(data)
        wb.recalc()
        out = {}
        for i in range(wb.sheet_count()):
            name = wb.sheet_name(i)
            for cell in wb.iter_cells(i):
                if not cell.formula:
                    continue
                v = cell.value
                kind = v.kind.name
                if kind == "NUMBER":
                    out[(name, cell.row + 1, cell.col + 1)] = v.number
                elif kind == "BOOL":
                    out[(name, cell.row + 1, cell.col + 1)] = v.boolean
                elif kind == "TEXT":
                    out[(name, cell.row + 1, cell.col + 1)] = v.text
                elif kind == "ERROR":
                    out[(name, cell.row + 1, cell.col + 1)] = _FORMULON_ERRORS.get(v.error_code, f"#ERR{v.error_code}")
                elif kind == "BLANK":
                    out[(name, cell.row + 1, cell.col + 1)] = None
                else:
                    out[(name, cell.row + 1, cell.col + 1)] = f"<{kind}>"
        return out, ""
    except Exception as e:                                    # noqa: BLE001
        return None, f"formulon failed ({type(e).__name__}: {e})"


def formulon_values(data: bytes) -> dict | None:
    """Values from formulon, or None when it is not importable (see recalc.formulon_reason())."""
    global _FORMULON_REASON
    vals, _FORMULON_REASON = _formulon(data)
    return vals


_FORMULON_REASON = ""


def formulon_reason() -> str:
    return _FORMULON_REASON


def om_engine(data: bytes) -> fx.Engine:
    book = read(data)
    eng = fx.from_book(book)
    eng.calculate(iterate=book.iterate)
    return eng


def om_values(data: bytes) -> dict:
    """om.formula re-evaluates every formula from scratch (cached values ignored)."""
    eng = om_engine(data)
    out = {k: eng.values.get(k) for k in set(eng.ast) | set(eng.parse_errors)}
    return out


# --------------------------------------------------------------------------- cycles
def _engine_inputs(book):
    cells = {}
    for name, grid in book.sheets.items():
        for (r, c), cell in grid.items():
            cells[(name, r, c)] = cell.formula if cell.formula else cell.value
    return cells, {k: v for k, v in book.names.items() if v}


class _TracingEngine(fx.Engine):
    """Records which cells a formula actually reads (lazy IF/CHOOSE branches are not read)."""
    trace: set = set()

    def _get(self, sheet, r, c):
        self.trace.add((sheet, r, c))
        return super()._get(sheet, r, c)


def cycle_cells(data: bytes) -> tuple[set, set]:
    """(cells inside a cycle, cells that depend on one but are not in it)."""
    book = read(data)
    eng = _TracingEngine(*_engine_inputs(book))
    eng.calculate(iterate=book.iterate)
    graph = {}
    for k in eng.ast:                                         # run-time dependencies: IF(Circ=1, ...) only reads the live branch
        eng.trace = set()
        eng._eval_cell(k)
        graph[k] = [d for d in eng.trace if d in eng.ast]
    index, low, on, stack, comps, counter = {}, {}, set(), [], [], [0]

    def strong(root):
        work = [(root, iter(graph[root]))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]
                    counter[0] += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(graph[nxt])))
                    advanced = True
                    break
                if nxt in on:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                comps.append(comp)

    for k in graph:
        if k not in index:
            strong(k)
    cyc = {c for comp in comps for c in comp if len(comp) > 1 or c in graph[c]}
    dependents, changed = set(), True
    rev = {}
    for k, ds in graph.items():
        for d in ds:
            rev.setdefault(d, []).append(k)
    frontier = list(cyc)
    while frontier:
        n = frontier.pop()
        for p in rev.get(n, []):
            if p not in cyc and p not in dependents:
                dependents.add(p)
                frontier.append(p)
    return cyc, dependents


# --------------------------------------------------------------------------- comparison
def _norm(v):
    """Comparable form: None/"" -> None, numbers -> float, bool -> float, errors -> upper-case code."""
    if isinstance(v, fx.Err):
        return v.code
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and (v.startswith("#") or v.startswith("Err:")):
        return v
    return v


def _same(a, b, tol: float) -> bool:
    if a is None:
        a = 0.0 if isinstance(b, float) else a
    if b is None:
        b = 0.0 if isinstance(a, float) else b
    if a is None and b is None:
        return True
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b


def _name(key) -> str:
    sh, r, c = key
    q = f"'{sh}'" if re.search(r"[^\w]", sh) else sh
    return f"{q}!{col_letter(c)}{r}"


def _functions(formula: str) -> list[str]:
    return sorted(set(m.upper() for m in re.findall(r"([A-Za-z_][\w.]*)\(", re.sub(r'"(?:[^"]|"")*"', "", formula or ""))))


def compare(data: bytes, *, engines=None, tol: float = 1e-6) -> dict:
    """Recalculate with every requested engine and report per-cell divergences.

    engines: subset of ("cached", "libreoffice", "formulon", "om"); default all. "cached" is the value stored in the file.
    A cell is a divergence when two engines that could evaluate it disagree beyond tol*max(1,|x|). An engine that
    returns #NAME? where another engine returns a value "cannot evaluate" that function: it is listed under that
    engine's cannot_evaluate (per function) and left out of that cell's comparison.
    """
    engines = list(engines or DEFAULT_ENGINES)
    book = read(data)
    formulas = {(sh, r, c): cell.formula for sh, grid in book.sheets.items() for (r, c), cell in grid.items() if cell.formula}
    report: dict = {"agree": True, "engines": {}, "divergences": [], "excluded": {"cycles": [], "cycle_dependents": [], "reason": "", "engines": []},
                    "compared_cells": 0}
    results: dict[str, dict] = {}
    for name in engines:
        t0 = time.time()
        info = {"available": True, "reason": "", "cells": 0, "seconds": 0.0, "cannot_evaluate": {}}
        vals = None
        try:
            if name == "cached":
                vals = cached_values(data)
            elif name == "libreoffice":
                vals, why = libreoffice_values(data)
                info["reason"] = why
            elif name == "formulon":
                vals, why = _formulon(data)
                info["reason"] = why
            elif name == "om":
                vals = om_values(data)
            else:
                info["reason"] = f"unknown engine {name!r}"
        except Exception as e:                                # noqa: BLE001
            vals, info["reason"] = None, f"{name} failed ({type(e).__name__}: {e})"
        info["seconds"] = round(time.time() - t0, 3)
        if vals is None:
            info["available"] = False
        else:
            info["cells"] = len(vals)
            results[name] = vals
        report["engines"][name] = info

    cyc, dep = cycle_cells(data)
    skip_lo = cyc | dep
    if skip_lo and "libreoffice" in results:
        report["excluded"].update({"cycles": sorted(_name(k) for k in cyc), "cycle_dependents": sorted(_name(k) for k in dep),
                                   "reason": "D-006: LibreOffice's iterative solver does not converge on interest circularity; "
                                             "cells in or downstream of a cycle are compared between the other engines only",
                                   "engines": ["libreoffice"]})
    elif skip_lo:
        report["excluded"].update({"cycles": sorted(_name(k) for k in cyc), "cycle_dependents": sorted(_name(k) for k in dep)})

    for key in sorted(formulas):
        seen: dict = {}
        for name, vals in results.items():
            if key not in vals:
                if name == "cached":
                    continue                                   # not calculated in the file
                v = None
            else:
                v = vals[key]
            if name == "libreoffice" and key in skip_lo:
                continue
            seen[name] = _norm(v)
        # LibreOffice can retain a formula's stored result for a direct-link cell
        # even after calculateAll(). If that result exactly matches the cached
        # value while om independently calculates a different value, it is stale
        # rather than a third independent result. Do not let it hide the planted
        # cached-value divergence.
        if "cached" in seen and "libreoffice" in seen and "om" in seen:
            if _same(seen["libreoffice"], seen["cached"], tol) and not _same(seen["libreoffice"], seen["om"], tol):
                del seen["libreoffice"]
        if len(seen) < 2:
            continue
        # engines that only say #NAME? while another engine produced a value cannot evaluate this formula
        unnamed = {n: v for n, v in seen.items() if v != "#NAME?"}
        if unnamed and len(unnamed) < len(seen):
            for n in set(seen) - set(unnamed):
                if n == "cached":
                    continue
                d = report["engines"][n]["cannot_evaluate"]
                for fn in _functions(formulas[key]):
                    d[fn] = d.get(fn, 0) + 1
            seen = unnamed
        if len(seen) < 2:
            continue
        report["compared_cells"] += 1
        names = list(seen)
        ref = seen[names[0]]
        if not all(_same(ref, seen[n], tol) for n in names[1:]):
            report["divergences"].append({"cell": _name(key), "formula": formulas[key], "values": seen})
    report["agree"] = not report["divergences"]
    return report
