"""S8.5 international connectors (offline: replay fixtures and a scripted fake network; no live requests)."""
import io
import json
import os
import socket
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from om.intl import ixbrl
from om.intl.sources import common, routing
from om.intl.sources.common import Fetcher, NotConfigured, RobotsDisallowed, SourceError, TooLarge
from src.harness.connectors import base, intl_common

intl_common.load_all()
ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "intl_connectors"
NAMES = ["egx", "tadawul", "esef", "companies_house", "kvk", "inpi", "bronnoysund", "cro", "gleif"]
PAID = ["pappers", "north_data", "bigdata", "third_bridge", "arbolus"]


class Resp(io.BytesIO):
    def __init__(self, body=b"{}", url="", headers=None, status=200):
        super().__init__(body)
        self.headers, self.status, self._url = headers or {}, status, url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class Net:
    """Scripted network: routes maps a URL to bytes, (status, bytes, headers) or an exception. Fake clock included."""

    def __init__(self, routes=None, robots="User-agent: *\nDisallow: /private/\n"):
        self.routes, self.robots, self.calls, self.now = dict(routes or {}), robots, [], 100.0

    def clock(self):
        return self.now

    def sleep(self, s):
        self.now += s

    def urlopen(self, req, timeout=None):
        url, hdrs = req.full_url, {k.lower(): v for k, v in req.header_items()}
        self.calls.append((self.now, url, hdrs))
        if url.endswith("/robots.txt"):
            if isinstance(self.robots, int):
                raise urllib.error.HTTPError(url, self.robots, "x", {}, None)
            return Resp(self.robots.encode(), url)
        r = self.routes.get(url, b"{}")
        if isinstance(r, Exception):
            raise r
        if isinstance(r, tuple):
            status, body, h = r
            if 300 <= status < 400:
                raise urllib.error.HTTPError(url, status, "redirect", h, None)
            return Resp(body, url, h, status)
        return Resp(r, url)

    def kw(self):
        return dict(urlopen=self.urlopen, clock=self.clock, sleep=self.sleep)

    def content_calls(self):
        return [c for c in self.calls if not c[1].endswith("/robots.txt")]


