"""S8.1 standards knowledge base: schema, coverage, citations, no-copy guard and retrieval (offline)."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

from om.intl.standards import RECIPE_IDS, load

ROOT = Path(__file__).resolve().parent.parent
FRAMEWORKS = {"IFRS", "EAS", "SOCPA-IFRS", "UAE-IFRS", "FRS102", "IndAS", "USGAAP"}
TOPICS = {"leases", "revenue", "inventory", "development_costs", "revaluation", "impairment_reversal", "borrowing_costs",
          "associates_jvs", "hyperinflation", "fx_devaluation", "zakat_tax", "end_of_service", "government_grants",
          "eas_ifrs_mapping"}
STANDARDS = ["IFRS 15", "IFRS 16", "IFRS 9", "IFRS 3", "IFRS 10", "IFRS 11", "IFRS 12", "IAS 2", "IAS 7", "IAS 12", "IAS 16",
             "IAS 19", "IAS 20", "IAS 21", "IAS 23", "IAS 28", "IAS 29", "IAS 36", "IAS 37", "IAS 38", "IAS 40", "IFRS 8",
             "IAS 24", "IAS 33", "IAS 1", "IFRS 18"]


def all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from all_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from all_strings(v)


class StandardsKB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = load(force=True)

    def test_frameworks_and_layout(self):
        self.assertTrue(FRAMEWORKS <= set(self.kb.frameworks))
        for fid, f in self.kb.frameworks.items():
            p = f["presentation"]
            for k in ("pnl_layout", "balance_sheet_order", "oci", "required_line_items", "cash_flow"):
                self.assertTrue(p.get(k), (fid, k))
            for st in ("IS", "BS", "CF"):
                self.assertTrue(p["required_line_items"][st], (fid, st))
            for k in ("measurement_bases", "key_disclosures", "relationship_to_ifrs", "effective_dates", "summary"):
                self.assertTrue(f.get(k), (fid, k))
            self.assertEqual(f["authored"], "acretia")
            self.assertIn(f["confidence"], ("verified", "unverified"))
            self.assertTrue(f["citations"])

    def test_difference_schema(self):
        ids = set()
        for d in self.kb.differences:
            for k in ("id", "topic", "frameworks", "summary", "analyst_impact", "adjustment", "citations", "authored", "confidence"):
                self.assertTrue(d.get(k), (d.get("id"), k))
            self.assertNotIn(d["id"], ids)
            ids.add(d["id"])
            self.assertEqual(d["authored"], "acretia")
            self.assertIn(d["confidence"], ("verified", "unverified"))
            self.assertIn(d["adjustment"], RECIPE_IDS, d["id"])
            self.assertTrue(set(d["frameworks"]) <= FRAMEWORKS, d["id"])
            for c in d["citations"]:
                self.assertTrue(c["standard"] and c["ref"], d["id"])
                self.assertTrue(re.match(r"https://[\w.-]+/", c["url"]), (d["id"], c["url"]))

    def test_topic_and_recipe_coverage(self):
        topics = {d["topic"] for d in self.kb.differences}
        self.assertTrue(TOPICS <= topics, TOPICS - topics)
        self.assertEqual(set(RECIPE_IDS), set(self._contract_recipes()))
        used = {d["adjustment"] for d in self.kb.differences}
        self.assertGreaterEqual(len(used), 16)
        ids = {d["id"] for d in self.kb.differences}
        self.assertTrue({"diff-leases-ifrs16-asc842", "diff-leases-eas49", "diff-eas-ifrs-new-standards"} <= ids)
        eas = " ".join(d["summary"] for d in self.kb.find(topic="eas_ifrs_mapping"))
        for n in ("EAS 47", "EAS 48", "EAS 49"):
            self.assertIn(n, eas)

    def _contract_recipes(self):
        txt = (ROOT / "docs/s8/contract.md").read_text(encoding="utf-8")
        block = txt.split("## Adjustment recipe ids", 1)[1].split("Signature:", 1)[0]
        return re.findall(r"`([a-z0-9_]+)`", block)

    def test_ifrs_depth(self):
        have = {s["standard"] for s in self.kb.standards}
        self.assertEqual(set(STANDARDS) - have, set())
        for s in self.kb.standards:
            self.assertTrue(s["citations"] and s["summary"] and s["analyst_impact"], s["id"])
            self.assertEqual(s["authored"], "acretia")
            if s.get("adjustment"):
                self.assertIn(s["adjustment"], RECIPE_IDS)

    def test_no_copy_guard(self):
        quote = re.compile(r'["“”]([^"“”]+)["“”]')
        data = [self.kb.frameworks, self.kb.differences, self.kb.standards]
        for text in all_strings(data):
            for m in quote.finditer(text):
                self.assertLessEqual(len(m.group(1).split()), 25, m.group(1)[:80])
        # no long verbatim runs shared across entries: sanity check on paragraph reuse
        seen = {}
        for d in self.kb.differences:
            s = re.sub(r"\s+", " ", d["summary"])
            self.assertNotIn(s, seen)
            seen[s] = d["id"]

    def test_docs_present_and_consistent(self):
        base = ROOT / "docs/s8/standards"
        self.assertTrue((base / "README.md").exists())
        for fid in self.kb.frameworks:
            self.assertTrue((base / f"{fid.lower()}.md").exists(), fid)
        text = (base / "differences.md").read_text(encoding="utf-8")
        for d in self.kb.differences:
            self.assertIn(d["id"], text)

    def test_docs_match_generator(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/gen_standards_docs.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_verification_fields(self):
        for e in list(self.kb.differences) + list(self.kb.frameworks.values()):
            for v in e.get("verified_facts", []):
                self.assertTrue(v["fact"] and v["url"].startswith("https://"), e["id"] if "id" in e else e["name"])
            if e["confidence"] == "verified":
                self.assertFalse(e.get("unverified_facts"), e.get("id"))
            if e.get("unverified_facts"):
                self.assertEqual(e["confidence"], "unverified")
        flipped = {"diff-zakat-vs-income-tax", "diff-uae-corporate-tax", "diff-uae-dmtt-pillar-two", "diff-egypt-income-tax",
                   "diff-hyperinflation-ias29", "diff-eosb-ksa", "diff-leases-indas116", "diff-indas-applicability"}
        by = {d["id"]: d for d in self.kb.differences}
        for i in flipped:
            self.assertEqual(by[i]["confidence"], "verified", i)
            self.assertTrue(by[i]["verified_facts"], i)

    def test_new_entries_and_facts(self):
        ids = {d["id"] for d in self.kb.differences}
        self.assertTrue({"diff-leases-indas116", "diff-eas17-separate-fs", "diff-indas-applicability", "diff-uae-dmtt-pillar-two"} <= ids)
        txt = " ".join(d["summary"] for d in self.kb.differences)
        for needle in ("2.5 percent", "20 percent", "AED 375,000", "15 percent", "EUR 750 million", "INR 250 crore"):
            self.assertIn(needle, txt)
        std = {s["standard"]: s["summary"] for s in self.kb.standards}
        for k, words in {"IFRS 9": ["stage", "forward-looking"], "IAS 12": ["balance-sheet liability", "substantively enacted"],
                         "IAS 16": ["cost model", "revaluation model"], "IAS 19": ["projected unit credit", "OCI"],
                         "IAS 23": ["qualifying asset", "substantial period"], "IAS 36": ["higher of", "cash-generating"],
                         "IAS 37": ["probable", "contingent liabilities"], "IAS 38": ["technical feasibility", "Research"],
                         "IAS 40": ["cost model", "fair value model"], "IFRS 8": ["10 percent", "75 percent", "CODM"],
                         "IAS 24": ["Key management"], "IAS 33": ["dilutive", "antidilutive"],
                         "IFRS 15": ["five-step", "contracts with customers"], "IFRS 16": ["right-of-use asset", "lease liability"]}.items():
            for w in words:
                self.assertIn(w.lower(), std[k].lower(), (k, w))

    def test_more_answers(self):
        cases = [("What is the UAE Domestic Minimum Top-up Tax rate?", "diff-uae-dmtt-pillar-two"),
                 ("When does Ind AS apply to a company with net worth of INR 250 crore?", "diff-indas-applicability"),
                 ("Ind AS 116 differences from IFRS 16", "diff-leases-indas116"),
                 ("equity method in separate financial statements in Egypt EAS 17", "diff-eas17-separate-fs"),
                 ("Saudi end of service award calculation", "diff-eosb-ksa"),
                 ("how do I strip devaluation FX losses out of recurring EBITDA", "diff-fx-devaluation-ias21")]
        for q, want in cases:
            self.assertIn(want, [e["id"] for e in self.kb.answer(q).entries], q)

    def test_find(self):
        self.assertTrue(self.kb.find(topic="leases"))
        self.assertTrue(all("EAS" in d["frameworks"] for d in self.kb.find(framework="EAS")))
        self.assertTrue(self.kb.find(topic="lifo", framework="USGAAP"))
        self.assertEqual(self.kb.find(topic="no-such-topic-xyz"), [])

    def test_answer_samples(self):
        cases = [
            ("How does an operating lease differ between IFRS 16 and ASC 842?", "diff-leases-ifrs16-asc842"),
            ("Is LIFO allowed under IFRS?", "diff-inventory-lifo"),
            ("What is zakat and how is it different from income tax in Saudi Arabia?", "diff-zakat-vs-income-tax"),
            ("What happens to Egyptian companies with USD debt after a devaluation of the pound?", "diff-fx-devaluation-ias21"),
            ("How is end of service gratuity accounted for in the UAE?", "diff-eosb-gcc-egypt"),
            ("Which IFRS standard corresponds to EAS 48?", "diff-eas-ifrs-new-standards"),
            ("Can development costs be capitalised under US GAAP?", "diff-development-costs"),
            ("When does IAS 29 hyperinflation accounting apply?", "diff-hyperinflation-ias29"),
            ("Are impairment reversals allowed?", "diff-impairment-reversal"),
            ("Can I revalue property under US GAAP?", "diff-revaluation"),
            ("how to treat government grants and subsidies", "diff-government-grants"),
            ("كيف تعامل الزكاة في السعودية", "diff-zakat-vs-income-tax"),
            ("EOSB provision as debt", "diff-eosb-gcc-egypt"),
            ("ZATCA", "diff-zakat-vs-income-tax"),
        ]
        for q, want in cases:
            a = self.kb.answer(q)
            self.assertIn(want, [e["id"] for e in a.entries], q)
            self.assertTrue(a.text and a.citations, q)
            for c in a.citations:
                self.assertTrue(c["url"].startswith("https://"))

    def test_answer_unrelated_returns_empty(self):
        a = self.kb.answer("what is the best pizza recipe")
        self.assertEqual(a.entries, [])
        self.assertEqual(a.citations, [])

    def test_deterministic(self):
        q = "ifrs 16 vs asc 842 ebitda"
        self.assertEqual(self.kb.answer(q).text, self.kb.answer(q).text)


if __name__ == "__main__":
    unittest.main()
