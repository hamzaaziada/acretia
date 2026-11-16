"""Per-job token and cost ledger plus an atomic spend guard (stdlib only).

Every model call is one append-only JSONL row (audit trail). The guard works by RESERVE -> SETTLE (FP-S2b, F3):

    ledger = Ledger("data/ledger.jsonl", guard=SpendGuard(limit_usd=5.0, job_limit_usd=1.0))
    res = ledger.reserve("job-1", "gpt-4.1-mini", worst_case_usd)      # checks the guard AND books it, atomically
    try:   ... send the call ...
    except: ledger.release(res); raise                                 # never reached the provider: free the money
    ledger.settle(res, {"input_tokens": 1800, "output_tokens": 300})   # replaces the reservation by the actual cost

Committed spend plus in-flight reservations never exceed the limit. In one process this is one lock; when the ledger
has a `path`, committed rows and reservations also live in one SQLite file (`<path>.sqlite`, WAL, BEGIN IMMEDIATE) so
several processes share one budget. Reservations older than `reservation_ttl` seconds (a crashed process) are ignored.
`precheck` / `record` / `total` keep their old signatures.
"""
from __future__ import annotations

import contextlib
import itertools
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# USD per million tokens (input, output), matched by the longest substring of the lower-cased model id ("." -> "-").
# Verified entries are public list prices fetched 2026-11-16 (sources in src/harness/profiles/*.json `price_source`).
# Unverified entries are deliberately conservative. Unknown models use DEFAULT_PRICE = the most expensive known price.
PRICES: dict[str, tuple[float, float]] = {
    # Anthropic (verified): platform.claude.com/docs/en/about-claude/pricing
    "claude-fable": (10.0, 50.0), "claude-mythos": (10.0, 50.0),
    "claude-opus": (15.0, 75.0), "claude-opus-4-5": (5.0, 25.0), "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0), "claude-opus-4-8": (5.0, 25.0), "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet": (3.0, 15.0), "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku": (1.0, 5.0), "claude-haiku-5": (0.50, 2.50),
    # OpenAI (verified): developers.openai.com/api/docs/pricing
    "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.0, 8.0), "gpt-5": (1.25, 10.0), "gpt-5-mini": (0.25, 2.0),
    "gpt-5-pro": (15.0, 120.0), "gpt-4o": (2.5, 10.0),
    # Google (verified): aistudio.google.com/docs/pricing; Pro entries use the >200k-token tier (conservative)
    "gemini-2.5-pro": (2.50, 15.0), "gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-3.1-pro": (4.0, 18.0), "gemini-3-flash": (0.50, 3.0), "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50), "gemini-3.6-flash": (1.50, 7.50), "gemini-3.8-flash": (1.50, 7.50),
    "gemini-pro": (4.0, 18.0), "gemini-flash": (1.50, 7.50), "gemini": (4.0, 18.0),
    # unverified, conservative (price_verified: false)
    "deepseek": (0.60, 2.20), "kimi": (1.20, 5.0), "glm": (1.20, 4.40), "llama": (0.90, 0.90),
    "mistral-large": (3.0, 9.0), "qwen": (0.60, 1.80),
    # self-hosted: free
    "ollama": (0.0, 0.0), "local": (0.0, 0.0),
}
DEFAULT_PRICE = (max(p[0] for p in PRICES.values()), max(p[1] for p in PRICES.values()))   # most expensive known
CACHED_DISCOUNT = 0.1            # cached input tokens bill at 10% of the input price
RESERVATION_TTL = 3600.0


class BudgetExceeded(RuntimeError):
    """Raised instead of sending a call whose worst-case cost would exceed the limit."""


def price_for(model: str, prices: dict | None = None) -> tuple[float, float]:
    m = (model or "").lower().replace(".", "-")
    table = prices if prices is not None else PRICES
    best = max((k for k in table if k.lower().replace(".", "-") in m), key=len, default=None)
    if best:
        return tuple(table[best])
    return (max(p[0] for p in table.values()), max(p[1] for p in table.values())) if prices is not None and table else DEFAULT_PRICE