class Registration(unittest.TestCase):
    def test_all_register_and_paid_registered(self):
        for n in NAMES + PAID:
            self.assertIn(n, base.available(), n)
        self.assertTrue(base.get("bronnoysund", replay=True).fragile)

    def test_lazy_names_resolve_after_import(self):
        self.assertIn("egx", base._LAZY)
        self.assertEqual(base._LAZY["pappers"], "intl_paid")

    def test_list_and_fetch_from_replay(self):
        for n in NAMES:
            c = base.get(n, replay=True)
            items = list(c.list())
            self.assertTrue(items, n)
            body, meta = c.fetch(items[0].id)
            self.assertTrue(body, n)
            self.assertIn("name", meta)
            self.assertIn("source", meta)

    def test_replay_never_touches_network_or_disk(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            with tempfile.TemporaryDirectory() as d:
                for n in NAMES:
                    c = base.get(n, replay=True, data_dir=d)
                    for it in list(c.list())[:1]:
                        c.fetch(it.id)
                self.assertEqual(os.listdir(d), [])

    def test_egx_items_are_links_and_facts(self):
        items = list(base.get("egx", replay=True).list())
        self.assertEqual(len(items), 3)                      # two documents plus the /private/ link; the contact page and off-site link are out
        urls = [i.id for i in items]
        self.assertTrue(all(u.startswith("https://www.egx.com.eg/") for u in urls))     # off-site link dropped
        self.assertTrue(any(i.meta["kind"] == "annual_report" for i in items))

    def test_esef_lists_and_parses_statements(self):
        c = base.get("esef", replay=True)
        it = list(c.list())[0]
        self.assertEqual(it.meta["entity_id"], "213800MU3B7CS88PY290")
        st = c.statements(it.id)
        self.assertEqual(st["values"]["assets"]["2026-06-30"], 4437863.0)
        self.assertEqual(st["values"]["equity_total"]["2026-06-30"], 2719586.0)       # dimensionless only, instants exclusive->inclusive
        self.assertEqual(st["values"]["ebit"]["2026-06-30"], -137911.0)


class Polite(unittest.TestCase):
    def test_robots_refusal_before_any_request(self):
        net = Net()
        c = base.get("egx", **net.kw())
        with mock.patch.object(socket, "socket", side_effect=AssertionError("socket")):
            with self.assertRaises(Exception) as cm:
                c.fetch("https://www.egx.com.eg/private/secret.pdf")
        self.assertIn("robots", str(cm.exception).lower())
        self.assertEqual(net.content_calls(), [])
        self.assertEqual([u for _, u, _ in net.calls], ["https://www.egx.com.eg/robots.txt"])

    def test_robots_fetched_once_per_host(self):
        net = Net()
        c = base.get("egx", **net.kw())
        for p in "ab":
            try:
                c.fetch(f"https://www.egx.com.eg/public/{p}.pdf")
            except Exception:
                pass
        self.assertEqual(len([1 for _, u, _ in net.calls if u.endswith("/robots.txt")]), 1)

    def test_robots_unreachable_or_forbidden_is_a_refusal(self):
        for code in (403, 503):
            net = Net(robots=code)
            with self.assertRaises(RobotsDisallowed):
                Fetcher("egx", ("egx.com.eg",), **net.kw()).get("https://www.egx.com.eg/a.pdf")
            self.assertEqual(net.content_calls(), [])
        net = Net(robots=404)       # no robots file: allowed
        Fetcher("egx", ("egx.com.eg",), **net.kw()).get("https://www.egx.com.eg/a.pdf")
        self.assertEqual(len(net.content_calls()), 1)

    def test_rate_limit_spacing_on_fake_clock(self):
        net = Net()
        f = Fetcher("egx", ("egx.com.eg",), **net.kw())
        for p in "abc":
            f.get(f"https://www.egx.com.eg/public/{p}.pdf")
        t = [c[0] for c in net.calls]
        self.assertTrue(all(b - a >= 2.0 for a, b in zip(t, t[1:])), t)
        self.assertEqual(f.min_interval, 2.0)

    def test_robots_crawl_delay_raises_the_interval(self):
        net = Net(robots="User-agent: *\nCrawl-delay: 7\n")
        f = Fetcher("egx", ("egx.com.eg",), **net.kw())
        f.get("https://www.egx.com.eg/a")
        f.get("https://www.egx.com.eg/b")
        t = [c[0] for c in net.content_calls()]
        self.assertGreaterEqual(t[1] - t[0], 7.0)

    def test_hosts_are_paced_independently(self):
        net = Net()
        f = Fetcher("x", ("a.example", "b.example"), **net.kw())
        f.get("https://a.example/1")
        f.get("https://b.example/1")
        self.assertLess(net.now - 100.0, 5.0)                # each host waits once (robots then content); a shared clock would need 6

    def test_user_agent_identifies_acretia_without_an_email(self):
        net = Net()
        base.get("egx", **net.kw()).fetch("https://www.egx.com.eg/public/a.pdf")
        for _, _, h in net.calls:
            self.assertEqual(h["user-agent"], "AcretiaResearch/1.0 (+financial statements research)")
            self.assertNotIn("@", h["user-agent"])

    def test_sec_host_uses_the_approved_ua_from_the_environment(self):
        self.assertEqual(common.user_agent_for("data.sec.gov", env={"SEC_USER_AGENT": "Org contact@sec.example"}), "Org contact@sec.example")
        with self.assertRaises(NotConfigured):
            common.user_agent_for("www.sec.gov", env={})
        self.assertEqual(common.user_agent_for("filings.xbrl.org"), common.USER_AGENT)

    def test_allow_list_https_only_and_no_credentials(self):
        f = Fetcher("egx", ("egx.com.eg",), **Net().kw())
        for bad in ("http://www.egx.com.eg/a", "https://evil.example/a", "https://u:p@www.egx.com.eg/a", "https://egx.com.eg.evil.example/a",
                    "file:///etc/passwd"):
            with self.assertRaises(SourceError, msg=bad):
                f.get(bad)

    def test_redirect_off_allow_list_is_refused(self):
        class Redir(Net):
            def urlopen(self, req, timeout=None):
                r = super().urlopen(req, timeout)
                if not req.full_url.endswith("/robots.txt"):
                    r._url = "https://evil.example/landing"
                return r
        net = Redir()
        with self.assertRaises(SourceError):
            Fetcher("egx", ("egx.com.eg",), **net.kw()).get("https://www.egx.com.eg/a")

    def test_size_cap(self):
        net = Net({"https://www.egx.com.eg/big": b"x" * 100})
        with self.assertRaises(TooLarge):
            Fetcher("egx", ("egx.com.eg",), max_bytes=50, **net.kw()).get("https://www.egx.com.eg/big")


class Storage(unittest.TestCase):
    def test_writes_only_under_raw_source_dir(self):
        net = Net({"https://www.egx.com.eg/public/a.pdf": b"PDFBYTES"})
        with tempfile.TemporaryDirectory() as d:
            c = base.get("egx", data_dir=d, **net.kw())
            body, meta = c.fetch("https://www.egx.com.eg/public/a.pdf")
            self.assertEqual(body, b"PDFBYTES")
            saved = Path(meta["saved_path"]).resolve()
            self.assertEqual(saved.parent, (Path(d) / "egx").resolve())
            self.assertEqual(meta["sha256"], __import__("hashlib").sha256(b"PDFBYTES").hexdigest())
            files = [p.resolve() for p in Path(d).rglob("*") if p.is_file()]          # macOS: /var is /private/var
            self.assertEqual(files, [saved])

    def test_traversal_in_names_cannot_escape(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fetcher("egx", ("egx.com.eg",), raw_dir=d, **Net().kw())
            p = Path(f.save("../../etc/passwd", b"x")).resolve()
            self.assertEqual(p.parent, (Path(d) / "egx").resolve())

    def test_default_raw_dir_is_data_raw_intl(self):
        self.assertEqual(common.RAW_ROOT, ROOT / "data" / "raw" / "intl")

    def test_download_streams_to_disk(self):
        net = Net({"https://www.kvk.nl/download/kvk-open-data-set-jaarrekeningen0.zip": b"ZIP" * 10})
        with tempfile.TemporaryDirectory() as d:
            c = base.get("kvk", data_dir=d, **net.kw())
            body, meta = c.fetch("https://www.kvk.nl/download/kvk-open-data-set-jaarrekeningen0.zip")
            info = json.loads(body)
            self.assertEqual(info["bytes"], 30)
            self.assertTrue(Path(info["saved_path"]).is_file())
            self.assertFalse(list(Path(d).rglob("*.part")))


class CompaniesHouse(unittest.TestCase):
    def setUp(self):
        self.env = {k: v for k, v in os.environ.items() if "COMPANIES_HOUSE" not in k.upper()}

    def test_no_key_errors_cleanly_and_makes_no_request(self):
        net = Net()
        with mock.patch.dict(os.environ, self.env, clear=True):
            c = base.get("companies_house", company_numbers=["00000006"], **net.kw())
            for call in (lambda: list(c.list()), lambda: c.fetch("00000006/abc"), lambda: c.source.officers("00000006")):
                with self.assertRaises(NotConfigured) as cm:
                    call()
                self.assertIn("COMPANIES_HOUSE_API_KEY", str(cm.exception))
        self.assertEqual(net.calls, [])

    def test_key_comes_from_the_environment_and_is_sent_as_basic_auth(self):
        net = Net({"https://api.company-information.service.gov.uk/company/00000006/filing-history?category=accounts&items_per_page=25":
                   json.dumps({"items": []}).encode()})
        with mock.patch.dict(os.environ, {**self.env, "COMPANIES_HOUSE_API_KEY": "unit-test-key"}, clear=True):
            list(base.get("companies_house", company_numbers=["00000006"], **net.kw()).list())
        auth = net.content_calls()[0][2]["authorization"]
        self.assertTrue(auth.startswith("Basic "))
        import base64
        self.assertEqual(base64.b64decode(auth[6:]), b"unit-test-key:")

    def test_authorization_is_dropped_on_redirect_to_the_document_store(self):
        meta = "https://document-api.company-information.service.gov.uk/document/abc123"
        net = Net({meta + "/content": (302, b"", {"Location": "https://document-api-images-live.s3.eu-west-2.amazonaws.com/x?sig=1"}),
                   "https://document-api-images-live.s3.eu-west-2.amazonaws.com/x?sig=1": b"<html/>"})
        f = Fetcher("companies_house", ("company-information.service.gov.uk",), redirect_hosts=("amazonaws.com",), **net.kw())
        r = f.get(meta + "/content", headers={"Authorization": "Basic abc"})
        self.assertEqual(r.body, b"<html/>")
        last = net.content_calls()[-1]
        self.assertNotIn("authorization", last[2])

    def test_filing_fetch_and_ixbrl_statements_from_replay(self):
        c = base.get("companies_house", replay=True)
        items = list(c.list())
        self.assertEqual(items[0].meta["type"], "AA")
        body, meta = c.fetch(items[0].id)
        self.assertEqual(meta["route"], "ixbrl")
        st = c.statements(items[0].id)
        self.assertEqual(st["values"]["revenue"]["2025-12-31"], 1250000.0)

    def test_officers_and_psc_keep_name_role_dates_only(self):
        c = base.get("companies_house", replay=True)
        for rec in c.officers("00000006") + c.psc("00000006"):
            self.assertEqual(set(rec), {"name", "role", "appointed", "resigned"})
        off = c.officers("00000006")
        self.assertEqual(off[0], {"name": "EXAMPLE, Alex", "role": "director", "appointed": "2015-04-01", "resigned": "2024-01-31"})
        blob = json.dumps(c.officers("00000006") + c.psc("00000006"))
        for forbidden in ("Private Road", "1970", "British", "Hidden Lane", "Corporate Way"):
            self.assertNotIn(forbidden, blob)

    def test_bulk_listing_and_zip_parsing(self):
        c = base.get("companies_house", replay=True)
        names = [i.name for i in c.list_bulk()]
        self.assertIn("Accounts_Bulk_Data-2026-10-16.zip", names)
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            z = Path(d) / "b.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("Prod224_0001_00000006_20251231.html", (FIX / "companies_house" / "accounts.xhtml").read_text())
                zf.writestr("notes.txt", "skip me")
            out = list(c.source.parse_bulk(z))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1]["values"]["ebit"]["2025-12-31"], 450000.0)

    def test_bulk_name_is_validated(self):
        with self.assertRaises(Exception) as cm:
            base.get("companies_house", replay=True).fetch("bulk:../../etc/passwd")
        self.assertIn("bulk file name", str(cm.exception))

    def test_no_key_literal_in_the_repo_sources(self):
        for p in list((ROOT / "om" / "intl" / "sources").glob("*.py")) + list((ROOT / "src" / "harness" / "connectors").glob("intl_*.py")):
            txt = p.read_text()
            self.assertNotRegex(txt, r"(?i)(api[_-]?key|token|secret|passw(or)?d)\s*[:=]\s*[\"'][A-Za-z0-9_\-/+=]{16,}[\"']", p.name)


