"""Earnings roll-forward (P-J5): one click, or automatic when a newer 10-K/10-Q lands in the SEC data.

  POST /deals/{deal_id}/rollforward       member  -> submits an `earnings_update` run for the deal's latest model
  GET  /deals/{deal_id}/watch             viewer  -> watch state and recent roll-forwards
  PUT  /deals/{deal_id}/watch             member  -> {enabled, ticker?}: turn automatic roll-forward on or off

The watcher (`init(state)`, interval `ACRETIA_WATCH_INTERVAL` seconds, default 6 h, `0` disables) asks a filing
provider for the newest 10-K/10-Q of each watched deal's ticker; a filing different from the baseline taken when the
watch was enabled submits a `source="schedule"` run. When any such run finishes, every org member gets a notification
("Model rolled forward to FY2026 - 7 cells changed") linking to the diff. Tests inject a provider via `PROVIDER`.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse

from . import db
from .http import ApiError, Route

P = "/api/v1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS deal_watch(
  org_id TEXT NOT NULL, deal_id TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, ticker TEXT NOT NULL DEFAULT '',
  last_accn TEXT, last_filing_json TEXT, last_checked TEXT, last_job_id TEXT, last_error TEXT NOT NULL DEFAULT '',
  created_by TEXT, updated_at TEXT, PRIMARY KEY(org_id, deal_id));
CREATE TABLE IF NOT EXISTS watch_runs(
  job_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, deal_id TEXT NOT NULL, trigger_kind TEXT NOT NULL, filing_json TEXT,
  requested_by TEXT, created_at TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0, result_json TEXT);
CREATE INDEX IF NOT EXISTS idx_watch_runs_deal ON watch_runs(org_id, deal_id, created_at);
"""
TICKER_RX = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
PROVIDER = None            # test hook: callable(state, ticker) -> filing dict | None


def ensure(conn) -> None:
    """The module may be wired into the server's schema list later; make the tables on first use either way."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='watch_runs'").fetchone() is None:
        conn.executescript(SCHEMA)


# =========================================================================== filings
def sec_cache_latest(state, ticker: str) -> dict | None:
    """Newest 10-K/10-Q (20-F/40-F) in the SEC cache under data/raw, from its companyfacts file. None when absent."""
    from .agents import engines
    found = engines.load_cf(state, ticker)
    if found is None:
        return None
    cf, _info = found
    best = None
    for tax in (cf.get("facts") or {}).values():
        for concept in tax.values():
            for rows in (concept.get("units") or {}).values():
                for f in rows:
                    form = str(f.get("form") or "")
                    if not form.startswith(("10-K", "10-Q", "20-F", "40-F")) or not f.get("accn"):
                        continue
                    key = (str(f.get("filed") or ""), str(f.get("end") or ""))
                    if best is None or key > best[0]:
                        best = (key, f)
    if best is None:
        return None
    f = best[1]
    end = str(f.get("end") or "")
    fp = str(f.get("fp") or "")
    fy = f.get("fy") or (int(end[:4]) if end[:4].isdigit() else None)
    label = (f"{fp} FY{fy}" if fp.startswith("Q") else f"FY{fy}") if fy else (f.get("form") or "latest filing")
    return {"accn": f["accn"], "form": f.get("form"), "filed": f.get("filed"), "period_end": end, "fy": fy, "fp": fp, "label": label}


def _provider(provider=None):
    return provider or PROVIDER or sec_cache_latest


# =========================================================================== helpers
def _need_deal(conn, org_id, deal_id):
    r = conn.execute("SELECT deal_id, name FROM deals WHERE org_id=? AND deal_id=?", (org_id, deal_id)).fetchone()
    if r is None:
        raise ApiError(404, "not_found", "No such deal.")
    return r


def latest_model(store, deal_id):
    """(name, version) of the deal's newest xlsx deliverable, or None."""
    best = None
    for n in store.deliverables(deal_id):
        h = store.history(deal_id, n)
        if h and h[-1]["kind"] == "xlsx":
            best = (n, h[-1]["version"])
    return best


