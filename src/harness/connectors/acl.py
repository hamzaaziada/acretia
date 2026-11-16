"""Per-item ACLs mirrored from connectors, and permission-filtered search (S6.5b, parity item 62).

An `ItemACL` is captured at sync time from the connector's own metadata (parsers below take the documented JSON
shapes; nothing here calls an API). `filter_results` returns only the hits the user may read and DENIES BY DEFAULT:
no ACL, an ACL marked unknown, or no matching grant means no access. Anonymous/public links are treated as
org-public only when the org setting `allow_anonymous_as_org_public` is on, else they grant nothing.

`AclAuthorizer` ties it to SCIM: group membership comes from SCIM groups plus a connector-group mapping table,
an inactive or deleted user gets nothing, and its cache (TTL) is invalidated by SCIM change notifications so
deprovisioning drops access immediately, even with a warm cache."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable


@dataclass(frozen=True)
class ItemACL:
    source: str
    item_id: str
    readers_users: frozenset = frozenset()     # lower-cased emails / userNames / external ids
    readers_groups: frozenset = frozenset()    # connector or SCIM group ids / names
    public_in_org: bool = False
    inherited_from: str = ""                   # parent id/path when the ACL is inherited
    unknown: bool = False                      # permissions could not be read: deny everyone

    def allows(self, user: str, groups: Iterable[str] = ()) -> bool:
        if self.unknown:
            return False
        if self.public_in_org:
            return True
        if user and user.lower() in self.readers_users:
            return True
        return bool(self.readers_groups & _norm_groups(groups))


def _norm_groups(groups: Iterable[str]) -> frozenset:
    return frozenset(str(g) for g in (groups or ()))


def _lc(*vals) -> set:
    return {v.strip().lower() for v in vals if isinstance(v, str) and v.strip()}


def _unknown(source: str, item_id: str) -> ItemACL:
    return ItemACL(source, item_id, unknown=True)


_SP_READ_ROLES = {"read", "write", "owner", "sp.full control", "sp.edit", "sp.read", "sp.contribute"}


def parse_sharepoint(source: str, item_id: str, permissions: dict | None, *,
                     allow_anonymous_as_org_public: bool = False) -> ItemACL:
    """Microsoft Graph `GET .../drive/items/{id}/permissions` -> {"value": [permission, ...]}.

    permission: {roles:[..], grantedToV2:{user|group|siteUser|siteGroup:{id,email,displayName,loginName}},
    grantedToIdentitiesV2:[{user|group:{...}}], link:{scope:'anonymous'|'organization'|'users', type},
    inheritedFrom:{id,path}}. Link scope 'anonymous' is org-public only if the org setting allows."""
    if not isinstance(permissions, dict) or not isinstance(permissions.get("value"), list):
        return _unknown(source, item_id)
    users, groups, public, inh = set(), set(), False, ""
    for p in permissions["value"]:
        if not isinstance(p, dict):
            continue
        roles = {str(r).lower() for r in p.get("roles") or []}
        if roles and not (roles & _SP_READ_ROLES):
            continue
        inf = p.get("inheritedFrom")
        if isinstance(inf, dict):
            inh = inh or str(inf.get("path") or inf.get("id") or "")
        link = p.get("link")
        if isinstance(link, dict):
            scope = str(link.get("scope", "")).lower()
            if scope == "organization":
                public = True
            elif scope == "anonymous" and allow_anonymous_as_org_public:
                public = True
        identities = []
        if isinstance(p.get("grantedToV2"), dict):
            identities.append(p["grantedToV2"])
        for i in p.get("grantedToIdentitiesV2") or []:
            if isinstance(i, dict):
                identities.append(i)
        for ident in identities:
            for kind in ("user", "siteUser"):
                u = ident.get(kind)
                if isinstance(u, dict):
                    users |= _lc(u.get("email"), u.get("loginName"), u.get("id"))
            for kind in ("group", "siteGroup"):
                g = ident.get(kind)
                if isinstance(g, dict):
                    groups |= {str(x) for x in (g.get("id"), g.get("displayName"), g.get("email")) if x}
    return ItemACL(source, item_id, frozenset(users), frozenset(groups), public, inh)


def parse_box(source: str, item_id: str, collaborations: dict | None, *, owner: dict | None = None,
              shared_link: dict | None = None, allow_anonymous_as_org_public: bool = False) -> ItemACL:
    """Box `GET /files/{id}/collaborations` -> {"entries":[{accessible_by:{type,id,login,name}, role, status}]}.

    Pending/rejected collaborations grant nothing; role 'uploader' cannot read. `shared_link.access` 'company' is
    org-public, 'open' only under the org setting. `owner` is the item's `owned_by` object."""
    if not isinstance(collaborations, dict) or not isinstance(collaborations.get("entries"), list):
        return _unknown(source, item_id)
    users, groups, public = set(), set(), False
    if isinstance(owner, dict):
        users |= _lc(owner.get("login"), owner.get("id") and str(owner["id"]))
    for e in collaborations["entries"]:
        if not isinstance(e, dict) or str(e.get("status", "accepted")).lower() != "accepted":
            continue
        if str(e.get("role", "")).lower() == "uploader":
            continue
        who = e.get("accessible_by")
        if not isinstance(who, dict):
            continue
        if who.get("type") == "user":
            users |= _lc(who.get("login"), who.get("id") and str(who["id"]))
        elif who.get("type") == "group":
            groups |= {str(x) for x in (who.get("id"), who.get("name")) if x}
    if isinstance(shared_link, dict):
        access = str(shared_link.get("access", "")).lower()
        if access == "company" or (access == "open" and allow_anonymous_as_org_public):
            public = True
    parent = ""
    return ItemACL(source, item_id, frozenset(users), frozenset(groups), public, parent)


