"""om.modelapi: build, edit, ask, audit, explain, export and roll forward, all offline on synthetic filings."""
import copy
import io
import json
import os
import re
import shutil
import tempfile
import unittest
import warnings
import zipfile
from datetime import date
from unittest import mock

from om import delivery, modelapi, prices, wbedit, xlsx
from tests.test_model3 import synthetic_companyfacts


def scaled(cf: dict, k: float) -> dict:
    """The same company at another size (every reported number x k): keeps statements tied, changes the multiples."""
    out = copy.deepcopy(cf)
    for node in out["facts"]["us-gaap"].values():
        for rows in node["units"].values():
            for r in rows:
                r["val"] = r["val"] * k
    return out


BASE = synthetic_companyfacts()
VARIANTS = {"AAA": BASE, "BBB": scaled(BASE, 0.5), "CCC": scaled(BASE, 2.0), "DDD": scaled(BASE, 1.5)}
QUOTES = {t: prices.Quote(t, p, "USD", date(2025, 1, 3), "unit-test") for t, p in (("AAA", 50.0), ("BBB", 30.0), ("CCC", 80.0), ("DDD", 40.0))}


def fetch(t):
    return copy.deepcopy(VARIANTS[t])


def parts(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    return {n: z.read(n) for n in z.namelist()}


KEEP = ("kind", "tickers", "outputs", "checks", "grade", "validate", "engines", "timings", "warnings", "markets", "assumptions")


def plant(model_id, changes=None, tamper=None):
    """Store a doctored copy as its own model (the way a corrupted file would arrive). ``changes``: wbedit edits (formulas
    become what you type); ``tamper``: {"Sheet!A1": number} rewrites only the cached <v> and leaves the formula."""
    rec, data, private = modelapi._load(model_id, 1)
    new = wbedit.edit(data, changes)[0] if changes else data
    for key, val in (tamper or {}).items():
        sheet, a1 = key.split("!")
        files = parts(new)
        part = wbedit._sheet_parts(files)[sheet]
        xml = files[part].decode()
        m = wbedit._cell_re(a1).search(xml)
        cell = re.sub(r"<v>[^<]*</v>", f"<v>{val}</v>", m.group(0))
        files[part] = (xml[:m.start()] + cell + xml[m.end():]).encode()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in files.items():
                z.writestr(n, b)
        new = out.getvalue()
    return modelapi._commit(None, {k: rec[k] for k in KEEP}, new, {**private, "build": None}, None)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="modelapi-")
        cls.env = mock.patch.dict(os.environ, {"ACRETIA_MODELS_DIR": cls.tmp})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)


