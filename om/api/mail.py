"""Email-in (P-J1 by email, D-SF-08): poll the firm's mailbox and turn allowed senders' emails into agent runs.

Security posture (SPEC §2.2 item 12):
  * Acretia never sends email. There is no SMTP code path in this module and `smtplib` is never imported; the
    `send_enabled` flag is stored (owner only, off by default) but replies are delivered in-app as notifications.
  * Mail content is data. The body becomes the job prompt text and is never interpreted as instructions to the app;
    the sender, subject and message id travel in the job's private `_email` input, not in the prompt.
  * The sender must be an org member (role member or owner) or an exact address on the owner's allowed list.
    The address is parsed with `email.utils` and compared to the real address, never the display name.
  * IMAP runs over TLS with certificate and host name verification; the host may not resolve to a private address.

Entry points: `poll_once(state, org_id=None)`, `init(state)` (background thread), `main(argv)` (CLI `poll-mail`).
"""
from __future__ import annotations

import argparse
import email
import email.policy
import email.utils
import difflib
import hashlib
import html.parser
import imaplib
import ipaddress
import json
import mailbox as _mailbox
import os
import re
import socket
import ssl
import threading
import time
from pathlib import Path

from . import db, deals, security
from .http import ApiError, sanitize_filename

SCHEMA = """
CREATE TABLE IF NOT EXISTS mailbox(
  org_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('imap','maildir')), host TEXT, port INTEGER, username TEXT,
  secret_enc TEXT NOT NULL DEFAULT '', folder TEXT, path TEXT, poll_seconds INTEGER NOT NULL DEFAULT 300,
  allowed_senders_json TEXT NOT NULL DEFAULT '[]', send_enabled INTEGER NOT NULL DEFAULT 0, last_uid INTEGER NOT NULL DEFAULT 0,
  uidvalidity TEXT, last_poll TEXT, status TEXT NOT NULL DEFAULT 'new', last_error TEXT NOT NULL DEFAULT '', owner_id TEXT,
  updated_at TEXT);
CREATE TABLE IF NOT EXISTS mail_log(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, message_id TEXT NOT NULL, sender TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL DEFAULT '', outcome TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', job_id TEXT, deal_id TEXT,
  attachments INTEGER NOT NULL DEFAULT 0, at TEXT NOT NULL, UNIQUE(org_id, message_id));
CREATE INDEX IF NOT EXISTS idx_mail_log_org ON mail_log(org_id, at);
"""

