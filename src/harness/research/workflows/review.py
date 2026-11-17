"""Pre-run source review (parity item 24).

The gate lists the planned sources (tools, document ids, URLs), emits a ``source_review`` event, then waits for approval:
* a callback (``review=callable(sources) -> bool``) decides synchronously, or
* ``approve(job_id)`` / ``reject(job_id)`` set a flag (in memory, and a ``<job_id>.review`` file beside the evidence
  chain so another process can approve). The wait polls the cancel flag, so a cancel always wins.
``request.options.source_review = false`` skips the gate. ``options.review_timeout_s`` (default 86400) bounds the wait.

Jobs mode (S6.1c): ``jobs.py`` passes a persisted ``review=`` callback that waits through :func:`poll_decision`;
``jobs.status()`` then says ``awaiting_review`` and ``jobs.approve`` / ``jobs.reject`` decide (the decision lives in the
job KV, so it survives a crash). The in-memory ``approve`` / ``reject`` below stay the path for direct ``run_research``.
The wait is also visible as the ``source_review`` event with ``data.status == "awaiting_review"``.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_DECISIONS: dict[str, str] = {}
_PENDING: dict[str, list] = {}
POLL_S = 0.02


def _flag(evidence_dir, job_id) -> Path:
    return Path(evidence_dir or "storage/evidence") / f"{job_id}.review"


def approve(job_id: str, *, evidence_dir=None) -> bool:
    return _decide(job_id, "approved", evidence_dir)


def reject(job_id: str, *, evidence_dir=None) -> bool:
    return _decide(job_id, "rejected", evidence_dir)


def _decide(job_id, decision, evidence_dir) -> bool:
    with _LOCK:
        _DECISIONS[job_id] = decision
    if evidence_dir is not None:
        p = _flag(evidence_dir, job_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(decision, encoding="utf-8")
    return True


def pending() -> dict:
    with _LOCK:
        return {k: list(v) for k, v in _PENDING.items()}


def poll_decision(fetch, cancelled, timeout: float, poll: float = POLL_S) -> str:
    """Shared wait loop: ``fetch() -> "approved" | "rejected" | None``; cancel wins; returns "timeout" past ``timeout``."""
    deadline = time.monotonic() + timeout
    while True:
        if cancelled():
            return "cancelled"
        d = fetch()
        if d in ("approved", "rejected"):
            return d
        if time.monotonic() > deadline:
            return "timeout"
        time.sleep(poll)


def _urls(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and (k == "url" or v.startswith(("http://", "https://"))):
                out.append(v)
            else:
                _urls(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _urls(v, out)


def plan_sources(ctx) -> list:
    """Deterministic list of what the run will read: tool calls (templates resolved where possible), docs, URLs."""
    from .base import lookup, resolve, TemplateError
    out = []
    for s in ctx.workflow.steps:
        if s.kind != "tool":
            continue
        try:
            args = resolve(s.args_template, ctx.scope(_ITEM))
        except TemplateError:
            args = s.args_template
        out.append({"kind": "tool", "tool": s.tool, "args": args, "optional": s.optional})
    for d in ctx.request.get("doc_ids") or []:
        out.append({"kind": "document", "doc_id": d})
    urls: list = []
    _urls(ctx.options, urls)
    for u in dict.fromkeys(urls):
        out.append({"kind": "url", "url": u})
    return out


_ITEM = "<item>"


def await_review(ctx, sources) -> str:
    cb = ctx.review
    if callable(cb):
        return "approved" if cb(sources) else "rejected"
    job_id = ctx.job_id
    ev_dir = ctx.bundle.path.parent
    timeout = float(ctx.options.get("review_timeout_s", 86400))
    with _LOCK:
        _PENDING[job_id] = sources
        _DECISIONS.pop(job_id, None)
    flag = _flag(ev_dir, job_id)
    flag.unlink(missing_ok=True)
    def fetch():
        with _LOCK:
            d = _DECISIONS.get(job_id)
        if d is None and flag.exists():
            d = flag.read_text(encoding="utf-8").strip() or None
        return d
    try:
        return poll_decision(fetch, ctx.cancelled, timeout)
    finally:
        with _LOCK:
            _PENDING.pop(job_id, None)
            _DECISIONS.pop(job_id, None)
        flag.unlink(missing_ok=True)
