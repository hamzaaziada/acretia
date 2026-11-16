# SCIM 2.0 and connector ACLs (S6.5b, parity items 59 and 62)

Libraries: `src/harness/admin/scim.py`, `src/harness/connectors/acl.py`. No HTTP here; the product app maps requests onto these calls.

## SCIM service (item 59)

`ScimService(db_conn, org_id)` (sqlite3-style connection; creates its `scim_*` tables). One instance per request, per org.

Auth, before anything else: `verify_scim_token(conn, org_id, bearer) -> bool`. Only a SHA-256 hash is stored; compared with `hmac.compare_digest`. `issue_scim_token(conn, org_id)` returns the raw token once; `revoke_scim_tokens`. On False answer 401.

| HTTP | Call | Success |
|---|---|---|
| POST /Users | `create_user(body)` | 201 + User |
| GET /Users/{id} | `get_user(id)` | 200 |
| GET /Users?filter=&startIndex=&count= | `list_users(filter, start_index, count)` | 200 ListResponse |
| PUT /Users/{id} | `replace_user(id, body, if_match=None)` | 200 |
| PATCH /Users/{id} | `patch_user(id, body, if_match=None)` | 200 |
| DELETE /Users/{id} | `delete_user(id)` | 204 |
| POST /Groups, GET /Groups[/{id}], PATCH, DELETE | `create_group`, `list_groups`, `get_group`, `patch_group`, `delete_group` | as above |

- Filters: `userName eq "x"` (case-insensitive), `active eq true|false`, joined with `and`. Anything else is 400 `invalidFilter`. `count` is capped at 200, `startIndex` is 1-based.
- PatchOp: `add` / `replace` / `remove`, paths `active`, `userName`, `displayName`, `externalId`, `emails`, `name.*`; a path-less op with an object value (Okta style); string `"False"` (Azure AD) accepted. Group paths: `members`, `members[value eq "id"]`, `displayName`.
- Unknown schemas or attributes are 400 `invalidValue`; body over 256 KiB is 413.
- User resource: `{schemas, id, userName, active, name, emails, displayName, externalId, groups, meta{resourceType, created, lastModified, version: W/"n", location}}`. Send `meta.version` as the `ETag` header; map `If-Match` to `if_match` (mismatch gives 412).
- Errors: raise `ScimError`; respond with `e.status` and body `e.to_json()` (`{schemas:[...Error], status, detail, scimType}`). 400 invalidFilter/invalidValue/invalidPath, 404, 409 uniqueness, 412, 413.
- Cross-org: every query is scoped by `org_id`; another org's id is 404.

### Deprovisioning

`active=false` (PUT, PATCH, Okta/Azure forms) and DELETE run, in one transaction:
1. `svc.on_deprovision` hooks `(org_id, user_id)` (sessions). Default hook writes a `scim_revocations` row, kind `session`.
2. `svc.on_disable_schedules` (kind `schedules`) and `svc.on_disable_tokens` (kind `api_tokens`).
3. An audit row (`svc.audit_rows()`).

Append real hooks that revoke in the session store, scheduler and token table (they may use `svc.conn` to stay in the transaction). A hook that raises rolls everything back: the user stays active and the IdP retries. Re-deactivating an inactive user does not re-fire hooks. `svc.is_active(user_id)` is the single check for "may this user act".

`svc.change_listeners` (`fn(org_id, user_id|None)`) fire after commit on any activation change, delete or group change; `None` means the whole org.

## ACL model (item 62)

`ItemACL(source, item_id, readers_users, readers_groups, public_in_org, inherited_from, unknown)`. Capture at sync time and store beside the ingested item; store the output of the parsers (never raw tokens).

| Connector | Parser | Input (documented API shape) |
|---|---|---|
| SharePoint / OneDrive | `parse_sharepoint(source, item_id, graph_permissions, allow_anonymous_as_org_public=False)` | Graph `.../permissions` (`grantedToV2`, `grantedToIdentitiesV2`, `link.scope`, `inheritedFrom`) |
| Box | `parse_box(source, item_id, collaborations, owner=, shared_link=, allow_anonymous_as_org_public=)` | `/files/{id}/collaborations`; pending and `uploader` roles grant nothing |
| Dropbox | `parse_dropbox(source, item_id, members, shared_links=, allow_anonymous_as_org_public=)` | `sharing/list_file_members`; invitees grant nothing |
| Synced folder | `parse_posix(source, item_id, {uid,gid,mode}, user_map, group_map=)` | POSIX stat; unmapped uid/gid grants nobody |

An anonymous/"open" link is org-public only when the org setting `allow_anonymous_as_org_public` is true; otherwise it grants nothing. Org-scope links (`organization`, Box `company`, Dropbox `team_only`) are org-public. A missing or unparsable permissions payload gives `unknown=True`, which is denied to everyone. `inherit(child, parent)` copies a parent's ACL onto a child with none.

## How search must call it

Every retrieval path (om/search.py results, the grid's source lookups, Ask retrieval and citations) must filter hits before they leave the server, and before snippets reach a model prompt:

```python
from src.harness.connectors.acl import AclAuthorizer, AclCache, GroupMap

# once per process/org
auth = AclAuthorizer(scim_service, acl_lookup=load_item_acl, cache=AclCache(ttl=300), group_map=GroupMap(table))
# per request, with the authenticated user's SCIM id
hits = auth.filter(user_id, hits)          # each hit needs "source" and "item_id" (or pass key=)
```

- `acl_lookup(source, item_id) -> ItemACL | None` reads the stored ACL; `None` means deny.
- Pure variant for tests: `filter_results(results, user_identity, groups, acl_lookup)`; default deny.
- Group membership = SCIM groups (id and display name) plus `GroupMap` (connector group id to SCIM group), so an ACL naming a Box/SharePoint group matches.
- Filter first, then rank or truncate to top-k, or a page of hits can come back short or leak counts. Never report totals from the unfiltered set.
- Citations and "open source" links re-check with `auth.can_read(user_id, source, item_id)`.
- Cache: ACL lookups and principals live for the TTL. SCIM changes invalidate immediately through `change_listeners` (registered by `AclAuthorizer`), so deprovisioning drops access on the next call even with a warm cache. After an ACL re-sync call `cache.invalidate_acls(org_id, source)`.
- Items with no connector ACL (uploaded directly) must be given an explicit `ItemACL` at ingest (for example uploader plus org-public), or they are invisible by default.
