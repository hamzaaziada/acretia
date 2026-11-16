"""Item 63: custom MCP servers per org. Tools appear to users as `org.<server>.<tool>` and their output is untrusted."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import urllib.parse

from ..mcp.client import MCPClient, MCPError
from . import AdminError, PermissionDenied, actor_parts, audit, conn, need_org, ref_ok, require_admin

DEFAULT_EXECUTABLES = ("python", "python3", "node", "uvx", "npx")
_EXE_RE = re.compile(r"^(python|python3(\.\d+)?|node|uvx|npx)$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
PREFIX = "org"


# ------------------------------------------------------------------------------------------------ validation
def _exe_allowed(argv0: str, allow: set[str]) -> bool:
    base = os.path.basename(argv0)
    if base not in allow and re.sub(r"\.\d+$", "", base) not in allow:
        return False
    if not _EXE_RE.match(base):
        return False
    if os.sep in argv0 or (os.altsep and os.altsep in argv0):
        real = os.path.realpath(argv0)
        trusted = {os.path.realpath(sys.executable)}
        w = shutil.which(base)
        if w:
            trusted.add(os.path.realpath(w))
        return real in trusted
    return True


def _check_command(command, allow: set[str]) -> list[str]:
    if isinstance(command, str):
        raise AdminError("command must be an argv list, not a shell string")
    if not isinstance(command, (list, tuple)) or not command or not all(isinstance(a, str) and a and "\x00" not in a for a in command):
        raise AdminError("command must be a non-empty list of non-empty strings")
    if not _exe_allowed(command[0], allow):
        raise AdminError(f"executable {command[0]!r} is not on the org allowlist {sorted(allow)}")
    return list(command)


def _check_url(url, resolver=None) -> str:
    if not isinstance(url, str):
        raise AdminError("url must be a string")
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https":
        raise AdminError("MCP server URLs must be https")
    try:
        from ..connectors.web import validate_url
    except ImportError:                                      # pragma: no cover - web connector always ships
        validate_url = None
    if validate_url is not None:
        try:
            validate_url(url, **({"resolver": resolver} if resolver else {}))
        except Exception as e:
            raise AdminError(f"URL refused by the SSRF guard: {e}") from None
    return url


def effective_allowlist(org_id: str, *, db=None) -> set[str]:
    with conn(db) as c:
        r = c.execute("SELECT executables FROM admin_mcp_allowlist WHERE org_id=?", (org_id,)).fetchone()
    return set(json.loads(r["executables"])) if r else set(DEFAULT_EXECUTABLES)


def set_executable_allowlist(org_id: str, executables: list[str], actor, *, db=None) -> list[str]:
    """An org may only narrow the defaults (python, python3, node, uvx, npx); anything else is refused."""
    need_org(org_id)
    uid, _ = require_admin(actor)
    bad = [e for e in executables if e not in DEFAULT_EXECUTABLES]
    if bad:
        raise AdminError(f"executables {bad} are not permitted; choose from {DEFAULT_EXECUTABLES}")
    with conn(db) as c:
        before = sorted(effective_allowlist(org_id, db=c))
        c.execute("INSERT INTO admin_mcp_allowlist(org_id,executables,updated_by,updated_at) VALUES (?,?,?,?) ON CONFLICT(org_id) "
                  "DO UPDATE SET executables=excluded.executables, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                  (org_id, json.dumps(sorted(set(executables))), uid, time.time()))
        audit(c, org_id, actor, "mcp.set_allowlist", "allowlist", before, sorted(set(executables)))
    return sorted(set(executables))


# ------------------------------------------------------------------------------------------------ registry
def register_mcp_server(org_id: str, name: str, command, env_refs: dict | None, allow_tools, actor, *, db=None,
                        resolver=None) -> dict:
    """`command` is an argv list (stdio server) or an https URL string. `allow_tools` is a list of tool names or "*"."""
    need_org(org_id)
    uid, _ = require_admin(actor)
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise AdminError("name must match [a-z][a-z0-9_-]{0,31}")
    if allow_tools != "*" and not (isinstance(allow_tools, (list, tuple)) and all(isinstance(t, str) and t for t in allow_tools)):
        raise AdminError('allow_tools must be a list of tool names or "*"')
    env_refs = dict(env_refs or {})
    for k, v in env_refs.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)) or not ref_ok(v):
            raise AdminError(f"env_refs[{k!r}] must be a secret reference (env:NAME or scheme://path), never a value")
    with conn(db) as c:
        if isinstance(command, str) and command.lower().startswith(("http://", "https://")):
            transport, url, argv = "url", _check_url(command, resolver), None
        else:
            transport, url, argv = "stdio", None, _check_command(command, effective_allowlist(org_id, db=c))
        row = {"transport": transport, "command": argv, "url": url, "env_refs": env_refs,
               "allow_tools": list(allow_tools) if allow_tools != "*" else "*", "enabled": True}
        before = _get(c, org_id, name)
        c.execute("INSERT INTO admin_mcp_servers(org_id,name,transport,command,url,env_refs,allow_tools,enabled,updated_by,updated_at) "
                  "VALUES (?,?,?,?,?,?,?,1,?,?) ON CONFLICT(org_id,name) DO UPDATE SET transport=excluded.transport, "
                  "command=excluded.command, url=excluded.url, env_refs=excluded.env_refs, allow_tools=excluded.allow_tools, "
                  "enabled=1, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                  (org_id, name, transport, json.dumps(argv), url, json.dumps(env_refs, sort_keys=True),
                   json.dumps(row["allow_tools"]), uid, time.time()))
        audit(c, org_id, actor, "mcp.register", name, before, row)
    return {"org_id": org_id, "name": name, **row}


def _get(c, org_id, name) -> dict | None:
    r = c.execute("SELECT * FROM admin_mcp_servers WHERE org_id=? AND name=?", (org_id, name)).fetchone()
    if r is None:
        return None
    return {"org_id": org_id, "name": r["name"], "transport": r["transport"], "command": json.loads(r["command"] or "null"),
            "url": r["url"], "env_refs": json.loads(r["env_refs"]), "allow_tools": json.loads(r["allow_tools"]),
            "enabled": bool(r["enabled"])}


def set_server_enabled(org_id: str, name: str, enabled: bool, actor, *, db=None) -> dict:
    need_org(org_id)
    uid, _ = require_admin(actor)
    with conn(db) as c:
        before = _get(c, org_id, name)
        if before is None:
            raise AdminError(f"unknown MCP server {name!r}")
        c.execute("UPDATE admin_mcp_servers SET enabled=?, updated_by=?, updated_at=? WHERE org_id=? AND name=?",
                  (int(bool(enabled)), uid, time.time(), org_id, name))
        audit(c, org_id, actor, "mcp.set_enabled", name, {"enabled": before["enabled"]}, {"enabled": bool(enabled)})
        return _get(c, org_id, name)


def list_servers(org_id: str, *, db=None) -> list[dict]:
    need_org(org_id)
    with conn(db) as c:
        return [_get(c, org_id, r["name"]) for r in c.execute("SELECT name FROM admin_mcp_servers WHERE org_id=? ORDER BY name", (org_id,))]


# ------------------------------------------------------------------------------------------------ spawn + tools
def default_env_resolver(ref: str) -> str:
    if ref.startswith("env:"):
        v = os.environ.get(ref[4:])
        if v is None:
            raise AdminError(f"environment variable {ref[4:]!r} is not set")
        return v
    raise AdminError(f"no resolver for secret reference scheme in {ref!r}; supply env_resolver=")


def _spawn(server: dict, timeout: float, env_resolver) -> MCPClient:
    env = {k: env_resolver(v) for k, v in server["env_refs"].items()}
    client = MCPClient.spawn(server["command"], env=env, timeout=timeout)
    try:
        client.initialize()
    except BaseException:
        client.close()
        raise
    return client


def _visible(server: dict, tool: str) -> bool:
    return server["allow_tools"] == "*" or tool in server["allow_tools"]


def _member(org_id: str, user) -> None:
    if isinstance(user, dict) and user.get("org_id") not in (None, org_id):
        raise PermissionDenied("user does not belong to this org")
    actor_parts(user)


def tools_report(org_id: str, user, *, timeout: float = 10, env_resolver=default_env_resolver, db=None) -> tuple[list[dict], list[dict]]:
    """-> (tools, errors). Disabled servers are skipped; a server that fails to start only adds an error row."""
    need_org(org_id)
    _member(org_id, user)
    tools, errors = [], []
    for s in list_servers(org_id, db=db):
        if not s["enabled"]:
            continue
        if s["transport"] == "url":
            # No HTTP transport in MCPClient yet: expose only the tools the admin named explicitly.
            if s["allow_tools"] != "*":
                tools += [_entry(s, t, "", {}) for t in s["allow_tools"]]
            continue
        try:
            client = _spawn(s, timeout, env_resolver)
            try:
                for t in client.list_tools():
                    if _visible(s, t["name"]):
                        tools.append(_entry(s, t["name"], t.get("description", ""), t.get("inputSchema", {})))
            finally:
                client.close()
        except (MCPError, AdminError, OSError) as e:
            errors.append({"server": s["name"], "error": str(e)})
    return tools, errors


def _entry(s: dict, tool: str, description: str, schema: dict) -> dict:
    return {"name": f"{PREFIX}.{s['name']}.{tool}", "server": s["name"], "tool": tool, "description": description,
            "inputSchema": schema, "untrusted": True}


def tools_for_user(org_id: str, user, *, timeout: float = 10, env_resolver=default_env_resolver, db=None) -> list[dict]:
    return tools_report(org_id, user, timeout=timeout, env_resolver=env_resolver, db=db)[0]


def call_tool(org_id: str, user, full_name: str, args: dict | None = None, *, evidence_path=None, timeout: float = 30,
              env_resolver=default_env_resolver, db=None) -> dict:
    """Run `org.<server>.<tool>`. The result is marked `untrusted: True` (data, never instructions) and logged to evidence."""
    need_org(org_id)
    _member(org_id, user)
    parts = (full_name or "").split(".", 2)
    if len(parts) != 3 or parts[0] != PREFIX:
        raise AdminError(f"custom tool names look like {PREFIX}.<server>.<tool>, got {full_name!r}")
    _, sname, tool = parts
    with conn(db) as c:
        s = _get(c, org_id, sname)
    if s is None or not s["enabled"]:
        raise AdminError(f"unknown or disabled MCP server {sname!r}")
    if not _visible(s, tool):
        raise AdminError(f"tool {tool!r} is not allowed on server {sname!r}")
    if s["transport"] != "stdio":
        raise AdminError("calling tools on URL servers is not supported yet (no HTTP transport)")
    from ..evidence import EvidenceBundle
    path = evidence_path or os.path.join("storage", "evidence", f"admin-mcp-{org_id}.jsonl")
    client, err, out = None, None, None
    try:
        client = _spawn(s, timeout, env_resolver)
        out = client.call_tool(tool, args or {})
    except (MCPError, OSError) as e:
        err = e
    finally:
        if client is not None:
            client.close()
    bundle = EvidenceBundle(path)
    try:
        bundle.append(full_name, args or {}, source=full_name,
                      output={"untrusted": True, "error": str(err)} if err else {"untrusted": True, "result": out})
    finally:
        bundle.close()
    if err:
        raise AdminError(f"custom tool {full_name} failed: {err}") from None
    return {"name": full_name, "result": out, "untrusted": True, "source": full_name}
