"""Shared in-process job harness and deliverable audits for the measurement runners (SPEC section 11, D-032).

Both `eval/tsb/run.py` and `eval/reliability/run.py` run briefs as real jobs through `om.api.jobs` against a temporary data
directory with the seeded demo org.  Replay mode only: nothing here opens a socket or calls a model.  Everything a
runner reports is derived from what the job actually produced; nothing is invented.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TERMINAL = ("done", "failed", "cancelled")
INPUT_BLUE = "0000FF"
REPLAY_MARK = "REPLAY FIXTURE"
OFFLINE_TICKERS = {"AAPL": "real", "DEMOA": "synthetic", "DEMOB": "synthetic", "DEMOT": "synthetic"}


# --------------------------------------------------------------------------- statistics helpers
def pct(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in 0..100); None for an empty list."""
    v = sorted(values)
    if not v:
        return None
    if len(v) == 1:
        return v[0]
    k = (len(v) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def iqr(values: list[float]) -> tuple[float | None, float | None]:
    return pct(values, 25), pct(values, 75)


def fmt(x, nd: int = 3) -> str:
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


# --------------------------------------------------------------------------- run record
@dataclass
class Run:
    job_id: str
    status: str
    prompt: str
    wall_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    error: str | None = None
    hint: str | None = None
    steps: list = field(default_factory=list)
    deliverables: list = field(default_factory=list)       # [{name, kind, version, sha256, badges, data(bytes)}]
    sources: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    time_saved: dict | None = None
    tokens: int = 0
    cost_usd: float = 0.0
    approvals: int = 0
    task_ids: list = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.status == "done"

    @property
    def blocked(self) -> bool:
        """A step failed because an engine has not landed (the product says so in the hint)."""
        h = (self.hint or "") + " " + (self.error or "")
        return self.status == "failed" and ("hasn't landed" in h or "not available in this build" in h)

    def step(self, fn: str) -> dict | None:
        return next((s for s in self.steps if s.get("fn") == fn), None)

    def step_output(self, fn: str) -> dict:
        return ((self.step(fn) or {}).get("output")) or {}


class Harness:
    """One temp data dir, one seeded demo org, one JobService.  Sequential use only (it patches nothing by itself)."""

    def __init__(self, workdir: str | None = None, llm_mode: str = "replay"):
        from om.api import demo, jobs
        from om.api import state as sm
        from om.api.agents import engines
        self._env = {k: os.environ.get(k) for k in ("ACRETIA_LLM_MODE", "ACRETIA_LLM_FIXTURES")}
        os.environ["ACRETIA_LLM_MODE"] = llm_mode
        if llm_mode == "replay":
            os.environ["ACRETIA_LLM_FIXTURES"] = str(engines.REPLAY_DIR)
        self._own_tmp = workdir is None
        self.tmp = Path(workdir or tempfile.mkdtemp(prefix="acretia-eval-"))
        self.jobs, self.engines = jobs, engines
        self.state = sm.create(self.tmp, llm_mode=llm_mode, demo=True)
        self.info = demo.seed(self.tmp, self.state)
        self.org = self.info["org_id"]
        self.uid = self.info["users"]["owner@meridian.example"]
        self.svc = jobs.init(self.state)

    def close(self):
        try:
            self.jobs.shutdown()
            time.sleep(0.05)
            self.state.close_conn()
        finally:
            for k, v in self._env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            if self._own_tmp:
                shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ---------------------------------------------------------------- running
    def deal_id(self, key: str | None):
        if not key:
            return None
        for name, did in self.info["deals"].items():
            if key.lower() in name.lower():
                return did
        raise KeyError(f"no seeded deal matching {key!r}")

    def _wait(self, jid: str, timeout: float) -> tuple[dict, int]:
        end = time.time() + timeout
        approvals = 0
        while time.time() < end:
            r = self.svc._row(jid)
            if r["status"] in TERMINAL:
                return r, approvals
            if r["status"] == "awaiting_approval":
                pend = (json.loads(r["inputs_json"] or "{}") or {}).get("_pending") or {}
                if pend.get("step_id"):
                    # approval gates are approved with the ghost deck / source list exactly as drafted (empty payload)
                    self.svc.approve(self.org, jid, pend["step_id"], {}, self.uid)
                    approvals += 1
            time.sleep(0.01)
        r = self.svc._row(jid)
        raise TimeoutError(f"job {jid} did not finish within {timeout}s (status={r['status']}, in worker set={jid in self.svc._active}, "
                           f"steps={[(x['id'], x['status']) for x in json.loads(r['steps_json'] or '[]')]})")

    def run(self, prompt: str, deal: str | None = None, inputs: dict | None = None, timeout: float = 180.0) -> Run:
        t0 = time.perf_counter()
        j = self.svc.submit(self.org, self.uid, prompt, deal_id=self.deal_id(deal), inputs={"source_review": False, **(inputs or {})})
        return self.collect(j["id"], t0, timeout)

    def resume(self, run: Run, timeout: float = 180.0) -> Run:
        t0 = time.perf_counter()
        self.svc.resume(self.org, run.job_id)
        return self.collect(run.job_id, t0, timeout)

    def collect(self, jid: str, t0: float | None = None, timeout: float = 180.0) -> Run:
        t0 = t0 or time.perf_counter()
        r, approvals = self._wait(jid, timeout)
        time.sleep(0.01)
        r = self.svc._row(jid)
        steps = json.loads(r["steps_json"] or "[]")
        evs = self.svc.events_after(jid, 0)
        store = self.state.deal_store(self.state.conn(), self.org)
        dels = []
        for e in evs:
            if e["type"] == "deliverable":
                d = dict(e["data"])
                d["data"] = store.get_version(d["deal_id"], d["name"], d["version"])
                dels.append(d)
        plan = json.loads(r["plan_json"]) if r["plan_json"] else {}
        ts = json.loads(r["time_saved_json"]) if r["time_saved_json"] else None
        return Run(job_id=jid, status=r["status"], prompt=r["prompt"], wall_seconds=float(r["wall_seconds"] or 0.0),
                   elapsed_seconds=time.perf_counter() - t0, error=r["error"], hint=r["hint"], steps=steps, deliverables=dels,
                   sources=[e["data"] for e in evs if e["type"] == "source"], plan=plan, time_saved=ts,
                   tokens=int(r["tokens"] or 0), cost_usd=float(r["cost_usd"] or 0.0), approvals=approvals,
                   task_ids=[t["task_id"] for t in plan.get("tasks", [])])

    def unresolved_citations(self, run: Run) -> list[str]:
        """Citation tokens a step emitted that do not resolve to a stored citation (a number that claims a source but has none)."""
        from om.api import citations
        bad = []
        for s in run.steps:
            for tok in (s.get("output") or {}).get("citations", []) or []:
                if not citations.resolve(self.state.conn(), self.org, tok):
                    bad.append(tok)
        return bad

    # ---------------------------------------------------------------- failure injection (a one-shot exception in an engine step)
    def inject_failure(self, fn: str):
        """Make step function `fn` raise once (first call only).  Returns (counter dict, restore callable)."""
        orig = self.engines.STEP_FNS[fn]
        calls = {"n": 0}
        lock = threading.Lock()

        def flaky(cx):
            with lock:
                calls["n"] += 1
                first = calls["n"] == 1
            if first:
                raise RuntimeError("injected one-shot failure (eval harness)")
            return orig(cx)

        self.engines.STEP_FNS[fn] = flaky

        def restore():
            self.engines.STEP_FNS[fn] = orig
        return calls, restore

    def count_calls(self, fns: list[str]):
        """Wrap step functions with call counters (to prove a resume does not re-run finished steps)."""
        origs = {f: self.engines.STEP_FNS[f] for f in fns}
        calls = {f: 0 for f in fns}
        for f in fns:
            def mk(f):
                def w(cx):
                    calls[f] += 1
                    return origs[f](cx)
                return w
            self.engines.STEP_FNS[f] = mk(f)

        def restore():
            self.engines.STEP_FNS.update(origs)
        return calls, restore


# --------------------------------------------------------------------------- fingerprints (determinism)
def _norm(v):
    if isinstance(v, float):
        return round(v, 9)
    return v


def docx_text(data: bytes) -> str:
    x = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8", "replace")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()


def pptx_texts(data: bytes) -> list[list[str]]:
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    out = []
    for sl in prs.slides:
        texts = []
        for sh in sl.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                texts.append(sh.text_frame.text.strip())
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    texts.append(" | ".join(c.text.strip() for c in row.cells))
        out.append(texts)
    return out


def fingerprint(kind: str, data: bytes):
    """Canonical content of a deliverable.  xlsx: {sheet: {(r,c): (formula, value)}}; pptx: slide texts; docx: text; json: parsed."""
    if kind == "xlsx":
        from om import xlsx
        b = xlsx.read(data)
        return {sh: {rc: (c.formula, _norm(c.value)) for rc, c in cells.items()} for sh, cells in b.sheets.items()}
    if kind == "pptx":
        return pptx_texts(data)
    if kind == "docx":
        return docx_text(data)
    if kind == "json":
        return json.loads(data.decode("utf-8"))
    return data


def diff_count(a, b) -> int:
    """Number of differing leaves between two fingerprints (cells for xlsx, slides for pptx, 0/1 otherwise)."""
    if isinstance(a, dict) and isinstance(b, dict) and a and all(isinstance(v, dict) for v in a.values()) and set(a) | set(b) and \
            all(isinstance(k, tuple) for v in a.values() for k in v):
        n = 0
        for sh in set(a) | set(b):
            x, y = a.get(sh, {}), b.get(sh, {})
            n += sum(1 for rc in set(x) | set(y) if x.get(rc) != y.get(rc))
        return n
    if isinstance(a, list) and isinstance(b, list):
        return sum(1 for i in range(max(len(a), len(b))) if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None))
    return 0 if a == b else 1