def resolve_ticker(conn, store, org_id, deal_id, given=None) -> str | None:
    if given:
        return given.strip().upper()
    w = conn.execute("SELECT ticker FROM deal_watch WHERE org_id=? AND deal_id=?", (org_id, deal_id)).fetchone()
    if w and w["ticker"]:
        return w["ticker"]
    m = latest_model(store, deal_id)
    if m:
        t = re.match(r"^([A-Za-z]{1,5})[_\- .]", m[0])
        if t and t.group(1).isupper():
            return t.group(1).upper()
    r = conn.execute("SELECT target FROM deal_meta WHERE org_id=? AND deal_id=?", (org_id, deal_id)).fetchone()
    tgt = (r["target"] if r else "") or ""
    return tgt.upper() if re.fullmatch(r"[A-Z]{1,5}", tgt) else None


def _user_for(conn, org_id, preferred) -> str | None:
    """A member (not viewer) to attribute a scheduled run to: the watch's creator, else an owner."""
    if preferred:
        r = conn.execute("SELECT role FROM memberships WHERE org_id=? AND user_id=?", (org_id, preferred)).fetchone()
        if r and r["role"] in ("member", "owner"):
            return preferred
    r = conn.execute("SELECT user_id FROM memberships WHERE org_id=? AND role='owner' ORDER BY created_at LIMIT 1", (org_id,)).fetchone()
    return r["user_id"] if r else None


def submit_rollforward(state, org_id, deal_id, user_id, ticker, source="app", filing=None, trigger="manual") -> dict:
    """Submit the earnings_update run and remember it so its completion is announced."""
    from . import firm, jobs
    from .agents import catalogue as C
    conn = state.conn()
    ensure(conn)
    store = state.deal_store(conn, org_id)
    model = latest_model(store, deal_id)
    if model is None:
        raise ApiError(409, "no_model", "This deal has no model to roll forward.",
                       "Build a model first (for example, 'three-statement model for AAPL'), then roll it forward when new results are filed.")
    lim = firm.spend_limit(conn, org_id, deal_id)
    if not lim["allowed"]:
        raise ApiError(402, "spend_limit", "A spend limit has been reached.", lim["hint"])
    prompt = f"Roll forward the {ticker} model to the latest reported results (earnings update)."
    if filing and filing.get("label"):
        prompt = f"Roll forward the {ticker} model to {filing['label']} (earnings update)."
    job = jobs.svc().submit(org_id, user_id, prompt, deal_id, C.builtin_id("earnings_update"),
                            {"ticker": ticker, "model": model[0]}, source=source)
    conn.execute("INSERT OR IGNORE INTO watch_runs(job_id,org_id,deal_id,trigger_kind,filing_json,requested_by,created_at) VALUES(?,?,?,?,?,?,?)",
                 (job["id"], org_id, deal_id, trigger, json.dumps(filing) if filing else None, user_id, db.now()))
    return job


# =========================================================================== completion -> notification
def _members(conn, org_id) -> list:
    return [r["user_id"] for r in conn.execute(
        "SELECT m.user_id FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND u.disabled=0", (org_id,))]