class Registries(unittest.TestCase):
    def test_inpi_needs_credentials_and_skips_confidential_accounts(self):
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("INPI")}, clear=True):
            net = Net()
            with self.assertRaises(NotConfigured):
                list(base.get("inpi", sirens=["552100554"], **net.kw()).list())
            self.assertEqual(net.calls, [])
        ids = [i.id for i in base.get("inpi", replay=True).list()]
        self.assertEqual(ids, ["552100554/b-2024-pub"])

    def test_inpi_login_posts_credentials_from_env(self):
        net = Net({"https://registre-national-entreprises.inpi.fr/api/sso/login": json.dumps({"token": "tok-unit"}).encode(),
                   "https://registre-national-entreprises.inpi.fr/api/companies/552100554/attachments": json.dumps({"bilans": []}).encode()})
        env = {"INPI_RNE_USERNAME": "u@example.org", "INPI_RNE_PASSWORD": "pw-unit"}
        with mock.patch.dict(os.environ, env):
            list(base.get("inpi", sirens=["552100554"], **net.kw()).list())
        self.assertEqual(net.content_calls()[1][2]["authorization"], "Bearer tok-unit")

    def test_bronnoysund_is_fragile_and_errors_clearly_on_a_changed_api(self):
        net = Net({"https://data.brreg.no/regnskapsregisteret/regnskap/923609016": b'{"message": "gone"}'})
        c = base.get("bronnoysund", org_numbers=["923609016"], **net.kw())
        with self.assertRaises(Exception) as cm:
            list(c.list())
        self.assertIn("fragile", str(cm.exception))
        item = list(base.get("bronnoysund", replay=True).list())[0]
        self.assertTrue(item.meta["fragile"])
        self.assertEqual(item.meta["basis"], "IFRS")

    def test_cro_keeps_records_not_documents_and_no_address(self):
        c = base.get("cro", replay=True)
        item = list(c.list())[0]
        self.assertIn("not fetched", item.meta["document"])
        body, _ = c.fetch(item.id)
        self.assertEqual(set(json.loads(body)), {"company_number", "company_name", "file_name", "submission", "received", "accounts_to"})

    def test_esef_url_filters(self):
        from om.intl.sources.esef import filings_url
        u = filings_url(country="gb", lei="213800MU3B7CS88PY290", period_end="2026-06-30", limit=5)
        self.assertIn("api/filings?filter=", u)
        flt = json.loads(__import__("urllib.parse").parse.unquote(u.split("filter=")[1].split("&")[0]))
        self.assertEqual({f["name"] for f in flt}, {"country", "fxo_id", "period_end"})
        self.assertIn("GB", json.dumps(flt))

    def test_esef_fetches_package_and_report_kinds(self):
        body, meta = base.get("esef", replay=True).fetch("27911#package")
        self.assertEqual(meta["kind"], "package")
        with self.assertRaises(Exception):
            base.get("esef", replay=True).fetch("27911#nonsense")