def deliverables_identical(r1: Run, r2: Run) -> tuple[bool, int, list[str]]:
    """(identical, differing_leaves, notes).  Matches deliverables by name; compares canonical content, not just bytes."""
    notes = []
    n1 = {d["name"]: d for d in r1.deliverables}
    n2 = {d["name"]: d for d in r2.deliverables}
    if set(n1) != set(n2):
        return False, 1, [f"deliverable sets differ: {sorted(n1)} vs {sorted(n2)}"]
    total = 0
    for name in sorted(n1):
        f1, f2 = fingerprint(n1[name]["kind"], n1[name]["data"]), fingerprint(n2[name]["kind"], n2[name]["data"])
        k = diff_count(f1, f2)
        if k:
            notes.append(f"{name}: {k} differing {'cells' if n1[name]['kind'] == 'xlsx' else 'items'}")
        total += k
    return total == 0, total, notes


# --------------------------------------------------------------------------- numbers audit (silent wrong numbers)
FIG = re.compile(r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?\s?(?:bn|b|m|k|billion|million|thousand)?\b|\d[\d,]*(?:\.\d+)?\s?(?:%|x\b|bn\b|billion\b|million\b))", re.I)
FLAG_WORDS = re.compile(r"REPLAY FIXTURE|SYNTHETIC|illustrative|unaudited|\bestimate[ds]?\b|not drafted|canned", re.I)
SRC_LINE = re.compile(r"^\s*(source|sources|figures from)\b", re.I)
HIST_HDR = re.compile(r"(?:^|[\s(])(?:FY|CY)?\s?\d{4}\s?A\b|\bactual", re.I)