def _changed(store, deal_id, name, version) -> int | None:
    if version < 2:
        return None
    try:
        d = store.diff(deal_id, name, version - 1, version)
    except Exception:                                                   # noqa: BLE001
        return None
    ch = d.get("changes") or []
    if ch and "unified" in ch[0]:
        return sum(1 for ln in ch[0]["unified"] if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
    return len(ch)


def _period(run, job_view) -> str:
    try:
        f = json.loads(run["filing_json"] or "null")
    except ValueError:
        f = None
    if f and f.get("label"):
        return f["label"]
    for s in job_view.get("steps") or []:
        m = re.search(r"rolled forward to (FY\d{4}|Q\d FY\d{4})", s.get("detail") or "")
        if m:
            return m.group(1)
    return "the latest reported period"


def check_completions(state) -> list[dict]:
    """Announce every finished roll-forward run once. Returns what was sent (for tests and logs)."""
    from . import jobs
    conn = state.conn()
    ensure(conn)
    sent = []
    for run in conn.execute("SELECT * FROM watch_runs WHERE notified=0 ORDER BY created_at").fetchall():
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (run["job_id"],)).fetchone()
        if row is None:
            conn.execute("UPDATE watch_runs SET notified=1 WHERE job_id=?", (run["job_id"],))
            continue
        if row["status"] not in jobs.TERMINAL:
            continue
        org_id, deal_id = run["org_id"], run["deal_id"]
        deal = conn.execute("SELECT name FROM deals WHERE org_id=? AND deal_id=?", (org_id, deal_id)).fetchone()
        dname = deal["name"] if deal else deal_id
        conn.execute("UPDATE watch_runs SET notified=1 WHERE job_id=? AND notified=0", (run["job_id"],))
        if row["status"] != "done":
            who = [run["requested_by"]] if run["requested_by"] else []
            if run["trigger_kind"] == "schedule":
                who = _members(conn, org_id)
            for u in dict.fromkeys(who):
                state.notify(conn, org_id, u, "rollforward.failed", "Roll-forward did not finish",
                             f"{dname}: {(row['error'] or 'the run stopped')[:160]}", f"/runs/{run['job_id']}")
            sent.append({"job_id": run["job_id"], "status": row["status"], "to": len(who)})
            continue
        view = jobs.svc().view(row) if jobs.SERVICE is not None else {"steps": json.loads(row["steps_json"] or "[]"), "deliverables": []}
        dels = view.get("deliverables") or []
        if not dels:
            for s in json.loads(row["steps_json"] or "[]"):
                dels += ((s.get("output") or {}).get("deliverables") or [])
        model = next((d for d in dels if d.get("kind") == "xlsx"), None)
        deck = next((d for d in dels if d.get("kind") == "pptx"), None)
        store = state.deal_store(conn, org_id)
        n = _changed(store, deal_id, model["name"], model["version"]) if model else None
        period = _period(run, view)
        what = "Model and deck" if deck else "Model"
        title = f"{what} rolled forward to {period}" + (f" — {n} cell{'s' if n != 1 else ''} changed" if n is not None else "")
        link = f"/runs/{run['job_id']}"
        if model:
            q = urllib.parse.quote(model["name"])
            link = f"/deals/{deal_id}/models/{q}" + (f"?diff={model['version'] - 1}..{model['version']}" if model["version"] > 1 else "")
        users = _members(conn, org_id)
        for u in users:
            state.notify(conn, org_id, u, "rollforward.done", title, f"{dname}. Open the model to see exactly what moved.", link)
        res = {"job_id": run["job_id"], "title": title, "link": link, "changed": n, "period": period, "to": len(users)}
        conn.execute("UPDATE watch_runs SET result_json=? WHERE job_id=?", (json.dumps(res), run["job_id"]))
        state.audit(conn, org_id, None, "rollforward.notified", f"job:{run['job_id']}", {"deal_id": deal_id, "title": title})
        sent.append(res)
    return sent


