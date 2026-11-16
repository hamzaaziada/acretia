"""S6.4 email in and out (parity 25-27, 29).

Outbound: ``render_summary`` shows only verified, cited figures; ``send`` takes a pluggable transport (default
``SMTPTransport``: env-configured, TLS required, off unless configured). Inbound: ``parse_request_email`` treats the
message as untrusted data: allowlisted + authenticated sender, subject/first line only, attachments through ``unpack``.
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import html as _html
import os
import re
import shutil
import smtplib
import sqlite3
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from pathlib import Path

from ..connectors import unpack as _unpack

TARGETS_S = {"research": 600.0, "deck": 900.0}      # parity 26 (<10 min) and 27 (<15 min)


# --------------------------------------------------------------------------- outbound: rendering
def _d(x) -> dict:
    return x.to_dict() if hasattr(x, "to_dict") else dict(x)


def _clean(s) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(s)).strip()


def cite_text(c: dict) -> str | None:
    """'doc p.N' or URL, plus as-of. None when the citation cannot be shown (no source or no as-of)."""
    src = c.get("url") or c.get("source_url")
    if not src and c.get("doc_id") and c.get("page"):
        src = f"{c['doc_id']} p.{c['page']}"
    if not src or not c.get("as_of"):
        return None
    return f"{_clean(src)} (as of {c['as_of']})"


def _fmt(v: float, units: str) -> str:
    n = f"{v:,.0f}" if float(v).is_integer() or abs(v) >= 1000 else f"{v:,.2f}"
    u = _clean(units)
    return f"{u}{n}" if u in ("$", "USD $") else (f"{n}{u}" if u in ("%", "x") else f"{n} {u}".strip())


def _safe_url(u):
    return u if isinstance(u, str) and re.match(r"https?://[^\s<>\"']+$", u) else None


def render_summary(result, *, deck_url: str | None = None, files: list | None = None, alerts: list | None = None):
    """-> (subject, text, html). Only ``result.figures`` that have a citation with a source and as-of are shown;
    rejected figures are only counted."""
    r = _d(result)
    shown, withheld = [], 0
    for f in r.get("figures") or []:
        f = _d(f)
        cite = cite_text(_d(f.get("citation") or {}))
        if cite is None:
            withheld += 1
            continue
        shown.append((_clean(f.get("label", "")), _clean(f.get("period", "")), _fmt(f["value"], f.get("units", "")), cite))
    n_rej = len(r.get("rejected") or [])
    subject = _clean(f"Acretia research summary: {len(shown)} verified figure{'s' if len(shown) != 1 else ''}")
    names = [_clean(x.get("name") if isinstance(x, dict) else x) for x in (files or [])]
    deck = _safe_url(deck_url)
    al = [a for a in (alerts or [])]

    t = [subject, ""]
    for lab, per, val, cite in shown:
        t.append(f"- {lab} ({per}): {val}  [source: {cite}]")
    if not shown:
        t.append("No verified figures.")
    if n_rej or withheld:
        t.append(f"\n{n_rej + withheld} item(s) failed verification and are not shown.")
    for a in al:
        t.append("\n" + _alert_text(a))
    if deck:
        t.append(f"\nDeck: {deck}")
    for n in names:
        t.append(f"Attached: {n}")

    e = _html.escape
    h = [f"<h2>{e(subject)}</h2>", "<table><tr><th>Figure</th><th>Period</th><th>Value</th><th>Source</th></tr>"]
    for lab, per, val, cite in shown:
        h.append(f"<tr><td>{e(lab)}</td><td>{e(per)}</td><td>{e(val)}</td><td>{e(cite)}</td></tr>")
    h.append("</table>")
    if not shown:
        h.append("<p>No verified figures.</p>")
    if n_rej or withheld:
        h.append(f"<p>{n_rej + withheld} item(s) failed verification and are not shown.</p>")
    for a in al:
        h.append(f"<p>{e(_alert_text(a))}</p>")
    if deck:
        h.append(f'<p>Deck: <a href="{e(deck, quote=True)}">{e(deck)}</a></p>')
    for n in names:
        h.append(f"<p>Attached: {e(n)}</p>")
    return subject, "\n".join(t), "<html><body>" + "\n".join(h) + "</body></html>"


def _alert_text(a: dict) -> str:
    pc, cc = cite_text(_d(a.get("prev_citation") or {})) or "none", cite_text(_d(a.get("cur_citation") or {})) or "none"
    if a.get("kind") == "new_filing":
        head = f"ALERT new filing {_clean(a.get('accession'))}"
    else:
        pct = a.get("change_pct")
        head = (f"ALERT {_clean(a.get('label'))} ({_clean(a.get('period'))}) changed "
                f"{a.get('prev_value')} -> {a.get('cur_value')}" + (f" ({pct:.1f}%)" if pct is not None else ""))
    return f"{head}  [previous: {pc}] [current: {cc}]"


def build_message(to, subject: str, text: str, html: str, *, sender: str, attachments: list | None = None) -> EmailMessage:
    """attachments: [(filename, bytes, 'type/subtype')]. Header values are single-line (EmailMessage rejects CR/LF)."""
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, ", ".join([to] if isinstance(to, str) else to), _clean(subject)
    m.set_content(text)
    m.add_alternative(html, subtype="html")
    for name, data, ctype in attachments or []:
        mt, _, st = ctype.partition("/")
        m.add_attachment(data, maintype=mt, subtype=st or "octet-stream", filename=_unpack.sanitize_component(name))
    return m


# --------------------------------------------------------------------------- outbound: transport
class EmailConfigError(RuntimeError):
    pass


class TransportDisabled(EmailConfigError):
    pass


class SMTPTransport:
    """Env: ACRETIA_SMTP_HOST, _PORT, _USER, _SECURITY (ssl|starttls; default ssl on 465 else starttls) and
    ACRETIA_SMTP_PASSWORD (or a ``password_provider`` callable for a secret store). Disabled unless HOST is set.
    Never sends without TLS and never authenticates over plaintext. The password is never logged or in repr."""

    def __init__(self, host=None, port=None, user=None, security=None, *, password_provider=None, env=None,
                 timeout: float = 30.0):
        env = os.environ if env is None else env
        self.host = host or env.get("ACRETIA_SMTP_HOST") or None
        self.port = int(port or env.get("ACRETIA_SMTP_PORT") or 587)
        self.user = user or env.get("ACRETIA_SMTP_USER") or None
        self.security = (security or env.get("ACRETIA_SMTP_SECURITY") or ("ssl" if self.port == 465 else "starttls")).lower()
        self._pw = password_provider or (lambda: env.get("ACRETIA_SMTP_PASSWORD"))
        self.timeout = timeout
        if self.security not in ("ssl", "starttls"):
            raise EmailConfigError("SMTP security must be 'ssl' or 'starttls'; plaintext is not allowed")

    @property
    def enabled(self) -> bool:
        return bool(self.host)

    def __repr__(self):
        return f"SMTPTransport(host={self.host!r}, port={self.port}, user={self.user!r}, security={self.security!r})"

    def send(self, message: EmailMessage) -> None:
        if not self.enabled:
            raise TransportDisabled("SMTP is not configured (set ACRETIA_SMTP_HOST)")
        ctx = ssl.create_default_context()
        if self.security == "ssl":
            cli = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=ctx)
        else:
            cli = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        with cli:
            if self.security == "starttls":
                cli.ehlo()
                if not cli.has_extn("starttls"):
                    raise EmailConfigError("server does not offer STARTTLS; refusing to continue in plaintext")
                cli.starttls(context=ctx)
                cli.ehlo()
            pw = self._pw()
            if self.user and pw:
                cli.login(self.user, pw)
            cli.send_message(message)


def send(message: EmailMessage, transport, *, tracker=None, job_id: str | None = None):
    if not message["To"]:
        raise ValueError("message has no recipient")
    res = transport.send(message)
    if tracker and job_id:
        tracker.emailed(job_id)
    return res


# --------------------------------------------------------------------------- latency telemetry
class LatencyTracker:
    """received -> submitted -> emailed timestamps per job (parity 26/27 targets: 10 / 15 minutes)."""

    def __init__(self, path: str = ":memory:", clock=time.time):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock, self._clock = threading.Lock(), clock
        self._db.execute("CREATE TABLE IF NOT EXISTS lat(token TEXT PRIMARY KEY, job_id TEXT, kind TEXT, received REAL,"
                         " submitted REAL, emailed REAL)")
        self._db.commit()

    def _ts(self, ts):
        return self._clock() if ts is None else (ts.timestamp() if isinstance(ts, datetime) else float(ts))

    def received(self, token: str, kind: str = "research", ts=None, slot_time=None) -> str:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO lat(token, kind, received) VALUES(?,?,?)",
                             (token, kind, self._ts(slot_time if slot_time is not None else ts)))
            self._db.commit()
        return token

    def submitted(self, token: str, job_id: str, ts=None):
        with self._lock:
            self._db.execute("UPDATE lat SET job_id=?, submitted=? WHERE token=?", (job_id, self._ts(ts), token))
            self._db.commit()

    def emailed(self, job_id: str, ts=None):
        with self._lock:
            self._db.execute("UPDATE lat SET emailed=? WHERE job_id=?", (self._ts(ts), job_id))
            self._db.commit()

    def report(self, job_id: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT kind, received, submitted, emailed FROM lat WHERE job_id=?", (job_id,)).fetchone()
        if not r:
            return None
        kind, rec, sub, em = r
        total = None if em is None else em - rec
        target = TARGETS_S.get(kind, TARGETS_S["research"])
        return {"job_id": job_id, "kind": kind, "receive_to_submit_s": None if sub is None else sub - rec,
                "submit_to_email_s": None if (sub is None or em is None) else em - sub, "total_s": total,
                "target_s": target, "met_target": None if total is None else total <= target}


# --------------------------------------------------------------------------- inbound
class InboundRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class InboundRequest:
    org_id: str
    user: str
    kind: str                         # research | deck | save_material
    request: dict                     # ResearchRequest dict (question fenced); deck/save: same shape, see docs
    attachments: list = field(default_factory=list)       # saved files: {name, path, size, sha256, origin}
    rejected_attachments: list = field(default_factory=list)   # {name, reason}
    auth: str = "unauthenticated"     # pass | unauthenticated
    subject: str = ""
    message_id: str | None = None
    received_at: float = field(default_factory=time.time)


_FAIL = {"fail", "softfail", "permerror"}
_AR_RES = re.compile(r"\b(dkim|spf|dmarc)\s*=\s*([a-z]+)", re.I)
_AR_D = re.compile(r"header\.d\s*=\s*([A-Za-z0-9.-]+)", re.I)
_QUOTE_CUT = re.compile(r"^(on .{5,200}wrote:|-{2,}\s*original message\s*-{2,}|-{2,}\s*forwarded message|from:\s.+|sent from my .*|"
                        r"get outlook for .*)$", re.I)


def _aligned(d: str, domain: str) -> bool:
    d, domain = d.lower().rstrip("."), domain.lower()
    return domain == d or domain.endswith("." + d) or d.endswith("." + domain)


def _auth(msg, from_domain: str, authserv_ids) -> str:
    results: dict[str, list[str]] = {}
    doms = []
    for h in msg.get_all("Authentication-Results", []):
        h = str(h)
        if authserv_ids and h.split(";", 1)[0].strip().lower() not in {a.lower() for a in authserv_ids}:
            continue
        for k, v in _AR_RES.findall(h):
            results.setdefault(k.lower(), []).append(v.lower())
        if re.search(r"dkim\s*=\s*pass", h, re.I):
            doms += _AR_D.findall(h)
    if not results:
        return "unauthenticated"
    bad = [f"{k}={v}" for k, vs in results.items() for v in vs if v in _FAIL]
    if bad:
        raise InboundRejected(f"authentication failed ({', '.join(bad)})")
    if "dkim" in results and "pass" in results["dkim"] and doms and not any(_aligned(d, from_domain) for d in doms):
        raise InboundRejected("DKIM domain does not align with the From domain")
    ok = "pass" in results.get("dkim", []) or "pass" in results.get("spf", []) or "pass" in results.get("dmarc", [])
    return "pass" if ok else "unauthenticated"


def _match_org(addr: str, org_allowlist) -> str | None:
    a = addr.lower()
    for org, entries in org_allowlist.items():
        for e in entries:
            e = e.strip().lower()
            if e == a or (e.startswith("@") and a.endswith(e)) or (e.startswith("*@") and a.endswith(e[1:])):
                return org
    return None


def _strip_body(text: str) -> list[str]:
    lines = []
    for ln in text.replace("\r", "").split("\n"):
        s = ln.strip()
        if s == "--" or ln.startswith("-- ") or _QUOTE_CUT.match(s):
            break
        if s.startswith(">"):
            continue
        if s:
            lines.append(s)
    return lines


_PREFIX = re.compile(r"^\s*((re|fwd?|aw)\s*:\s*)+", re.I)


def _classify(subject: str, body_lines: list[str]) -> tuple[str, str]:
    subj = _PREFIX.sub("", _clean(subject))
    first = _clean(body_lines[0]) if body_lines else ""
    for text, from_body in ((subj, False), (first, True)):
        m = re.match(r"^(deck|save)\s*:\s*(.*)$", text, re.I) or re.match(r"^/(deck|save|research)\b\s*(.*)$", text, re.I)
        if m:
            cmd = m.group(1).lower()
            rest = m.group(2).strip() or (first if not from_body else "")
            return {"deck": "deck", "save": "save_material"}.get(cmd, "research"), rest
    return "research", subj or first


def _fence(text: str) -> str:
    text = re.sub(r"</?email_request>", "", _clean(text), flags=re.I)[:500]
    return f"<email_request>\n{text}\n</email_request>"


def _safe_copy(src: Path, dest_dir: Path, name: str) -> Path:
    dest_dir = Path(dest_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _unpack.sanitize_component(name)
    target = dest_dir / name
    n = 1
    while target.exists():
        target = dest_dir / f"{Path(name).stem}_{n}{Path(name).suffix}"
        n += 1
    if target.resolve().parent != dest_dir:
        raise InboundRejected("unsafe attachment path")
    shutil.copyfile(src, target)
    return target


def parse_request_email(eml_bytes: bytes, *, org_allowlist, project_resolver=None, authserv_ids=None,
                        limits=None, max_attachment_bytes: int = 50 * 1024 * 1024) -> InboundRequest:
    """Validate and parse one inbound .eml. Raises InboundRejected. ``org_allowlist``: {org_id: [addr | @domain]}.
    ``project_resolver(org_id, user, hint) -> directory | None`` says where attachments are saved (hint is a
    ``[Project]`` tag from the subject or None)."""
    msg = email.message_from_bytes(eml_bytes, policy=email.policy.default)
    froms = msg.get_all("From", [])
    if len(froms) != 1:
        raise InboundRejected("exactly one From header required")
    raw_from = str(froms[0])
    pairs = getaddresses([raw_from])
    if len(pairs) != 1 or not pairs[0][1] or "@" not in pairs[0][1]:
        raise InboundRejected("unparseable From")
    display, addr = pairs[0]
    addr = addr.lower()
    for found in re.findall(r"[\w.+-]+@[\w.-]+", display or ""):
        if found.lower() != addr:
            raise InboundRejected("display-name address differs from the sender address (spoof)")
    org = _match_org(addr, org_allowlist)
    if org is None:
        raise InboundRejected("sender is not on an org allowlist")
    auth = _auth(msg, addr.split("@", 1)[1], authserv_ids)

    body = msg.get_body(preferencelist=("plain",))
    text = body.get_content() if body is not None else ""
    lines = _strip_body(text)
    subject = str(msg.get("Subject", "") or "")
    kind, req_text = _classify(subject, lines)

    hint = None
    m = re.search(r"\[([^\]\r\n]{1,80})\]", subject)
    if m:
        hint = m.group(1).strip()
        req_text = re.sub(r"\[[^\]]*\]", "", req_text).strip()

    saved, rejected = [], []
    parts = list(msg.iter_attachments())
    dest = project_resolver(org, addr, hint) if (parts and project_resolver) else None
    for i, part in enumerate(parts, 1):
        name = _unpack.sanitize_component(part.get_filename() or f"attachment_{i}")
        try:
            payload = part.get_payload(decode=True) if part.get_content_type() != "message/rfc822" else \
                part.get_payload(0).as_bytes(policy=email.policy.default)
            payload = payload or b""
            if len(payload) > max_attachment_bytes:
                raise _unpack.ArchiveBombError("attachment too large")
            if dest is None:
                rejected.append({"name": name, "reason": "no project folder resolved"})
                continue
            with tempfile.TemporaryDirectory(prefix="acretia-inbound-") as tmp:
                res = _unpack.unpack(payload, Path(tmp) / "x", name=name, limits=limits)
                for f in res.files:
                    p = Path(tmp) / "x" / f["path"]
                    target = _safe_copy(p, dest, Path(f["path"]).name)
                    saved.append({"name": target.name, "path": str(target), "size": f["size"],
                                  "sha256": f["sha256"], "origin": f.get("origin", name)})
        except (_unpack.UnpackError, InboundRejected) as e:
            rejected.append({"name": name, "reason": f"{type(e).__name__}: {e}"})

    if kind == "save_material" and not saved and not req_text:
        raise InboundRejected("save request has no attachments")
    if kind != "save_material" and not req_text:
        if not saved:
            raise InboundRejected("empty request")
        kind, req_text = "save_material", ""
    question = _fence(req_text or "save material")
    request = {"v": 1, "question": question, "org_id": org, "user_id": addr,
               "tickers": sorted(set(re.findall(r"\$([A-Za-z]{1,5})\b", req_text)))}
    request["tickers"] = [t.upper() for t in request["tickers"]]
    return InboundRequest(org_id=org, user=addr, kind=kind, request=request, attachments=saved,
                          rejected_attachments=rejected, auth=auth, subject=_clean(subject),
                          message_id=str(msg.get("Message-ID") or "") or None)


def handle_inbound(inbound: InboundRequest, *, submit, deck_handoff=None, tracker: LatencyTracker | None = None,
                   received_ts=None) -> str | None:
    """Route a parsed request. research -> ``submit(request)`` (jobs.submit); deck -> ``deck_handoff(inbound)`` (session
    B's engine); save_material -> nothing to run (files already saved). Returns a job id or None."""
    token = f"mail:{inbound.message_id or hashlib.sha1(repr(inbound.request).encode()).hexdigest()[:12]}"
    if tracker:
        tracker.received(token, inbound.kind if inbound.kind in TARGETS_S else "research", ts=received_ts or inbound.received_at)
    job_id = None
    if inbound.kind == "research":
        job_id = submit(inbound.request)
    elif inbound.kind == "deck":
        if deck_handoff is None:
            raise InboundRejected("deck engine not wired")
        job_id = deck_handoff(inbound)
    if tracker and job_id:
        tracker.submitted(token, job_id)
    return job_id
