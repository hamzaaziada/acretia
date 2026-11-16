#!/usr/bin/env python3
"""Budget guard + ledger for every meshpool model call.

This module is the single choke point for model traffic in the project. It is
built first (phase 0) because the $35 hard cap is the hardest constraint in the
task, and because the guard itself must be able to run without spending money.

Behaviour required by PROMPT.md <budget> / <build_efficiency>:

* Before any work, make one tiny call and record the starting value of
  ``x-litellm-key-spend``. The budget is that starting value plus $35.00, all
  limits are relative to it. This module pins that baseline in
  ``eval/guard_baseline.json`` on first use.
* ``ledger.csv``: one row per model call -- timestamp, phase, model, profile,
  task id, role, input tokens, cached input tokens, output tokens, computed
  cost (from the usage fields and pricing.json).
* Refuse any call once spend since start passes $38.00 (stop spend).
* Refuse calls that exceed the current phase budget unless money is explicitly
  moved from the reserve and the reason is logged.
* Reconcile the ledger with ``x-litellm-key-spend``; if they differ by >5%,
  trust the header and report it.

Spend source of truth: the ``x-litellm-key-spend`` response header. The usage
object has no cached-token breakdown (PROMPT.md access notes), so cached tokens
are best-effort from the usage object when present, and cache savings are
measured from spend deltas, not from usage fields.
"""
from __future__ import annotations

import csv
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Paths and constants
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
LEDGER_PATH = EVAL_DIR / "ledger.csv"
TRANSACTIONS_PATH = EVAL_DIR / "ledger_transactions.csv"
BASELINE_PATH = EVAL_DIR / "guard_baseline.json"
PRICING_PATH = EVAL_DIR / "pricing.json"

HARD_CAP = float(os.environ.get("MH_HARD_CAP", "1e9"))     # owner set the limit on the API key itself
STOP_SPEND = float(os.environ.get("MH_STOP_SPEND", "1e9"))  # the key limit is the stop; set to cap locally
RESERVE = 3.50           # reserve held back from phase budgets

# Phase budgets, in US$, relative to baseline (PROMPT.md <budget>).
PHASE_BUDGETS: dict[str, float] = {
    "phase_0_recon": 1.50,
    "phase_1_baseline": 5.00,
    "phase_2_build": 13.00,
    "phase_3_other_profiles": 3.00,
    "phase_4_final_eval": 9.00,
    "reserve": RESERVE,
}

LEDGER_FIELDS = [
    "timestamp", "phase", "model", "profile", "task_id", "job_id",
    "role", "input_tokens", "cached_input_tokens", "output_tokens",
    "computed_cost", "key_spend", "since_start", "http_status", "note",
]


class BudgetExceeded(RuntimeError):
    """Raised instead of sending a call that the guard refuses."""


@dataclass
class LedgerState:
    phase: str = "phase_0_recon"
    baseline: float | None = None
    last_key_spend: float | None = None
    calls: int = 0
    phase_transactions: dict[str, float] = field(default_factory=dict)

    @property
    def since_start(self) -> float:
        if self.baseline is None or self.last_key_spend is None:
            return 0.0
        return self.last_key_spend - self.baseline


