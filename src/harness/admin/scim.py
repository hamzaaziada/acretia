"""SCIM 2.0 (RFC 7643 / 7644) Users and Groups core (S6.5b, parity item 59).

A pure library over a DB-API (sqlite3) connection. The HTTP layer (product app session) maps requests onto
`ScimService` methods and returns `ScimError.to_json()` with `ScimError.status` on failure.

Deprovisioning (active=false, PatchOp active, or DELETE) runs in ONE transaction: session-revocation hooks,
schedule-disable hooks, API-token-disable hooks, and an audit row. If any hook raises, everything rolls back
and the user stays active (fail closed on the caller, never half-deprovisioned). Change listeners (the ACL cache)
are notified after commit so access drops immediately.

Bearer tokens: only a SHA-256 hash is stored; verification compares hashes with hmac.compare_digest."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"

MAX_PAYLOAD_BYTES = 256 * 1024
MAX_PAGE = 200
MAX_PATCH_OPS = 100
MAX_GROUP_MEMBERS = 10_000

_USER_ATTRS = {"schemas", "id", "externalId", "userName", "name", "displayName", "emails", "active", "meta", "groups"}
_NAME_ATTRS = {"formatted", "givenName", "familyName"}
_EMAIL_ATTRS = {"value", "primary", "type", "display"}
_GROUP_ATTRS = {"schemas", "id", "externalId", "displayName", "members", "meta"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scim_tokens(org_id TEXT NOT NULL, token_hash TEXT NOT NULL, created TEXT NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS scim_users(id TEXT PRIMARY KEY, org_id TEXT NOT NULL, user_name TEXT NOT NULL,
  doc TEXT NOT NULL, active INTEGER NOT NULL, version INTEGER NOT NULL, created TEXT NOT NULL, modified TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS scim_users_uname ON scim_users(org_id, user_name);
CREATE TABLE IF NOT EXISTS scim_groups(id TEXT PRIMARY KEY, org_id TEXT NOT NULL, display_name TEXT NOT NULL,
  external_id TEXT, version INTEGER NOT NULL, created TEXT NOT NULL, modified TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS scim_groups_name ON scim_groups(org_id, display_name);
CREATE TABLE IF NOT EXISTS scim_group_members(group_id TEXT NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY(group_id, user_id));
CREATE TABLE IF NOT EXISTS scim_revocations(id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL,
  user_id TEXT NOT NULL, kind TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scim_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL, action TEXT NOT NULL,
  subject TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL);
"""


class ScimError(Exception):
    """SCIM error (RFC 7644 §3.12). `.status` is the HTTP status; `.to_json()` the body."""

    def __init__(self, status: int, detail: str, scim_type: str | None = None):
        super().__init__(detail)
        self.status, self.detail, self.scim_type = status, detail, scim_type

    def to_json(self) -> dict:
        out = {"schemas": [ERROR_SCHEMA], "status": str(self.status), "detail": self.detail}
        if self.scim_type:
            out["scimType"] = self.scim_type
        return out


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_schema(conn) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def issue_scim_token(conn, org_id: str) -> str:
    """Create a bearer token for the org. The raw token is returned once; only its hash is stored."""
    ensure_schema(conn)
    token = "scim_" + secrets.token_urlsafe(32)
    with conn:
        conn.execute("INSERT INTO scim_tokens(org_id, token_hash, created) VALUES(?,?,?)", (org_id, hash_token(token), _now()))
    return token


def revoke_scim_tokens(conn, org_id: str) -> None:
    with conn:
        conn.execute("UPDATE scim_tokens SET revoked=1 WHERE org_id=?", (org_id,))


