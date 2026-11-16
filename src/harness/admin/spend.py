"""Item 61: hierarchical spend limits (org > team > deal) with monthly or total periods.

`guard_for` returns a `SpendGuard` subclass that checks the worst-case cost of a call against EVERY applicable limit
before the call is sent (deal first, then team, then org). `OrgLedger` is a `Ledger` that also books each recorded
cost into the org tables, so no change to ledger.py is needed.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..ledger import BudgetExceeded, Ledger, SpendGuard
from . import AdminError, audit, conn, need_org, require_admin

SCOPES = ("deal", "team", "org")          # check order: most specific first
PERIODS = ("monthly", "total")


class LimitExceeded(BudgetExceeded):
    def __init__(self, message, scope, scope_id, period, limit_usd, spent, worst_case):
        super().__init__(message)
        self.scope, self.scope_id, self.period = scope, scope_id, period
        self.limit_usd, self.spent, self.worst_case = limit_usd, spent, worst_case


def _month(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")


def set_limit(org_id: str, scope: str, scope_id: str | None, limit_usd: float, period: str, actor, *, db=None) -> dict:
    need_org(org_id)
    if scope not in SCOPES:
        raise AdminError(f"scope must be one of {SCOPES}")
    if period not in PERIODS:
        raise AdminError(f"period must be one of {PERIODS}")
    if isinstance(limit_usd, bool) or not isinstance(limit_usd, (int, float)) or limit_usd < 0 or limit_usd != limit_usd:
        raise AdminError("limit_usd must be a non-negative number")
    scope_id = org_id if scope == "org" else scope_id
    if not isinstance(scope_id, str) or not scope_id:
        raise AdminError(f"scope_id is required for scope {scope!r}")
    uid, _ = require_admin(actor)
    with conn(db) as c:
        r = c.execute("SELECT limit_usd FROM admin_spend_limits WHERE org_id=? AND scope=? AND scope_id=? AND period=?",
                      (org_id, scope, scope_id, period)).fetchone()
        c.execute("INSERT INTO admin_spend_limits(org_id,scope,scope_id,period,limit_usd,updated_by,updated_at) "
                  "VALUES (?,?,?,?,?,?,?) ON CONFLICT(org_id,scope,scope_id,period) DO UPDATE SET "
                  "limit_usd=excluded.limit_usd, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                  (org_id, scope, scope_id, period, float(limit_usd), uid, time.time()))
        audit(c, org_id, actor, "spend.set_limit", f"{scope}:{scope_id}:{period}",
              None if r is None else {"limit_usd": r["limit_usd"]}, {"limit_usd": float(limit_usd)})
    return {"org_id": org_id, "scope": scope, "scope_id": scope_id, "period": period, "limit_usd": float(limit_usd)}


def get_limits(org_id: str, *, db=None) -> list[dict]:
    need_org(org_id)
    with conn(db) as c:
        return [dict(r) for r in c.execute("SELECT scope,scope_id,period,limit_usd FROM admin_spend_limits WHERE org_id=? "
                                           "ORDER BY scope,scope_id,period", (org_id,))]


def record(org_id: str, team_id: str | None, deal_id: str | None, job_id: str | None, cost_usd: float, *,
           at: float | None = None, db=None) -> int:
    """Book one cost. A single INSERT in its own transaction, so concurrent callers never lose an update."""
    need_org(org_id)
    if isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)) or cost_usd < 0 or cost_usd != cost_usd:
        raise AdminError("cost_usd must be a non-negative number")
    ts = time.time() if at is None else float(at)
    with conn(db) as c:
        cur = c.execute("INSERT INTO admin_spend_usage(org_id,team_id,deal_id,job_id,cost_usd,at,month) VALUES (?,?,?,?,?,?,?)",
                        (org_id, team_id, deal_id, job_id, float(cost_usd), ts, _month(ts)))
        return cur.lastrowid


def usage(org_id: str, scope: str, scope_id: str | None, period: str, *, now: float | None = None, db=None) -> float:
    need_org(org_id)
    if scope not in SCOPES or period not in PERIODS:
        raise AdminError("bad scope or period")
    q, a = "SELECT COALESCE(SUM(cost_usd),0) FROM admin_spend_usage WHERE org_id=?", [org_id]
    if scope == "team":
        q, a = q + " AND team_id=?", a + [scope_id]
    elif scope == "deal":
        q, a = q + " AND deal_id=?", a + [scope_id]
    if period == "monthly":
        q, a = q + " AND month=?", a + [_month(time.time() if now is None else now)]
    with conn(db) as c:
        return float(c.execute(q, a).fetchone()[0])


class OrgSpendGuard(SpendGuard):
    """Checks all applicable org/team/deal limits against the DB totals (the ledger's own totals are not used)."""

    def __init__(self, org_id: str, team_id: str | None = None, deal_id: str | None = None, *, db=None, clock=time.time):
        super().__init__(limit_usd=float("inf"))
        self.org_id, self.team_id, self.deal_id, self._db, self._clock = org_id, team_id, deal_id, db, clock

    def applicable(self) -> list[tuple[str, str | None]]:
        return [("deal", self.deal_id), ("team", self.team_id), ("org", self.org_id)]

    def check(self, spent_total: float = 0.0, spent_job: float = 0.0, worst_case: float = 0.0, job_id: str | None = None) -> None:
        with conn(self._db) as c:
            lims = {(r["scope"], r["scope_id"], r["period"]): r["limit_usd"] for r in c.execute(
                "SELECT scope,scope_id,period,limit_usd FROM admin_spend_limits WHERE org_id=?", (self.org_id,))}
            for scope, sid in self.applicable():
                if sid is None:
                    continue
                for period in PERIODS:
                    lim = lims.get((scope, sid, period))
                    if lim is None:
                        continue
                    spent = usage(self.org_id, scope, sid, period, now=self._clock(), db=c)
                    if spent + worst_case > lim + 1e-12:
                        raise LimitExceeded(
                            f"{scope} limit hit ({scope}={sid}, {period}): worst-case ${worst_case:.4f} on top of "
                            f"${spent:.4f} spent exceeds ${lim:.2f}; call not sent",
                            scope, sid, period, lim, spent, worst_case)


def guard_for(org_id: str, team_id: str | None = None, deal_id: str | None = None, *, db=None, clock=time.time) -> OrgSpendGuard:
    need_org(org_id)
    return OrgSpendGuard(org_id, team_id, deal_id, db=db, clock=clock)


class OrgLedger(Ledger):
    """A Ledger whose guard is the org guard and whose recorded costs also land in the org spend tables."""

    def __init__(self, org_id: str, team_id: str | None = None, deal_id: str | None = None, path=None, *, db=None, prices=None):
        super().__init__(path=path, guard=guard_for(org_id, team_id, deal_id, db=db), prices=prices)
        self.org_id, self.team_id, self.deal_id, self._db = org_id, team_id, deal_id, db

    def record(self, job_id, model, input_tokens, output_tokens, cached_tokens=0, note: str = "") -> dict:
        row = super().record(job_id, model, input_tokens, output_tokens, cached_tokens, note)
        record(self.org_id, self.team_id, self.deal_id, job_id, row["cost_usd"], db=self._db)
        return row