def cost_usd(model: str, input_tokens: int | None, output_tokens: int | None, cached_tokens: int | None = 0,
             prices: dict | None = None) -> float:
    pin, pout = price_for(model, prices)
    inp, out, cached = int(input_tokens or 0), int(output_tokens or 0), int(cached_tokens or 0)
    cached = min(cached, inp)
    return ((inp - cached) * pin + cached * pin * CACHED_DISCOUNT + out * pout) / 1_000_000


class SpendGuard:
    """`limit_usd` caps the ledger total (all jobs); `job_limit_usd`, if given, caps each job."""

    def __init__(self, limit_usd: float, job_limit_usd: float | None = None):
        self.limit_usd, self.job_limit_usd = float(limit_usd), (None if job_limit_usd is None else float(job_limit_usd))

    def check(self, spent_total: float, spent_job: float, worst_case: float, job_id: str | None = None) -> None:
        if spent_total + worst_case > self.limit_usd + 1e-12:
            raise BudgetExceeded(f"worst-case cost ${worst_case:.4f} on top of ${spent_total:.4f} spent exceeds the "
                                 f"${self.limit_usd:.2f} limit; call not sent")
        if self.job_limit_usd is not None and spent_job + worst_case > self.job_limit_usd + 1e-12:
            raise BudgetExceeded(f"worst-case cost ${worst_case:.4f} on top of ${spent_job:.4f} spent by job {job_id!r} exceeds "
                                 f"the ${self.job_limit_usd:.2f} job limit; call not sent")


def _blank() -> dict:
    return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0}


@dataclass
class Reservation:
    """Money held for one in-flight call. Pass it to `Ledger.settle` or `Ledger.release` exactly once."""
    id: str
    job_id: str | None
    model: str
    usd: float
    ts: float
    done: bool = False


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rows(id INTEGER PRIMARY KEY, job TEXT, in_t INTEGER, out_t INTEGER, cached_t INTEGER, cost REAL);
CREATE TABLE IF NOT EXISTS resv(id TEXT PRIMARY KEY, job TEXT, usd REAL, ts REAL);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""
_seq = itertools.count(1)