@dataclass
class Audit:
    total: int = 0
    sourced: int = 0
    flagged: int = 0
    silent: int = 0
    examples: list = field(default_factory=list)

    def add(self, other: "Audit"):
        self.total += other.total
        self.sourced += other.sourced
        self.flagged += other.flagged
        self.silent += other.silent
        self.examples += other.examples[:3]
        self.examples = self.examples[:8]

    def silent_at(self, where: str, what):
        self.silent += 1
        self.total += 1
        if len(self.examples) < 8:
            self.examples.append(f"{where} = {what}")


def audit_xlsx(data: bytes, name: str = "", flagged_cells: frozenset = frozenset()) -> Audit:
    """Every hard-coded number must carry a source (cell comment or link) or a flag.

    - On a filings/historical sheet, or in an actual-period column (FY2024A, Actual) of a time-series row (3+ numbers across), an
      unsourced constant is SILENT (a lone control cell such as a scenario switch is an input, not a historical).
    - Elsewhere a constant is flagged when it uses the blue input-cell convention (a declared assumption); a constant that is
      neither sourced nor blue is SILENT.
    - `flagged_cells` ("Sheet!A1") are cells the job itself disclosed as user overrides in its step notes; they count as flagged.
    Years used as period labels (1990-2100 in the first 12 rows) are labels, not figures.
    """
    from om import xlsx
    b = xlsx.read(data)
    a = Audit()
    for sh, cells in b.sheets.items():
        hist_cols = set()
        for (r, c), cell in cells.items():
            if r <= 12 and isinstance(cell.value, str) and HIST_HDR.search(cell.value):
                hist_cols.add(c)
        filings = bool(re.search(r"filing|histor|actual|source", sh, re.I))
        row_nums: dict[int, int] = {}
        for (r, c), cell in cells.items():
            if c >= 3 and isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                row_nums[r] = row_nums.get(r, 0) + 1
        for (r, c), cell in cells.items():
            v = cell.value
            if cell.formula or isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            if r <= 12 and float(v).is_integer() and 1990 <= v <= 2100:
                continue
            a.total += 1
            if b.comments.get(sh, {}).get((r, c)) or (b.links.get(sh, {}).get((r, c)) or "").startswith("http"):
                a.sourced += 1
            elif f"{sh}!{xlsx.col_letter(c)}{r}" in flagged_cells:
                a.flagged += 1
            elif not filings and not (c in hist_cols and row_nums.get(r, 0) >= 3) and cell.color == INPUT_BLUE:
                a.flagged += 1
            else:
                a.total -= 1
                a.silent_at(f"{name}!{sh}!R{r}C{c}", v)
    return a


