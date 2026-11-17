"""Users, orgs, memberships, sessions, invites and the `/auth/*`, `/org/*`, `/me/*` routes (SPEC §3, §4)."""
from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import os
import re
import time

from . import db, security
from .http import ApiError, Response, Route, ROLE_ORDER, _json_bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, locale TEXT NOT NULL DEFAULT 'en',
  created_at TEXT NOT NULL, settings_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL, password_hash TEXT NOT NULL,
  locale TEXT NOT NULL DEFAULT 'en', created_at TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0,
  preferences_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS memberships(
  org_id TEXT NOT NULL REFERENCES orgs(id), user_id TEXT NOT NULL REFERENCES users(id),
  role TEXT NOT NULL CHECK(role IN ('owner','member','viewer')), created_at TEXT NOT NULL,
  PRIMARY KEY(org_id, user_id));
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, csrf_hash TEXT NOT NULL, user_id TEXT NOT NULL,
  org_id TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL, ip TEXT NOT NULL DEFAULT '',
  ua TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, org_id);
CREATE TABLE IF NOT EXISTS invites(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, email TEXT NOT NULL, role TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, accepted_at TEXT);
"""

IDLE_SECONDS = 12 * 3600
ABSOLUTE_SECONDS = 7 * 86400
INVITE_SECONDS = 14 * 86400
ROLES = ("owner", "member", "viewer")
EMAIL_RX = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

clock = time.time  # monkeypatched in tests
LIMITER = security.RateLimiter(limit=10, window=15 * 60)


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _epoch(s: str) -> float:
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def csrf_for(session_token: str) -> str:
    """CSRF token derived from the session token (stateless; only its hash is stored)."""
    return hmac.new(session_token.encode("utf-8"), b"acretia-csrf", hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- validation helpers
def _need(body, *keys) -> dict:
    if not isinstance(body, dict):
        raise ApiError(400, "bad_request", "A JSON object body is required.", "Send JSON with Content-Type: application/json.")
    for k in keys:
        if not isinstance(body.get(k), str) or not body[k].strip():
            raise ApiError(400, "bad_request", f"`{k}` is required.", f"Include a non-empty `{k}` string.")
    return body


def _email(v) -> str:
    v = str(v or "").strip()
    if len(v) > 254 or not EMAIL_RX.match(v):
        raise ApiError(400, "bad_email", "That does not look like an email address.", "Use a full address such as name@firm.com.")
    return v


def _password(v) -> str:
    if not isinstance(v, str) or len(v) < security.MIN_PASSWORD:
        raise ApiError(400, "weak_password", f"Passwords need at least {security.MIN_PASSWORD} characters.",
                       "Use a longer passphrase.")
    if len(v) > 256:
        raise ApiError(400, "bad_request", "That password is too long.", "Use at most 256 characters.")
    return v


def _role(v) -> str:
    if v not in ROLES:
        raise ApiError(400, "bad_role", "Role must be owner, member or viewer.", "Choose one of: owner, member, viewer.")
    return v


# --------------------------------------------------------------------------- data access
def slugify(name: str, conn) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "org"
    slug = base
    while conn.execute("SELECT 1 FROM orgs WHERE slug=?", (slug,)).fetchone():
        slug = f"{base}-{os.urandom(2).hex()}"
    return slug


def create_user(conn, email, password, name, locale="en") -> str:
    uid = db.new_id("usr")
    conn.execute("INSERT INTO users(id,email,name,password_hash,locale,created_at) VALUES(?,?,?,?,?,?)",
                 (uid, email.strip(), name.strip(), security.hash_password(password), locale, db.now()))
    return uid


def add_membership(conn, org_id, user_id, role):
    conn.execute("INSERT INTO memberships(org_id,user_id,role,created_at) VALUES(?,?,?,?) "
                 "ON CONFLICT(org_id,user_id) DO UPDATE SET role=excluded.role", (org_id, user_id, role, db.now()))


def create_org(conn, name, owner_email, owner_password, owner_name) -> dict:
    """Create an org with its first owner. Raises ValueError for bad input or an email already registered."""
    if not str(name or "").strip():
        raise ValueError("organization name is required")
    if not EMAIL_RX.match(str(owner_email or "").strip()):
        raise ValueError("owner email is not valid")
    if len(owner_password or "") < security.MIN_PASSWORD:
        raise ValueError(f"owner password needs at least {security.MIN_PASSWORD} characters")
    if conn.execute("SELECT 1 FROM users WHERE email=?", (owner_email.strip(),)).fetchone():
        raise ValueError("that email is already registered")
    org_id = db.new_id("org")
    conn.execute("INSERT INTO orgs(id,name,slug,locale,created_at,settings_json) VALUES(?,?,?,?,?,?)",
                 (org_id, name.strip(), slugify(name, conn), "en", db.now(), "{}"))
    uid = create_user(conn, owner_email, owner_password, owner_name or owner_email.split("@")[0])
    add_membership(conn, org_id, uid, "owner")
    return {"org_id": org_id, "user_id": uid}


def _org_dict(conn, org_id) -> dict:
    r = conn.execute("SELECT id,name,slug,locale FROM orgs WHERE id=?", (org_id,)).fetchone()
    return dict(r) if r else {}


def _orgs_for(conn, user_id) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT o.id, o.name, o.slug, m.role FROM memberships m JOIN orgs o ON o.id=m.org_id WHERE m.user_id=? "
        "ORDER BY m.created_at, o.id", (user_id,))]


def _prefs(row) -> dict:
    try:
        saved = json.loads(row["preferences_json"] or "{}")
    except ValueError:
        saved = {}
    out = {"theme": "system", "locale": row["locale"] or "en", "digits": "latn"}
    out.update({k: v for k, v in saved.items() if k in out})
    return out


def user_dict(conn, user_id) -> dict:
    r = conn.execute("SELECT id,email,name,locale,preferences_json FROM users WHERE id=?", (user_id,)).fetchone()
    return {"id": r["id"], "email": r["email"], "name": r["name"], "locale": r["locale"], "preferences": _prefs(r)}


def me_payload(conn, user_id, org_id, role, csrf_token) -> dict:
    return {"user": user_dict(conn, user_id), "org": _org_dict(conn, org_id), "role": role,
            "orgs": _orgs_for(conn, user_id), "csrf_token": csrf_token}


# --------------------------------------------------------------------------- sessions
def create_session(conn, user_id, org_id, ip="", ua="") -> tuple[str, str]:
    """Returns (session_token, csrf_token). Only sha256 of each is stored."""
    token = security.new_token(32)
    csrf = csrf_for(token)
    now = _iso(clock())
    conn.execute("INSERT INTO sessions(id,token_hash,csrf_hash,user_id,org_id,created_at,last_seen,ip,ua) VALUES(?,?,?,?,?,?,?,?,?)",
                 (db.new_id("ses"), security.token_hash(token), security.token_hash(csrf), user_id, org_id, now, now,
                  ip, (ua or "")[:300]))
    return token, csrf


def resolve_session(conn, token: str | None) -> dict | None:
    """Session token -> {session_id, user, org_id, role, csrf_hash} or None (expired/forged/disabled/removed)."""
    if not token or len(token) > 200:
        return None
    s = conn.execute("SELECT * FROM sessions WHERE token_hash=?", (security.token_hash(token),)).fetchone()
    if s is None:
        return None
    t = clock()
    try:
        created, last = _epoch(s["created_at"]), _epoch(s["last_seen"])
    except ValueError:
        return None
    if t - created > ABSOLUTE_SECONDS or t - last > IDLE_SECONDS:
        conn.execute("DELETE FROM sessions WHERE id=?", (s["id"],))
        return None
    u = conn.execute("SELECT id,email,name,locale,disabled FROM users WHERE id=?", (s["user_id"],)).fetchone()
    m = conn.execute("SELECT role FROM memberships WHERE org_id=? AND user_id=?", (s["org_id"], s["user_id"])).fetchone()
    if u is None or u["disabled"] or m is None:
        conn.execute("DELETE FROM sessions WHERE id=?", (s["id"],))
        return None
    if t - last > 60:
        conn.execute("UPDATE sessions SET last_seen=? WHERE id=?", (_iso(t), s["id"]))
    return {"session_id": s["id"], "csrf_hash": s["csrf_hash"], "org_id": s["org_id"], "role": m["role"],
            "user": {"id": u["id"], "email": u["email"], "name": u["name"], "locale": u["locale"]}}


def _cookie_token(headers) -> str | None:
    return security.parse_cookies(headers.get("Cookie")).get(security.SESSION_COOKIE)


def _json_with_cookie(ctx, payload, token, status=200):
    secure = security.is_secure(ctx.headers)
    return Response(status, _json_bytes(payload), "application/json; charset=utf-8",
                    {"Set-Cookie": security.build_cookie(token, secure=secure, max_age=ABSOLUTE_SECONDS)})


def _ip(ctx) -> str:
    return ctx.headers.get("X-Acretia-Client-Ip") or ""


def _ua(ctx) -> str:
    return ctx.headers.get("User-Agent") or ""


def _become(ctx, user_id, org_id, role):
    ctx.user, ctx.org_id, ctx.role = user_dict(ctx.conn, user_id), org_id, role


# --------------------------------------------------------------------------- /auth routes
def signup(ctx):
    conn = ctx.conn
    if os.environ.get("ACRETIA_ALLOW_SIGNUP") != "1" and conn.execute("SELECT 1 FROM orgs LIMIT 1").fetchone():
        raise ApiError(403, "signup_disabled", "Self-service signup is turned off.",
                       "Ask an owner of your organization for an invite.")
    b = _need(ctx.json, "email", "password", "name", "org_name")
    email, pw = _email(b["email"]), _password(b["password"])
    if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise ApiError(409, "email_taken", "That email is already registered.", "Sign in instead, or use a different email.")
    res = create_org(conn, b["org_name"][:120], email, pw, b["name"][:120])
    token, csrf = create_session(conn, res["user_id"], res["org_id"], _ip(ctx), _ua(ctx))
    _become(ctx, res["user_id"], res["org_id"], "owner")
    ctx.audit("auth.signup", f"org:{res['org_id']}", {"email": email})
    return _json_with_cookie(ctx, me_payload(conn, res["user_id"], res["org_id"], "owner", csrf), token, 201)


def login(ctx):
    conn = ctx.conn
    b = _need(ctx.json, "email", "password")
    email = b["email"].strip().lower()
    key = f"{email}|{_ip(ctx)}"
    if LIMITER.blocked(key):
        wait = max(1, LIMITER.retry_after(key) // 60 + 1)
        raise ApiError(429, "rate_limited", "Too many failed sign-in attempts.",
                       f"Wait about {wait} minutes and try again, or ask an owner to reset your password.",
                       headers={"Retry-After": str(LIMITER.retry_after(key))})
    u = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    ok = False
    if u is None:
        security.burn_password_time(b["password"])
    else:
        ok = security.verify_password(b["password"], u["password_hash"]) and not u["disabled"]
    if not ok:
        LIMITER.fail(key)
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect.",
                       "Check both and try again, or ask an owner to reset your access.")
    orgs = _orgs_for(conn, u["id"])
    if not orgs:
        raise ApiError(403, "no_org", "This account is not a member of any organization.", "Ask an owner to invite you.")
    want = b.get("org_id")
    chosen = next((o for o in orgs if o["id"] == want), None) if want else None
    if want and chosen is None:
        raise ApiError(404, "not_found", "No such organization.")
    chosen = chosen or orgs[0]
    LIMITER.reset(key)
    if ctx.session_id:
        conn.execute("DELETE FROM sessions WHERE id=?", (ctx.session_id,))
    token, csrf = create_session(conn, u["id"], chosen["id"], _ip(ctx), _ua(ctx))
    _become(ctx, u["id"], chosen["id"], chosen["role"])
    ctx.audit("auth.login", f"user:{u['id']}", {})
    return _json_with_cookie(ctx, me_payload(conn, u["id"], chosen["id"], chosen["role"], csrf), token)


def logout(ctx):
    ctx.conn.execute("DELETE FROM sessions WHERE id=?", (ctx.session_id,))
    ctx.audit("auth.logout", f"user:{ctx.user['id']}", {})
    return Response(200, _json_bytes({"ok": True}), "application/json; charset=utf-8",
                    {"Set-Cookie": security.clear_cookie(security.is_secure(ctx.headers))})


def me(ctx):
    tok = _cookie_token(ctx.headers) or ""
    return me_payload(ctx.conn, ctx.user["id"], ctx.org_id, ctx.role, csrf_for(tok))


def switch_org(ctx):
    b = _need(ctx.json, "org_id")
    m = ctx.conn.execute("SELECT role FROM memberships WHERE org_id=? AND user_id=?", (b["org_id"], ctx.user["id"])).fetchone()
    if m is None:
        raise ApiError(404, "not_found", "No such organization.")
    ctx.conn.execute("UPDATE sessions SET org_id=? WHERE id=?", (b["org_id"], ctx.session_id))
    ctx.org_id, ctx.role = b["org_id"], m["role"]
    ctx.audit("auth.switch_org", f"org:{b['org_id']}", {})
    return me_payload(ctx.conn, ctx.user["id"], b["org_id"], m["role"], csrf_for(_cookie_token(ctx.headers) or ""))


def accept_invite(ctx):
    conn = ctx.conn
    b = _need(ctx.json, "token", "password")
    inv = conn.execute("SELECT * FROM invites WHERE token_hash=?", (security.token_hash(b["token"]),)).fetchone()
    bad = ApiError(400, "invite_invalid", "This invite link is not valid.", "Ask an owner to send a new invite.")
    if inv is None or inv["accepted_at"] or clock() - _epoch(inv["created_at"]) > INVITE_SECONDS:
        raise bad
    u = conn.execute("SELECT * FROM users WHERE email=?", (inv["email"],)).fetchone()
    if u is None:
        _need(b, "name")
        uid = create_user(conn, inv["email"], _password(b["password"]), b["name"][:120])
    else:
        if not security.verify_password(b["password"], u["password_hash"]) or u["disabled"]:
            raise ApiError(401, "invalid_credentials", "Email or password is incorrect.",
                           "Enter the password of your existing account to join this organization.")
        uid = u["id"]
    add_membership(conn, inv["org_id"], uid, inv["role"])
    conn.execute("UPDATE invites SET accepted_at=? WHERE id=?", (db.now(), inv["id"]))
    token, csrf = create_session(conn, uid, inv["org_id"], _ip(ctx), _ua(ctx))
    _become(ctx, uid, inv["org_id"], inv["role"])
    ctx.audit("org.invite_accepted", f"user:{uid}", {"invite": inv["id"], "role": inv["role"]})
    return _json_with_cookie(ctx, me_payload(conn, uid, inv["org_id"], inv["role"], csrf), token)


# --------------------------------------------------------------------------- /org routes
def org_info(ctx):
    return _org_dict(ctx.conn, ctx.org_id) | {"role": ctx.role}


def org_update(ctx):
    b = ctx.json if isinstance(ctx.json, dict) else {}
    if "name" in b:
        if not isinstance(b["name"], str) or not b["name"].strip():
            raise ApiError(400, "bad_request", "`name` must be a non-empty string.", "Send a name.")
        ctx.conn.execute("UPDATE orgs SET name=? WHERE id=?", (b["name"].strip()[:120], ctx.org_id))
    if "locale" in b:
        if b["locale"] not in ("en", "ar"):
            raise ApiError(400, "bad_request", "`locale` must be en or ar.", "Use en or ar.")
        ctx.conn.execute("UPDATE orgs SET locale=? WHERE id=?", (b["locale"], ctx.org_id))
    ctx.audit("org.update", f"org:{ctx.org_id}", {k: b[k] for k in ("name", "locale") if k in b})
    return _org_dict(ctx.conn, ctx.org_id) | {"role": ctx.role}


def _member(r) -> dict:
    return {"user_id": r["id"], "email": r["email"], "name": r["name"], "role": r["role"],
            "joined_at": r["created_at"], "disabled": bool(r["disabled"])}


_MEMBER_SQL = ("SELECT u.id, u.email, u.name, u.disabled, m.role, m.created_at FROM memberships m "
               "JOIN users u ON u.id=m.user_id WHERE m.org_id=?")


def list_members(ctx):
    rows = ctx.conn.execute(_MEMBER_SQL + " ORDER BY m.created_at, u.email", (ctx.org_id,)).fetchall()
    return {"items": [_member(r) for r in rows], "next_cursor": None}


def _owner_count(conn, org_id) -> int:
    return conn.execute("SELECT COUNT(*) FROM memberships WHERE org_id=? AND role='owner'", (org_id,)).fetchone()[0]


def _target_member(ctx):
    r = ctx.conn.execute(_MEMBER_SQL + " AND u.id=?", (ctx.org_id, ctx.params["user_id"])).fetchone()
    if r is None:
        raise ApiError(404, "not_found", "No such member.")
    return r


def _last_owner_guard(ctx, member):
    if member["role"] == "owner" and _owner_count(ctx.conn, ctx.org_id) <= 1:
        raise ApiError(409, "last_owner", "An organization must keep at least one owner.",
                       "Promote another member to owner first, then change this one.")


def add_member(ctx):
    conn = ctx.conn
    b = _need(ctx.json, "email")
    email, role = _email(b["email"]), _role(b.get("role", "member"))
    u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if u is None:
        _need(b, "name", "password")
        uid = create_user(conn, email, _password(b["password"]), b["name"][:120])
    else:
        uid = u["id"]
    add_membership(conn, ctx.org_id, uid, role)
    ctx.audit("org.member_add", f"user:{uid}", {"role": role})
    r = conn.execute(_MEMBER_SQL + " AND u.id=?", (ctx.org_id, uid)).fetchone()
    return 201, _member(r)


def update_member(ctx):
    m = _target_member(ctx)
    b = _need(ctx.json, "role")
    role = _role(b["role"])
    if role != "owner":
        _last_owner_guard(ctx, m)
    ctx.conn.execute("UPDATE memberships SET role=? WHERE org_id=? AND user_id=?", (role, ctx.org_id, m["id"]))
    ctx.audit("org.member_role", f"user:{m['id']}", {"from": m["role"], "to": role})
    return _member(ctx.conn.execute(_MEMBER_SQL + " AND u.id=?", (ctx.org_id, m["id"])).fetchone())


def remove_member(ctx):
    m = _target_member(ctx)
    _last_owner_guard(ctx, m)
    ctx.conn.execute("DELETE FROM memberships WHERE org_id=? AND user_id=?", (ctx.org_id, m["id"]))
    ctx.conn.execute("DELETE FROM sessions WHERE org_id=? AND user_id=?", (ctx.org_id, m["id"]))
    ctx.audit("org.member_remove", f"user:{m['id']}", {"role": m["role"]})
    return {"ok": True}


def create_invite(ctx):
    b = _need(ctx.json, "email")
    email, role = _email(b["email"]), _role(b.get("role", "member"))
    token = security.new_token(24)
    iid = db.new_id("inv")
    ctx.conn.execute("INSERT INTO invites(id,org_id,email,role,token_hash,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                     (iid, ctx.org_id, email, role, security.token_hash(token), ctx.user["id"], _iso(clock())))
    ctx.audit("org.invite", f"invite:{iid}", {"email": email, "role": role})
    return 201, {"invite": {"id": iid, "email": email, "role": role}, "token": token,
                 "accept_path": f"/accept-invite?token={token}",
                 "note": "Email sending is off by default; share this link with the invitee."}


def list_invites(ctx):
    rows = ctx.conn.execute("SELECT id,email,role,created_at,accepted_at FROM invites WHERE org_id=? ORDER BY created_at DESC",
                            (ctx.org_id,)).fetchall()
    return {"items": [dict(r) for r in rows], "next_cursor": None}


def revoke_invite(ctx):
    r = ctx.conn.execute("SELECT id FROM invites WHERE id=? AND org_id=? AND accepted_at IS NULL",
                         (ctx.params["invite_id"], ctx.org_id)).fetchone()
    if r is None:
        raise ApiError(404, "not_found", "No such invite.")
    ctx.conn.execute("DELETE FROM invites WHERE id=?", (r["id"],))
    ctx.audit("org.invite_revoke", f"invite:{r['id']}", {})
    return {"ok": True}


# --------------------------------------------------------------------------- /me/preferences
_PREF_VALUES = {"theme": ("light", "dark", "system"), "locale": ("en", "ar"), "digits": ("latn", "arab")}


def get_prefs(ctx):
    r = ctx.conn.execute("SELECT locale, preferences_json FROM users WHERE id=?", (ctx.user["id"],)).fetchone()
    return _prefs(r)


def put_prefs(ctx):
    b = ctx.json
    if not isinstance(b, dict):
        raise ApiError(400, "bad_request", "A JSON object body is required.", "Send {theme, locale, digits}.")
    for k, v in b.items():
        if k not in _PREF_VALUES or v not in _PREF_VALUES[k]:
            allowed = ", ".join(f"{a}: {'/'.join(vs)}" for a, vs in _PREF_VALUES.items())
            raise ApiError(400, "bad_preference", f"Unsupported preference `{k}`={v!r}.", f"Allowed: {allowed}.")
    r = ctx.conn.execute("SELECT locale, preferences_json FROM users WHERE id=?", (ctx.user["id"],)).fetchone()
    cur = _prefs(r)
    cur.update(b)
    ctx.conn.execute("UPDATE users SET preferences_json=?, locale=? WHERE id=?",
                     (json.dumps(cur, sort_keys=True), cur["locale"], ctx.user["id"]))
    ctx.audit("me.preferences", f"user:{ctx.user['id']}", b)
    return cur


P = "/api/v1"
ROUTES = [
    Route("POST", P + "/auth/signup", signup, role="public"),
    Route("POST", P + "/auth/login", login, role="public"),
    Route("POST", P + "/auth/logout", logout, role="viewer"),
    Route("GET", P + "/auth/me", me, role="viewer"),
    Route("POST", P + "/auth/switch-org", switch_org, role="viewer"),
    Route("POST", P + "/auth/invites/accept", accept_invite, role="public"),
    Route("GET", P + "/org", org_info, role="viewer"),
    Route("PATCH", P + "/org", org_update, role="owner"),
    Route("GET", P + "/org/members", list_members, role="member"),
    Route("POST", P + "/org/members", add_member, role="owner"),
    Route("PATCH", P + "/org/members/{user_id}", update_member, role="owner"),
    Route("DELETE", P + "/org/members/{user_id}", remove_member, role="owner"),
    Route("GET", P + "/org/invites", list_invites, role="owner"),
    Route("POST", P + "/org/invites", create_invite, role="owner"),
    Route("DELETE", P + "/org/invites/{invite_id}", revoke_invite, role="owner"),
    Route("GET", P + "/me/preferences", get_prefs, role="viewer"),
    Route("PUT", P + "/me/preferences", put_prefs, role="viewer"),
]