class BuildTests(Base):
    def test_every_kind_builds_and_is_stored(self):
        cases = [("three_statement", ["AAA"], None), ("dcf", ["AAA"], None), ("lbo", ["AAA"], QUOTES),
                 ("merger", ["AAA", "BBB"], QUOTES), ("comps", ["AAA", "BBB", "CCC", "DDD"], QUOTES)]
        ids = set()
        for kind, tickers, quotes in cases:
            with self.subTest(kind=kind):
                r = modelapi.build_model(kind, tickers, quotes=quotes, fetch=fetch)
                for k in ("model_id", "version", "kind", "bytes_sha256", "outputs", "checks", "grade", "validate", "engines", "timings", "warnings"):
                    self.assertIn(k, r)
                self.assertEqual((r["kind"], r["version"], r["parent"]), (kind, 1, None))
                self.assertTrue(r["outputs"])
                self.assertEqual(r["checks"]["master"], "OK")
                self.assertTrue(r["checks"]["ok"])
                self.assertTrue(all(k in r["timings"] for k in ("build", "grade", "validate", "recalc", "manifest", "total")))
                self.assertGreater(r["timings"]["total"], 0)
                self.assertTrue(r["engines"]["agree"])
                self.assertEqual(modelapi.get_model(r["model_id"]), r)
                self.assertEqual(modelapi.hashlib.sha256(modelapi.get_bytes(r["model_id"])).hexdigest(), r["bytes_sha256"])
                self.assertTrue(r["model_id"].startswith("m_"))
                json.dumps(r, allow_nan=False)                               # JSON-friendly all the way down
                ids.add(r["model_id"])
        self.assertEqual(len(ids), len(cases))
        dcf = modelapi.build_model("dcf", ["AAA"], fetch=fetch)
        self.assertEqual(dcf["outputs"][0]["id"], "m3.dcf.value_per_share")
        self.assertTrue(all(o["id"].startswith("m3.dcf") for o in dcf["outputs"][:4]))
        self.assertIsInstance(dcf["outputs"][0]["value"], float)
        self.assertTrue(dcf["outputs"][0]["label"])

    def test_build_is_idempotent_and_ids_follow_content(self):
        a = modelapi.build_model("three_statement", ["AAA"], fetch=fetch)
        b = modelapi.build_model("three_statement", ["AAA"], fetch=fetch)
        self.assertEqual(a["model_id"], b["model_id"])
        self.assertEqual(len(modelapi.list_versions(a["model_id"])), 1)
        c = modelapi.build_model("three_statement", ["BBB"], fetch=fetch)
        self.assertNotEqual(a["model_id"], c["model_id"])

    def test_typed_errors(self):
        with self.assertRaises(modelapi.NoMarketPrice) as cm:
            modelapi.build_model("lbo", ["AAA"], fetch=fetch)                  # no quote, no public float in the filings
        self.assertEqual(cm.exception.code, "no_market_price")
        with self.assertRaises(modelapi.NoMarketPrice):
            modelapi.build_model("merger", ["AAA", "BBB"], quotes={"AAA": QUOTES["AAA"]}, fetch=fetch)
        with self.assertRaises(modelapi.UnsupportedCompany) as cm:
            modelapi.build_model("three_statement", ["AAA"], fetch=lambda t: synthetic_companyfacts(years=(2024,)))
        self.assertEqual(cm.exception.code, "unsupported_company")
        with self.assertRaises(modelapi.UnsupportedCompany):
            modelapi.build_model("three_statement", ["ZZZ"], fetch=lambda t: (_ for _ in ()).throw(KeyError(t)))
        with self.assertRaises(modelapi.InvalidRequest):
            modelapi.build_model("swap", ["AAA"], fetch=fetch)
        with self.assertRaises(modelapi.InvalidRequest):
            modelapi.build_model("merger", ["AAA"], fetch=fetch)
        for bad in ("m_" + "0" * 20, "../etc", None):
            with self.assertRaises(modelapi.NotFound) as cm:
                modelapi.get_model(bad)
            self.assertEqual(cm.exception.code, "not_found")
        self.assertEqual(modelapi.NotAnInput("x").to_dict()["code"], "not_an_input")
        self.assertEqual(modelapi.Blocked({"steps": []}).code, "blocked")
        self.assertIsInstance(modelapi.Blocked({"steps": []}), delivery.DeliveryBlocked)