def verify_scim_token(conn, org_id: str, token: str | None) -> bool:
    """Constant-time check of a bearer token against the org's stored hashes. Never compares raw tokens, and
    always compares against every stored hash so timing does not reveal which (if any) matched."""
    if not isinstance(token, str) or not token or len(token) > 512:
        return False
    cand = hash_token(token)
    ok = False
    for (h,) in conn.execute("SELECT token_hash FROM scim_tokens WHERE org_id=? AND revoked=0", (org_id,)).fetchall():
        ok |= hmac.compare_digest(cand, h)
    return ok


def _check_payload(body, kind: str) -> dict:
    if not isinstance(body, dict):
        raise ScimError(400, f"{kind} body must be a JSON object", "invalidSyntax")
    try:
        size = len(json.dumps(body))
    except (TypeError, ValueError):
        raise ScimError(400, "body is not JSON serialisable", "invalidSyntax")
    if size > MAX_PAYLOAD_BYTES:
        raise ScimError(413, f"payload exceeds {MAX_PAYLOAD_BYTES} bytes", "tooMany")
    return body


def _check_schemas(body: dict, allowed: str) -> None:
    schemas = body.get("schemas")
    if not isinstance(schemas, list) or not schemas or not all(isinstance(s, str) for s in schemas):
        raise ScimError(400, "schemas is required", "invalidSyntax")
    bad = [s for s in schemas if s != allowed]
    if bad:
        raise ScimError(400, f"unsupported schema: {bad[0]}", "invalidValue")


_USERNAME_RE = re.compile(r"^[^\s\x00-\x1f]{1,256}$")


def _str(v, name: str, maxlen: int = 256, required: bool = False) -> str | None:
    if v is None:
        if required:
            raise ScimError(400, f"{name} is required", "invalidValue")
        return None
    if not isinstance(v, str) or len(v) > maxlen or any(ord(c) < 32 for c in v):
        raise ScimError(400, f"{name} must be a string up to {maxlen} chars without control characters", "invalidValue")
    if required and not v.strip():
        raise ScimError(400, f"{name} is required", "invalidValue")
    return v


def _bool(v, name: str) -> bool:
    if isinstance(v, bool):
        return v
    raise ScimError(400, f"{name} must be a boolean", "invalidValue")


def _clean_user(body: dict) -> tuple[dict, bool]:
    body = _check_payload(body, "User")
    _check_schemas(body, USER_SCHEMA)
    unknown = set(body) - _USER_ATTRS
    if unknown:
        raise ScimError(400, f"unknown attribute: {sorted(unknown)[0]}", "invalidValue")
    uname = _str(body.get("userName"), "userName", required=True)
    if not _USERNAME_RE.match(uname):
        raise ScimError(400, "userName must be 1-256 non-space characters", "invalidValue")
    doc: dict = {"userName": uname}
    ext = _str(body.get("externalId"), "externalId")
    if ext is not None:
        doc["externalId"] = ext
    dn = _str(body.get("displayName"), "displayName")
    if dn is not None:
        doc["displayName"] = dn
    name = body.get("name")
    if name is not None:
        if not isinstance(name, dict) or set(name) - _NAME_ATTRS:
            raise ScimError(400, "name has unsupported attributes", "invalidValue")
        doc["name"] = {k: _str(v, f"name.{k}") for k, v in name.items() if v is not None}
    emails = body.get("emails")
    if emails is not None:
        if not isinstance(emails, list) or len(emails) > 20:
            raise ScimError(400, "emails must be a list of up to 20", "invalidValue")
        clean = []
        for e in emails:
            if not isinstance(e, dict) or set(e) - _EMAIL_ATTRS:
                raise ScimError(400, "emails entry has unsupported attributes", "invalidValue")
            val = _str(e.get("value"), "emails.value", 320, required=True)
            if "@" not in val:
                raise ScimError(400, "emails.value must be an email address", "invalidValue")
            item = {"value": val}
            if "primary" in e:
                item["primary"] = _bool(e["primary"], "emails.primary")
            if e.get("type") is not None:
                item["type"] = _str(e["type"], "emails.type", 32)
            clean.append(item)
        doc["emails"] = clean
    active = _bool(body["active"], "active") if "active" in body else True
    return doc, active


