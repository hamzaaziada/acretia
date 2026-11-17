"""Agent library: the built-in catalogue plus saved agents (prompt or chain), search, pins and admin enable/disable.

Built-ins are virtual rows (id `agt_builtin_<task_id>`) and read-only except for enable (owner) and pin (anyone).
Saved agents are private to their creator unless `shared`; another org's agents are a 404.  Disabled agents are
hidden from search and listings and cannot be run (parity items 32 and 58).
"""
from __future__ import annotations

import json
import re

from ..db import new_id, now
from ..http import ApiError, Route
from . import catalogue as C
from . import planner

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'prompt',
  steps_json TEXT, prompt_template TEXT NOT NULL DEFAULT '', created_by TEXT, shared INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  builtin INTEGER NOT NULL DEFAULT 0, tags_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT);
CREATE INDEX IF NOT EXISTS agents_org ON agents(org_id);
CREATE TABLE IF NOT EXISTS agent_prefs(org_id TEXT NOT NULL, agent_id TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, changed_by TEXT, changed_at TEXT,
  PRIMARY KEY(org_id, agent_id));
CREATE TABLE IF NOT EXISTS agent_pins(org_id TEXT NOT NULL, user_id TEXT NOT NULL, agent_id TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(org_id, user_id, agent_id));
"""


def _builtin_view(tid: str) -> dict:
    c = C.CATALOGUE[tid]
    return {"id": C.builtin_id(tid), "name": c["name"], "description": c["description"], "tags": list(c["tags"]), "kind": "builtin", "builtin": True, "task_id": tid,
            "inputs": c["inputs"], "steps": [{"fn": s["fn"], "title": s["title"], "engine": s["engine"]} for s in c["steps"]], "outputs": c["outputs"],
            "review_minutes_estimate": c["review_minutes_estimate"], "shared": True, "created_by": None}


def _saved_view(r) -> dict:
    d = {"id": r["id"], "name": r["name"], "description": r["description"], "tags": json.loads(r["tags_json"] or "[]"), "kind": r["kind"], "builtin": False,
         "task_id": None, "shared": bool(r["shared"]), "created_by": r["created_by"], "created_at": r["created_at"], "updated_at": r["updated_at"]}
    if r["kind"] == "chain":
        d["prompts"] = json.loads(r["steps_json"] or "[]")
    else:
        d["prompt"] = r["prompt_template"]
    return d


def _prefs(conn, org_id: str) -> dict[str, bool]:
    return {r[0]: bool(r[1]) for r in conn.execute("SELECT agent_id, enabled FROM agent_prefs WHERE org_id=?", (org_id,)).fetchall()}


def _pins(conn, org_id: str, user_id: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT agent_id FROM agent_pins WHERE org_id=? AND user_id=?", (org_id, user_id)).fetchall()}


def _all(conn, org_id: str, user_id: str) -> list[dict]:
    pref, pins = _prefs(conn, org_id), _pins(conn, org_id, user_id)
    items = [_builtin_view(t) for t in C.CATALOGUE]
    for r in conn.execute("SELECT * FROM agents WHERE org_id=? AND builtin=0 AND (shared=1 OR created_by=?)", (org_id, user_id)).fetchall():
        items.append(_saved_view(r))
    for it in items:
        it["enabled"] = pref.get(it["id"], True)
        it["pinned"] = it["id"] in pins
    return items


def search(items: list[dict], q: str = "", tag: str = "") -> list[dict]:
    """Match every query word against name + description + tags (name hits rank first)."""
    words = [w for w in re.split(r"\W+", (q or "").lower()) if w]
    out = []
    for it in items:
        if tag and tag.lower() not in [t.lower() for t in it["tags"]]:
            continue
        blob = f"{it['name']} {it['description']} {' '.join(it['tags'])}".lower()
        if not all(w in blob for w in words):
            continue
        score = sum(3 for w in words if w in it["name"].lower()) + sum(1 for w in words if w in it["description"].lower())
        out.append((it, score))
    out.sort(key=lambda p: (not p[0]["pinned"], -p[1], p[0]["name"].lower()))
    return [p[0] for p in out]


def resolve(conn, org_id: str, user_id: str, agent_id: str) -> dict:
    """The runnable form of an agent: {id, name, kind, task_id, prompts, review_minutes_estimate}. 404 / 409 with hints."""
    tid = C.task_of_builtin(agent_id)
    pref = _prefs(conn, org_id)
    if tid:
        a = _builtin_view(tid)
    else:
        r = conn.execute("SELECT * FROM agents WHERE id=? AND org_id=?", (agent_id, org_id)).fetchone()
        if r is None or not (r["shared"] or r["created_by"] == user_id):
            raise ApiError(404, "not_found", "No such agent.")
        a = _saved_view(r)
    if not pref.get(agent_id, True):
        raise ApiError(409, "agent_disabled", "An admin has disabled this agent.", "Ask an organization owner to enable it, or pick another agent.")
    out = {"id": agent_id, "name": a["name"], "kind": a["kind"], "task_id": a.get("task_id"), "prompts": None}
    if a["kind"] == "chain":
        out["prompts"] = list(a["prompts"])
    elif a["kind"] == "prompt":
        out["prompts"] = [a["prompt"]]
    return out


def default_prompt(agent: dict, inputs: dict) -> str:
    t = inputs.get("ticker")
    return f"{agent['name']}" + (f" for {t}" if t else "")


def fill(template: str, inputs: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(inputs.get(m.group(1), m.group(0))), template)


# ---------------------------------------------------------------------- routes
def _body(ctx) -> dict:
    b = ctx.json
    if not isinstance(b, dict):
        raise ApiError(400, "bad_body", "The request body must be a JSON object.", "Send JSON such as {\"name\": \"...\", \"prompt\": \"...\"}.")
    return b


def _visible(ctx, agent_id: str) -> dict:
    for it in _all(ctx.conn, ctx.org_id, ctx.user["id"]):
        if it["id"] == agent_id:
            return it
    raise ApiError(404, "not_found", "No such agent.")


def _list(ctx):
    items = _all(ctx.conn, ctx.org_id, ctx.user["id"])
    admin = ctx.query.get("include_disabled") in ("1", "true") and ctx.role == "owner"
    if not admin:
        items = [i for i in items if i["enabled"]]
    items = search(items, ctx.query.get("q", ""), ctx.query.get("tag", ""))
    return {"items": items, "next_cursor": None, "total": len(items)}


def _get(ctx):
    it = _visible(ctx, ctx.params["agent_id"])
    if not it["enabled"] and ctx.role != "owner":
        raise ApiError(404, "not_found", "No such agent.")
    return {"agent": it}


def _validate_agent(b: dict, partial: bool = False) -> dict:
    out: dict = {}
    if "name" in b or not partial:
        n = str(b.get("name", "")).strip()
        if not 1 <= len(n) <= 80:
            raise ApiError(400, "bad_name", "An agent needs a name of 1 to 80 characters.", "Give the agent a short descriptive name.")
        out["name"] = n
    if "description" in b:
        d = str(b.get("description") or "")
        if len(d) > 500:
            raise ApiError(400, "bad_description", "The description is longer than 500 characters.", "Shorten it.")
        out["description"] = d
    if "tags" in b:
        t = b["tags"]
        if not isinstance(t, list) or len(t) > 10 or not all(isinstance(x, str) and 0 < len(x) <= 30 for x in t):
            raise ApiError(400, "bad_tags", "Tags must be up to 10 short strings.", "Send tags like [\"valuation\", \"excel\"].")
        out["tags"] = t
    kind = b.get("kind") or ("chain" if "prompts" in b and b.get("prompts") is not None else "prompt")
    if kind not in ("prompt", "chain"):
        raise ApiError(400, "bad_kind", "Saved agents are 'prompt' or 'chain'.", "Send kind: 'prompt' with a prompt, or kind: 'chain' with prompts.")
    if not partial or "prompt" in b or "prompts" in b or "kind" in b:
        if kind == "chain":
            ps = b.get("prompts")
            if not isinstance(ps, list) or not 1 <= len(ps) <= 8 or not all(isinstance(p, str) and 0 < len(p.strip()) <= 2000 for p in ps):
                raise ApiError(400, "bad_chain", "A chain needs 1 to 8 prompts of up to 2,000 characters.", "Send prompts: [\"Comps for Apple\", \"DCF for Apple\"].")
            check = [p.strip() for p in ps]
        else:
            p = b.get("prompt")
            if not isinstance(p, str) or not p.strip() or len(p) > 2000:
                raise ApiError(400, "bad_prompt", "A prompt agent needs a prompt of up to 2,000 characters.", "Send prompt: \"DCF for {ticker}\".")
            check = [p.strip()]
        for p in check:                                        # every prompt must be plannable by the rules (placeholders allowed)
            probe = re.sub(r"\{\w+\}", "AAPL", p)
            try:
                planner.plan_prompt(probe)
            except planner.PlanError as e:
                raise ApiError(400, "unplannable_prompt", f"The prompt '{p[:60]}' does not map to a task. {e.message}", e.hint) from None
        out["kind"] = kind
        out["prompts"], out["prompt"] = (check if kind == "chain" else None), (check[0] if kind == "prompt" else "")
    if "shared" in b:
        out["shared"] = 1 if b["shared"] else 0
    return out


def _create(ctx):
    ctx.require("member")
    v = _validate_agent(_body(ctx))
    aid = new_id("agt")
    ctx.conn.execute("INSERT INTO agents(id, org_id, name, description, kind, steps_json, prompt_template, created_by, shared, created_at, builtin, tags_json, updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?)",
                     (aid, ctx.org_id, v["name"], v.get("description", ""), v["kind"], json.dumps(v["prompts"]) if v["kind"] == "chain" else None, v.get("prompt", ""),
                      ctx.user["id"], v.get("shared", 0), now(), json.dumps(v.get("tags", [])), now()))
    ctx.audit("agent.create", aid, {"name": v["name"], "shared": bool(v.get("shared"))})
    return 201, {"agent": _visible(ctx, aid)}


def _own(ctx, agent_id: str):
    if C.task_of_builtin(agent_id):
        raise ApiError(403, "builtin_read_only", "Built-in agents are read-only.", "Create your own agent from the same prompt, or ask an owner to disable this one.")
    r = ctx.conn.execute("SELECT * FROM agents WHERE id=? AND org_id=?", (agent_id, ctx.org_id)).fetchone()
    if r is None or not (r["shared"] or r["created_by"] == ctx.user["id"]):
        raise ApiError(404, "not_found", "No such agent.")
    if r["created_by"] != ctx.user["id"] and ctx.role != "owner":
        raise ApiError(403, "not_yours", "Only the agent's creator or an organization owner can change it.", "Ask the creator, or an owner.")
    return r


def _patch(ctx):
    ctx.require("member")
    aid = ctx.params["agent_id"]
    r = _own(ctx, aid)
    b = _body(ctx)
    cur = _saved_view(r)
    merged = {**{"name": cur["name"], "description": cur["description"], "tags": cur["tags"], "shared": cur["shared"], "kind": cur["kind"],
                 "prompt": cur.get("prompt"), "prompts": cur.get("prompts")}, **b}
    v = _validate_agent(merged)
    ctx.conn.execute("UPDATE agents SET name=?, description=?, kind=?, steps_json=?, prompt_template=?, shared=?, tags_json=?, updated_at=? WHERE id=? AND org_id=?",
                     (v["name"], v.get("description", ""), v["kind"], json.dumps(v["prompts"]) if v["kind"] == "chain" else None, v.get("prompt", ""),
                      v.get("shared", int(cur["shared"])), json.dumps(v.get("tags", cur["tags"])), now(), aid, ctx.org_id))
    ctx.audit("agent.update", aid, {"fields": sorted(b)})
    return {"agent": _visible(ctx, aid)}


def _delete(ctx):
    ctx.require("member")
    aid = ctx.params["agent_id"]
    _own(ctx, aid)
    ctx.conn.execute("DELETE FROM agents WHERE id=? AND org_id=?", (aid, ctx.org_id))
    ctx.conn.execute("DELETE FROM agent_pins WHERE org_id=? AND agent_id=?", (ctx.org_id, aid))
    ctx.audit("agent.delete", aid)
    return {"ok": True}


def _run(ctx):
    ctx.require("member")
    from .. import jobs
    aid = ctx.params["agent_id"]
    _visible(ctx, aid)
    b = ctx.json if isinstance(ctx.json, dict) else {}
    ins = b.get("inputs") or {}
    if not isinstance(ins, dict):
        raise ApiError(400, "bad_inputs", "inputs must be an object.", "Send inputs like {\"ticker\": \"AAPL\"}.")
    job = jobs.svc().submit(ctx.org_id, ctx.user["id"], b.get("prompt", ""), b.get("deal_id"), aid, ins)
    return 201, {"job": job}


def _pin(ctx):
    aid = ctx.params["agent_id"]
    _visible(ctx, aid)
    want = (ctx.json or {}).get("pinned", True) if isinstance(ctx.json, dict) else True
    if want:
        ctx.conn.execute("INSERT OR IGNORE INTO agent_pins(org_id, user_id, agent_id, created_at) VALUES(?,?,?,?)", (ctx.org_id, ctx.user["id"], aid, now()))
    else:
        ctx.conn.execute("DELETE FROM agent_pins WHERE org_id=? AND user_id=? AND agent_id=?", (ctx.org_id, ctx.user["id"], aid))
    return {"agent": _visible(ctx, aid)}


def _enabled(ctx):
    ctx.require("owner")
    aid = ctx.params["agent_id"]
    _visible(ctx, aid)
    b = _body(ctx)
    if not isinstance(b.get("enabled"), bool):
        raise ApiError(400, "bad_enabled", "Send enabled as true or false.", "Send {\"enabled\": false} to disable the agent for the whole organization.")
    ctx.conn.execute("INSERT INTO agent_prefs(org_id, agent_id, enabled, changed_by, changed_at) VALUES(?,?,?,?,?) "
                     "ON CONFLICT(org_id, agent_id) DO UPDATE SET enabled=excluded.enabled, changed_by=excluded.changed_by, changed_at=excluded.changed_at",
                     (ctx.org_id, aid, 1 if b["enabled"] else 0, ctx.user["id"], now()))
    ctx.audit("agent.enabled", aid, {"enabled": b["enabled"]})
    return {"agent": _visible(ctx, aid)}


ROUTES = [
    Route("GET", "/api/v1/agents", _list, role="viewer"),
    Route("POST", "/api/v1/agents", _create, role="member"),
    Route("GET", "/api/v1/agents/{agent_id}", _get, role="viewer"),
    Route("PATCH", "/api/v1/agents/{agent_id}", _patch, role="member"),
    Route("DELETE", "/api/v1/agents/{agent_id}", _delete, role="member"),
    Route("POST", "/api/v1/agents/{agent_id}/run", _run, role="member"),
    Route("POST", "/api/v1/agents/{agent_id}/pin", _pin, role="viewer"),
    Route("POST", "/api/v1/agents/{agent_id}/enabled", _enabled, role="owner"),
]