class ModelTests(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.m = modelapi.build_model("three_statement", ["AAA"], fetch=fetch)
        cls.mid = cls.m["model_id"]

    def tax_cell(self):
        rows = [i for i in modelapi.list_inputs(self.mid) if i["sheet"] == "Assumptions" and "tax" in i["label"].lower() and i["period"]]
        self.assertTrue(rows)
        return rows[0]

    def test_list_inputs_shape(self):
        ins = modelapi.list_inputs(self.mid)
        self.assertGreater(len(ins), 100)
        self.assertEqual(set(ins[0]), {"cell", "sheet", "label", "period", "value", "fmt", "source"})
        sheets = {i["sheet"] for i in ins}
        self.assertIn("Assumptions", sheets)
        self.assertNotIn("Filings", sheets)                                    # reported figures are not inputs
        t = self.tax_cell()
        self.assertTrue(t["period"].startswith("FY"))
        self.assertIsInstance(t["value"], float)
        self.assertTrue(t["cell"].startswith("Assumptions!"))

    def test_set_inputs_makes_a_new_version_and_changes_outputs(self):
        before = modelapi.get_model(self.mid)
        sha0 = before["bytes_sha256"]
        t = self.tax_cell()
        r = modelapi.set_inputs(self.mid, {t["cell"]: t["value"] + 0.10})
        self.assertEqual(r["model_id"], self.mid)
        self.assertEqual(r["version"], before["version"] + 1)
        self.assertEqual(r["parent"], {"version": before["version"], "bytes_sha256": sha0})
        self.assertTrue(r["checks"]["ok"])
        self.assertEqual(r["checks"]["master"], "OK")
        ch = {o["id"]: o for o in r["edit"]["changed_outputs"]}
        self.assertTrue(ch)
        self.assertTrue(any(o["before"] != o["after"] for o in ch.values()))
        by_old = {o["id"]: o["value"] for o in before["outputs"]}
        by_new = {o["id"]: o["value"] for o in r["outputs"]}
        for i, o in ch.items():
            self.assertEqual(o["before"], by_old[i])
            self.assertEqual(o["after"], by_new[i])
        self.assertEqual(r["edit"]["changes"][0]["before"], t["value"])
        self.assertEqual(r["edit"]["changes"][0]["after"], t["value"] + 0.10)
        # the old version is immutable and still there; untouched zip parts are byte-identical
        self.assertEqual(modelapi.get_model(self.mid, before["version"])["bytes_sha256"], sha0)
        old, new = parts(modelapi.get_bytes(self.mid, before["version"])), parts(modelapi.get_bytes(self.mid, r["version"]))
        self.assertEqual([n for n in old if n in new], list(new))
        touched = set(r["edit"]["parts_touched"])
        self.assertTrue(touched)
        same = [n for n in old if n in new and n not in touched]
        self.assertTrue(same)
        for n in same:
            self.assertEqual(old[n], new[n], n)
        # the new value is what list_inputs now shows; editing again branches from the latest
        self.assertEqual(next(i for i in modelapi.list_inputs(self.mid) if i["cell"] == t["cell"])["value"], t["value"] + 0.10)
        r3 = modelapi.set_inputs(self.mid, {t["cell"]: t["value"]})
        self.assertEqual(r3["parent"]["version"], r["version"])
        self.assertEqual([v["version"] for v in modelapi.list_versions(self.mid)][:3], [1, 2, 3])
        # setting the value it already has is a no-op
        self.assertEqual(modelapi.set_inputs(self.mid, {t["cell"]: t["value"]})["version"], r3["version"])

    def test_only_blue_inputs_may_be_edited(self):
        book = xlsx.read(modelapi.get_bytes(self.mid))
        formula_cell = next(f"IS!{xlsx.ref(r, c)}" for (r, c), x in sorted(book.sheets["IS"].items()) if x.formula and c > 4)
        filing_cell = next(f"Filings!{xlsx.ref(r, c)}" for (r, c), x in sorted(book.sheets["Filings"].items())
                           if isinstance(x.value, (int, float)) and c > 2)
        v0 = len(modelapi.list_versions(self.mid))
        for cell in (formula_cell, filing_cell, "IS!ZZ999", "Nope!A1"):
            with self.subTest(cell=cell), self.assertRaises(modelapi.NotAnInput) as cm:
                modelapi.set_inputs(self.mid, {cell: 1.0})
            self.assertEqual(cm.exception.code, "not_an_input")
            self.assertEqual(cm.exception.detail[0]["cell"], cell)
        with self.assertRaises(modelapi.NotAnInput) as cm:
            modelapi.set_inputs(self.mid, {self.tax_cell()["cell"]: 0.2, formula_cell: 5})        # one bad cell refuses all of them
        self.assertIn("a formula", str(cm.exception))
        with self.assertRaises(modelapi.InvalidRequest):
            modelapi.set_inputs(self.mid, {self.tax_cell()["cell"]: "0.3"})
        with self.assertRaises(modelapi.InvalidRequest):
            modelapi.set_inputs(self.mid, {})
        self.assertEqual(len(modelapi.list_versions(self.mid)), v0)

    def test_ask_reconciles(self):
        a = modelapi.ask(self.mid, "What is revenue in FY2025?", version=1)
        self.assertTrue(a["cells"] and a["values"])
        self.assertTrue(a["reconciled"], a)
        book = xlsx.read(modelapi.get_bytes(self.mid))
        sheet, r, c, _, _ = modelapi.wbgraph.split_key(a["cells"][0])
        self.assertEqual(book.sheets[sheet][(r, c)].value, a["values"][0])
        multi = modelapi.ask(self.mid, "net income", version=1)
        self.assertGreater(len(multi["cells"]), 3)                                # a row across the periods, from one tab
        self.assertTrue(multi["reconciled"])
        nope = modelapi.ask(self.mid, "zxqv blorp")
        self.assertFalse(nope["reconciled"])
        self.assertEqual(nope["cells"], [])
        with self.assertRaises(modelapi.InvalidRequest):
            modelapi.ask(self.mid, "  ")
        # a doctored cached value (formula left alone) no longer reconciles with the independent recalculation
        bad = plant(self.mid, tamper={a["cells"][0]: a["values"][0] + 1})
        lie = modelapi.ask(bad["model_id"], "What is revenue in FY2025?")
        self.assertEqual(lie["cells"], a["cells"])
        self.assertEqual(lie["values"][0], a["values"][0] + 1)
        self.assertFalse(lie["reconciled"])
        self.assertEqual(lie["unreconciled"], a["cells"])

    def test_audit_lists_links_and_catches_a_planted_error(self):
        clean = modelapi.audit(self.mid, 1)
        tabs = {t["sheet"]: t for t in clean["tabs"]}
        self.assertIn("IS", tabs)
        self.assertGreater(tabs["IS"]["formulas"], 50)
        self.assertGreater(tabs["Assumptions"]["inputs"], 100)
        self.assertTrue(tabs["IS"]["links_in"] and tabs["IS"]["links_out"])
        self.assertTrue(all(set(l) == {"sheet", "count"} for l in tabs["IS"]["links_out"]))
        self.assertTrue(any(l["sheet"] == "IS" for l in tabs["CF"]["links_out"] + tabs["BS"]["links_out"]))
        self.assertEqual(tabs["Checks"]["checks"]["error"], 0)
        self.assertGreater(tabs["Checks"]["checks"]["ok"], 5)
        self.assertEqual(sum(len(t["errors"]) for t in clean["tabs"]), 0)
        self.assertEqual(tabs["Filings"]["unsourced"], [])
        book = xlsx.read(modelapi.get_bytes(self.mid, 1))
        target = next(f"IS!{xlsx.ref(r, c)}" for (r, c), x in sorted(book.sheets["IS"].items()) if x.formula and c > 6)
        v = plant(self.mid, {target: "=1/0"})
        bad = modelapi.audit(v["model_id"])
        bt = {t["sheet"]: t for t in bad["tabs"]}
        self.assertIn(target, bt["IS"]["errors"])
        self.assertTrue(any(bt[s]["errors"] for s in ("CF", "BS", "Checks", "DCF")))     # the error propagates downstream
        self.assertTrue(any(f["severity"] == "critical" for f in bad["findings"]))
        json.dumps(bad, allow_nan=False)
        # a cell typed over a formula shows up as a hard-code
        hv = plant(self.mid, {target: 12345.0})
        hard = [c for t in modelapi.audit(hv["model_id"])["tabs"] for c in t["hardcodes"]]
        self.assertIn(target, hard)

    def test_explain_shows_the_source_on_a_historical_leaf(self):
        out = next(o for o in modelapi.get_model(self.mid)["outputs"] if o["id"] == "m3.revenue.2022")
        ex = modelapi.explain(self.mid, f"{out['sheet']}!{out['ref']}", version=1)
        self.assertEqual(ex["value"], out["value"])
        self.assertTrue(ex["inputs"])
        leaf = ex["inputs"][0]
        self.assertTrue(leaf["source"])
        self.assertRegex(leaf["source"], r"\d{10}-\d{2}-\d{6}")                    # accession number of the 10-K
        self.assertTrue(leaf["cell"].startswith("Filings!"))
        self.assertEqual(ex["unsourced_leaves"], [])
        self.assertTrue(out["citations"])
        # a forecast cell traces down through the drivers to blue inputs with no filing source
        fc = next(o for o in modelapi.get_model(self.mid)["outputs"] if o["id"] == "m3.revenue.2026")
        fx_ = modelapi.explain(self.mid, f"{fc['sheet']}!{fc['ref']}", version=1)
        self.assertTrue(fx_["precedents"])
        with self.assertRaises(modelapi.NotFound):
            modelapi.explain(self.mid, "IS!ZZ900", version=1)
        with self.assertRaises(modelapi.InvalidRequest):
            modelapi.explain(self.mid, "not a cell", version=1)

    def test_export_gated(self):
        b, info = modelapi.export_with_report(self.mid, version=1)
        self.assertEqual(b, modelapi.get_bytes(self.mid, 1))
        self.assertTrue(info["gate"]["passed"])
        self.assertEqual(info["warnings"], [])
        man = json.loads(modelapi.export(self.mid, fmt="manifest_json", version=1))
        self.assertTrue(man["outputs"])
        self.assertEqual(man["workbook_sha256"], modelapi.get_model(self.mid, 1)["bytes_sha256"])
        # broken: the master check reads ERROR -> blocked, for every format
        book = xlsx.read(modelapi.get_bytes(self.mid, 1))
        master = next(f"Checks!C{r}" for (r, c), x in sorted(book.sheets["Checks"].items()) if c == 1 and "master" in str(x.value).lower())
        v = plant(self.mid, {master: "ERROR"})
        for fmt in ("xlsx", "xlsx_values", "manifest_json"):
            with self.subTest(fmt=fmt), self.assertRaises(modelapi.Blocked) as cm:
                modelapi.export(v["model_id"], fmt=fmt)
            self.assertEqual(cm.exception.code, "blocked")
            self.assertIsInstance(cm.exception, delivery.DeliveryBlocked)
            self.assertTrue(any(not s["passed"] for s in cm.exception.report["steps"]))
        with self.assertRaises(modelapi.InvalidRequest):
            modelapi.export(self.mid, fmt="pdf")

    def test_values_only_fallback_and_hook(self):
        src = modelapi.get_bytes(self.mid, 1)
        with mock.patch.object(xlsx, "values_only", create=True, side_effect=lambda d: b"VALUES"):
            self.assertEqual(modelapi.export(self.mid, fmt="xlsx_values", version=1), b"VALUES")
        with mock.patch.object(xlsx, "values_only", None, create=True):                # absent: the fallback runs
            out = modelapi.export(self.mid, fmt="xlsx_values", version=1)
        a, b = xlsx.read(src), xlsx.read(out)
        self.assertEqual(a.order, b.order)
        n = 0
        for sh in a.order:
            for rc, cell in a.sheets[sh].items():
                got = b.sheets[sh][rc]
                self.assertIsNone(got.formula, f"{sh}!{rc}")
                self.assertTrue(modelapi._close(cell.value, got.value), f"{sh}!{rc}: {cell.value!r} vs {got.value!r}")
                n += bool(cell.formula)
        self.assertGreater(n, 500)
        names = zipfile.ZipFile(io.BytesIO(out)).namelist()
        self.assertNotIn("xl/calcChain.xml", names)

    def test_logo_paths(self):
        png = b"\x89PNG\r\n\x1a\nfake"
        # absent: ignored with a warning, same bytes as without a logo
        calls = []
        with mock.patch.object(xlsx.Sheet, "image", None, create=True), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            b, info = modelapi.export_with_report(self.mid, logo_png=png, version=1)
        self.assertEqual(b, modelapi.get_bytes(self.mid, 1))
        self.assertTrue(any("no Sheet.image" in n for n in info["warnings"]))
        self.assertTrue(any("logo ignored" in str(x.message) for x in w))
        # present: the model is rebuilt from its stored filings (plus input edits) and the logo is placed on the first sheet
        t = [i for i in modelapi.list_inputs(self.mid) if i["sheet"] == "Assumptions" and "tax" in i["label"].lower()][0]
        edited = modelapi.set_inputs(self.mid, {t["cell"]: round(t["value"] + 0.03, 6)})

        def image(self_, data, anchor):
            calls.append((self_.name, data, anchor))

        with mock.patch.object(xlsx.Sheet, "image", image, create=True):
            b2, info2 = modelapi.export_with_report(self.mid, logo_png=png, version=edited["version"])
        self.assertEqual(calls, [("Cover", png, modelapi.LOGO_ANCHOR)])
        self.assertEqual(info2["warnings"], [])
        self.assertEqual(xlsx.read(b2).order, xlsx.read(modelapi.get_bytes(self.mid, edited["version"])).order)
        self.assertEqual(xlsx.read(b2).value("Assumptions", t["cell"].split("!")[1]), round(t["value"] + 0.03, 6))
        # present but failing: falls back to the stored workbook with a warning
        with mock.patch.object(xlsx.Sheet, "image", mock.Mock(side_effect=RuntimeError("boom")), create=True), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            b3, info3 = modelapi.export_with_report(self.mid, logo_png=png, version=1)
        self.assertEqual(b3, modelapi.get_bytes(self.mid, 1))
        self.assertTrue(any("boom" in n for n in info3["warnings"]))


class UpdateEarningsTests(Base):
    def test_roll_forward_to_the_latest_filing(self):
        m = modelapi.build_model("three_statement", ["AAA"], fetch=lambda t: synthetic_companyfacts(years=(2022, 2023)))
        self.assertEqual(m["version"], 1)
        r = modelapi.update_earnings(m["model_id"], fetch=lambda t: synthetic_companyfacts(years=(2022, 2023, 2024)))
        self.assertEqual((r["model_id"], r["version"]), (m["model_id"], 2))
        self.assertEqual(r["parent"]["version"], 1)
        self.assertEqual(r["parent"]["bytes_sha256"], m["bytes_sha256"])
        self.assertTrue(r["update"]["rolled"])
        self.assertEqual(r["update"]["new_actual"]["year"], 2024)
        self.assertTrue(r["update"]["variance"])
        self.assertIn("roll_forward", r["timings"])
        self.assertGreater(r["timings"]["total"], r["timings"]["roll_forward"])
        self.assertEqual(r["update"]["timings"], r["timings"])
        self.assertTrue(r["checks"]["ok"], r["checks"])
        self.assertTrue(r["outputs"])
        self.assertIn("Roll-forward", xlsx.read(modelapi.get_bytes(m["model_id"])).order)
        # nothing newer: the same version comes back, no new version is written
        again = modelapi.update_earnings(m["model_id"], fetch=lambda t: synthetic_companyfacts(years=(2022, 2023, 2024)))
        self.assertFalse(again["update"]["rolled"])
        self.assertEqual(again["version"], 2)
        self.assertEqual(len(modelapi.list_versions(m["model_id"])), 2)
        # the rolled workbook can still be edited and asked
        inp = modelapi.list_inputs(m["model_id"])
        self.assertTrue(inp)
        self.assertTrue(modelapi.ask(m["model_id"], "revenue FY2024")["cells"])

    def test_only_three_statement_models_roll(self):
        m = modelapi.build_model("lbo", ["AAA"], quotes=QUOTES, fetch=fetch)
        with self.assertRaises(modelapi.InvalidRequest):
            modelapi.update_earnings(m["model_id"], fetch=fetch)
        with self.assertRaises(modelapi.NotFound):
            modelapi.update_earnings("m_" + "1" * 20, fetch=fetch)


class DefaultFetchTests(Base):
    def test_default_fetch_goes_through_om_sec(self):
        class Fake:
            def __init__(self, ua, cache):
                self.ua = ua

            def tickers(self):
                return [{"ticker": "AAA", "cik": 7}]

            def companyfacts(self, cik):
                return {"cik": cik, "facts": {}}

        with mock.patch("om.sec.SecClient", Fake), mock.patch.dict(os.environ, {"SEC_USER_AGENT": "x y@z.co"}):
            self.assertEqual(modelapi.default_fetch("aaa"), {"cik": 7, "facts": {}})
            with self.assertRaises(modelapi.UnsupportedCompany):
                modelapi.default_fetch("nope")


if __name__ == "__main__":
    unittest.main()
