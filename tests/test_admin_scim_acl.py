import sqlite3
import unittest
from unittest import mock

from src.harness.admin import scim as S
from src.harness.admin.scim import ScimError, ScimService, USER_SCHEMA, GROUP_SCHEMA, PATCH_SCHEMA
from src.harness.connectors import acl as A


def user(name, **kw):
    return {"schemas": [USER_SCHEMA], "userName": name, **kw}


def patch(*ops):
    return {"schemas": [PATCH_SCHEMA], "Operations": list(ops)}


class Base(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.svc = ScimService(self.db, "org1")
        self.addCleanup(self.db.close)


class TestScimCrud(Base):
    def test_create_get_shape(self):
        u = self.svc.create_user(user("alice@x.com", emails=[{"value": "alice@x.com", "primary": True}]))
        self.assertEqual(u["schemas"], [USER_SCHEMA])
        self.assertTrue(u["id"] and u["active"])
        self.assertEqual(u["meta"]["resourceType"], "User")
        self.assertEqual(u["meta"]["version"], 'W/"1"')
        self.assertEqual(self.svc.get_user(u["id"])["userName"], "alice@x.com")

    def test_uniqueness_409_case_insensitive(self):
        self.svc.create_user(user("alice@x.com"))
        with self.assertRaises(ScimError) as c:
            self.svc.create_user(user("ALICE@x.com"))
        self.assertEqual(c.exception.status, 409)
        self.assertEqual(c.exception.to_json()["scimType"], "uniqueness")

    def test_404(self):
        with self.assertRaises(ScimError) as c:
            self.svc.get_user("nope")
        self.assertEqual(c.exception.status, 404)
        self.assertIn(S.ERROR_SCHEMA, c.exception.to_json()["schemas"])

    def test_validation(self):
        bad = [
            {"schemas": ["urn:evil"], "userName": "a"},
            {"schemas": [USER_SCHEMA]},
            {"schemas": [USER_SCHEMA], "userName": "a", "bogus": 1},
            {"schemas": [USER_SCHEMA], "userName": "a b"},
            {"schemas": [USER_SCHEMA], "userName": "a", "active": "yes"},
            {"schemas": [USER_SCHEMA], "userName": "a", "emails": [{"value": "nope"}]},
            "string",
        ]
        for b in bad:
            with self.assertRaises(ScimError) as c:
                self.svc.create_user(b)
            self.assertEqual(c.exception.status, 400, b)

    def test_payload_limit(self):
        with self.assertRaises(ScimError) as c:
            self.svc.create_user(user("a", displayName="x" * (S.MAX_PAYLOAD_BYTES + 10)))
        self.assertEqual(c.exception.status, 413)

    def test_filters_and_pagination(self):
        ids = [self.svc.create_user(user(f"u{i:02d}@x.com"))["id"] for i in range(25)]
        self.svc.patch_user(ids[0], patch({"op": "replace", "path": "active", "value": False}))
        r = self.svc.list_users('userName eq "U03@x.com"')
        self.assertEqual(r["totalResults"], 1)
        self.assertEqual(r["Resources"][0]["userName"], "u03@x.com")
        self.assertEqual(self.svc.list_users("active eq true")["totalResults"], 24)
        self.assertEqual(self.svc.list_users("active eq false")["totalResults"], 1)
        p1 = self.svc.list_users(start_index=1, count=10)
        p3 = self.svc.list_users(start_index=21, count=10)
        self.assertEqual((p1["totalResults"], p1["itemsPerPage"], p3["itemsPerPage"]), (25, 10, 5))
        seen = [x["id"] for x in p1["Resources"]] + [x["id"] for x in self.svc.list_users(start_index=11, count=10)["Resources"]] \
            + [x["id"] for x in p3["Resources"]]
        self.assertEqual(sorted(seen), sorted(ids))
        self.assertEqual(self.svc.list_users(count=0)["Resources"], [])
        self.assertEqual(self.svc.list_users('userName eq "a" and active eq true')["totalResults"], 0)

    def test_invalid_filter_400(self):
        for f in ('displayName co "x"', 'userName eq x', 'active eq "true"', "garbage", 'userName sw "a"'):
            with self.assertRaises(ScimError) as c:
                self.svc.list_users(f)
            self.assertEqual((c.exception.status, c.exception.scim_type), (400, "invalidFilter"), f)

    def test_replace_and_etag(self):
        u = self.svc.create_user(user("a@x.com"))
        r = self.svc.replace_user(u["id"], user("a2@x.com", displayName="A"))
        self.assertEqual((r["userName"], r["displayName"], r["meta"]["version"]), ("a2@x.com", "A", 'W/"2"'))
        with self.assertRaises(ScimError) as c:
            self.svc.replace_user(u["id"], user("a3@x.com"), if_match='W/"1"')
        self.assertEqual(c.exception.status, 412)
        other = self.svc.create_user(user("b@x.com"))
        with self.assertRaises(ScimError) as c:
            self.svc.replace_user(other["id"], user("a2@x.com"))
        self.assertEqual(c.exception.status, 409)

    def test_patch_add_replace_remove(self):
        u = self.svc.create_user(user("a@x.com", displayName="A"))
        r = self.svc.patch_user(u["id"], patch(
            {"op": "replace", "path": "displayName", "value": "Alice"},
            {"op": "add", "path": "name.givenName", "value": "Al"},
            {"op": "add", "value": {"externalId": "e1"}},
            {"op": "add", "path": "emails", "value": [{"value": "a@x.com"}]},
        ))
        self.assertEqual((r["displayName"], r["name"]["givenName"], r["externalId"]), ("Alice", "Al", "e1"))
        r = self.svc.patch_user(u["id"], patch({"op": "remove", "path": "displayName"}))
        self.assertNotIn("displayName", r)
        for bad in (patch({"op": "remove", "path": "userName"}), patch({"op": "replace", "path": "nope", "value": 1}),
                    patch({"op": "move", "path": "x"}), {"schemas": ["urn:x"], "Operations": []}):
            with self.assertRaises(ScimError) as c:
                self.svc.patch_user(u["id"], bad)
            self.assertEqual(c.exception.status, 400)

    def test_groups(self):
        a, b = self.svc.create_user(user("a@x.com")), self.svc.create_user(user("b@x.com"))
        g = self.svc.create_group({"schemas": [GROUP_SCHEMA], "displayName": "Deal Team", "members": [{"value": a["id"]}]})
        self.assertEqual([m["value"] for m in g["members"]], [a["id"]])
        g = self.svc.patch_group(g["id"], patch({"op": "add", "path": "members", "value": [{"value": b["id"]}]}))
        self.assertEqual(len(g["members"]), 2)
        g = self.svc.patch_group(g["id"], patch({"op": "remove", "path": f'members[value eq "{a["id"]}"]'}))
        self.assertEqual([m["value"] for m in g["members"]], [b["id"]])
        self.assertEqual(self.svc.get_user(b["id"])["groups"][0]["display"], "Deal Team")
        with self.assertRaises(ScimError) as c:
            self.svc.create_group({"schemas": [GROUP_SCHEMA], "displayName": "Deal Team"})
        self.assertEqual(c.exception.status, 409)
        with self.assertRaises(ScimError) as c:
            self.svc.patch_group(g["id"], patch({"op": "add", "path": "members", "value": [{"value": "ghost"}]}))
        self.assertEqual(c.exception.status, 400)


class TestDeprovision(Base):
    def test_patch_active_false_fires_hooks_audit_and_not_active(self):
        calls = []
        self.svc.on_deprovision.append(lambda o, u: calls.append(("session", o, u)))
        self.svc.on_disable_schedules.append(lambda o, u: calls.append(("sched", o, u)))
        self.svc.on_disable_tokens.append(lambda o, u: calls.append(("tok", o, u)))
        u = self.svc.create_user(user("a@x.com"))
        r = self.svc.patch_user(u["id"], patch({"op": "replace", "path": "active", "value": False}))
        self.assertFalse(r["active"])
        self.assertEqual(calls, [("session", "org1", u["id"]), ("sched", "org1", u["id"]), ("tok", "org1", u["id"])])
        self.assertEqual(sorted(k for _, k in self.svc.revocations(u["id"])), ["api_tokens", "schedules", "session"])
        self.assertFalse(self.svc.is_active(u["id"]))
        self.assertEqual(self.svc.list_users("active eq true")["totalResults"], 0)
        self.assertIn("user.deprovision", [a["action"] for a in self.svc.audit_rows()])
        # idempotent: second deactivate does not re-fire
        self.svc.patch_user(u["id"], patch({"op": "replace", "path": "active", "value": "False"}))
        self.assertEqual(len(calls), 3)

    def test_replace_with_active_false_and_okta_style(self):
        u = self.svc.create_user(user("a@x.com"))
        self.svc.patch_user(u["id"], patch({"op": "replace", "value": {"active": False}}))
        self.assertFalse(self.svc.is_active(u["id"]))
        v = self.svc.create_user(user("b@x.com"))
        self.svc.replace_user(v["id"], user("b@x.com", active=False))
        self.assertFalse(self.svc.is_active(v["id"]))
        self.assertEqual(len(self.svc.revocations(v["id"])), 3)

    def test_delete_fires_hooks_and_removes(self):
        calls = []
        self.svc.on_deprovision.append(lambda o, u: calls.append(u))
        u = self.svc.create_user(user("a@x.com"))
        self.svc.delete_user(u["id"])
        self.assertEqual(calls, [u["id"]])
        with self.assertRaises(ScimError):
            self.svc.get_user(u["id"])
        self.assertFalse(self.svc.is_active(u["id"]))
        self.assertEqual(len(self.svc.revocations(u["id"])), 3)

    def test_hook_failure_rolls_back_user_stays_consistent(self):
        def boom(o, u):
            raise RuntimeError("session store down")
        self.svc.on_deprovision.append(boom)
        u = self.svc.create_user(user("a@x.com"))
        with self.assertRaises(RuntimeError):
            self.svc.patch_user(u["id"], patch({"op": "replace", "path": "active", "value": False}))
        self.assertTrue(self.svc.is_active(u["id"]))          # whole transaction rolled back
        self.assertEqual(self.svc.revocations(u["id"]), [])


class TestAuthAndIsolation(Base):
    def test_token(self):
        t = S.issue_scim_token(self.db, "org1")
        self.assertTrue(S.verify_scim_token(self.db, "org1", t))
        self.assertFalse(S.verify_scim_token(self.db, "org1", t + "x"))
        self.assertFalse(S.verify_scim_token(self.db, "org1", ""))
        self.assertFalse(S.verify_scim_token(self.db, "org1", None))
        self.assertFalse(S.verify_scim_token(self.db, "org2", t))        # other org
        raw = " ".join(str(r) for r in self.db.execute("SELECT * FROM scim_tokens"))
        self.assertNotIn(t, raw)                                         # only a hash is stored
        S.revoke_scim_tokens(self.db, "org1")
        self.assertFalse(S.verify_scim_token(self.db, "org1", t))

    def test_token_compare_is_constant_time_on_hashes(self):
        t = S.issue_scim_token(self.db, "org1")
        with mock.patch.object(S.hmac, "compare_digest", wraps=S.hmac.compare_digest) as cd:
            S.verify_scim_token(self.db, "org1", "wrong")
            S.verify_scim_token(self.db, "org1", t)
        self.assertEqual(cd.call_count, 2)
        for call in cd.call_args_list:                                   # both args are 64-hex hashes, never the raw token
            for arg in call.args:
                self.assertEqual(len(arg), 64)
                self.assertNotIn("scim_", arg)

    def test_cross_org_isolation(self):
        other = ScimService(self.db, "org2")
        u = self.svc.create_user(user("a@x.com"))
        with self.assertRaises(ScimError) as c:
            other.get_user(u["id"])
        self.assertEqual(c.exception.status, 404)
        with self.assertRaises(ScimError):
            other.patch_user(u["id"], patch({"op": "replace", "path": "active", "value": False}))
        with self.assertRaises(ScimError):
            other.delete_user(u["id"])
        other.create_user(user("a@x.com"))                               # same userName allowed in another org
        self.assertEqual(other.list_users()["totalResults"], 1)
        self.assertTrue(self.svc.is_active(u["id"]))
        g = self.svc.create_group({"schemas": [GROUP_SCHEMA], "displayName": "G"})
        with self.assertRaises(ScimError):
            other.get_group(g["id"])
        with self.assertRaises(ScimError) as c:                          # cannot add another org's user to a group
            other.create_group({"schemas": [GROUP_SCHEMA], "displayName": "G", "members": [{"value": u["id"]}]})
        self.assertEqual(c.exception.status, 400)


# ---- ACL fixtures (hand-written from the documented shapes)
SP_PERMS = {"value": [
    {"id": "1", "roles": ["write"], "grantedToV2": {"user": {"id": "u1", "email": "Alice@x.com", "displayName": "Alice"}}},
    {"id": "2", "roles": ["read"], "grantedToV2": {"siteGroup": {"id": "7", "displayName": "Deal Team"}},
     "inheritedFrom": {"id": "folder9", "path": "/Deals"}},
    {"id": "3", "roles": ["read"], "grantedToIdentitiesV2": [{"user": {"email": "bob@x.com"}}, {"group": {"id": "g5"}}],
     "link": {"scope": "users", "type": "view"}},
]}
SP_ANON = {"value": [{"id": "4", "roles": ["read"], "link": {"scope": "anonymous", "type": "view"}}]}
SP_ORG = {"value": [{"id": "5", "roles": ["read"], "link": {"scope": "organization", "type": "view"}}]}
BOX_COLLAB = {"entries": [
    {"role": "editor", "status": "accepted", "accessible_by": {"type": "user", "id": "11", "login": "carol@x.com"}},
    {"role": "viewer", "status": "pending", "accessible_by": {"type": "user", "id": "12", "login": "pending@x.com"}},
    {"role": "uploader", "status": "accepted", "accessible_by": {"type": "user", "id": "13", "login": "up@x.com"}},
    {"role": "viewer", "status": "accepted", "accessible_by": {"type": "group", "id": "88", "name": "Research"}},
]}
DBX_MEMBERS = {
    "users": [{"access_type": {".tag": "editor"}, "user": {"email": "dan@x.com", "account_id": "dbid:1"}},
              {"access_type": {".tag": "traverse"}, "user": {"email": "nope@x.com"}}],
    "groups": [{"access_type": {".tag": "viewer"}, "group": {"group_id": "g:1", "group_name": "Credit"}}],
    "invitees": [{"access_type": {".tag": "viewer"}, "invitee": {".tag": "email", "email": "inv@x.com"}}],
}


class TestAclParsers(unittest.TestCase):
    def test_sharepoint(self):
        a = A.parse_sharepoint("sharepoint", "i1", SP_PERMS)
        self.assertEqual(a.readers_users, {"alice@x.com", "u1", "bob@x.com"})
        self.assertEqual(a.readers_groups, {"7", "Deal Team", "g5"})
        self.assertFalse(a.public_in_org)
        self.assertEqual(a.inherited_from, "/Deals")

    def test_sharepoint_anonymous_link_under_both_settings(self):
        self.assertFalse(A.parse_sharepoint("sharepoint", "i", SP_ANON).public_in_org)
        self.assertTrue(A.parse_sharepoint("sharepoint", "i", SP_ANON, allow_anonymous_as_org_public=True).public_in_org)
        self.assertTrue(A.parse_sharepoint("sharepoint", "i", SP_ORG).public_in_org)
        a = A.parse_sharepoint("sharepoint", "i", SP_ANON)
        self.assertFalse(a.allows("anyone@x.com", ["g"]))                # private, not unknown, nobody listed

    def test_box(self):
        a = A.parse_box("box", "f1", BOX_COLLAB, owner={"id": 10, "login": "owner@x.com"})
        self.assertEqual(a.readers_users, {"carol@x.com", "11", "owner@x.com", "10"})
        self.assertEqual(a.readers_groups, {"88", "Research"})
        self.assertNotIn("pending@x.com", a.readers_users)
        self.assertNotIn("up@x.com", a.readers_users)
        self.assertTrue(A.parse_box("box", "f", BOX_COLLAB, shared_link={"access": "company"}).public_in_org)
        self.assertFalse(A.parse_box("box", "f", BOX_COLLAB, shared_link={"access": "open"}).public_in_org)
        self.assertTrue(A.parse_box("box", "f", BOX_COLLAB, shared_link={"access": "open"}, allow_anonymous_as_org_public=True).public_in_org)

    def test_dropbox(self):
        a = A.parse_dropbox("dropbox", "d1", DBX_MEMBERS)
        self.assertEqual(a.readers_users, {"dan@x.com", "dbid:1"})
        self.assertEqual(a.readers_groups, {"g:1", "Credit"})
        links = [{"link_permissions": {"resolved_visibility": {".tag": "public"}}}]
        self.assertFalse(A.parse_dropbox("dropbox", "d", DBX_MEMBERS, shared_links=links).public_in_org)
        self.assertTrue(A.parse_dropbox("dropbox", "d", DBX_MEMBERS, shared_links=links, allow_anonymous_as_org_public=True).public_in_org)

    def test_posix(self):
        um, gm = {"1000": "Eve@x.com"}, {"50": "analysts"}
        a = A.parse_posix("synced_folder", "p", {"uid": 1000, "gid": 50, "mode": 0o640}, um, group_map=gm)
        self.assertEqual((a.readers_users, a.readers_groups, a.public_in_org), ({"eve@x.com"}, {"analysts"}, False))
        self.assertTrue(A.parse_posix("s", "p", {"uid": 1, "gid": 1, "mode": "644"}, um).public_in_org)
        a = A.parse_posix("s", "p", {"uid": 4242, "gid": 9, "mode": 0o660}, um, group_map=gm)   # unmapped ids grant nobody
        self.assertEqual((a.readers_users, a.readers_groups), (frozenset(), frozenset()))
        self.assertFalse(A.parse_posix("s", "p", {"uid": 1000, "gid": 50, "mode": 0o200}, um).allows("eve@x.com"))

    def test_malformed_is_unknown(self):
        for fn, arg in ((A.parse_sharepoint, None), (A.parse_sharepoint, {"value": "x"}), (A.parse_box, {}),
                        (A.parse_dropbox, {}), (A.parse_posix, {})):
            a = fn("s", "i", arg) if fn is not A.parse_posix else fn("s", "i", arg, {})
            self.assertTrue(a.unknown)
            self.assertFalse(a.allows("x@x.com", ["anything"]))


class TestFilter(unittest.TestCase):
    def setUp(self):
        self.acls = {
            ("sharepoint", "a"): A.parse_sharepoint("sharepoint", "a", SP_PERMS),
            ("box", "b"): A.parse_box("box", "b", BOX_COLLAB),
            ("sharepoint", "pub"): A.parse_sharepoint("sharepoint", "pub", SP_ORG),
            ("box", "unk"): A.parse_box("box", "unk", None),
        }
        self.lookup = lambda s, i: self.acls.get((s, i))
        self.hits = [{"source": s, "item_id": i} for s, i in
                     [("sharepoint", "a"), ("box", "b"), ("sharepoint", "pub"), ("box", "unk"), ("dropbox", "nolacl")]]

    def ids(self, user, groups):
        return [h["item_id"] for h in A.filter_results(self.hits, user, groups, self.lookup)]

    def test_default_deny(self):
        self.assertEqual(self.ids("stranger@x.com", []), ["pub"])         # unknown ACL and missing ACL never leak
        self.assertEqual(A.filter_results([{"source": "", "item_id": "x"}, {}], "a@x.com", [], lambda s, i: None), [])

    def test_user_and_group_grants(self):
        self.assertEqual(self.ids("ALICE@x.com", []), ["a", "pub"])
        self.assertEqual(self.ids("nobody@x.com", ["Deal Team"]), ["a", "pub"])
        self.assertEqual(self.ids("nobody@x.com", ["Research"]), ["b", "pub"])

    def test_large_result_set(self):
        acls = {}
        for i in range(20000):
            acls[("box", f"f{i}")] = A.ItemACL("box", f"f{i}", frozenset({"u@x.com"} if i % 3 == 0 else ()),
                                               frozenset({"g"} if i % 3 == 1 else ()))
        hits = [{"source": "box", "item_id": f"f{i}"} for i in range(20000)] + [{"source": "box", "item_id": "missing"}]
        got = A.filter_results(hits, "u@x.com", [], lambda s, i: acls.get((s, i)))
        self.assertEqual(len(got), len([i for i in range(20000) if i % 3 == 0]))
        self.assertEqual(len(A.filter_results(hits, "u@x.com", ["g"], lambda s, i: acls.get((s, i)))),
                         len([i for i in range(20000) if i % 3 in (0, 1)]))


class TestAuthorizerWithScim(Base):
    def setUp(self):
        super().setUp()
        self.now = [0.0]
        self.cache = A.AclCache(ttl=1000, clock=lambda: self.now[0])
        self.acls = {("box", "grp"): A.ItemACL("box", "grp", readers_groups=frozenset({"Deal Team"})),
                     ("box", "mapped"): A.ItemACL("box", "mapped", readers_groups=frozenset({"box-group-7"})),
                     ("box", "me"): A.ItemACL("box", "me", readers_users=frozenset({"a@x.com"}))}
        self.gmap = A.GroupMap({"box-group-7": ["Deal Team"]})
        self.auth = A.AclAuthorizer(self.svc, lambda s, i: self.acls.get((s, i)), self.cache, self.gmap)
        self.u = self.svc.create_user(user("a@x.com"))
        self.hits = [{"source": "box", "item_id": i} for i in ("grp", "mapped", "me")]

    def got(self):
        return [h["item_id"] for h in self.auth.filter(self.u["id"], self.hits)]

    def test_group_grant_via_scim_and_mapping(self):
        self.assertEqual(self.got(), ["me"])
        self.svc.create_group({"schemas": [GROUP_SCHEMA], "displayName": "Deal Team", "members": [{"value": self.u["id"]}]})
        self.assertEqual(self.got(), ["grp", "mapped", "me"])           # SCIM change invalidated the warm principal cache

    def test_deprovision_drops_access_with_warm_cache(self):
        self.assertEqual(self.got(), ["me"])                             # warms ACL + principal caches
        self.assertEqual(len(self.cache._principal), 1)
        self.svc.patch_user(self.u["id"], patch({"op": "replace", "path": "active", "value": False}))
        self.assertEqual(self.got(), [])                                 # same clock tick, no TTL expiry
        v = self.svc.create_user(user("b@x.com"))
        self.acls[("box", "me")] = A.ItemACL("box", "me", readers_users=frozenset({"b@x.com"}))
        self.cache.invalidate_acls("org1")
        self.assertEqual(len(self.auth.filter(v["id"], self.hits)), 1)
        self.svc.delete_user(v["id"])
        self.assertEqual(self.auth.filter(v["id"], self.hits), [])

    def test_ttl_expiry(self):
        self.assertEqual(self.got(), ["me"])
        self.acls[("box", "me")] = A.ItemACL("box", "me")                # source ACL revoked
        self.assertEqual(self.got(), ["me"])                             # still cached
        self.now[0] = 2000
        self.assertEqual(self.got(), [])                                 # TTL passed

    def test_unknown_user_denied(self):
        self.assertEqual(self.auth.filter("ghost", self.hits), [])


if __name__ == "__main__":
    unittest.main()