# =========================================================================== watcher
def tick(state, provider=None) -> list[str]:
    """One pass over every enabled watch. Returns the ids of runs submitted."""
    conn = state.conn()
    ensure(conn)
    fetch = _provider(provider)
    submitted = []
    for w in conn.execute("SELECT * FROM deal_watch WHERE enabled=1").fetchall():
        org_id, deal_id = w["org_id"], w["deal_id"]
        ts = db.now()
        try:
            f = fetch(state, w["ticker"])
        except Exception as e:                                          # noqa: BLE001
            conn.execute("UPDATE deal_watch SET last_checked=?, last_error=? WHERE org_id=? AND deal_id=?",
                         (ts, f"filing lookup failed ({type(e).__name__})", org_id, deal_id))
            continue
        if not f or not f.get("accn"):
            conn.execute("UPDATE deal_watch SET last_checked=?, last_error=? WHERE org_id=? AND deal_id=?",
                         (ts, f"No filings found for {w['ticker']} in the SEC data.", org_id, deal_id))
            continue
        if w["last_accn"] is None:                                      # first sight becomes the baseline
            conn.execute("UPDATE deal_watch SET last_accn=?, last_filing_json=?, last_checked=?, last_error='' WHERE org_id=? AND deal_id=?",
                         (f["accn"], json.dumps(f), ts, org_id, deal_id))
            continue
        if f["accn"] == w["last_accn"]:
            conn.execute("UPDATE deal_watch SET last_checked=?, last_error='' WHERE org_id=? AND deal_id=?", (ts, org_id, deal_id))
            continue
        user = _user_for(conn, org_id, w["created_by"])
        try:
            if user is None:
                raise ApiError(409, "no_user", "No member can own the run.", "Add an owner.")
            job = submit_rollforward(state, org_id, deal_id, user, w["ticker"], source="schedule", filing=f, trigger="schedule")
        except ApiError as e:
            conn.execute("UPDATE deal_watch SET last_checked=?, last_error=? WHERE org_id=? AND deal_id=?", (ts, e.message[:200], org_id, deal_id))
            continue
        conn.execute("UPDATE deal_watch SET last_accn=?, last_filing_json=?, last_checked=?, last_job_id=?, last_error='' WHERE org_id=? AND deal_id=?",
                     (f["accn"], json.dumps(f), ts, job["id"], org_id, deal_id))
        state.audit(conn, org_id, user, "rollforward.scheduled", f"job:{job['id']}", {"deal_id": deal_id, "filing": f.get("label"), "accn": f["accn"]})
        submitted.append(job["id"])
    return submitted


_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def _loop(state, interval: float, completion_every: float):
    import time
    nxt = time.monotonic() + interval
    while not _STOP.wait(completion_every):
        try:
            check_completions(state)
            if time.monotonic() >= nxt:
                nxt = time.monotonic() + interval
                tick(state)
        except Exception:                                               # noqa: BLE001
            continue


def init(state, completion_every: float = 10.0):
    """Start the watcher thread (idempotent). `ACRETIA_WATCH_INTERVAL=0` disables it."""
    global _THREAD
    try:
        interval = float(os.environ.get("ACRETIA_WATCH_INTERVAL", "21600"))
    except ValueError:
        interval = 21600.0
    if interval <= 0:
        return None
    if _THREAD is not None and _THREAD.is_alive():
        return _THREAD
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, args=(state, interval, completion_every), name="acretia-watch", daemon=True)
    _THREAD.start()
    return _THREAD


def shutdown() -> None:
    global _THREAD
    _STOP.set()
    if _THREAD is not None:
        _THREAD.join(timeout=2)
    _THREAD = None


# =========================================================================== routes
def _body(ctx) -> dict:
    b = ctx.json
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError(400, "bad_body", "The request body must be a JSON object.", "Send a JSON object.")
    return b


def _ticker_arg(b: dict) -> str | None:
    t = b.get("ticker")
    if t in (None, ""):
        return None
    if not isinstance(t, str) or not TICKER_RX.match(t.strip()):
        raise ApiError(400, "bad_request", "That is not a ticker symbol.", "Use a symbol such as AAPL.")
    return t.strip().upper()


def _state():
    from . import state as state_mod
    return state_mod.STATE


def rollforward(ctx):
    ctx.require("member")
    deal_id = ctx.params["deal_id"]
    _need_deal(ctx.conn, ctx.org_id, deal_id)
    ensure(ctx.conn)
    st = _state()
    ticker = resolve_ticker(ctx.conn, st.deal_store(ctx.conn, ctx.org_id), ctx.org_id, deal_id, _ticker_arg(_body(ctx)))
    if not ticker:
        raise ApiError(400, "ticker_needed", "Which company should be rolled forward?",
                       'Send {"ticker": "AAPL"}, or name the model file after its ticker (AAPL_three_statement_model.xlsx).')
    job = submit_rollforward(st, ctx.org_id, deal_id, ctx.user["id"], ticker)
    ctx.audit("rollforward.start", f"deal:{deal_id}", {"job_id": job["id"], "ticker": ticker})
    return 202, {"job": job, "ticker": ticker}