class Ledger:
    """Thread-safe budget guard and ledger writer."""

    def __init__(self, phase: str = "phase_0_recon", base_url: str | None = None,
                 api_key: str | None = None) -> None:
        self.state = LedgerState(phase=phase)
        self.base_url = (base_url or os.environ.get("MESHPOOL_BASE_URL")
                         or "http://127.0.0.1:8099/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("MESHPOOL_API_KEY", "[REDACTED]")
        self._lock = threading.Lock()
        self._pricing = json.loads(PRICING_PATH.read_text()) if PRICING_PATH.exists() else {}
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        self.state.baseline = self._load_baseline()
        self._ensure_ledger()
        self._ensure_transactions()

    # -- baseline ----------------------------------------------------------- #
    def _load_baseline(self) -> float | None:
        if BASELINE_PATH.exists():
            return float(json.loads(BASELINE_PATH.read_text())["baseline"])
        return None

    def _save_baseline(self, value: float) -> None:
        BASELINE_PATH.write_text(json.dumps({
            "baseline": value,
            "set_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": "starting x-litellm-key-spend; budget = baseline + 35.00 USD",
        }, indent=2))

    def _ensure_ledger(self) -> None:
        if not LEDGER_PATH.exists():
            with LEDGER_PATH.open("w", newline="") as f:
                csv.writer(f).writerow(LEDGER_FIELDS)

    def _ensure_transactions(self) -> None:
        if not TRANSACTIONS_PATH.exists():
            with TRANSACTIONS_PATH.open("w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp", "from", "to", "amount", "why"])

    # -- guard -------------------------------------------------------------- #
    def phase_remaining(self) -> float:
        budget = PHASE_BUDGETS.get(self.state.phase, 0.0)
        spent = self.state.phase_transactions.get(self.state.phase, 0.0)
        return budget - spent

    def check_budget(self, estimated_cost: float = 0.0) -> None:
        """Raise BudgetExceeded if the call may not proceed."""
        if self.state.baseline is not None and self.state.last_key_spend is not None:
            if self.state.since_start >= STOP_SPEND:
                raise BudgetExceeded(
                    f"stop-spend reached: ${self.state.since_start:.4f} since start "
                    f"(limit ${STOP_SPEND:.2f})")
            if self.state.since_start + estimated_cost > HARD_CAP:
                raise BudgetExceeded(
                    f"hard cap would be exceeded: ${self.state.since_start:.4f}"
                    f"+${estimated_cost:.4f} > ${HARD_CAP:.2f}")
        # phase budget (0.0 means unknown phase -> only global caps apply)
        if self.state.phase in PHASE_BUDGETS:
            if self.phase_remaining() - estimated_cost < 0:
                raise BudgetExceeded(
                    f"phase {self.state.phase} budget exhausted: "
                    f"${spent_total(self.state.phase):.4f} of "
                    f"${PHASE_BUDGETS[self.state.phase]:.2f}; move reserve "
                    f"explicitly to continue")

    def move_reserve(self, to_phase: str, amount: float, why: str) -> None:
        """Deliberately move money out of the reserve, logging the reason."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        with self._lock:
            avail = PHASE_BUDGETS["reserve"] - self.state.phase_transactions.get("reserve", 0.0)
            if amount > avail:
                raise BudgetExceeded(f"reserve only has ${avail:.4f} left")
            self.state.phase_transactions["reserve"] = (
                self.state.phase_transactions.get("reserve", 0.0) + amount)
            # phase budgets are caps; log the transfer for the record
            with TRANSACTIONS_PATH.open("a", newline="") as f:
                csv.writer(f).writerow([
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "reserve", to_phase, f"{amount:.4f}", why])

    # -- cost --------------------------------------------------------------- #
    def compute_cost(self, model: str, usage: dict, at_utc: time.struct_time | None = None) -> float:
        p = self._pricing.get(model)
        if not p or p.get("input") is None:
            return 0.0  # price unknown; header reconciliation is source of truth
        inp = int(usage.get("prompt_tokens") or 0)
        out = int(usage.get("completion_tokens") or 0)
        cached = int(usage.get("prompt_cache_hit_tokens")
                     or usage.get("cached_tokens") or 0) if usage else 0
        p_in, p_out = p["input"], p["output"]
        p_hit = p.get("input_cache_hit", p_in)
        if "peak" in p:  # deepseek: choose tier by UTC time
            t = at_utc or time.gmtime()
            hm = t.tm_hour + t.tm_min / 60.0
            weekday = t.tm_wday < 5
            peak = weekday and (1.0 <= hm < 4.0 or 6.0 <= hm < 10.0)
            tier = p["peak"] if peak else p
            p_in, p_out, p_hit = tier["input"], tier["output"], tier["input_cache_hit"]
        fresh = max(inp - cached, 0)
        return (fresh * p_in + cached * p_hit + out * p_out) / 1_000_000.0

    # -- recording ---------------------------------------------------------- #
    def record(self, *, model: str, profile: str, task_id: str, role: str,
               usage: dict | None, key_spend: float | None, status: int,
               job_id: str = "", note: str = "") -> dict:
        usage = usage or {}
        with self._lock:
            if key_spend is not None:
                if self.state.baseline is None:
                    self.state.baseline = key_spend
                    self._save_baseline(key_spend)
                self.state.last_key_spend = key_spend
            cost = self.compute_cost(model, usage)
            self.state.phase_transactions[self.state.phase] = (
                self.state.phase_transactions.get(self.state.phase, 0.0) + cost)
            self.state.calls += 1
            row = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "phase": self.state.phase,
                "model": model,
                "profile": profile,
                "task_id": task_id,
                "job_id": job_id,
                "role": role,
                "input_tokens": int(usage.get("prompt_tokens") or 0),
                "cached_input_tokens": int(usage.get("prompt_cache_hit_tokens")
                                           or usage.get("cached_tokens") or 0),
                "output_tokens": int(usage.get("completion_tokens") or 0),
                "computed_cost": f"{cost:.6f}",
                "key_spend": "" if key_spend is None else f"{key_spend:.6f}",
                "since_start": "" if self.state.baseline is None else f"{self.state.since_start:.6f}",
                "http_status": status,
                "note": note,
            }
            with LEDGER_PATH.open("a", newline="") as f:
                csv.DictWriter(f, fieldnames=LEDGER_FIELDS).writerow(row)
            return row

    # -- live call ---------------------------------------------------------- #
    def chat(self, *, model: str, messages: list, profile: str = "deepseek",
             task_id: str = "", role: str = "builder", job_id: str = "",
             max_tokens: int = 16384, estimated_cost: float = 0.0,
             temperature: float | None = None, extra: dict | None = None,
             timeout: int = 600, retries: int = 2) -> dict:
        """One guarded chat completion. Returns the parsed JSON response."""
        self.check_budget(estimated_cost)
        body: dict[str, Any] = {"model": model, "messages": messages,
                                "max_tokens": max_tokens}
        if temperature is not None:
            body["temperature"] = temperature
        if extra:
            body.update(extra)
        if os.environ.get("MH_CACHE_KEY") == "1" and task_id:   # stable per-task key: lets the gateway keep one cache
            root = task_id.split("-esc")[0]
            body["prompt_cache_key"] = root
            body["user"] = root
        wire = os.environ.get("MH_WIRE", "chat")       # v2 runs set MH_WIRE=responses (cache-friendly route, cache_report.md)
        stream = os.environ.get("MH_STREAM") == "1" and wire == "chat"   # streamed replies: no long gateway stalls
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
            timeout = int(os.environ.get("MH_STREAM_IDLE_S", "20"))      # silent this long: give up and retry
            idle = timeout
            if os.environ.get("MH_STREAM_FIRST_S"):    # v4: under load the first token can take >20 s; wait longer
                timeout = int(os.environ["MH_STREAM_FIRST_S"])   # for it, then cut off a stream silent for `idle`
        if wire == "responses":
            body = to_responses(body)
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}/{'responses' if wire == 'responses' else 'chat/completions'}", data=data,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json",
                     # metadata for per-task/engine/subagent attribution
                     "X-Harness-Task-Id": task_id, "X-Harness-Job-Id": job_id,
                     "X-Harness-Role": role, "X-Harness-Profile": profile,
                     "X-Harness-Phase": self.state.phase,
                     # v4: Codex-style session header, so the gateway can keep one conversation on one backend
                     **({"session_id": task_id.split("-esc")[0]}
                        if os.environ.get("MH_SESSION_HEADERS") == "1" and task_id else {})},
            method="POST")
        status, spike, raw = 0, None, b""
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    spike = _spend_of(r.headers)
                    status = r.status
                    raw = (json.dumps(sse_to_chat(_first_then_idle(r, idle))).encode() if stream and status == 200
                           else r.read())
            except urllib.error.HTTPError as e:
                raw = e.read()
                spike = _spend_of(e.headers)
                status = e.code
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                raw = f"timed out or connection lost: {e}".encode()
                status = 0
            if status in (200, 429) or attempt == retries:
                break
            time.sleep(1.5 * (attempt + 1))
        try:
            payload = json.loads(raw.decode("utf-8", "replace")) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw[:500].decode("utf-8", "replace")}
        if wire == "responses" and status == 200:
            payload = from_responses(payload)
            log_usage_line(task_id, model, payload.get("usage") or {})
        self.record(model=model, profile=profile, task_id=task_id, role=role,
                    job_id=job_id, usage=payload.get("usage") if status == 200 else None,
                    key_spend=spike, status=status,
                    note="" if status == 200 else str(payload)[:200])
        if status == 400 and os.environ.get("MH_DUMP_400"):     # keep the rejected request for diagnosis
            try:
                d = Path(os.environ["MH_DUMP_400"]); d.mkdir(parents=True, exist_ok=True)
                (d / f"{task_id or 'req'}-{int(time.time())}.json").write_bytes(data)
            except OSError:
                pass
        if status != 200:
            raise RuntimeError(f"meshpool HTTP {status}: {payload}")
        return payload

    # -- reconciliation ----------------------------------------------------- #
    def reconcile(self) -> dict:
        header = self.state.last_key_spend
        computed = sum(self.state.phase_transactions.values())
        result = {"header_since_start": self.state.since_start,
                  "computed_total": computed, "calls": self.state.calls}
        if header is not None and self.state.baseline is not None:
            diff = abs(computed - self.state.since_start)
            pct = diff / self.state.since_start if self.state.since_start else 0.0
            result["abs_diff"] = diff
            result["pct_diff"] = pct
            result["within_5pct"] = pct <= 0.05
            result["trust"] = "header"
        return result


def to_responses(body: dict) -> dict:
    """Chat-completions request -> Responses API request (same content, same order: the prefix stays byte-stable)."""
    items = []
    for m in body.get("messages", []):
        role = m.get("role")
        if role == "tool":
            items.append({"type": "function_call_output", "call_id": m.get("tool_call_id", ""),
                          "output": str(m.get("content") or "")})
            continue
        if m.get("content"):
            items.append({"role": role, "content": m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])})
        for c in m.get("tool_calls") or []:
            f = c.get("function", {})
            items.append({"type": "function_call", "call_id": c.get("id", ""), "name": f.get("name", ""),
                          "arguments": f.get("arguments", "{}")})
    out = {"model": body["model"], "input": items, "max_output_tokens": body.get("max_tokens", 8192)}
    if body.get("prompt_cache_key"):
        out["prompt_cache_key"] = body["prompt_cache_key"]
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if body.get("tools"):
        out["tools"] = [{"type": "function", "name": t["function"]["name"],
                         "description": t["function"].get("description", ""),
                         "parameters": t["function"].get("parameters", {})} for t in body["tools"]]
        out["tool_choice"] = body.get("tool_choice", "auto")
    if (body.get("response_format") or {}).get("type") == "json_object":
        out["text"] = {"format": {"type": "json_object"}}
    return out


def from_responses(p: dict) -> dict:
    """Responses API reply -> chat-completions shape the harness expects."""
    text, calls = [], []
    for it in p.get("output", []):
        if it.get("type") == "message":
            text += [c.get("text", "") for c in it.get("content", []) if c.get("type") in ("output_text", "text")]
        elif it.get("type") == "function_call":
            calls.append({"id": it.get("call_id") or it.get("id", ""), "type": "function",
                          "function": {"name": it.get("name", ""), "arguments": it.get("arguments", "{}")}})
    u = p.get("usage") or {}
    cached = (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
    msg = {"role": "assistant", "content": "".join(text) or None}
    if calls:
        msg["tool_calls"] = calls
    return {"id": p.get("id"), "choices": [{"index": 0, "message": msg,
                                            "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0),
                      "prompt_tokens_details": {"cached_tokens": cached}, "prompt_cache_hit_tokens": cached}}


def log_usage_line(tag: str, model: str, usage: dict) -> None:
    """The spend guard cannot read Responses usage; write the per-call token line it would have written."""
    path = os.environ.get("MH_USAGE_LOG", "/home/user/guard/usage.csv")
    if not os.path.exists(path):
        return
    with open(path, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())},{tag},{model},{usage.get('prompt_tokens', 0)},"
                f"{(usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)},{usage.get('completion_tokens', 0)}\n")


def spent_total(phase: str) -> float:
    total = 0.0
    if LEDGER_PATH.exists():
        with LEDGER_PATH.open() as f:
            for row in csv.DictReader(f):
                if row.get("phase") == phase:
                    try:
                        total += float(row.get("computed_cost") or 0.0)
                    except ValueError:
                        pass
    return total


def _first_then_idle(r, idle):
    """Yield SSE lines; once the first line has arrived, cut the socket timeout to the idle cutoff (no-op when the
    first-token wait and the idle cutoff are the same)."""
    first = True
    for line in r:
        yield line
        if first:
            first = False
            try:
                r.fp.raw._sock.settimeout(idle)
            except Exception:                            # noqa: BLE001 - best effort; the first-token wait still applies
                pass


def sse_to_chat(lines) -> dict:
    """Assemble a streamed chat-completions reply (SSE lines) into the non-streamed response shape: content,
    tool calls (deltas merged by index), reasoning text and the final usage chunk."""
    content, reasoning, calls, usage, finish, rid = [], [], {}, {}, None, None
    for raw in lines:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            ev = json.loads(data)
        except ValueError:
            continue
        rid = ev.get("id") or rid
        if ev.get("usage"):
            usage = ev["usage"]
        for ch in ev.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content"):
                content.append(d["content"])
            if d.get("reasoning_content"):
                reasoning.append(d["reasoning_content"])
            for tc in d.get("tool_calls") or []:
                idx = tc.get("index")
                if idx is None:                          # no index: a new call id starts a new call
                    idx = max(calls) if calls else 0
                    if tc.get("id") and calls.get(idx, {}).get("id") and calls[idx]["id"] != tc["id"]:
                        idx += 1
                slot = calls.setdefault(idx, {"id": "", "type": "function",
                                              "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                f = tc.get("function") or {}
                slot["function"]["name"] += f.get("name") or ""
                slot["function"]["arguments"] += f.get("arguments") or ""
            finish = ch.get("finish_reason") or finish
    msg = {"role": "assistant", "content": "".join(content) or None}
    if reasoning:
        msg["reasoning_content"] = "".join(reasoning)
    if calls:
        msg["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {"id": rid, "choices": [{"index": 0, "message": msg, "finish_reason": finish}], "usage": usage}


def _spend_of(headers: Any) -> float | None:
    v = headers.get("x-litellm-key-spend")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="ledger / budget guard utilities")
    ap.add_argument("cmd", choices=["baseline", "status", "reconcile", "ledger"])
    ap.add_argument("--phase", default="phase_0_recon")
    ap.add_argument("--model", default="deepseek-v4.1-flash")
    args = ap.parse_args()

    led = Ledger(phase=args.phase)
    if args.cmd == "baseline":
        led.chat(model=args.model,
                 messages=[{"role": "user", "content": "."}], max_tokens=1,
                 role="builder", task_id="baseline", estimated_cost=0.01)
        print(f"baseline=${led.state.baseline:.6f} since_start=${led.state.since_start:.6f}")
    elif args.cmd == "status":
        print(f"phase={led.state.phase} baseline={led.state.baseline} "
              f"last={led.state.last_key_spend} since_start={led.state.since_start:.4f} "
              f"phase_remaining={led.phase_remaining():.4f} calls={led.state.calls}")
    elif args.cmd == "reconcile":
        print(json.dumps(led.reconcile(), indent=2))
    elif args.cmd == "ledger":
        print(f"spent_total({args.phase}) = {spent_total(args.phase):.6f}")


if __name__ == "__main__":
    main()