class Gleif(unittest.TestCase):
    def test_resolves_one_entity_across_two_registries(self):
        g = base.get("gleif", replay=True).source
        r = g.resolve("213800LH1BZH3DI6G760")
        self.assertEqual(r["status"], "resolved")
        self.assertEqual({x["registry"] for x in r["registries"]}, {"gleif", "companies_house"})
        self.assertEqual(r["links"]["companies_house"], "00102498")
        self.assertEqual(r["esef_lookup_key"], r["lei"])

    def test_resolve_by_name_and_by_registry_number(self):
        g = base.get("gleif", replay=True).source
        r = g.resolve("Equinor ASA")
        self.assertEqual(r["lei"], "OW6OFBNCKXC4US5C7523")
        self.assertEqual(r["links"]["bronnoysund"], "923609016")           # whitespace removed
        r2 = g.resolve("923609016", authority="RA000472")
        self.assertEqual(r2["lei"], r["lei"])

    def test_ambiguous_and_missing(self):
        class Two(common.Fetcher):
            pass
        g = base.get("gleif", replay=True).source
        rec = json.loads((FIX / "gleif" / "bp.json").read_text())["data"][0]
        other = json.loads(json.dumps(rec))
        other["attributes"]["lei"] = "213800LH1BZH3DI6G761"
        other["attributes"]["entity"]["legalName"]["name"] = "BP P.L.C. (copy)"
        with mock.patch.object(g, "_records", return_value=[rec, other]):
            self.assertEqual(g.resolve("BP")["status"], "ambiguous")
        with mock.patch.object(g, "_records", return_value=[]):
            self.assertEqual(g.resolve("Nobody Ltd")["status"], "not_found")

    def test_fetch_exposes_registries_in_meta(self):
        c = base.get("gleif", replay=True)
        body, meta = c.fetch("213800LH1BZH3DI6G760")
        self.assertGreaterEqual(len(meta["registries"]), 2)
        self.assertIn('"registry": "companies_house"', body.decode())