class Ledger:
    """Append-only JSONL (when `path` is given) plus totals per job. Thread-safe and, with a path, process-safe for the
    guard (see module docstring). An existing JSONL is imported on first use, so spend survives restarts."""

    def __init__(self, path: str | Path | None = None, guard: SpendGuard | None = None, prices: dict | None = None,
                 reservation_ttl: float = RESERVATION_TTL):
        self.path = Path(path) if path else None
        self.guard, self.prices, self.reservation_ttl = guard, prices, float(reservation_ttl)
        self._lock = threading.RLock()
        self._tls = threading.local()
        self._jobs: dict[str, dict] = {}
        self._all = _blank()
        self._resv: dict[str, Reservation] = {}      # in-process mode only
        self.rows: list[dict] = []
        self._db_path = self.path.with_name(self.path.name + ".sqlite") if self.path else None
        if self._db_path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
        elif self.path and self.path.is_file():
            self._load_jsonl(self._add)

    # ------------------------------------------------------------------ sqlite (cross-process)
    @contextlib.contextmanager
    def _tx(self):
        c = sqlite3.connect(self._db_path, timeout=60, isolation_level=None)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=60000")
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")
        finally:
            c.close()

    def _init_db(self) -> None:
        with self._tx() as c:
            for stmt in _SCHEMA.strip().split(";"):
                if stmt.strip():
                    c.execute(stmt)
            if not c.execute("SELECT 1 FROM meta WHERE k='imported'").fetchone():
                if self.path.is_file():
                    def ins(row):
                        c.execute("INSERT INTO rows(job,in_t,out_t,cached_t,cost) VALUES(?,?,?,?,?)",
                                  (row.get("job_id") or "-", int(row.get("input_tokens") or 0), int(row.get("output_tokens") or 0),
                                   int(row.get("cached_tokens") or 0), float(row.get("cost_usd") or 0.0)))
                    self._load_jsonl(ins)
                c.execute("INSERT INTO meta VALUES('imported','1')")

    def _load_jsonl(self, sink) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                sink(json.loads(line))
            except (ValueError, TypeError):
                continue          # a torn last line never blocks startup

    def _db_totals(self, c, job_id: str | None) -> tuple[float, float, float, float]:
        """(committed_total, committed_job, inflight_total, inflight_job) from the shared file."""
        j = job_id or "-"
        ct = c.execute("SELECT COALESCE(SUM(cost),0) FROM rows").fetchone()[0]
        cj = c.execute("SELECT COALESCE(SUM(cost),0) FROM rows WHERE job=?", (j,)).fetchone()[0]
        cut = time.time() - self.reservation_ttl
        it = c.execute("SELECT COALESCE(SUM(usd),0) FROM resv WHERE ts>=?", (cut,)).fetchone()[0]
        ij = c.execute("SELECT COALESCE(SUM(usd),0) FROM resv WHERE ts>=? AND job=?", (cut, j)).fetchone()[0]
        return ct, cj, it, ij

    # ------------------------------------------------------------------ in-memory accounting
    def _add(self, row: dict) -> None:
        for acc in (self._all, self._jobs.setdefault(row.get("job_id") or "-", _blank())):
            acc["calls"] += 1
            acc["input_tokens"] += int(row.get("input_tokens") or 0)
            acc["output_tokens"] += int(row.get("output_tokens") or 0)
            acc["cached_tokens"] += int(row.get("cached_tokens") or 0)
            acc["cost_usd"] += float(row.get("cost_usd") or 0.0)
        self.rows.append(row)

    def _mem_inflight(self, job_id: str | None) -> tuple[float, float]:
        j = job_id or "-"
        return (sum(r.usd for r in self._resv.values()), sum(r.usd for r in self._resv.values() if (r.job_id or "-") == j))

    def inflight_usd(self, job_id: str | None = None) -> float:
        """Money currently reserved by unsettled calls (all jobs, or one job)."""
        with self._lock:
            if self._db_path:
                with self._tx() as c:
                    _, _, it, ij = self._db_totals(c, job_id)
                return ij if job_id is not None else it
            it, ij = self._mem_inflight(job_id)
            return ij if job_id is not None else it

    # ------------------------------------------------------------------ guard API
    def worst_case(self, model: str, est_input_tokens: int, max_tokens: int) -> float:
        return cost_usd(model, est_input_tokens, max_tokens, 0, self.prices)

    def precheck(self, job_id: str | None, model: str, est_input_tokens: int, max_tokens: int) -> float:
        """Non-reserving check (kept for compatibility; the adapter uses `reserve`)."""
        worst = self.worst_case(model, est_input_tokens, max_tokens)
        if self.guard is not None:
            with self._lock:
                if self._db_path:
                    with self._tx() as c:
                        ct, cj, it, ij = self._db_totals(c, job_id)
                    self.guard.check(ct + it, cj + ij, worst, job_id)
                else:
                    it, ij = self._mem_inflight(job_id)
                    self.guard.check(self._all["cost_usd"] + it, self._jobs.get(job_id or "-", _blank())["cost_usd"] + ij, worst, job_id)
        return worst

    def reserve(self, job_id: str | None, model: str, worst_case_usd: float) -> Reservation:
        """Check the guard against committed spend + all in-flight reservations and book `worst_case_usd`, as ONE
        atomic step (lock; plus a SQLite write transaction when the ledger has a path). Raises BudgetExceeded."""
        usd = max(0.0, float(worst_case_usd))
        res = Reservation(f"{os.getpid()}-{id(self):x}-{next(_seq)}-{time.time_ns()}", job_id, model, usd, time.time())
        with self._lock:
            if self._db_path:
                with self._tx() as c:
                    if self.guard is not None:
                        ct, cj, it, ij = self._db_totals(c, job_id)
                        self.guard.check(ct + it, cj + ij, usd, job_id)
                    c.execute("INSERT INTO resv VALUES(?,?,?,?)", (res.id, job_id or "-", usd, res.ts))
            else:
                if self.guard is not None:
                    it, ij = self._mem_inflight(job_id)
                    self.guard.check(self._all["cost_usd"] + it, self._jobs.get(job_id or "-", _blank())["cost_usd"] + ij, usd, job_id)
                self._resv[res.id] = res
        return res

    def release(self, reservation: Reservation) -> None:
        """Free a reservation for a call that never reached the provider. Idempotent."""
        with self._lock:
            if reservation.done:
                return
            reservation.done = True
            if self._db_path:
                with self._tx() as c:
                    c.execute("DELETE FROM resv WHERE id=?", (reservation.id,))
            else:
                self._resv.pop(reservation.id, None)

    def _tokens_for_usd(self, model: str, usd: float) -> int:
        pout = price_for(model, self.prices)[1]
        return int(usd * 1_000_000 / pout) + 1 if pout > 0 and usd > 0 else 0

    def settle(self, reservation: Reservation, actual_usage: dict | None = None, note: str = "") -> dict:
        """Replace the reservation by the actual cost (one atomic step). `actual_usage` has input_tokens,
        output_tokens, cached_tokens; when None (unknown) the whole reserved worst case is billed, never $0."""
        with self._lock:
            if reservation.done:
                return {}
            u = actual_usage
            if u is None or (u.get("input_tokens") is None and u.get("output_tokens") is None):
                i, o, cached = 0, self._tokens_for_usd(reservation.model, reservation.usd), 0
                note = (note + " " if note else "") + "worst-case (usage unknown)"
            else:
                i, o, cached = u.get("input_tokens") or 0, u.get("output_tokens") or 0, u.get("cached_tokens") or 0
            reservation.done = True
            self._tls.release = reservation.id
            try:
                return self.record(reservation.job_id, reservation.model, i, o, cached, note)
            finally:
                self._tls.release = None
                if not self._db_path:
                    self._resv.pop(reservation.id, None)

    # ------------------------------------------------------------------ recording
    def record(self, job_id: str | None, model: str, input_tokens: int | None, output_tokens: int | None,
               cached_tokens: int | None = 0, note: str = "") -> dict:
        cost = cost_usd(model, input_tokens, output_tokens, cached_tokens, self.prices)
        row = {"ts": round(time.time(), 3), "job_id": job_id, "model": model, "input_tokens": int(input_tokens or 0),
               "output_tokens": int(output_tokens or 0), "cached_tokens": int(cached_tokens or 0),
               "cost_usd": round(cost, 8), "note": note}
        release_id = getattr(self._tls, "release", None)
        with self._lock:
            if self._db_path:
                with self._tx() as c:
                    c.execute("INSERT INTO rows(job,in_t,out_t,cached_t,cost) VALUES(?,?,?,?,?)",
                              (job_id or "-", row["input_tokens"], row["output_tokens"], row["cached_tokens"], row["cost_usd"]))
                    if release_id:
                        c.execute("DELETE FROM resv WHERE id=?", (release_id,))
            self._add(row)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def total(self, job_id: str | None = None) -> dict:
        """Totals for one job, or for everything when job_id is omitted (shared across processes when file-backed)."""
        with self._lock:
            if self._db_path:
                with self._tx() as c:
                    q, a = "SELECT COUNT(*),COALESCE(SUM(in_t),0),COALESCE(SUM(out_t),0),COALESCE(SUM(cached_t),0),COALESCE(SUM(cost),0) FROM rows", ()
                    if job_id is not None:
                        q, a = q + " WHERE job=?", (job_id or "-",)
                    n, i, o, ca, co = c.execute(q, a).fetchone()
                return {"calls": n, "input_tokens": i, "output_tokens": o, "cached_tokens": ca, "cost_usd": co}
            return dict(self._jobs.get(job_id or "-", _blank()) if job_id is not None else self._all)

    def jobs(self) -> dict[str, dict]:
        with self._lock:
            if self._db_path:
                with self._tx() as c:
                    return {j: {"calls": n, "input_tokens": i, "output_tokens": o, "cached_tokens": ca, "cost_usd": co}
                            for j, n, i, o, ca, co in c.execute(
                                "SELECT job,COUNT(*),SUM(in_t),SUM(out_t),SUM(cached_t),SUM(cost) FROM rows GROUP BY job")}
            return {k: dict(v) for k, v in self._jobs.items()}