def audit_pptx(data: bytes, name: str = "") -> Audit:
    """Every slide with figures needs a Source line naming the filing / as-of date, or an explicit flag on the slide."""
    a = Audit()
    for i, texts in enumerate(pptx_texts(data), 1):
        src = [t for t in texts if SRC_LINE.search(t)]
        body = [t for t in texts if not SRC_LINE.search(t)]
        figs = [m.group(0) for t in body for m in FIG.finditer(t)]
        if not figs:
            continue
        sourced = any(re.search(r"SEC|10-K|10-Q|filing|EDGAR|annual report|\d{4}-\d{2}-\d{2}", t, re.I) for t in src)
        flagged = any(FLAG_WORDS.search(t) for t in texts)
        if sourced:
            a.total += len(figs)
            a.sourced += len(figs)
        elif flagged:
            a.total += len(figs)
            a.flagged += len(figs)
        else:
            for f in figs:
                a.silent_at(f"{name} slide {i}", f)
    return a


def audit_docx(data: bytes, name: str = "") -> Audit:
    txt = docx_text(data)
    figs = [m.group(0) for m in FIG.finditer(txt)]
    a = Audit()
    if not figs:
        return a
    if re.search(r"Figures from|\bSource[s]?:|per the 10-K|filed \d{4}-\d{2}-\d{2}", txt):
        a.total = a.sourced = len(figs)
    elif FLAG_WORDS.search(txt):
        a.total = a.flagged = len(figs)
    else:
        for f in figs:
            a.silent_at(name, f)
    return a


def audit_json(data: bytes, name: str = "") -> Audit:
    """Findings must carry doc_id + page (a locator) when their text states a figure."""
    a = Audit()
    try:
        j = json.loads(data.decode("utf-8"))
    except ValueError:
        a.silent_at(name, "unparseable json")
        return a
    for f in j.get("findings", []) if isinstance(j, dict) else []:
        txt = " ".join(str(f.get(k, "")) for k in ("title", "summary", "detail", "quote", "text", "what"))
        figs = FIG.findall(txt)
        if not figs:
            continue
        if f.get("doc_id") and f.get("page"):
            a.total += len(figs)
            a.sourced += len(figs)
        else:
            for x in figs:
                a.silent_at(f"{name} finding", x)
    return a


