"""Per-job token and cost ledger plus a spend guard (stdlib only).

Ported in spirit from reference/meshpool-harness/eval/ledger.py: every model call is one append-only JSONL row, the
guard refuses a call BEFORE it is sent when its worst case (all `max_tokens` used) would push spend past the limit.

    ledger = Ledger("data/ledger.jsonl", guard=SpendGuard(limit_usd=5.0, job_limit_usd=1.0))
    ledger.precheck("job-1", "gpt-4.1-mini", est_input_tokens=2000, max_tokens=4000)   # may raise BudgetExceeded
    ledger.record("job-1", "gpt-4.1-mini", input_tokens=1800, output_tokens=300)
    ledger.total("job-1") -> {"calls": 1, "input_tokens": 1800, "output_tokens": 300, "cached_tokens": 0, "cost_usd": ...}
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

# USD per million tokens (input, output), matched by the longest substring of the lower-cased model id.
# Approximate list prices; pass `prices=` to Ledger to override. Unknown models use DEFAULT_PRICE, deliberately high.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus": (15.0, 75.0), "claude-sonnet": (3.0, 15.0), "claude-haiku": (1.0, 5.0),
    "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.0, 8.0), "gpt-5": (1.25, 10.0), "gpt-4o": (2.5, 10.0),
    "gemini-flash": (0.30, 2.50), "gemini-pro": (1.25, 10.0), "gemini": (0.30, 2.50),
    "deepseek": (0.27, 1.10), "llama": (0.60, 0.60), "mistral-large": (2.0, 6.0), "qwen": (0.30, 0.90),
    "ollama": (0.0, 0.0), "local": (0.0, 0.0),
}
DEFAULT_PRICE = (15.0, 75.0)
CACHED_DISCOUNT = 0.1            # cached input tokens bill at 10% of the input price


class BudgetExceeded(RuntimeError):
    """Raised instead of sending a call whose worst-case cost would exceed the limit."""


def price_for(model: str, prices: dict | None = None) -> tuple[float, float]:
    m = (model or "").lower()
    table = prices if prices is not None else PRICES
    best = max((k for k in table if k.lower() in m), key=len, default=None)
    return tuple(table[best]) if best else DEFAULT_PRICE


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


class Ledger:
    """Append-only JSONL (when `path` is given) plus in-memory totals per job. Thread-safe. An existing file is
    replayed into the totals on construction, so spend survives restarts."""

    def __init__(self, path: str | Path | None = None, guard: SpendGuard | None = None, prices: dict | None = None):
        self.path = Path(path) if path else None
        self.guard, self.prices = guard, prices
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._all = _blank()
        self.rows: list[dict] = []
        if self.path and self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    self._add(json.loads(line))
                except (ValueError, TypeError):
                    continue          # a torn last line never blocks startup

    def _add(self, row: dict) -> None:
        for acc in (self._all, self._jobs.setdefault(row.get("job_id") or "-", _blank())):
            acc["calls"] += 1
            acc["input_tokens"] += int(row.get("input_tokens") or 0)
            acc["output_tokens"] += int(row.get("output_tokens") or 0)
            acc["cached_tokens"] += int(row.get("cached_tokens") or 0)
            acc["cost_usd"] += float(row.get("cost_usd") or 0.0)
        self.rows.append(row)

    def precheck(self, job_id: str | None, model: str, est_input_tokens: int, max_tokens: int) -> float:
        """Refuse BEFORE the call when input estimate + all max_tokens at output price would break the guard."""
        worst = cost_usd(model, est_input_tokens, max_tokens, 0, self.prices)
        if self.guard is not None:
            with self._lock:
                self.guard.check(self._all["cost_usd"], self._jobs.get(job_id or "-", _blank())["cost_usd"], worst, job_id)
        return worst

    def record(self, job_id: str | None, model: str, input_tokens: int | None, output_tokens: int | None,
               cached_tokens: int | None = 0, note: str = "") -> dict:
        cost = cost_usd(model, input_tokens, output_tokens, cached_tokens, self.prices)
        row = {"ts": round(time.time(), 3), "job_id": job_id, "model": model, "input_tokens": int(input_tokens or 0),
               "output_tokens": int(output_tokens or 0), "cached_tokens": int(cached_tokens or 0),
               "cost_usd": round(cost, 8), "note": note}
        with self._lock:
            self._add(row)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def total(self, job_id: str | None = None) -> dict:
        """Totals for one job, or for everything when job_id is omitted."""
        with self._lock:
            return dict(self._jobs.get(job_id or "-", _blank()) if job_id is not None else self._all)

    def jobs(self) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._jobs.items()}