MAX_PROMPT = 8000                    # chars; also the 8 kB cap on what we take from a body
MAX_RAW = 60 * 1024 * 1024
MAX_ATTACH = 50 * 1024 * 1024
MAX_ATTACH_TOTAL = 100 * 1024 * 1024
MAX_ATTACH_COUNT = 25
PER_POLL = 50
EMAIL_RX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
DEAL_TAG = re.compile(r"\[\s*deal\s*:\s*([^\]\r\n]{1,120}?)\s*\]", re.I)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# =========================================================================== network guard
def _is_global(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def resolve_public(host: str, port: int) -> str:
    """Resolve `host` and refuse private/loopback/link-local results (SSRF). Returns the address to connect to."""
    if os.environ.get("ACRETIA_ALLOW_PRIVATE_HOSTS") == "1":
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return infos[0][4][0]
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addrs = [i[4][0] for i in infos]
    if not addrs or not all(_is_global(a) for a in addrs):
        raise ApiError(400, "host_not_allowed", "The mailbox host resolves to a private address.",
                       "Use the public host name of your mail server.")
    return addrs[0]


class _PinnedIMAP(imaplib.IMAP4_SSL):
    """IMAP over TLS to a pre-resolved address, verifying the certificate against the original host name."""

    def __init__(self, host, port, ip, ssl_context, timeout):
        self._pin = ip
        super().__init__(host, port, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout):
        sock = socket.create_connection((self._pin, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def connect_imap(rec: dict, secret: str, timeout: float = 20.0):
    host, port = rec["host"], int(rec.get("port") or 993)
    ip = resolve_public(host, port)
    conn = _PinnedIMAP(host, port, ip, ssl.create_default_context(), timeout)
    conn.login(rec.get("username") or "", secret)
    return conn


# =========================================================================== message parsing
def sender_of(msg) -> str | None:
    """The one real From address, lower-cased; None when absent, duplicated or malformed. Display names are ignored."""
    froms = msg.get_all("From") or []
    if len(froms) != 1:
        return None
    pairs = email.utils.getaddresses([str(froms[0])])
    if len(pairs) != 1:
        return None
    addr = pairs[0][1].strip().lower()
    return addr if EMAIL_RX.match(addr) else None


class _Text(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "tr", "li"):
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


_ATTRIB = re.compile(r"^\s*On .{3,200}wrote:\s*$", re.I)
_ORIG = re.compile(r"^\s*(-{2,}\s*(original message|forwarded message)\s*-{2,}|_{8,}|from:\s.+\bsent:\s)", re.I)
_SENT = re.compile(r"^\s*(sent from my |get outlook for )", re.I)


def body_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:                                                   # noqa: BLE001
        return ""
    if part.get_content_type() == "text/html":
        p = _Text()
        try:
            p.feed(text)
        except Exception:                                               # noqa: BLE001
            pass
        text = "".join(p.out)
    return text if isinstance(text, str) else ""


def strip_reply(text: str) -> str:
    """Drop quoted replies, the signature and mobile footers; cap at 8 kB. Everything else is kept verbatim."""
    lines = _CTRL.sub("", text.replace("\r\n", "\n").replace("\r", "\n")).split("\n")
    keep = []
    for i, ln in enumerate(lines):
        joined = ln + " " + lines[i + 1] if i + 1 < len(lines) else ln
        if _ATTRIB.match(ln) or (ln.lstrip().lower().startswith("on ") and not ln.rstrip().endswith("wrote:") and _ATTRIB.match(joined)):
            break
        if ln.rstrip() == "--" or ln == "-- " or _ORIG.match(ln) or _SENT.match(ln):
            break
        if ln.lstrip().startswith(">"):
            continue
        keep.append(ln.rstrip())
    out = "\n".join(keep).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out[:MAX_PROMPT]


def resolve_deal(conn, org_id: str, subject: str, body: str = "") -> tuple[str | None, str]:
    """-> (deal_id | None, note). `[deal: <name or id>]` first, then a fuzzy match, then a deal name inside the subject."""
    rows = conn.execute("SELECT deal_id, name FROM deals WHERE org_id=?", (org_id,)).fetchall()
    if not rows:
        return None, "no deals"
    by_id = {r["deal_id"].lower(): r["deal_id"] for r in rows}
    names = {r["name"].strip().lower(): r["deal_id"] for r in rows if r["name"].strip()}
    m = DEAL_TAG.search(subject) or DEAL_TAG.search(body[:400])
    if m:
        t = m.group(1).strip().lower()
        if t in by_id:
            return by_id[t], "tag id"
        if t in names:
            return names[t], "tag name"
        close = difflib.get_close_matches(t, list(names), n=2, cutoff=0.75)
        if close and (len(close) == 1 or difflib.SequenceMatcher(None, t, close[0]).ratio() > difflib.SequenceMatcher(None, t, close[1]).ratio() + 0.05):
            return names[close[0]], "tag fuzzy"
        return None, f"deal tag '{t[:60]}' matched no deal"
    subj = DEAL_TAG.sub("", subject).lower()
    hits = [n for n in names if len(n) >= 4 and re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", subj)]
    if hits:
        return names[max(hits, key=len)], "subject name"
    return None, "no deal in subject"


# =========================================================================== attachments -> documents
def _attachments(msg) -> list:
    out = []
    for part in msg.iter_attachments():
        if part.get_content_type() == "message/rfc822":
            try:
                data = part.get_payload(0).as_bytes()
            except Exception:                                           # noqa: BLE001
                continue
            out.append((part.get_filename() or "forwarded.eml", data, False))
            continue
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:                                               # noqa: BLE001
            continue
        inline = (part.get_content_disposition() or "") == "inline"
        out.append((part.get_filename() or "attachment", data, inline))
    return out


def _store_documents(state, conn, org_id, deal_id, user_id, atts) -> tuple[list, list]:
    """Sniff, cap and store attachments as deal documents (queued for indexing). -> (doc_ids, skipped)."""
    accepted, skipped, total = [], [], 0

    def consider(name, data, inline):
        nonlocal total
        name = sanitize_filename(name)
        if not data:
            skipped.append({"name": name, "reason": "empty"})
        elif inline and len(data) < 30_000 and security.sniff(data, name) in ("png", "jpg"):
            return                                                       # signature logos
        elif len(data) > MAX_ATTACH or total + len(data) > MAX_ATTACH_TOTAL:
            skipped.append({"name": name, "reason": "too large"})
        elif len(accepted) >= MAX_ATTACH_COUNT:
            skipped.append({"name": name, "reason": "too many attachments"})
        else:
            kind = security.sniff(data, name)
            if kind is None:
                skipped.append({"name": name, "reason": "unsupported type"})
            elif kind == "zip":
                skipped.append({"name": name, "reason": "nested archive"})
            else:
                accepted.append((name, kind, data))
                total += len(data)

    for name, data, inline in atts:
        if security.sniff(data, name) == "zip":
            try:
                for rel, blob in security.iter_zip(data):
                    consider(rel.rsplit("/", 1)[-1], blob, False)
            except security.UnsafeArchive:
                skipped.append({"name": sanitize_filename(name), "reason": "unsafe archive"})
        else:
            consider(name, data, inline)
    ids, ts = [], db.now()
    with db.tx(conn):
        for name, kind, data in accepted:
            key = state.blobs.put(data)
            did = db.new_id("doc")
            conn.execute("INSERT INTO documents(id,org_id,deal_id,name,kind,sha256,size,created_at,folder,uploaded_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (did, org_id, deal_id, name, kind, key, len(data), ts, "email", user_id))
            ids.append(did)
        if ids:
            conn.execute("UPDATE deal_meta SET updated_at=? WHERE org_id=? AND deal_id=?", (ts, org_id, deal_id))
    for did in ids:
        try:
            deals._publish(conn, org_id, did)
        except Exception:                                               # noqa: BLE001
            pass
        deals.enqueue_index(state, did)
    return ids, skipped


# =========================================================================== processing one message
def _log(conn, org_id, mid, sender, subject, outcome, reason="", job_id=None, deal_id=None, attachments=0):
    conn.execute("INSERT OR IGNORE INTO mail_log(id,org_id,message_id,sender,subject,outcome,reason,job_id,deal_id,attachments,at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (db.new_id("mail"), org_id, mid, sender[:200], subject[:200], outcome, reason, job_id, deal_id, attachments, db.now()))


def _reject(state, conn, org_id, mid, sender, subject, reason):
    _log(conn, org_id, mid, sender, subject, "rejected", reason)
    state.audit(conn, org_id, None, "mail.rejected", f"mail:{mid[:80]}", {"reason": reason, "from": sender[:200], "subject": subject[:120]})
    return {"outcome": "rejected", "reason": reason}


def _auth_failed(msg) -> bool:
    for h in msg.get_all("Authentication-Results") or []:
        s = str(h).lower()
        if re.search(r"\b(dmarc|dkim|spf)=(fail|softfail|permerror)\b", s) and "dmarc=pass" not in s:
            return True
    return False


def handle_message(state, org_id: str, mb: dict, raw: bytes) -> dict:
    """Process one raw message: authorise the sender, store attachments, submit a job. Never raises on bad mail."""
    from . import firm, jobs
    conn = state.conn()
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:                                                   # noqa: BLE001
        mid = "raw-" + hashlib.sha256(raw[:4096]).hexdigest()[:32]
        return _reject(state, conn, org_id, mid, "", "", "unparseable")
    mid = str(msg.get("Message-ID") or "").strip()[:200] or "raw-" + hashlib.sha256(raw[:8192]).hexdigest()[:32]
    subject = _CTRL.sub("", str(msg.get("Subject") or "")).strip()
    sender = sender_of(msg)
    if conn.execute("SELECT 1 FROM mail_log WHERE org_id=? AND message_id=?", (org_id, mid)).fetchone():
        return {"outcome": "duplicate"}
    if sender is None:
        return _reject(state, conn, org_id, mid, str(msg.get("From") or ""), subject, "no_valid_sender")
    members = {r["email"].lower(): (r["user_id"], r["role"]) for r in conn.execute(
        "SELECT u.email, m.user_id, m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND u.disabled=0", (org_id,))}
    allowed = {a.lower() for a in json.loads(mb.get("allowed_senders_json") or "[]")}
    if sender in members:
        user_id, role = members[sender]
    elif sender in allowed:
        owner = mb.get("owner_id")
        row = conn.execute("SELECT role FROM memberships WHERE org_id=? AND user_id=?", (org_id, owner)).fetchone() if owner else None
        user_id, role = (owner, row["role"]) if row else (None, None)
    else:
        return _reject(state, conn, org_id, mid, sender, subject, "sender_not_allowed")
    if user_id is None or role not in ("member", "owner"):
        return _reject(state, conn, org_id, mid, sender, subject, "insufficient_role")
    if _auth_failed(msg):
        return _reject(state, conn, org_id, mid, sender, subject, "authentication_failed")
    body = strip_reply(body_text(msg))
    clean_subject = DEAL_TAG.sub("", subject).strip()
    prompt = body or clean_subject
    if not prompt:
        return _reject(state, conn, org_id, mid, sender, subject, "empty_request")
    deal_id, note = resolve_deal(conn, org_id, subject, body)
    lim = firm.spend_limit(conn, org_id, deal_id)
    if not lim["allowed"]:
        state.notify(conn, org_id, user_id, "mail.blocked", "Email request not started", lim["hint"] or "A spend limit is reached.", "/settings/firm")
        return _reject(state, conn, org_id, mid, sender, subject, lim["reason"])
    docs, skipped = [], []
    atts = _attachments(msg)
    if atts and deal_id:
        docs, skipped = _store_documents(state, conn, org_id, deal_id, user_id, atts)
    elif atts:
        skipped = [{"name": sanitize_filename(a[0]), "reason": "no deal named in the subject"} for a in atts]
    try:
        job = jobs.svc().submit(org_id, user_id, prompt, deal_id, None,
                                {"_email": {"from": sender, "subject": subject[:200], "message_id": mid, "documents": docs}}, source="email")
    except ApiError as e:
        _log(conn, org_id, mid, sender, subject, "error", e.message[:200], deal_id=deal_id, attachments=len(docs))
        state.audit(conn, org_id, user_id, "mail.error", f"mail:{mid[:80]}", {"error": e.message[:200]})
        return {"outcome": "error", "reason": e.message}
    _log(conn, org_id, mid, sender, subject, "accepted", note, job["id"], deal_id, len(docs))
    state.audit(conn, org_id, user_id, "mail.accepted", f"job:{job['id']}", {"from": sender, "subject": subject[:120], "deal_id": deal_id,
                                                                            "documents": len(docs), "skipped": len(skipped)})
    note_txt = f" {len(docs)} attachment{'s' if len(docs) != 1 else ''} added to the deal." if docs else ""
    state.notify(conn, org_id, user_id, "mail.accepted", "Email request received",
                 (clean_subject or prompt)[:120] + "." + note_txt + (" No deal was named, so attachments were not stored." if skipped and not deal_id else ""),
                 f"/runs/{job['id']}")
    return {"outcome": "accepted", "job_id": job["id"], "deal_id": deal_id, "documents": docs, "skipped": skipped}


# =========================================================================== sources: maildir and IMAP
def _maildir_new(path: str):
    """Yield (key, bytes) for unprocessed messages (the `new/` subdirectory)."""
    md = _mailbox.Maildir(path, factory=None, create=False)
    for key in sorted(md.iterkeys()):
        newfile = Path(path) / "new" / key
        if not newfile.is_file() or newfile.is_symlink():
            continue
        if newfile.stat().st_size > MAX_RAW:
            yield key, None
            continue
        yield key, newfile.read_bytes()


def _maildir_mark(path: str, key: str, flags: str = "S") -> None:
    cur = Path(path) / "cur"
    cur.mkdir(exist_ok=True)
    os.rename(Path(path) / "new" / key, cur / f"{key}:2,{flags}")


def _poll_maildir(state, org_id, mb, summary):
    path = mb["path"]
    for key, raw in _maildir_new(path):
        if summary["fetched"] >= PER_POLL:
            break
        summary["fetched"] += 1
        try:
            res = _handle_safe(state, org_id, mb, raw)
        finally:
            try:
                _maildir_mark(path, key, "S")
            except OSError:
                pass
        _count(summary, res)


def _poll_imap(state, org_id, mb, summary):
    conn = state.conn()
    secret = security.decrypt_secret(state.secret_key, mb["secret_enc"])
    imap = connect_imap(mb, secret)
    try:
        typ, _ = imap.select(mb.get("folder") or "INBOX")
        if typ != "OK":
            raise ApiError(400, "folder_missing", f"The folder {mb.get('folder')!r} does not exist.", "Check the folder name in the mailbox settings.")
        validity = ""
        try:
            typ, d = imap.response("UIDVALIDITY")
            validity = (d[0] or b"").decode() if d and d[0] else ""
        except Exception:                                               # noqa: BLE001
            pass
        last = int(mb.get("last_uid") or 0)
        if validity and mb.get("uidvalidity") and validity != mb["uidvalidity"]:
            last = 0                                                    # mailbox was re-created; Message-ID dedupe protects us
        typ, data = imap.uid("SEARCH", None, f"UID {last + 1}:*")
        uids = sorted(int(x) for x in (data[0] or b"").split() if int(x) > last)[:PER_POLL]
        top = last
        for uid in uids:
            typ, parts = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in (parts or []) if isinstance(p, tuple)), None)
            summary["fetched"] += 1
            res = _handle_safe(state, org_id, mb, raw)
            _count(summary, res)
            try:
                imap.uid("STORE", str(uid), "+FLAGS", "(\\Seen)")
            except Exception:                                           # noqa: BLE001
                pass
            top = uid
            conn.execute("UPDATE mailbox SET last_uid=?, uidvalidity=? WHERE org_id=?", (top, validity or mb.get("uidvalidity"), org_id))
    finally:
        try:
            imap.logout()
        except Exception:                                               # noqa: BLE001
            pass


def _handle_safe(state, org_id, mb, raw):
    if raw is None:
        return _reject(state, state.conn(), org_id, "oversize-" + db.new_id("mail"), "", "", "too_large")
    try:
        return handle_message(state, org_id, mb, raw)
    except Exception as e:                                              # noqa: BLE001
        return {"outcome": "error", "reason": f"{type(e).__name__}"}


def _count(summary, res):
    o = res.get("outcome")
    if o == "accepted":
        summary["accepted"] += 1
        summary["jobs"].append(res["job_id"])
    elif o == "rejected":
        summary["rejected"] += 1
    elif o == "error":
        summary["errors"] += 1
    elif o == "duplicate":
        summary["duplicates"] += 1


# =========================================================================== public API
def _new_summary(org_id):
    return {"org_id": org_id, "fetched": 0, "accepted": 0, "rejected": 0, "errors": 0, "duplicates": 0, "jobs": [], "error": None}


def poll_once(state, org_id: str | None = None) -> dict:
    """Poll one org's mailbox (or every configured one when `org_id` is None). Returns the summary."""
    conn = state.conn()
    if org_id is None:
        ids = [r["org_id"] for r in conn.execute("SELECT org_id FROM mailbox")]
        subs = [poll_once(state, o) for o in ids]
        tot = {k: sum(s[k] for s in subs) for k in ("fetched", "accepted", "rejected", "errors", "duplicates")}
        return {**tot, "orgs": subs, "jobs": [j for s in subs for j in s["jobs"]]}
    summary = _new_summary(org_id)
    r = conn.execute("SELECT * FROM mailbox WHERE org_id=?", (org_id,)).fetchone()
    if r is None:
        summary["error"] = "no mailbox configured"
        return summary
    mb = dict(r)
    try:
        if mb["kind"] == "maildir":
            _poll_maildir(state, org_id, mb, summary)
        else:
            _poll_imap(state, org_id, mb, summary)
        status, err = "ok", ""
    except ApiError as e:
        status, err = "error", e.message
    except (OSError, _mailbox.Error, imaplib.IMAP4.error, ssl.SSLError, ValueError, socket.gaierror) as e:
        status, err = "error", f"{type(e).__name__}: {str(e)[:160]}"
    summary["error"] = err or None
    conn.execute("UPDATE mailbox SET last_poll=?, status=?, last_error=? WHERE org_id=?", (db.now(), status, err, org_id))
    return summary


def test_mailbox(state, mb: dict) -> dict:
    """Connect without processing anything. -> {ok, message, hint, messages, send_enabled}."""
    base = {"send_enabled": bool(mb.get("send_enabled")), "messages": None}
    try:
        if mb["kind"] == "maildir":
            p = Path(mb["path"])
            if not (p / "new").is_dir() or not (p / "cur").is_dir():
                return {**base, "ok": False, "message": "The folder is not a Maildir (it needs new/, cur/ and tmp/ inside).",
                        "hint": "Point at the Maildir root that contains new, cur and tmp."}
            n = sum(1 for f in (p / "new").iterdir() if f.is_file())
            return {**base, "ok": True, "message": f"Maildir found with {n} unprocessed message{'s' if n != 1 else ''}.", "hint": "", "messages": n}
        imap = connect_imap(mb, security.decrypt_secret(state.secret_key, mb["secret_enc"]))
        try:
            typ, data = imap.select(mb.get("folder") or "INBOX", readonly=True)
            if typ != "OK":
                return {**base, "ok": False, "message": f"Signed in, but the folder {mb.get('folder')!r} was not found.",
                        "hint": "Check the folder name (usually INBOX)."}
            n = int((data[0] or b"0").decode() or 0)
            return {**base, "ok": True, "message": f"Signed in. {n} message{'s' if n != 1 else ''} in {mb.get('folder') or 'INBOX'}.", "hint": "", "messages": n}
        finally:
            try:
                imap.logout()
            except Exception:                                           # noqa: BLE001
                pass
    except ApiError as e:
        return {**base, "ok": False, "message": e.message, "hint": e.hint or ""}
    except imaplib.IMAP4.error:
        return {**base, "ok": False, "message": "The server refused the sign-in.", "hint": "Check the user name and use an app password if the account has two-step verification."}
    except ssl.SSLError:
        return {**base, "ok": False, "message": "The server's TLS certificate could not be verified.",
                "hint": "Use the host name printed on the certificate; self-signed certificates are not accepted."}
    except (OSError, ValueError) as e:
        return {**base, "ok": False, "message": f"Could not connect ({type(e).__name__}).", "hint": "Check the host, the port (993 for IMAP over TLS) and that the server is reachable."}


# =========================================================================== background poller + CLI
_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def _loop(state, tick: float):
    last: dict = {}
    while not _STOP.wait(tick):
        try:
            for r in state.conn().execute("SELECT org_id, poll_seconds FROM mailbox").fetchall():
                every = max(60, int(r["poll_seconds"] or 300))
                if time.monotonic() - last.get(r["org_id"], -1e9) >= every:
                    last[r["org_id"]] = time.monotonic()
                    poll_once(state, r["org_id"])
        except Exception:                                               # noqa: BLE001
            continue


def init(state, tick: float = 15.0) -> threading.Thread | None:
    """Start the background poller (idempotent). Disabled with ACRETIA_MAIL_POLL=0."""
    global _THREAD
    if os.environ.get("ACRETIA_MAIL_POLL", "1") == "0":
        return None
    if _THREAD is not None and _THREAD.is_alive():
        return _THREAD
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, args=(state, tick), name="acretia-mail", daemon=True)
    _THREAD.start()
    return _THREAD


def shutdown() -> None:
    global _THREAD
    _STOP.set()
    if _THREAD is not None:
        _THREAD.join(timeout=2)
    _THREAD = None


def main(argv=None) -> int:
    """`python3 -m om.api poll-mail --data DIR [--org ORG] [--no-wait]`: poll once, then wait for the runs it started."""
    from . import jobs, state as state_mod
    ap = argparse.ArgumentParser(prog="poll-mail")
    ap.add_argument("--data", default="data/app")
    ap.add_argument("--org", default=None)
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--wait-seconds", type=int, default=900)
    args = ap.parse_args(argv)
    st = state_mod.create(args.data)
    svc = jobs.init(st)
    try:
        res = poll_once(st, args.org)
        print(json.dumps({k: v for k, v in res.items() if k != "orgs"}, sort_keys=True))
        if not args.no_wait and res["jobs"]:
            end = time.time() + args.wait_seconds
            while time.time() < end:
                rows = st.conn().execute(f"SELECT status FROM jobs WHERE id IN ({','.join('?' * len(res['jobs']))})", res["jobs"]).fetchall()
                if all(r["status"] in jobs.TERMINAL or r["status"] == "awaiting_approval" for r in rows):
                    break
                time.sleep(1)
        return 0
    finally:
        svc.shutdown()
