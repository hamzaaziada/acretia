"""S6.0 durable research jobs on the SQLiteKV queue ``research``.

Layout in the KV file (``ACRETIA_JOBS_DB``, default ``storage/jobs.sqlite``); every key carries the org id, so
one org can never address another org's rows::

    job:{org}:{id}      Job row (+ request, user, timestamps)      written by submit / worker only
    result:{org}:{id}   ResearchResult JSON                         written once by the worker
    cancel:{org}:{id}   "1" when cancellation was requested
    ev:{org}:{id}:{n}   persisted event n (1-based);  evn:{org}:{id} is the counter
    review:{org}:{id}   source-review decision {decision, approver|reason, at}; written by approve / reject only

Source review (S6.1c, parity item 24): when a workflow reaches its review gate the job status becomes
``awaiting_review`` and the planned sources are persisted as the ``source_review`` event. ``approve`` / ``reject``
write the decision key (so it survives a worker crash: the redelivered run finds it and carries on).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

from om.contracts import Job, JobStep
from om.storage import SQLiteKV
from .api import API_VERSION, ResearchRequest, ResearchResult, run_research
from .workflows import review as _review

QUEUE = "research"
MAX_ATTEMPTS = 3
_TERMINAL = ("succeeded", "failed", "cancelled")
REVIEW_POLL_S = 0.1
_kvs: dict[str, SQLiteKV] = {}
_kv_lock = threading.Lock()


class JobNotFound(KeyError):
    """Unknown job id, or a job that belongs to another org (deliberately indistinguishable)."""


def _kv(path: str | None = None) -> SQLiteKV:
    path = path or os.environ.get("ACRETIA_JOBS_DB", "storage/jobs.sqlite")
    with _kv_lock:
        if path not in _kvs:
            _kvs[path] = SQLiteKV(path)
        return _kvs[path]


def close_all() -> None:
    with _kv_lock:
        for kv in _kvs.values():
            kv.close()
        _kvs.clear()


def _now() -> str:
    from .api import _now as n
    return n()


def _load(kv, job_id, org_id) -> dict:
    raw = kv.get(f"job:{org_id}:{job_id}")
    if raw is None:
        raise JobNotFound(job_id)
    return json.loads(raw)


def _save(kv, org_id, row) -> None:
    row["updated_at"] = _now()
    kv.set(f"job:{org_id}:{row['job']['id']}", json.dumps(row, sort_keys=True))


def submit(request, *, org_id: str | None = None) -> str:
    """Persist a queued Job and enqueue it. The org comes from ``request.org_id`` (``org_id=`` must agree if given)."""
    if isinstance(request, dict):
        request = ResearchRequest.from_dict(request)
    request.validate()
    if org_id is not None and org_id != request.org_id:
        raise ValueError("org_id differs from request.org_id")
    kv, org = _kv(), request.org_id
    job_id = "res_" + uuid.uuid4().hex[:16]
    row = {"v": API_VERSION, "org_id": org, "user_id": request.user_id, "request": request.to_dict(),
           "created_at": _now(), "job": Job(id=job_id, kind="research", status="queued").to_dict()}
    _save(kv, org, row)
    kv.enqueue(QUEUE, json.dumps({"org_id": org, "job_id": job_id}))
    return job_id


def status(job_id: str, *, org_id: str = "local") -> Job:
    return Job.from_dict(_load(_kv(), job_id, org_id)["job"])


def result(job_id: str, *, org_id: str = "local") -> ResearchResult | None:
    kv = _kv()
    _load(kv, job_id, org_id)
    raw = kv.get(f"result:{org_id}:{job_id}")
    return None if raw is None else ResearchResult.from_json(raw)


def cancel(job_id: str, *, org_id: str = "local") -> bool:
    """Request cancellation. Returns False if the job already finished. The worker honours it between steps."""
    kv = _kv()
    row = _load(kv, job_id, org_id)
    if row["job"]["status"] in _TERMINAL:
        return False
    kv.set(f"cancel:{org_id}:{job_id}", "1")
    return True


def _decide(job_id, org_id, decision, who_key, who) -> bool:
    kv = _kv()
    row = _load(kv, job_id, org_id)                     # JobNotFound for an unknown job or another org's job
    if row["job"]["status"] != "awaiting_review" or kv.get(f"review:{org_id}:{job_id}") is not None:
        return False
    rec = {"decision": decision, who_key: who, "at": _now()}
    kv.set(f"review:{org_id}:{job_id}", json.dumps(rec, sort_keys=True))
    if decision == "approved":
        row["job"]["status"] = "running"
    else:
        kv.set(f"cancel:{org_id}:{job_id}", "1")        # the waiting (or redelivered) worker ends it as cancelled
    row["review"] = rec
    _save(kv, org_id, row)
    _persist_event(kv, org_id, {"v": API_VERSION, "type": "source_review", "job_id": job_id, "ts": _now(),
                                "data": {"status": decision, **{who_key: who}}})
    return True


def approve(job_id: str, org_id: str = "local", approver: str | None = None) -> bool:
    """Approve the planned sources of a job in ``awaiting_review``; the job resumes. False if it is not waiting."""
    return _decide(job_id, org_id, "approved", "approver", approver)


def reject(job_id: str, reason: str | None = None, *, org_id: str = "local") -> bool:
    """Reject the planned sources: the job ends ``cancelled``. False if it is not waiting."""
    return _decide(job_id, org_id, "rejected", "reason", reason)


def review_sources(job_id: str, *, org_id: str = "local") -> list | None:
    """Planned sources of the latest ``source_review`` request, or None when the job never reached the gate."""
    for e in reversed(events(job_id, org_id=org_id)):
        if e["type"] == "source_review" and (e.get("data") or {}).get("status") == "awaiting_review":
            return e["data"].get("sources")
    return None


def _persist_event(kv, org_id, ev: dict) -> dict:
    n = kv.incr(f"evn:{org_id}:{ev['job_id']}")
    ev = dict(ev, seq=n)
    kv.set(f"ev:{org_id}:{ev['job_id']}:{n}", json.dumps(ev, sort_keys=True))
    return ev


def events(job_id: str, after_seq: int = 0, *, org_id: str = "local", limit: int = 500) -> list[dict]:
    kv = _kv()
    _load(kv, job_id, org_id)
    top = int(kv.get(f"evn:{org_id}:{job_id}", 0) or 0)
    out = []
    for n in range(max(after_seq, 0) + 1, top + 1):
        raw = kv.get(f"ev:{org_id}:{job_id}:{n}")
        if raw is not None:
            out.append(json.loads(raw))
        if len(out) >= limit:
            break
    return out


class _KVCancel:
    """threading.Event look-alike backed by the persisted cancel flag (cancel may come from another process)."""

    def __init__(self, kv, org_id, job_id):
        self._kv, self._key = kv, f"cancel:{org_id}:{job_id}"

    def is_set(self) -> bool:
        return self._kv.get(self._key) is not None


def _process(kv, lease, adapter, tools, evidence_dir) -> None:
    msg = json.loads(lease.payload)
    org, job_id = msg["org_id"], msg["job_id"]
    try:
        row = _load(kv, job_id, org)
    except JobNotFound:
        kv.ack(lease)
        return
    if kv.get(f"result:{org}:{job_id}") is not None:
        kv.ack(lease)                       # idempotent: a duplicate delivery of a finished job
        return
    if lease.attempts > MAX_ATTEMPTS:
        row["job"].update(status="failed", attempts=lease.attempts, error="max attempts exceeded")
        _save(kv, org, row)
        kv.ack(lease)
        return
    resuming = row["job"]["status"] == "awaiting_review"   # crashed while waiting: keep waiting (or finish approval)
    row["job"].update(status=row["job"]["status"] if resuming else "running", attempts=lease.attempts)
    _save(kv, org, row)
    cancel = _KVCancel(kv, org, job_id)
    timeout = float(row["request"].get("options", {}).get("review_timeout_s", 86400))

    def on_event(e):
        ev = _persist_event(kv, org, e)
        if e.get("type") == "source_review" and (e.get("data") or {}).get("status") == "awaiting_review":
            cur = _load(kv, job_id, org)
            if kv.get(f"review:{org}:{job_id}") is None and cur["job"]["status"] != "awaiting_review":
                cur["job"]["status"] = "awaiting_review"
                _save(kv, org, cur)
        return ev

    def review(sources) -> bool:
        def fetch():
            raw = kv.get(f"review:{org}:{job_id}")
            return json.loads(raw)["decision"] if raw is not None else None
        d = _review.poll_decision(fetch, cancel.is_set, timeout, REVIEW_POLL_S)
        cur = _load(kv, job_id, org)
        if d == "approved" and cur["job"]["status"] == "awaiting_review":
            cur["job"]["status"] = "running"
            _save(kv, org, cur)
        return d == "approved"
    ev_dir = evidence_dir or os.environ.get("ACRETIA_EVIDENCE_DIR", "storage/evidence")
    res = run_research(ResearchRequest.from_dict(row["request"]), adapter=adapter, tools=tools,
                       evidence_dir=ev_dir, job_id=job_id, cancel=cancel,
                       on_event=on_event, review=review)
    kv.set(f"result:{org}:{job_id}", res.to_json())
    row = _load(kv, job_id, org)                        # approve/reject may have added a "review" record meanwhile
    row["job"].update(status=res.status, steps=[s.to_dict() for s in res.steps], tokens=res.tokens,
                      cost_usd=res.cost_usd, error=res.error)
    Job.from_dict(row["job"])
    _save(kv, org, row)
    kv.ack(lease)


def worker_loop(stop_event: threading.Event, adapter=None, *, tools=None, evidence_dir=None, lease: float = 300.0,
                poll: float = 0.2, db_path: str | None = None) -> None:
    """Dequeue -> run_research -> ack. A crash leaves the item leased; once the lease expires it is delivered
    again and re-run (same job_id, evidence chain continues, result written once)."""
    kv = _kv(db_path)
    while not stop_event.is_set():
        item = kv.dequeue(QUEUE, lease=lease)
        if item is None:
            stop_event.wait(poll)
            continue
        try:
            _process(kv, item, adapter, tools, evidence_dir)
        except Exception:
            kv.nack(item, delay=1.0)
            time.sleep(0)
