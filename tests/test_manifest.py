"""ModelManifest export and the hard delivery gate. Offline; om.validate_xlsx / om.recalc are stubbed when absent."""
import contextlib
import hashlib
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from om import delivery, manifest, model3
from om import formula as fx
from om import statements as stm
from om.contracts import ModelManifest
from tests.test_model3 import synthetic_companyfacts


def _stub_validate(passed=True):
    m = types.ModuleType("om.validate_xlsx")
    m.validate = lambda data, *, circ_policy="breaker", require_green_links=True: {
        "passed": passed, "findings": [] if passed else [{"id": "X", "severity": "critical", "sheet": "IS", "cell": "C9", "message": "bad"}],
        "stats": {}}
    return m


def _stub_recalc(agree=True):
    m = types.ModuleType("om.recalc")
    m.compare = lambda data, *, engines=None, tol=1e-6: {
        "agree": agree, "engines": {"om": {"available": True, "reason": "", "cells": 10}}, "divergences": [] if agree else [{"cell": "IS!C9", "values": {}}],
        "compared_cells": 10}
    return m


@contextlib.contextmanager
def stubs(validate=True, recalc=True, force=False):
    mods = {}
    if force or importlib.util.find_spec("om.validate_xlsx") is None:
        mods["om.validate_xlsx"] = _stub_validate(validate)
    if force or importlib.util.find_spec("om.recalc") is None:
        mods["om.recalc"] = _stub_recalc(recalc)
    with mock.patch.dict(sys.modules, mods):
        if "om.validate_xlsx" in mods:
            import om
            with mock.patch.object(om, "validate_xlsx", mods["om.validate_xlsx"], create=True):
                if "om.recalc" in mods:
                    with mock.patch.object(om, "recalc", mods["om.recalc"], create=True):
                        yield
                else:
                    yield
        elif "om.recalc" in mods:
            import om
            with mock.patch.object(om, "recalc", mods["om.recalc"], create=True):
                yield
        else:
            yield


def _build(circ=1, plant=None):
    s = stm.build(synthetic_companyfacts(), "SYN")
    wb, meta = model3.build_workbook(s, circ=circ)
    if plant:
        sh = next(x for x in wb.sheets if x.name == plant[0])
        sh.set(plant[1], "=1/0")
        fx.calculate_workbook(wb)
    return wb.to_bytes(), meta


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.meta = _build(circ=0)

    def test_validates_and_hash(self):
        man = manifest.export(self.data, self.meta)
        ModelManifest.from_dict(man.to_dict())
        self.assertEqual(man.workbook_sha256, hashlib.sha256(self.data).hexdigest())

    def test_default_outputs_cells_and_citations(self):
        man, values = manifest.export_with_values(self.data, self.meta)
        ids = {o.id: o for o in man.outputs}
        for key in ("revenue", "ebitda", "net_income", "eps", "fcf"):
            for fy in (2022, 2023, 2024, 2025, 2029):
                self.assertIn(f"m3.{key}.{fy}", ids)
        self.assertIn("m3.dcf.value_per_share", ids)
        rev = ids["m3.revenue.2023"]
        self.assertEqual((rev.sheet, rev.ref), ("IS", f"D{self.meta['rows']['IS']['rev']}"))
        self.assertAlmostEqual(values["m3.revenue.2023"], 1100.0, places=3)
        self.assertEqual(ids["m3.dcf.value_per_share"].sheet, "DCF")
        for o in man.outputs:
            self.assertGreaterEqual(len(o.citations), 1, o.id)
            self.assertLessEqual(len(o.citations), manifest.MAX_CITATIONS)
            for c in o.citations:
                self.assertEqual(c.sheet, "Filings")
                self.assertTrue(c.source_url.startswith("https://"), c.source_url)
                self.assertEqual(c.sha256_span_hash, hashlib.sha256(c.quote.encode()).hexdigest())
                self.assertIn(c.doc_id, c.quote)

    def test_determinism(self):
        a = manifest.to_json(manifest.export(self.data, self.meta))
        data2, meta2 = _build(circ=0)
        b = manifest.to_json(manifest.export(data2, meta2))
        self.assertEqual(a, b)

    def test_explicit_outputs(self):
        r = self.meta["rows"]["IS"]["rev"]
        meta = dict(self.meta, outputs=[{"id": "x.rev", "sheet": "IS", "ref": f"C{r}", "units": "USD m", "label": "Rev"}])
        man = manifest.export(self.data, meta)
        self.assertEqual([o.id for o in man.outputs], ["x.rev"])
        self.assertGreaterEqual(len(man.outputs[0].citations), 1)