def _watch_view(conn, org_id, deal_id) -> dict:
    ensure(conn)
    w = conn.execute("SELECT * FROM deal_watch WHERE org_id=? AND deal_id=?", (org_id, deal_id)).fetchone()
    runs = []
    for r in conn.execute("SELECT wr.*, j.status FROM watch_runs wr LEFT JOIN jobs j ON j.id=wr.job_id WHERE wr.org_id=? AND wr.deal_id=? "
                          "ORDER BY wr.created_at DESC LIMIT 10", (org_id, deal_id)).fetchall():
        res = json.loads(r["result_json"] or "null")
        runs.append({"job_id": r["job_id"], "trigger": r["trigger_kind"], "status": r["status"], "created_at": r["created_at"],
                     "title": res and res.get("title"), "link": res and res.get("link")})
    base = {"deal_id": deal_id, "enabled": False, "ticker": "", "last_checked": None, "last_filing": None, "last_job_id": None,
            "last_error": "", "interval_seconds": float(os.environ.get("ACRETIA_WATCH_INTERVAL", "21600") or 21600), "runs": runs}
    if w is None:
        return base
    return base | {"enabled": bool(w["enabled"]), "ticker": w["ticker"], "last_checked": w["last_checked"],
                   "last_filing": json.loads(w["last_filing_json"] or "null"), "last_job_id": w["last_job_id"], "last_error": w["last_error"]}


def get_watch(ctx):
    _need_deal(ctx.conn, ctx.org_id, ctx.params["deal_id"])
    return _watch_view(ctx.conn, ctx.org_id, ctx.params["deal_id"])


def put_watch(ctx):
    ctx.require("member")
    deal_id = ctx.params["deal_id"]
    _need_deal(ctx.conn, ctx.org_id, deal_id)
    ensure(ctx.conn)
    b = _body(ctx)
    en = b.get("enabled")
    if not isinstance(en, bool):
        raise ApiError(400, "bad_request", "`enabled` must be true or false.", 'Send {"enabled": true}.')
    st = _state()
    store = st.deal_store(ctx.conn, ctx.org_id)
    ticker = resolve_ticker(ctx.conn, store, ctx.org_id, deal_id, _ticker_arg(b))
    if en and not ticker:
        raise ApiError(400, "ticker_needed", "Which company should be watched?", 'Send {"enabled": true, "ticker": "AAPL"}.')
    if en and latest_model(store, deal_id) is None:
        raise ApiError(409, "no_model", "This deal has no model to keep up to date.", "Build a model first, then turn on automatic roll-forward.")
    prev = ctx.conn.execute("SELECT * FROM deal_watch WHERE org_id=? AND deal_id=?", (ctx.org_id, deal_id)).fetchone()
    baseline, filing = (prev["last_accn"], prev["last_filing_json"]) if prev and prev["ticker"] == ticker else (None, None)
    if en and baseline is None:                                         # filings that already exist are not "new"
        try:
            f = _provider()(st, ticker)
        except Exception:                                               # noqa: BLE001
            f = None
        if f and f.get("accn"):
            baseline, filing = f["accn"], json.dumps(f)
    ctx.conn.execute(
        "INSERT INTO deal_watch(org_id,deal_id,enabled,ticker,last_accn,last_filing_json,created_by,updated_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(org_id,deal_id) DO UPDATE SET enabled=excluded.enabled, ticker=excluded.ticker, last_accn=excluded.last_accn, "
        "last_filing_json=excluded.last_filing_json, created_by=CASE WHEN deal_watch.enabled=0 THEN excluded.created_by ELSE deal_watch.created_by END, "
        "updated_at=excluded.updated_at", (ctx.org_id, deal_id, 1 if en else 0, ticker or "", baseline, filing, ctx.user["id"], db.now()))
    ctx.audit("rollforward.watch", f"deal:{deal_id}", {"enabled": en, "ticker": ticker})
    return _watch_view(ctx.conn, ctx.org_id, deal_id)


ROUTES = [
    Route("POST", f"{P}/deals/{{deal_id}}/rollforward", rollforward, "member"),
    Route("GET", f"{P}/deals/{{deal_id}}/watch", get_watch, "viewer"),
    Route("PUT", f"{P}/deals/{{deal_id}}/watch", put_watch, "member"),
]
