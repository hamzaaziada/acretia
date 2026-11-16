"""S6.4 schedules and monitoring (parity 25, 28).

A ``Schedule`` wraps a ResearchRequest dict plus a cadence. ``ScheduleStore.dispatch_due`` enqueues jobs and advances
``next_run_at``; a unique (schedule_id, slot) row makes a repeated tick a no-op. Monitoring is a schedule whose
request carries ``monitor``; ``diff_results`` turns two result snapshots into cited alert items.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import jobs
from .api import ResearchRequest

CADENCES = ("daily", "weekly", "cron", "once")
_EMAIL = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+$")
_ACCESSION = re.compile(r"\b\d{10}-\d{2}-\d{6}\b")


class ScheduleError(ValueError):
    pass


# --------------------------------------------------------------------------- cron
_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_DOWS = {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())}
_RANGES = ((0, 59, None), (0, 23, None), (1, 31, None), (1, 12, _MONTHS), (0, 7, _DOWS))


def _num(tok: str, names, lo: int, hi: int) -> int:
    t = tok.lower()
    if names and t in names:
        return names[t]
    if not t.isdigit():
        raise ScheduleError(f"bad cron value {tok!r}")
    v = int(t)
    if not lo <= v <= hi:
        raise ScheduleError(f"cron value {v} outside {lo}-{hi}")
    return v


def _field(text: str, lo: int, hi: int, names) -> set[int]:
    out: set[int] = set()
    if not text:
        raise ScheduleError("empty cron field")
    for part in text.split(","):
        rng, _, step_s = part.partition("/")
        if "/" in part:
            if not step_s.isdigit() or int(step_s) < 1:
                raise ScheduleError(f"bad cron step {part!r}")
            step = int(step_s)
        else:
            step = 1
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            x, y = rng.split("-", 1)
            a, b = _num(x, names, lo, hi), _num(y, names, lo, hi)
            if a > b:
                raise ScheduleError(f"descending cron range {rng!r}")
        else:
            a = _num(rng, names, lo, hi)
            b = hi if "/" in part else a
        out.update(range(a, b + 1, step))
    return out


@dataclass(frozen=True)
class CronSpec:
    minute: frozenset
    hour: frozenset
    dom: frozenset
    month: frozenset
    dow: frozenset            # 0=Sunday .. 6=Saturday
    dom_star: bool
    dow_star: bool

    def day_matches(self, d: date) -> bool:
        if d.month not in self.month:
            return False
        dom_ok, dow_ok = d.day in self.dom, ((d.weekday() + 1) % 7) in self.dow
        return (dom_ok or dow_ok) if not (self.dom_star or self.dow_star) else (dom_ok and dow_ok)


def parse_cron(expr: str) -> CronSpec:
    parts = (expr or "").split()
    if len(parts) != 5:
        raise ScheduleError("cron needs exactly 5 fields: minute hour day-of-month month day-of-week")
    sets = [_field(p, lo, hi, names) for p, (lo, hi, names) in zip(parts, _RANGES)]
    sets[4] = {v % 7 for v in sets[4]}
    return CronSpec(*(frozenset(s) for s in sets), dom_star=parts[2].startswith("*"), dow_star=parts[4].startswith("*"))


def _utc(naive: datetime, tz: ZoneInfo) -> datetime:
    # fold=0: an ambiguous (fall-back) time fires once, at its first occurrence; a nonexistent (spring-forward)
    # time maps to the same instant as the first valid wall-clock time after the gap, so it still fires once.
    return naive.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)


def next_run(spec: CronSpec | str, after: datetime, tz: str | ZoneInfo = "UTC") -> datetime:
    """First fire time strictly after ``after`` (aware), in UTC."""
    if isinstance(spec, str):
        spec = parse_cron(spec)
    tz = ZoneInfo(tz) if isinstance(tz, str) else tz
    after = after.astimezone(timezone.utc)
    day = after.astimezone(tz).date() - timedelta(days=1)
    for _ in range(366 * 9):
        if spec.day_matches(day):
            cands = [_utc(datetime(day.year, day.month, day.day, h, m), tz) for h in spec.hour for m in spec.minute]
            cands = [c for c in cands if c > after]
            if cands:
                return min(cands)
        day += timedelta(days=1)
    raise ScheduleError("cron expression never fires")


# --------------------------------------------------------------------------- model
def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _aware(now) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        now = _parse_iso(now)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


@dataclass
class Schedule:
    id: str
    org_id: str
    user_id: str | None
    request: dict
    cadence: str
    cron: str | None = None
    at: str | None = None
    weekday: int | None = None        # 0=Monday .. 6=Sunday (Python)
    hour: int = 9
    minute: int = 0
    tz: str = "UTC"
    deliver: dict = field(default_factory=lambda: {"email": [], "library": False})
    enabled: bool = True
    next_run_at: str | None = None
    last_run_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def cron_expr(self) -> str | None:
        if self.cadence == "cron":
            return self.cron
        if self.cadence == "daily":
            return f"{self.minute} {self.hour} * * *"
        if self.cadence == "weekly":
            return f"{self.minute} {self.hour} * * {(self.weekday + 1) % 7}"
        return None

    def compute_next(self, after: datetime) -> datetime | None:
        if self.cadence == "once":
            at = datetime.fromisoformat(self.at.replace("Z", "+00:00"))
            at = at if at.tzinfo else at.replace(tzinfo=ZoneInfo(self.tz))
            at = at.astimezone(timezone.utc)
            return at if at > after else None
        return next_run(self.cron_expr(), after, self.tz)

    def validate(self) -> None:
        if self.cadence not in CADENCES:
            raise ScheduleError(f"cadence must be one of {CADENCES}")
        try:
            ZoneInfo(self.tz)
        except Exception as e:
            raise ScheduleError(f"unknown time zone {self.tz!r}") from e
        if not (0 <= self.hour <= 23 and 0 <= self.minute <= 59):
            raise ScheduleError("hour/minute out of range")
        if self.cadence == "weekly" and not (isinstance(self.weekday, int) and 0 <= self.weekday <= 6):
            raise ScheduleError("weekly needs weekday 0 (Mon) .. 6 (Sun)")
        if self.cadence == "cron":
            parse_cron(self.cron or "")
        if self.cadence == "once":
            if not self.at:
                raise ScheduleError("once needs at (ISO datetime)")
            try:
                datetime.fromisoformat(self.at.replace("Z", "+00:00"))
            except ValueError as e:
                raise ScheduleError("at is not an ISO datetime") from e
        emails = (self.deliver or {}).get("email", [])
        if not isinstance(emails, list) or any(not isinstance(a, str) or not _EMAIL.match(a) for a in emails):
            raise ScheduleError("deliver.email must be a list of plain email addresses")
        req = {k: v for k, v in self.request.items() if k != "monitor"}
        ResearchRequest.from_dict(dict(req, org_id=self.org_id)).validate()


def _from_row(raw: str) -> Schedule:
    return Schedule(**json.loads(raw))


class ScheduleStore:
    """SQLite store. Every read/write by id is scoped by org_id; ``due``/``dispatch_due`` are the system tick."""

    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY, org_id TEXT NOT NULL, enabled INTEGER,
                    next_run_at TEXT, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS slots(schedule_id TEXT, slot TEXT, job_id TEXT,
                    PRIMARY KEY(schedule_id, slot));
                CREATE TABLE IF NOT EXISTS baselines(schedule_id TEXT PRIMARY KEY, body TEXT);""")

    def close(self):
        self._db.close()

    # ---- CRUD
    def _put(self, s: Schedule):
        self._db.execute("INSERT OR REPLACE INTO schedules VALUES(?,?,?,?,?)",
                         (s.id, s.org_id, int(s.enabled), s.next_run_at, json.dumps(s.to_dict(), sort_keys=True)))

    def create(self, org_id: str, user_id: str | None, request: dict, cadence: str, *, cron: str | None = None,
               at: str | None = None, weekday: int | None = None, hour: int = 9, minute: int = 0, tz: str = "UTC",
               deliver: dict | None = None, now=None) -> Schedule:
        s = Schedule(id="sch_" + uuid.uuid4().hex[:12], org_id=org_id, user_id=user_id, request=dict(request),
                     cadence=cadence, cron=cron, at=at, weekday=weekday, hour=hour, minute=minute, tz=tz,
                     deliver={"email": [], "library": False, **(deliver or {})})
        s.validate()
        nxt = s.compute_next(_aware(now))
        if nxt is None:
            raise ScheduleError("run time is in the past")
        s.next_run_at = _iso(nxt)
        with self._lock:
            self._put(s)
        return s

    def get(self, org_id: str, schedule_id: str) -> Schedule | None:
        with self._lock:
            r = self._db.execute("SELECT body FROM schedules WHERE id=? AND org_id=?", (schedule_id, org_id)).fetchone()
        return _from_row(r[0]) if r else None

    def list(self, org_id: str) -> list[Schedule]:
        with self._lock:
            rows = self._db.execute("SELECT body FROM schedules WHERE org_id=? ORDER BY id", (org_id,)).fetchall()
        return [_from_row(r[0]) for r in rows]

    def update(self, org_id: str, schedule_id: str, now=None, **changes) -> Schedule | None:
        with self._lock:
            s = self.get(org_id, schedule_id)
            if s is None:
                return None
            for k, v in changes.items():
                if k in ("id", "org_id", "last_run_at", "next_run_at") or not hasattr(s, k):
                    raise ScheduleError(f"cannot update {k!r}")
                setattr(s, k, v)
            s.validate()
            if s.enabled:
                nxt = s.compute_next(_aware(now))
                s.next_run_at, s.enabled = (_iso(nxt) if nxt else None), nxt is not None
            self._put(s)
            return s

    def disable(self, org_id: str, schedule_id: str) -> bool:
        with self._lock:
            s = self.get(org_id, schedule_id)
            if s is None:
                return False
            s.enabled = False
            self._put(s)
            return True

    def delete(self, org_id: str, schedule_id: str) -> bool:
        with self._lock:
            if self.get(org_id, schedule_id) is None:
                return False
            self._db.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
            self._db.execute("DELETE FROM baselines WHERE schedule_id=?", (schedule_id,))
            return True

    # ---- tick
    def due(self, now=None) -> list[Schedule]:
        now = _iso(_aware(now))
        with self._lock:
            rows = self._db.execute("SELECT body FROM schedules WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at",
                                    (now,)).fetchall()
        return [_from_row(r[0]) for r in rows]

    def dispatch_due(self, now=None, submit=jobs.submit, tracker=None) -> list[dict]:
        """Enqueue one job per due schedule and advance next_run_at. Missed slots collapse into one run. Idempotent:
        the (schedule_id, slot) primary key means a repeated tick, or two ticks racing, submit at most once."""
        now_dt = _aware(now)
        out = []
        for s in self.due(now_dt):
            slot = s.next_run_at
            with self._lock:
                self._db.execute("BEGIN IMMEDIATE")
                try:
                    cur = self._db.execute("INSERT OR IGNORE INTO slots(schedule_id, slot, job_id) VALUES(?,?,NULL)",
                                           (s.id, slot))
                    if cur.rowcount == 0:                       # slot already dispatched by an earlier tick
                        fresh = self.get(s.org_id, s.id)
                        if fresh and fresh.next_run_at == slot:  # crashed between claim and advance: just advance
                            self._advance(fresh, now_dt, slot)
                        self._db.execute("COMMIT")
                        continue
                    if tracker:
                        tracker.received(f"sched:{s.id}:{slot}", slot_time=_parse_iso(slot))
                    req = {k: v for k, v in s.request.items() if k != "monitor"}
                    req.update(org_id=s.org_id, user_id=s.user_id)
                    try:
                        job_id = submit(req)
                    except Exception:
                        self._db.execute("ROLLBACK")
                        raise
                    self._db.execute("UPDATE slots SET job_id=? WHERE schedule_id=? AND slot=?", (job_id, s.id, slot))
                    self._advance(s, now_dt, slot)
                    self._db.execute("COMMIT")
                except Exception:
                    if self._db.in_transaction:
                        self._db.execute("ROLLBACK")
                    raise
            if tracker:
                tracker.submitted(f"sched:{s.id}:{slot}", job_id)
            out.append({"schedule_id": s.id, "org_id": s.org_id, "slot": slot, "job_id": job_id})
        return out

    def _advance(self, s: Schedule, now: datetime, slot: str):
        s.last_run_at = _iso(now)
        nxt = s.compute_next(now) if s.cadence != "once" else None
        s.next_run_at = _iso(nxt) if nxt else None
        s.enabled = nxt is not None
        self._put(s)

    def job_for_slot(self, schedule_id: str, slot: str) -> str | None:
        with self._lock:
            r = self._db.execute("SELECT job_id FROM slots WHERE schedule_id=? AND slot=?", (schedule_id, slot)).fetchone()
        return r[0] if r else None

    # ---- monitoring
    def monitor_check(self, org_id: str, schedule_id: str, result) -> list[dict]:
        """Diff ``result`` against the stored baseline, store it as the new baseline, return alert items. The first
        run only sets the baseline."""
        s = self.get(org_id, schedule_id)
        if s is None:
            raise ScheduleError("unknown schedule")
        mon = s.request.get("monitor")
        if not mon:
            return []
        cur = _as_dict(result)
        with self._lock:
            r = self._db.execute("SELECT body FROM baselines WHERE schedule_id=?", (schedule_id,)).fetchone()
            self._db.execute("INSERT OR REPLACE INTO baselines VALUES(?,?)", (schedule_id, json.dumps(cur, sort_keys=True)))
        return diff_results(json.loads(r[0]), cur, mon) if r else []