def override_cells(run: Run) -> frozenset:
    """Cells a job disclosed as overridden by the user's prompt ("Overrides applied: DCF!C30=0.09, ..." in a step note)."""
    out = set()
    for s in run.steps:
        for n in ((s.get("output") or {}).get("notes") or []):
            m = re.match(r"Overrides applied:\s*(.*)", str(n))
            if m:
                out |= {x.split("=")[0].strip() for x in m.group(1).split(",") if "!" in x}
    return frozenset(out)


def audit_deliverable(d: dict, flagged_cells: frozenset = frozenset()) -> Audit:
    k = d["kind"]
    if k == "xlsx":
        return audit_xlsx(d["data"], d["name"], flagged_cells)
    fn = {"pptx": audit_pptx, "docx": audit_docx, "json": audit_json}.get(k)
    return fn(d["data"], d["name"]) if fn else Audit()


def audit_run(h: Harness, run: Run) -> Audit:
    a = Audit()
    fc = override_cells(run)
    for d in run.deliverables:
        a.add(audit_deliverable(d, fc))
    for tok in h.unresolved_citations(run):
        a.silent_at(run.job_id, f"citation token {tok} does not resolve")
    return a


# --------------------------------------------------------------------------- deterministic grades
def circularity_check(run: Run) -> dict:
    """Interest circularity modelled and converging: the build reports convergence and the workbook has the switch on with iterative calc enabled."""
    fn = "build_three_statement" if run.step("build_three_statement") else "build_dcf"
    facts = run.step_output(fn).get("facts") or {}
    xl = next((d for d in run.deliverables if d["kind"] == "xlsx"), None)
    switch = None
    iterate = None
    if xl:
        from om import xlsx
        b = xlsx.read(xl["data"])
        iterate = bool(b.iterate)
        for sh, cells in b.sheets.items():
            for (r, c), cell in cells.items():
                if isinstance(cell.value, str) and "circularity" in cell.value.lower():
                    row = [cells.get((r, cc)) for cc in range(c + 1, c + 6)]
                    nums = [x.value for x in row if x is not None and isinstance(x.value, (int, float)) and not isinstance(x.value, bool)]
                    if nums:
                        switch = nums[0]
                        break
            if switch is not None:
                break
    converged = bool(facts.get("converged"))
    ok = converged and iterate is True and switch == 1
    return {"converged": converged, "iterations": facts.get("iterations"), "iterative_calc_enabled": iterate, "switch_on": switch == 1 if switch is not None else None,
            "pass": ok}


def gate_result(run: Run) -> dict:
    """Deterministic gates from the run itself: model check (xlsx), deck validator badges (pptx), canned-text detector (docx)."""
    out = {"gates": [], "pass": True, "model_score": None, "blocking": []}
    chk = run.step_output("check_model")
    if run.step("check_model"):
        ok = bool(chk.get("production_ready"))
        out["model_score"] = chk.get("score")
        out["gates"].append(("modelcheck", ok))
        if not ok:
            out["blocking"].append(f"model check failed: {', '.join(chk.get('failed_graders') or []) or 'not production ready'}")
    for d in run.deliverables:
        if d["kind"] == "pptx":
            bd = d.get("badges") or {}
            ok = bool(bd.get("ok")) and not bd.get("critical")
            out["gates"].append(("validate_pptx", ok))
            if not ok:
                out["blocking"].append(f"deck validator: {bd}")
        if d["kind"] in ("docx", "json") and REPLAY_MARK in _text_of(d):
            out["blocking"].append("canned replay text (not drafted from research); a live run is needed before this can be client-ready")
        if d["kind"] == "xlsx" and run.step("check_model") is None:
            out["gates"].append(("modelcheck", None))          # no check step in this agent: reported as ungraded
    out["pass"] = all(ok is not False for _, ok in out["gates"])
    return out


def _text_of(d: dict) -> str:
    if d["kind"] == "docx":
        return docx_text(d["data"])
    return d["data"].decode("utf-8", "replace")