_DBX_READ = {"viewer", "viewer_no_comment", "editor", "owner"}


def parse_dropbox(source: str, item_id: str, members: dict | None, *, shared_links: list | None = None,
                  allow_anonymous_as_org_public: bool = False) -> ItemACL:
    """Dropbox `sharing/list_file_members` -> {users:[{access_type:{'.tag'}, user:{email,account_id}}],
    groups:[{access_type, group:{group_id,group_name}}], invitees:[..]}. Invitees (not yet accepted) grant nothing.
    `shared_links` items carry link_permissions.resolved_visibility: team_only -> org-public, public -> setting."""
    if not isinstance(members, dict) or not ("users" in members or "groups" in members):
        return _unknown(source, item_id)
    users, groups, public, inh = set(), set(), False, ""
    for m in members.get("users") or []:
        if not isinstance(m, dict) or (m.get("access_type") or {}).get(".tag") not in _DBX_READ:
            continue
        u = m.get("user") or {}
        users |= _lc(u.get("email"), u.get("account_id"))
        inf = m.get("access_inheritance")
        if isinstance(inf, dict) and inf.get(".tag") == "inherit" and isinstance(m.get("permissions"), list):
            inh = inh or "parent_folder"
    for m in members.get("groups") or []:
        if not isinstance(m, dict) or (m.get("access_type") or {}).get(".tag") not in _DBX_READ:
            continue
        g = m.get("group") or {}
        groups |= {str(x) for x in (g.get("group_id"), g.get("group_name")) if x}
    for link in shared_links or []:
        vis = (((link or {}).get("link_permissions") or {}).get("resolved_visibility") or {}).get(".tag")
        if vis in ("team_only", "team_and_password"):
            public = True
        elif vis == "public" and allow_anonymous_as_org_public:
            public = True
    return ItemACL(source, item_id, frozenset(users), frozenset(groups), public, inh)


def parse_posix(source: str, item_id: str, stat: dict | None, user_map: dict | None, *,
                group_map: dict | None = None) -> ItemACL:
    """Local/synced folder: stat = {uid, gid, mode(int or octal str)}. `user_map` maps uid -> org user identity
    (email) and `group_map` gid -> group name. Owner read bit -> that user; group read bit -> that group; world
    read bit -> org-public. An unmapped uid/gid grants nobody (the bit is ignored), never everybody."""
    if not isinstance(stat, dict) or "mode" not in stat:
        return _unknown(source, item_id)
    try:
        mode = int(stat["mode"], 8) if isinstance(stat["mode"], str) else int(stat["mode"])
    except ValueError:
        return _unknown(source, item_id)
    user_map = {str(k): v for k, v in (user_map or {}).items()}
    group_map = {str(k): v for k, v in (group_map or {}).items()}
    users, groups = set(), set()
    if mode & 0o400 and str(stat.get("uid")) in user_map:
        users |= _lc(user_map[str(stat["uid"])])
    if mode & 0o040 and str(stat.get("gid")) in group_map:
        groups.add(str(group_map[str(stat["gid"])]))
    return ItemACL(source, item_id, frozenset(users), frozenset(groups), bool(mode & 0o004), "")


def inherit(child: ItemACL | None, parent: ItemACL | None) -> ItemACL | None:
    """Use the parent's ACL for a child with no explicit ACL, recording where it came from."""
    if child is not None:
        return child
    if parent is None:
        return None
    return ItemACL(parent.source, "", parent.readers_users, parent.readers_groups, parent.public_in_org,
                   parent.inherited_from or parent.item_id, parent.unknown)