# --------------------------------------------------------------------------- monitoring diff
def _as_dict(x) -> dict:
    return x.to_dict() if hasattr(x, "to_dict") else dict(x)


def _cited(fig: dict) -> bool:
    c = fig.get("citation") or {}
    return bool(c.get("as_of")) and bool(c.get("url") or c.get("source_url") or (c.get("doc_id") and c.get("page")))


def _fig_key(f: dict):
    return (str(f.get("label", "")).strip().lower(), str(f.get("period", "")).strip())


def _accessions(res: dict) -> dict:
    """accession -> citation dict, from ``filings`` entries and from figure citations that name an accession."""
    out: dict = {}
    for f in res.get("filings") or []:
        acc = f.get("accession")
        if acc:
            out[acc] = {"doc_id": acc, "url": f.get("url"), "as_of": f.get("filed") or f.get("as_of"),
                        "form": f.get("form")}
    for f in res.get("figures") or []:
        c = f.get("citation") or {}
        for src in (c.get("doc_id"), c.get("url"), c.get("source_url")):
            m = _ACCESSION.search(src or "")
            if m:
                out.setdefault(m.group(0), c)
    return out


def parse_alert_rules(alert_on) -> tuple[bool, float | None]:
    new_filing, threshold = False, None
    for rule in alert_on or []:
        r = str(rule).strip().lower()
        if r == "new_filing":
            new_filing = True
            continue
        m = re.fullmatch(r"figure_change\s*>\s*(\d+(?:\.\d+)?)\s*%?", r)
        if not m:
            raise ScheduleError(f"unknown alert rule {rule!r}")
        x = float(m.group(1))
        threshold = x if threshold is None else min(threshold, x)
    return new_filing, threshold


