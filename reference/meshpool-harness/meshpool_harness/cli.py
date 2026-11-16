"""Single entry point.

  python -m meshpool_harness route "request" [--files a.csv ...]
  python -m meshpool_harness run "request" [--files ...] [--out DIR] [--engine code,slides] [--workdir REPO]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _engine(name):
    import importlib
    return importlib.import_module(f"engines.{name}.engine")


def run_request(request: str, files: list[str], out: str, engine: str | None = None, workdir: str | None = None,
                client=None, output_format: str | None = None) -> dict:
    from meshpool_harness.core.client import LiveClient
    from meshpool_harness.router.router import route
    if not request or not request.strip():
        raise SystemExit("error: empty request")
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        raise SystemExit(f"error: file(s) not found: {', '.join(missing)}")
    if engine:
        bad = [e for e in engine.split(",") if e not in ("code", "data", "sheets", "slides", "general", "browser")]
        if bad:
            raise SystemExit(f"error: unknown engine(s) {bad}; choose from code, data, sheets, slides, general")
    client = client or LiveClient("phase_2_build")
    task_id = "req-" + uuid.uuid4().hex[:8]
    r = route(request, files, output_format, workdir, client=client, engine=engine, task_id=task_id)
    outdir = Path(out).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    inputs = [str(Path(f).resolve()) for f in files]
    t0, results = time.time(), []
    for i, name in enumerate(r.engines):
        wd = workdir if (name == "code" and workdir) else str(outdir)
        for f in inputs:                         # engines see inputs inside their workdir
            dst = Path(wd) / Path(f).name
            if not dst.exists() and Path(f).parent != Path(wd):
                shutil.copy(f, dst)
        task = request
        if inputs:
            task += "\n\nInput files (in the working directory): " + ", ".join(Path(f).name for f in inputs)
        if results:
            prev = results[-1]
            task += (f"\n\nOutput of the previous step ({r.engines[i - 1]}), use it as your source:\n"
                     f"{prev['answer']}\nFiles: {', '.join(prev.get('artifacts', []))}")
        if len(r.engines) > 1:
            task += f"\n\nYou are step {i + 1} of {len(r.engines)} ({' -> '.join(r.engines)}); do only the {name} part."
        kw = {"files": inputs} if name == "data" else {}
        try:
            res = _engine(name).solve(task, workdir=wd, task_id=f"{task_id}-{name}", client=client, **kw)
        except Exception as e:   # one clean message instead of a traceback
            res = {"ok": False, "answer": "", "reason": f"{type(e).__name__}: {e}", "artifacts": []}
        res["engine"] = name
        results.append(res)
        if not res.get("ok"):
            break
    spent = client.spent() if hasattr(client, "spent") else None
    return {"task_id": task_id, "route": {"engines": r.engines, "confidence": r.confidence, "reason": r.reason,
                                         "used_model_call": r.used_model_call},
            "ok": all(x.get("ok") for x in results) and len(results) == len(r.engines),
            "steps": [{k: v for k, v in x.items() if k in ("engine", "ok", "answer", "artifacts", "evidence", "turns",
                                                          "reason", "usage")} for x in results],
            "out_dir": str(outdir), "wall_s": round(time.time() - t0, 1), "key_spend_since_start": spent}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="meshpool_harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("route", "run"):
        p = sub.add_parser(c)
        p.add_argument("request")
        p.add_argument("--files", nargs="*", default=[])
        p.add_argument("--engine")
        p.add_argument("--workdir")
        p.add_argument("--format", dest="output_format")
        if c == "run":
            p.add_argument("--out", default="./mh_out")
    w = sub.add_parser("work", help="fetch a task from a connector (github:, jira:, http:, file:, custom), run it, report back")
    w.add_argument("source", help="e.g. github:owner/repo#12, jira:PROJ-7, http:https://..., file:task.md")
    w.add_argument("--workdir", default=".")
    w.add_argument("--engine", default=None)
    w.add_argument("--out", default="./mh_out")
    w.add_argument("--report", action="store_true", help="post the outcome back to the source")
    a = ap.parse_args(argv)
    if a.cmd == "work":
        from meshpool_harness.connectors import get
        conn, ref = get(a.source)
        task = conn.fetch(ref)
        res = run_request(task.text(), [], a.out, a.engine, a.workdir)
        if a.report:
            conn.report(task, res)
        print(json.dumps({"task": task.ref, "source": task.source, **{k: res.get(k) for k in ("ok", "answer")}},
                         indent=1, default=str))
        return 0 if res.get("ok") else 1
    if a.cmd == "route":
        from meshpool_harness.router.rules import decide
        eng, conf, why = decide(a.request, a.files, a.output_format, a.workdir)
        print(json.dumps({"engines": eng, "confidence": conf, "reason": why}, indent=1))
        return 0
    res = run_request(a.request, a.files, a.out, a.engine, a.workdir, output_format=a.output_format)
    print(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
