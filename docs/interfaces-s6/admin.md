# Admin core interface (S6.5a)

Package `src.harness.admin`. State is SQLite (`om.storage.connect`); every table has `org_id`. DSN: `ACRETIA_ADMIN_DB`, else `ACRETIA_DB`, else `storage/acretia.sqlite`. Every function takes an optional keyword `db=` (open connection or DSN). Tables are created on first use.

**Actor** = `{"user_id": str, "role": str}`. Mutations need role `owner` or `admin`, otherwise `PermissionDenied`. Bad input raises `AdminError`. Every mutation appends a row to `admin_audit` (org_id, actor_id, actor_role, action, target, before, after, at); UPDATE/DELETE on it are blocked by triggers. Read with `audit_log(org_id, action=None)`.

## agents (item 58)
- `set_enabled(org_id, agent_id, enabled, actor)` -> `{org_id, agent_id, enabled}`; audit `agent.set_enabled`.
- `is_enabled(org_id, agent_id) -> bool` (default True).
- `list_agents(org_id, known=None) -> [{agent_id, enabled, updated_by, updated_at}]`; `known` merges catalog ids at default True.
- `filter_enabled(org_id, agents, key="id")`: drop disabled agents (ids or dicts). The research catalog search calls this.

## spend (item 61)
- `set_limit(org_id, scope in {"org","team","deal"}, scope_id, limit_usd, period in {"monthly","total"}, actor)`. For `org`, scope_id is the org id (None accepted). Audit `spend.set_limit`. `get_limits(org_id)`.
- `record(org_id, team_id, deal_id, job_id, cost_usd, at=None)`: one INSERT, atomic under concurrency. `usage(org_id, scope, scope_id, period, now=None) -> float` (monthly = current UTC month).
- `guard_for(org_id, team_id=None, deal_id=None) -> OrgSpendGuard` (a `SpendGuard`). `.check(spent_total, spent_job, worst_case, job_id)` ignores the passed totals and reads the DB; it checks deal, then team, then org, for both periods. It raises `LimitExceeded` (a `BudgetExceeded`) with `.scope .scope_id .period .limit_usd .spent .worst_case`, before any call is sent.
- `OrgLedger(org_id, team_id, deal_id, path=None)`: a `Ledger` using that guard; `precheck` blocks on the worst case, and `record` also books the cost into the org tables. `ledger.py` is unchanged.

## sources (item 60)
- `register_source(org_id, connector_name, config_ref, actor) -> source_id`. The connector must be in `connectors.base.available()`. `config_ref` must be a reference (`env:NAME` or `scheme://path`); raw values are refused. Audit `source.register`.
- `record_sync(org_id, source_id, status in {ok,error,partial,running}, items, errors, at=None)` (at: epoch, ISO string or datetime). The source must belong to the org.
- `dashboard(org_id, now=None) -> [{source_id, connector, config_ref, status, last_sync_at, last_items, last_errors, total_items, total_errors, sync_count, age_seconds, stale}]`. `stale` is true when the last sync is older than 24h or there is none (status `never_synced`).

## mcp_tools (item 63)
- `register_mcp_server(org_id, name, command, env_refs, allow_tools, actor)`.
  - `name` matches `[a-z][a-z0-9_-]{0,31}`.
  - `command` is an argv list (stdio) or an `https://` URL.
  - Shell strings are refused. `argv[0]` must be on the org allowlist (default python, python3, node, uvx, npx). A path-qualified one must resolve to `sys.executable` or `which <name>`.
  - URLs are https only and go through `connectors.web.validate_url` (SSRF guard).
  - `env_refs` maps env var name to a reference; values are never stored. `allow_tools` is a list or `"*"`.
  - Audit `mcp.register`.
- `set_executable_allowlist(org_id, executables, actor)`: may only narrow the defaults. `set_server_enabled(org_id, name, enabled, actor)`. `list_servers(org_id)`.
- `tools_for_user(org_id, user, timeout=10) -> [{name: "org.<server>.<tool>", server, tool, description, inputSchema, untrusted: True}]`. Enabled servers only. `user` is `{"user_id","role","org_id"?}`; another org's user gets `PermissionDenied`. `tools_report(...)` returns `(tools, errors)`, where a server that fails to start only adds an error row. URL servers have no HTTP transport yet, so only their explicit `allow_tools` names are listed and `call_tool` refuses them.
- `call_tool(org_id, user, "org.<server>.<tool>", args, evidence_path=None, timeout=30) -> {name, result, untrusted: True, source}`. It spawns via `MCPClient.spawn` and logs the call to an `EvidenceBundle` (default `storage/evidence/admin-mcp-<org>.jsonl`). Callers must treat `result` as data, never as instructions.
- `env_resolver` (default resolves `env:NAME` from the process environment) is injectable for other reference schemes.