def diff_results(prev, cur, monitor: dict | None = None) -> list[dict]:
    """Alert items between two result snapshots. Figures are matched on (label, period); only cited figures count.
    Every alert carries ``prev_citation`` and ``cur_citation``."""
    prev, cur = _as_dict(prev), _as_dict(cur)
    new_filing, threshold = parse_alert_rules((monitor or {}).get("alert_on", ["new_filing", "figure_change>5%"]))
    alerts: list[dict] = []
    if threshold is not None:
        before = {_fig_key(f): f for f in prev.get("figures") or [] if _cited(f)}
        for f in cur.get("figures") or []:
            p = before.get(_fig_key(f))
            if p is None or not _cited(f):
                continue
            pv, cv = float(p["value"]), float(f["value"])
            if pv == cv:
                continue
            pct = None if pv == 0 else abs(cv - pv) / abs(pv) * 100.0
            if pct is None or pct > threshold:
                alerts.append({"kind": "figure_change", "label": f["label"], "period": f["period"],
                               "units": f.get("units", ""), "prev_value": pv, "cur_value": cv,
                               "change_pct": None if pct is None else round(pct, 4), "threshold_pct": threshold,
                               "prev_citation": p["citation"], "cur_citation": f["citation"]})
    if new_filing:
        old, new = _accessions(prev), _accessions(cur)
        prior = next(iter(sorted(old.items(), reverse=True)), (None, None))[1]
        for acc in sorted(set(new) - set(old)):
            alerts.append({"kind": "new_filing", "accession": acc, "prev_citation": prior, "cur_citation": new[acc]})
    return alerts