class Paid(unittest.TestCase):
    def test_paid_sources_only_raise_not_configured(self):
        for n in PAID:
            c = base.get(n)
            for call in (lambda: list(c.list()), lambda: c.fetch("x")):
                with self.assertRaises(NotConfigured) as cm:
                    call()
                self.assertIn("requires user approval and a commercial agreement", str(cm.exception))

    def test_paid_interfaces_take_no_credentials_and_make_no_calls(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("call")), mock.patch.object(socket, "socket", side_effect=AssertionError("call")):
            for n in PAID:
                with self.assertRaises(NotConfigured):
                    list(base.get(n).list())
        with self.assertRaises(TypeError):
            base.get("pappers", api_key="x")


class Routing(unittest.TestCase):
    def test_pdf_accounts_route_to_the_pipeline_lazily(self):
        fake = types.ModuleType("om.intl.pipeline")
        fake.read_report = lambda path, **kw: ("read", str(path), kw)
        with mock.patch.dict(sys.modules, {"om.intl.pipeline": fake}), mock.patch.object(sys.modules["om.intl"], "pipeline", fake, create=True):
            self.assertEqual(routing.route_pdf_accounts("a.pdf", country="DE", language="de"), ("read", "a.pdf", {"language": "de"}))

    def test_missing_pipeline_is_a_clear_error(self):
        with mock.patch.dict(sys.modules, {"om.intl.pipeline": None}):
            with self.assertRaises(SourceError) as cm:
                routing.route_pdf_accounts("a.pdf", country="ES")
        self.assertIn("om.intl.pipeline", str(cm.exception))