class ScimService:
    """SCIM Users/Groups for one org. Every query is scoped by org_id, so another org's ids read as 404."""

    def __init__(self, db_conn, org_id: str):
        if not org_id or not isinstance(org_id, str):
            raise ValueError("org_id required")
        self.conn, self.org_id = db_conn, org_id
        ensure_schema(db_conn)
        self.on_deprovision: list[Callable[[str, str], None]] = [self._default_revoke("session")]
        self.on_disable_schedules: list[Callable[[str, str], None]] = [self._default_revoke("schedules")]
        self.on_disable_tokens: list[Callable[[str, str], None]] = [self._default_revoke("api_tokens")]
        self.change_listeners: list[Callable[[str, str | None], None]] = []   # (org_id, user_id or None=whole org)

    # ---- plumbing
    def _default_revoke(self, kind: str):
        def hook(org_id: str, user_id: str) -> None:
            self.conn.execute("INSERT INTO scim_revocations(org_id,user_id,kind,created) VALUES(?,?,?,?)",
                              (org_id, user_id, kind, _now()))
        hook.__name__ = f"default_revoke_{kind}"
        return hook

    def _audit(self, action: str, subject: str, detail: dict) -> None:
        self.conn.execute("INSERT INTO scim_audit(org_id,action,subject,detail,created) VALUES(?,?,?,?,?)",
                          (self.org_id, action, subject, json.dumps(detail, sort_keys=True), _now()))

    def _notify(self, user_id: str | None) -> None:
        for fn in list(self.change_listeners):
            fn(self.org_id, user_id)

    def _deprovision(self, user_id: str, reason: str) -> None:
        for hooks in (self.on_deprovision, self.on_disable_schedules, self.on_disable_tokens):
            for hook in hooks:
                hook(self.org_id, user_id)
        self._audit("user.deprovision", user_id, {"reason": reason})

    # ---- Users
    def _user_row(self, user_id: str):
        if not isinstance(user_id, str):
            raise ScimError(404, "User not found")
        row = self.conn.execute("SELECT id,doc,active,version,created,modified FROM scim_users WHERE id=? AND org_id=?",
                                (user_id, self.org_id)).fetchone()
        if not row:
            raise ScimError(404, f"User {user_id} not found")
        return row

    def _user_groups(self, user_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT g.id, g.display_name FROM scim_group_members m JOIN scim_groups g ON g.id=m.group_id "
                                 "WHERE m.user_id=? AND g.org_id=? ORDER BY g.display_name", (user_id, self.org_id)).fetchall()
        return [{"value": r[0], "display": r[1], "$ref": f"Groups/{r[0]}"} for r in rows]

    def _user_json(self, row) -> dict:
        uid, doc, active, version, created, modified = row
        out = json.loads(doc)
        out.update({"schemas": [USER_SCHEMA], "id": uid, "active": bool(active), "groups": self._user_groups(uid),
                    "meta": {"resourceType": "User", "created": created, "lastModified": modified,
                             "version": f'W/"{version}"', "location": f"Users/{uid}"}})
        return out

    def _check_etag(self, version: int, if_match: str | None) -> None:
        if if_match is not None and if_match != f'W/"{version}"':
            raise ScimError(412, "version mismatch", None)

    def create_user(self, body: dict) -> dict:
        doc, active = _clean_user(body)
        uid, now = str(uuid.uuid4()), _now()
        try:
            with self.conn:
                self.conn.execute("INSERT INTO scim_users(id,org_id,user_name,doc,active,version,created,modified) VALUES(?,?,?,?,?,1,?,?)",
                                  (uid, self.org_id, doc["userName"].lower(), json.dumps(doc), int(active), now, now))
                self._audit("user.create", uid, {"userName": doc["userName"], "active": active})
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                raise ScimError(409, f"userName {doc['userName']} already exists", "uniqueness")
            raise
        return self._user_json(self._user_row(uid))

    def get_user(self, user_id: str) -> dict:
        return self._user_json(self._user_row(user_id))

    def is_active(self, user_id: str) -> bool:
        row = self.conn.execute("SELECT active FROM scim_users WHERE id=? AND org_id=?", (user_id, self.org_id)).fetchone()
        return bool(row and row[0])

    _FILTER_RE = re.compile(r'^\s*(userName|active)\s+eq\s+("(?:[^"\\]|\\.)*"|true|false)\s*$', re.I)

    def _parse_filter(self, flt: str | None) -> tuple[str | None, bool | None]:
        if flt is None or not flt.strip():
            return None, None
        if len(flt) > 512:
            raise ScimError(400, "filter too long", "invalidFilter")
        uname, active = None, None
        for part in re.split(r"\s+and\s+", flt, flags=re.I):
            m = self._FILTER_RE.match(part)
            if not m:
                raise ScimError(400, f"unsupported filter: {part.strip()[:80]}", "invalidFilter")
            attr, val = m.group(1).lower(), m.group(2)
            if attr == "username":
                if not val.startswith('"'):
                    raise ScimError(400, "userName needs a quoted string", "invalidFilter")
                uname = json.loads(val).lower()
            else:
                if val.startswith('"'):
                    raise ScimError(400, "active needs true or false", "invalidFilter")
                active = val.lower() == "true"
        return uname, active

    def list_users(self, filter: str | None = None, start_index: int = 1, count: int = 100) -> dict:
        uname, active = self._parse_filter(filter)
        try:
            start_index, count = int(start_index), int(count)
        except (TypeError, ValueError):
            raise ScimError(400, "startIndex/count must be integers", "invalidValue")
        start_index, count = max(1, start_index), min(max(0, count), MAX_PAGE)
        where, args = ["org_id=?"], [self.org_id]
        if uname is not None:
            where.append("user_name=?"); args.append(uname)
        if active is not None:
            where.append("active=?"); args.append(int(active))
        w = " AND ".join(where)
        total = self.conn.execute(f"SELECT COUNT(*) FROM scim_users WHERE {w}", args).fetchone()[0]
        rows = self.conn.execute(f"SELECT id,doc,active,version,created,modified FROM scim_users WHERE {w} "
                                 "ORDER BY created, id LIMIT ? OFFSET ?", args + [count, start_index - 1]).fetchall()
        return {"schemas": [LIST_SCHEMA], "totalResults": total, "startIndex": start_index, "itemsPerPage": len(rows),
                "Resources": [self._user_json(r) for r in rows]}

    def _save_user(self, user_id: str, doc: dict, active: bool, was_active: bool, action: str, version: int) -> dict:
        try:
            with self.conn:
                self.conn.execute("UPDATE scim_users SET user_name=?, doc=?, active=?, version=version+1, modified=? WHERE id=? AND org_id=?",
                                  (doc["userName"].lower(), json.dumps(doc), int(active), _now(), user_id, self.org_id))
                self._audit(action, user_id, {"active": active})
                if was_active and not active:
                    self._deprovision(user_id, "active=false")
        except ScimError:
            raise
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                raise ScimError(409, f"userName {doc['userName']} already exists", "uniqueness")
            raise
        if was_active != active:
            self._notify(user_id)
        return self._user_json(self._user_row(user_id))

    def replace_user(self, user_id: str, body: dict, if_match: str | None = None) -> dict:
        row = self._user_row(user_id)
        self._check_etag(row[3], if_match)
        doc, active = _clean_user(body)
        return self._save_user(user_id, doc, active, bool(row[2]), "user.replace", row[3])

    def patch_user(self, user_id: str, body: dict, if_match: str | None = None) -> dict:
        row = self._user_row(user_id)
        self._check_etag(row[3], if_match)
        ops = self._patch_ops(body)
        doc, active = json.loads(row[1]), bool(row[2])
        for op, path, value in ops:
            doc, active = self._apply_user_op(doc, active, op, path, value)
        doc2, active2 = _clean_user({"schemas": [USER_SCHEMA], **doc, "active": active})
        return self._save_user(user_id, doc2, active2, bool(row[2]), "user.patch", row[3])

    @staticmethod
    def _patch_ops(body) -> list[tuple[str, str | None, object]]:
        body = _check_payload(body, "PatchOp")
        _check_schemas(body, PATCH_SCHEMA)
        ops = body.get("Operations")
        if not isinstance(ops, list) or not ops or len(ops) > MAX_PATCH_OPS:
            raise ScimError(400, f"Operations must be a list of 1..{MAX_PATCH_OPS}", "invalidSyntax")
        out = []
        for o in ops:
            if not isinstance(o, dict) or set(o) - {"op", "path", "value"}:
                raise ScimError(400, "invalid operation", "invalidSyntax")
            op = str(o.get("op", "")).lower()
            if op not in ("add", "replace", "remove"):
                raise ScimError(400, f"unsupported op {o.get('op')!r}", "invalidSyntax")
            path = o.get("path")
            if path is not None and not isinstance(path, str):
                raise ScimError(400, "path must be a string", "invalidPath")
            if op != "remove" and "value" not in o:
                raise ScimError(400, "value required", "invalidValue")
            if op == "remove" and not path:
                raise ScimError(400, "remove requires a path", "noTarget")
            out.append((op, path, o.get("value")))
        return out

    _USER_PATHS = {"username": "userName", "displayname": "displayName", "externalid": "externalId", "active": "active",
                   "emails": "emails", "name": "name", "name.givenname": "name.givenName",
                   "name.familyname": "name.familyName", "name.formatted": "name.formatted"}

    def _apply_user_op(self, doc: dict, active: bool, op: str, path: str | None, value):
        if path is None:   # Okta/Azure style: value is an object of attributes
            if not isinstance(value, dict):
                raise ScimError(400, "value must be an object when path is omitted", "invalidValue")
            for k, v in value.items():
                doc, active = self._apply_user_op(doc, active, op, k, v)
            return doc, active
        key = self._USER_PATHS.get(path.lower().strip())
        if key is None:
            raise ScimError(400, f"unsupported path {path[:60]!r}", "invalidPath")
        if key == "active":
            if op == "remove":
                raise ScimError(400, "active cannot be removed", "mutability")
            if isinstance(value, str) and value.lower() in ("true", "false"):   # Azure AD sends strings
                value = value.lower() == "true"
            return doc, _bool(value, "active")
        doc = json.loads(json.dumps(doc))
        if key == "userName" and op == "remove":
            raise ScimError(400, "userName cannot be removed", "mutability")
        if "." in key:
            parent, child = key.split(".")
            sub = doc.setdefault(parent, {})
            if op == "remove":
                sub.pop(child, None)
            else:
                sub[child] = value
            if not sub:
                doc.pop(parent, None)
        elif op == "remove":
            doc.pop(key, None)
        elif key == "emails" and op == "add" and isinstance(value, list):
            doc["emails"] = list(doc.get("emails", [])) + value
        else:
            doc[key] = value
        return doc, active

    def delete_user(self, user_id: str) -> None:
        row = self._user_row(user_id)
        with self.conn:
            if row[2]:
                self._deprovision(user_id, "delete")
            self.conn.execute("DELETE FROM scim_group_members WHERE user_id=?", (user_id,))
            self.conn.execute("DELETE FROM scim_users WHERE id=? AND org_id=?", (user_id, self.org_id))
            self._audit("user.delete", user_id, {})
        self._notify(user_id)

    # ---- Groups
    def _group_row(self, group_id: str):
        row = self.conn.execute("SELECT id,display_name,external_id,version,created,modified FROM scim_groups WHERE id=? AND org_id=?",
                                (group_id, self.org_id)).fetchone() if isinstance(group_id, str) else None
        if not row:
            raise ScimError(404, f"Group {group_id} not found")
        return row

    def _group_json(self, row) -> dict:
        gid, name, ext, version, created, modified = row
        members = self.conn.execute("SELECT u.id, u.doc FROM scim_group_members m JOIN scim_users u ON u.id=m.user_id "
                                    "WHERE m.group_id=? AND u.org_id=? ORDER BY u.id", (gid, self.org_id)).fetchall()
        out = {"schemas": [GROUP_SCHEMA], "id": gid, "displayName": name,
               "members": [{"value": m[0], "display": json.loads(m[1]).get("userName"), "$ref": f"Users/{m[0]}"} for m in members],
               "meta": {"resourceType": "Group", "created": created, "lastModified": modified,
                        "version": f'W/"{version}"', "location": f"Groups/{gid}"}}
        if ext:
            out["externalId"] = ext
        return out

    def _member_ids(self, members, field: str = "members") -> list[str]:
        if not isinstance(members, list) or len(members) > MAX_GROUP_MEMBERS:
            raise ScimError(400, f"{field} must be a list", "invalidValue")
        ids = []
        for m in members:
            if not isinstance(m, dict) or not isinstance(m.get("value"), str):
                raise ScimError(400, "member needs a string value", "invalidValue")
            if not self.conn.execute("SELECT 1 FROM scim_users WHERE id=? AND org_id=?", (m["value"], self.org_id)).fetchone():
                raise ScimError(400, f"member {m['value'][:40]} is not a user in this org", "invalidValue")
            ids.append(m["value"])
        return ids

    def create_group(self, body: dict) -> dict:
        body = _check_payload(body, "Group")
        _check_schemas(body, GROUP_SCHEMA)
        unknown = set(body) - _GROUP_ATTRS
        if unknown:
            raise ScimError(400, f"unknown attribute: {sorted(unknown)[0]}", "invalidValue")
        name = _str(body.get("displayName"), "displayName", required=True)
        ext = _str(body.get("externalId"), "externalId")
        gid, now = str(uuid.uuid4()), _now()
        try:
            with self.conn:
                members = self._member_ids(body.get("members", []))
                self.conn.execute("INSERT INTO scim_groups(id,org_id,display_name,external_id,version,created,modified) VALUES(?,?,?,?,1,?,?)",
                                  (gid, self.org_id, name, ext, now, now))
                self.conn.executemany("INSERT OR IGNORE INTO scim_group_members(group_id,user_id) VALUES(?,?)", [(gid, u) for u in members])
                self._audit("group.create", gid, {"displayName": name, "members": len(members)})
        except ScimError:
            raise
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                raise ScimError(409, f"group {name} already exists", "uniqueness")
            raise
        self._notify(None)
        return self._group_json(self._group_row(gid))

    def get_group(self, group_id: str) -> dict:
        return self._group_json(self._group_row(group_id))

    def list_groups(self, start_index: int = 1, count: int = 100) -> dict:
        start_index, count = max(1, int(start_index)), min(max(0, int(count)), MAX_PAGE)
        total = self.conn.execute("SELECT COUNT(*) FROM scim_groups WHERE org_id=?", (self.org_id,)).fetchone()[0]
        rows = self.conn.execute("SELECT id,display_name,external_id,version,created,modified FROM scim_groups WHERE org_id=? "
                                 "ORDER BY display_name LIMIT ? OFFSET ?", (self.org_id, count, start_index - 1)).fetchall()
        return {"schemas": [LIST_SCHEMA], "totalResults": total, "startIndex": start_index, "itemsPerPage": len(rows),
                "Resources": [self._group_json(r) for r in rows]}

    _MEMBER_PATH = re.compile(r'^members\[value\s+eq\s+"([^"\\]{1,64})"\]$', re.I)

    def patch_group(self, group_id: str, body: dict) -> dict:
        row = self._group_row(group_id)
        ops = self._patch_ops(body)
        try:
            with self.conn:
                for op, path, value in ops:
                    self._apply_group_op(group_id, op, path, value)
                self.conn.execute("UPDATE scim_groups SET version=version+1, modified=? WHERE id=?", (_now(), group_id))
                self._audit("group.patch", group_id, {"ops": len(ops)})
        except ScimError:
            raise
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                raise ScimError(409, "group displayName already exists", "uniqueness")
            raise
        self._notify(None)
        return self._group_json(self._group_row(group_id))

    def _apply_group_op(self, gid: str, op: str, path: str | None, value) -> None:
        if path is None:
            if not isinstance(value, dict):
                raise ScimError(400, "value must be an object when path is omitted", "invalidValue")
            for k, v in value.items():
                self._apply_group_op(gid, op, k, v)
            return
        p = path.strip()
        m = self._MEMBER_PATH.match(p)
        if m and op == "remove":
            self.conn.execute("DELETE FROM scim_group_members WHERE group_id=? AND user_id=?", (gid, m.group(1)))
        elif p.lower() == "members":
            if op == "remove":
                if value is None:
                    self.conn.execute("DELETE FROM scim_group_members WHERE group_id=?", (gid,))
                else:
                    for u in self._member_ids(value):
                        self.conn.execute("DELETE FROM scim_group_members WHERE group_id=? AND user_id=?", (gid, u))
            else:
                ids = self._member_ids(value)
                if op == "replace":
                    self.conn.execute("DELETE FROM scim_group_members WHERE group_id=?", (gid,))
                self.conn.executemany("INSERT OR IGNORE INTO scim_group_members(group_id,user_id) VALUES(?,?)", [(gid, u) for u in ids])
        elif p.lower() == "displayname" and op != "remove":
            self.conn.execute("UPDATE scim_groups SET display_name=? WHERE id=?", (_str(value, "displayName", required=True), gid))
        else:
            raise ScimError(400, f"unsupported path {p[:60]!r}", "invalidPath")

    def delete_group(self, group_id: str) -> None:
        self._group_row(group_id)
        with self.conn:
            self.conn.execute("DELETE FROM scim_group_members WHERE group_id=?", (group_id,))
            self.conn.execute("DELETE FROM scim_groups WHERE id=? AND org_id=?", (group_id, self.org_id))
            self._audit("group.delete", group_id, {})
        self._notify(None)

    # ---- helpers for the ACL layer
    def groups_of(self, user_id: str) -> set[str]:
        """Ids AND display names of the SCIM groups the user belongs to (ACLs may reference either)."""
        out: set[str] = set()
        for g in self._user_groups(user_id):
            out.add(g["value"]); out.add(g["display"])
        return out

    def user_identities(self, user_id: str) -> set[str]:
        row = self._user_row(user_id)
        doc = json.loads(row[1])
        ids = {user_id.lower(), doc["userName"].lower()}
        ids.update(e["value"].lower() for e in doc.get("emails", []))
        return ids

    def audit_rows(self) -> list[dict]:
        cur = self.conn.execute("SELECT action,subject,detail,created FROM scim_audit WHERE org_id=? ORDER BY id", (self.org_id,))
        return [dict(zip(("action", "subject", "detail", "created"), r)) for r in cur.fetchall()]

    def revocations(self, user_id: str | None = None) -> list[tuple[str, str]]:
        q, a = "SELECT user_id,kind FROM scim_revocations WHERE org_id=?", [self.org_id]
        if user_id:
            q += " AND user_id=?"; a.append(user_id)
        return [tuple(r) for r in self.conn.execute(q + " ORDER BY id", a).fetchall()]