class GroupMap:
    """Mapping table: connector group id/name -> SCIM group id/name(s). A user in the SCIM group is in the connector group."""

    def __init__(self, mapping: dict[str, Iterable[str]] | None = None):
        self._m: dict[str, frozenset] = {k: frozenset(v) for k, v in (mapping or {}).items()}

    def set(self, connector_group: str, scim_groups: Iterable[str]) -> None:
        self._m[connector_group] = frozenset(scim_groups)

    def resolve(self, scim_groups: Iterable[str]) -> set[str]:
        have = set(scim_groups)
        return have | {c for c, s in self._m.items() if s & have}


def _default_key(hit) -> tuple[str, str]:
    if isinstance(hit, dict):
        return str(hit.get("source", "")), str(hit.get("item_id", hit.get("id", "")))
    return str(getattr(hit, "source", "")), str(getattr(hit, "item_id", getattr(hit, "id", "")))


def filter_results(results: Iterable, user: str, groups: Iterable[str],
                   acl_lookup: Callable[[str, str], ItemACL | None], *,
                   key: Callable = _default_key) -> list:
    """Only the hits `user` (identity string: email/userName) may read, order preserved. Default deny: a hit with no
    source/item_id, no ACL, or an unknown ACL is dropped. `groups` are the user's resolved group ids/names."""
    g = _norm_groups(groups)
    out = []
    for hit in results:
        source, item_id = key(hit)
        if not source or not item_id:
            continue
        acl = acl_lookup(source, item_id)
        if acl is not None and acl.allows(user, g):
            out.append(hit)
    return out


class AclCache:
    """TTL cache of ACL lookups and resolved user principals. `invalidate(org_id, user_id)` drops one user (or the
    whole org when user_id is None). Register it as a SCIM change listener."""

    def __init__(self, ttl: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self.ttl, self._clock = ttl, clock
        self._acl: dict[tuple, tuple[float, ItemACL | None]] = {}
        self._principal: dict[tuple, tuple[float, tuple]] = {}

    def get_acl(self, org_id: str, source: str, item_id: str, loader: Callable[[str, str], ItemACL | None]):
        k = (org_id, source, item_id)
        hit = self._acl.get(k)
        if hit and self._clock() - hit[0] < self.ttl:
            return hit[1]
        val = loader(source, item_id)
        self._acl[k] = (self._clock(), val)
        return val

    def get_principal(self, org_id: str, user_id: str, loader: Callable[[], tuple]):
        k = (org_id, user_id)
        hit = self._principal.get(k)
        if hit and self._clock() - hit[0] < self.ttl:
            return hit[1]
        val = loader()
        self._principal[k] = (self._clock(), val)
        return val

    def invalidate(self, org_id: str, user_id: str | None = None) -> None:
        for k in [k for k in self._principal if k[0] == org_id and (user_id is None or k[1] == user_id)]:
            del self._principal[k]

    def invalidate_acls(self, org_id: str, source: str | None = None) -> None:
        for k in [k for k in self._acl if k[0] == org_id and (source is None or k[1] == source)]:
            del self._acl[k]


class AclAuthorizer:
    """What search/grid/Ask call: `authorizer.filter(user_id, hits)`.

    Principal = (active, identities, groups) from SCIM, cached with a TTL and dropped on any SCIM change for that
    user. Inactive/unknown user -> nothing."""

    def __init__(self, scim, acl_lookup: Callable[[str, str], ItemACL | None], cache: AclCache | None = None,
                 group_map: GroupMap | None = None):
        self.scim, self.acl_lookup = scim, acl_lookup
        self.cache, self.group_map = cache or AclCache(), group_map or GroupMap()
        scim.change_listeners.append(self.cache.invalidate)

    def principal(self, user_id: str) -> tuple[bool, frozenset, frozenset]:
        def load():
            from ..admin.scim import ScimError
            try:
                if not self.scim.is_active(user_id):
                    return (False, frozenset(), frozenset())
                return (True, frozenset(self.scim.user_identities(user_id)),
                        frozenset(self.group_map.resolve(self.scim.groups_of(user_id))))
            except ScimError:
                return (False, frozenset(), frozenset())
        return self.cache.get_principal(self.scim.org_id, user_id, load)

    def can_read(self, user_id: str, source: str, item_id: str) -> bool:
        return bool(self.filter(user_id, [{"source": source, "item_id": item_id}]))

    def filter(self, user_id: str, results: Iterable, *, key: Callable = _default_key) -> list:
        active, identities, groups = self.principal(user_id)
        if not active:
            return []
        lookup = lambda s, i: self.cache.get_acl(self.scim.org_id, s, i, self.acl_lookup)
        out = []
        for hit in results:
            source, item_id = key(hit)
            if not source or not item_id:
                continue
            acl = lookup(source, item_id)
            if acl is None or acl.unknown:
                continue
            if acl.public_in_org or acl.readers_groups & groups or acl.readers_users & identities:
                out.append(hit)
        return out