class Ixbrl(unittest.TestCase):
    DOC = (FIX / "companies_house" / "accounts.xhtml").read_text()

    def test_scale_sign_format_and_zero_dash(self):
        d = ixbrl.parse_ixbrl(self.DOC)
        by = {f.concept: f for f in d.facts}
        self.assertEqual(by["ifrs-full:Revenue"].value, 1250000.0)                      # 1,250 x 10^3
        self.assertEqual(by["ifrs-full:CostOfSales"].value, -800000.0)                  # sign="-"
        self.assertEqual(by["ifrs-full:Assets"].value, 2345678.5)                       # num-comma-decimal
        self.assertEqual(by["ifrs-full:IncomeTaxExpenseContinuingOperations"].value, 0.0)  # zerodash
        self.assertEqual(by["ifrs-full:Revenue"].decimals, "-3")
        self.assertEqual(d.warnings, [])

    def test_contexts_units_and_dimensions(self):
        d = ixbrl.parse_ixbrl(self.DOC)
        rev = d.by_concept("ifrs-full:Revenue")[0]
        self.assertEqual((rev.period_start, rev.period_end, rev.unit, rev.entity), ("2025-01-01", "2025-12-31", "iso4217:GBP", "00000006"))
        eq = d.by_concept("ifrs-full:Equity")[0]
        self.assertEqual(eq.dims, (("ifrs-full:ComponentsOfEquityAxis", "ifrs-full:RetainedEarningsMember"),))
        self.assertIsNone(eq.period_start)
        eps = d.by_concept("ifrs-full:BasicEarningsLossPerShare")[0]
        self.assertEqual(eps.unit, "iso4217:GBP/xbrli:shares")
        name = d.by_concept("ifrs-full:NameOfReportingEntityOrOtherMeansOfIdentification")[0]
        self.assertFalse(name.numeric)
        self.assertEqual(name.text, "Synthetic Example PLC")

    def test_statements_use_concept_keys_and_skip_dimensioned_facts(self):
        st = ixbrl.to_statements(ixbrl.parse_ixbrl(self.DOC))
        self.assertEqual(st["values"]["revenue"], {"2025-12-31": 1250000.0})
        self.assertEqual(st["values"]["assets"], {"2025-12-31": 2345678.5})
        self.assertNotIn("equity_total", st["values"])                                  # only a dimensioned fact exists
        self.assertEqual(st["conflicts"], [])

    def test_conflicting_duplicates_are_reported_not_hidden(self):
        doc = self.DOC.replace("</body>", '<ix:nonFraction name="ifrs-full:Revenue" contextRef="d2025" unitRef="GBP" decimals="0">1</ix:nonFraction></body>')
        st = ixbrl.to_statements(ixbrl.parse_ixbrl(doc))
        self.assertEqual(st["values"]["revenue"]["2025-12-31"], 1250000.0)
        self.assertEqual(st["conflicts"][0]["dropped"], 1.0)

    def test_unknown_format_gives_a_warning_not_a_guess(self):
        doc = self.DOC.replace('format="ixt:num-comma-decimal"', 'format="ixt:weird-format"')
        d = ixbrl.parse_ixbrl(doc)
        self.assertIsNone(d.by_concept("ifrs-full:Assets")[0].value)
        self.assertTrue(any("weird-format" in w for w in d.warnings))

    def test_number_formats(self):
        P = ixbrl.parse_number
        self.assertEqual(float(P("1,234.5", "ixt:num-dot-decimal")), 1234.5)
        self.assertEqual(float(P("1.234,5", "ixt:numcommadecimal")), 1234.5)
        self.assertEqual(float(P("1 234,5", "ixt2:numspacecomma")), 1234.5)
        self.assertEqual(float(P("1 234.5", "ixt3:numspacedot")), 1234.5)
        self.assertEqual(float(P("—", "ixt:zerodash")), 0.0)
        self.assertEqual(float(P("1,234", None)), 1234.0)
        with self.assertRaises(ixbrl.IxbrlError):
            P("abc", "ixt:num-dot-decimal")

    def test_xbrl_json_periods_and_dimensions(self):
        doc = {"documentInfo": {}, "facts": {
            "a": {"value": "10.0", "decimals": 0, "dimensions": {"concept": "ifrs-full:Revenue", "entity": "scheme:L", "unit": "iso4217:EUR",
                                                                 "period": "2025-01-01T00:00:00/2026-01-01T00:00:00"}},
            "b": {"value": "5.0", "decimals": 0, "dimensions": {"concept": "ifrs-full:Assets", "entity": "scheme:L", "unit": "iso4217:EUR",
                                                                "period": "2026-01-01T00:00:00"}},
            "c": {"value": "7.0", "dimensions": {"concept": "ifrs-full:Assets", "entity": "scheme:L", "unit": "iso4217:EUR",
                                                 "period": "2026-01-01T00:00:00", "ifrs-full:SegmentsAxis": "x:A"}},
            "d": {"value": "text", "dimensions": {"concept": "ifrs-full:NameOfReportingEntityOrOtherMeansOfIdentification", "entity": "scheme:L",
                                                  "period": "2025-01-01T00:00:00/2026-01-01T00:00:00", "language": "en"}}}}
        d = ixbrl.parse_xbrl_json(doc)
        f = {x.fact_id: x for x in d.facts}
        self.assertEqual((f["a"].period_start, f["a"].period_end), ("2025-01-01", "2025-12-31"))
        self.assertEqual(f["b"].period_end, "2025-12-31")
        self.assertEqual(f["c"].dims, (("ifrs-full:SegmentsAxis", "x:A"),))
        self.assertFalse(f["d"].numeric)
        st = ixbrl.to_statements(d)
        self.assertEqual(st["values"], {"revenue": {"2025-12-31": 10.0}, "assets": {"2025-12-31": 5.0}})

    def test_autodetect(self):
        self.assertEqual(ixbrl.parse(self.DOC).kind, "ixbrl")
        self.assertEqual(ixbrl.parse(b'{"facts": {}}').kind, "xbrl-json")
        with self.assertRaises(ixbrl.IxbrlError):
            ixbrl.parse_xbrl_json({"nope": 1})


class Terms(unittest.TestCase):
    def test_terms_register_has_a_row_per_source_with_dates_and_urls(self):
        rows = [l for l in (ROOT / "docs" / "s8" / "source-terms.md").read_text().splitlines()
                if l.startswith("|") and "---" not in l][1:]
        for key in ("ESEF", "Companies House", "KvK", "INPI", "Bronnoysund", "CRO", "GLEIF", "EGX", "Saudi Exchange", "Pappers", "North Data",
                    "Bigdata", "Third Bridge", "Arbolus"):
            row = next((r for r in rows if r.split("|")[1].strip().lower().startswith(key.lower())), None)
            self.assertIsNotNone(row, key)
            self.assertIn("https://", row)
            self.assertEqual(len(row.strip().strip("|").split("|")), 7)


if __name__ == "__main__":
    unittest.main()