class DeliveryTests(unittest.TestCase):
    def test_clean_build_delivers_three_files(self):
        d1, m1 = _build(circ=1)
        d0, _ = _build(circ=0)
        with stubs(), tempfile.TemporaryDirectory() as td:
            rep = delivery.gate(d1, m1, circ0_data=d0)
            self.assertTrue(rep["passed"], rep["steps"])
            self.assertEqual(rep["manifest"]["workbook_sha256"], hashlib.sha256(d1).hexdigest())
            out = delivery.deliver(d1, m1, os.path.join(td, "out"), name="syn", circ0_data=d0)
            self.assertEqual(set(out), {"xlsx", "manifest", "report"})
            for p in out.values():
                self.assertTrue(os.path.getsize(p) > 0)
            self.assertEqual(len(os.listdir(os.path.join(td, "out"))), 3)

    def test_planted_error_blocks_and_writes_nothing(self):
        data, meta = _build(circ=0, plant=("IS", "E9"))
        with stubs(), tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out")
            with self.assertRaises(delivery.DeliveryBlocked) as cm:
                delivery.deliver(data, meta, out, name="bad")
            self.assertFalse(cm.exception.report["passed"])
            self.assertFalse(os.path.exists(out))

    def test_failing_validate_blocks(self):
        data, meta = _build(circ=0)
        with stubs(validate=False, force=True), tempfile.TemporaryDirectory() as td:
            with self.assertRaises(delivery.DeliveryBlocked) as cm:
                delivery.deliver(data, meta, td, name="bad")
            steps = {s["name"]: s["passed"] for s in cm.exception.report["steps"]}
            self.assertFalse(steps["validate_xlsx"])
            self.assertEqual(os.listdir(td), [])

    def test_recalc_disagreement_blocks(self):
        data, meta = _build(circ=0)
        with stubs(recalc=False, force=True), tempfile.TemporaryDirectory() as td:
            with self.assertRaises(delivery.DeliveryBlocked):
                delivery.deliver(data, meta, td, name="bad")
            self.assertEqual(os.listdir(td), [])

    def test_missing_required_engine_blocks(self):
        data, meta = _build(circ=0)
        with stubs(force=True):
            rep = delivery.gate(data, meta, require_engines=("om", "libreoffice"))
        self.assertFalse(rep["passed"])

    def test_uncited_historical_output_blocks(self):
        data, meta = _build(circ=0)
        # an explicit historical output pointing at a cell with no sourced precedents
        meta = dict(meta, outputs=[{"id": "x.title", "sheet": "IS", "ref": "A2", "units": "USD m", "historical": True}])
        with stubs(force=True):
            rep = delivery.gate(data, meta)
        self.assertFalse(next(s for s in rep["steps"] if s["name"] == "manifest")["passed"])

    @unittest.skipUnless(importlib.util.find_spec("om.validate_xlsx") and importlib.util.find_spec("om.recalc"), "validate_xlsx/recalc not present")
    def test_real_modules(self):
        d0, m0 = _build(circ=0)
        rep = delivery.gate(d0, m0)
        names = [s["name"] for s in rep["steps"]]
        self.assertEqual(names, ["modelcheck.grade", "validate_xlsx", "recalc.compare", "master_check", "manifest"])
        for s in rep["steps"]:
            self.assertIsInstance(s["detail"], str)


if __name__ == "__main__":
    unittest.main()
