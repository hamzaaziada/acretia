import copy
import json
import unittest

from om.contracts import (CONTRACTS, Citation, ContractError, DeckSpec, DealMemory, GridCell, GridSpec, Job,
                          ModelManifest, ModelSpec, SlideRepairPatch, SlideSpec, SolvedSlideLayout,
                          ValidationReport, WorkbookGraph, sha256_hex)

H = sha256_hex("x")


def cit(**kw):
    d = {"doc_id": "10-K", "sha256_span_hash": H, "page": 3, "bbox_norm": [0.1, 0.2, 0.5, 0.6],
         "quote": "Revenue grew 5%", "source_url": "https://sec.gov/a", "sheet": "IS", "cell": "B4"}
    d.update(kw)
    return d


def manifest(n=3):
    return {"workbook_sha256": H, "outputs": [
        {"id": f"o{i}", "sheet": "DCF", "ref": "C5", "units": "USD m", "citations": [cit()]} for i in range(n)]}


SAMPLES = {
    Citation: cit(),
    WorkbookGraph: {"nodes": {"IS!A1": {"formula": None, "value": 1}, "IS!A2": {"formula": "=A1*2", "value": 2.0},
                              "'My Sheet'!B1": {"value": "x"}},
                    "edges": {"IS!A2": ["IS!A1", "IS!B1:B9"]}, "names": {"Rev": "IS!A1"}},
    ModelSpec: {"ticker": "AAPL", "company": "Apple", "model_type": "dcf", "years": [2024, 2025],
                "scenarios": ["base", "bear"], "assumptions": {"wacc": 0.09, "tags": ["a", None], "on": True}},
    ModelManifest: manifest(),
    SlideSpec: {"id": "s1", "layout": "bullets", "title": "T", "bullets": ["a", "b"], "notes": "n",
                "citations": [cit()], "data": {"k": [1, 2.5]}},
    SolvedSlideLayout: {"slide_id": "s1", "unit": "norm", "width": 1, "height": 1,
                        "boxes": [{"id": "b1", "kind": "title", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.2}]},
    SlideRepairPatch: {"slide_index": 0, "ops": [{"op": "move", "target": "b1", "args": {"dx": -5}}], "reason": "r"},
    DeckSpec: {"deck_id": "d", "title": "Deck", "slides": [{"id": "s1", "layout": "title"},
                                                           {"id": "s2", "layout": "chart"}]},
    GridSpec: {"grid_id": "g", "documents": ["d1", "d2"], "questions": [{"id": "q1", "text": "Revenue?"}]},
    GridCell: {"doc_id": "d1", "question_id": "q1", "answer": "5", "content_hash": H, "citations": [cit()],
               "confidence": 0.9},
    DealMemory: {"deal_id": "x", "name": "Project X", "definitions": {"EBITDA": "adj."},
                 "formatting": {"fmt": {"dec": 1}}, "versions": [
                     {"version": 1, "created_at": "2026-01-01T00:00:00Z"}, {"version": 2, "created_at": "2026-01-02"}]},
    Job: {"id": "j1", "kind": "model", "status": "running", "steps": [{"name": "fetch", "status": "succeeded"}],
          "attempts": 1, "tokens": 10, "cost_usd": 0.25},
    ValidationReport: {"target": "m.xlsx", "passed": False,
                       "findings": [{"rule": "r1", "severity": "critical", "message": "m", "location": "IS!A1"}]},
}


class Base(unittest.TestCase):
    def bad(self, cls, d, prefix, contains=""):
        with self.assertRaises(ContractError) as cm:
            cls.from_dict(d)
        msg = str(cm.exception)
        self.assertTrue(msg.startswith(prefix + ":"), msg)
        self.assertIn(contains, msg)


class RoundTrip(Base):
    def test_every_contract(self):
        self.assertEqual(set(SAMPLES), set(CONTRACTS))
        for cls, d in SAMPLES.items():
            with self.subTest(cls.__name__):
                x = cls.from_dict(d)
                self.assertEqual(cls.from_dict(x.to_dict()), x)
                self.assertEqual(cls.from_json(x.to_json()), x)
                self.assertEqual(json.loads(x.to_json()), x.to_dict())
                self.assertIs(x.validate(), x)

    def test_defaults_and_minimal(self):
        self.assertEqual(Job.from_dict({"id": "j", "kind": "k"}).status, "queued")
        self.assertEqual(ModelSpec.from_dict({"ticker": "A", "model_type": "lbo", "years": [2025]}).scenarios, ["base"])

    def test_bbox_is_tuple_but_serialises_as_list(self):
        c = Citation.from_dict(cit())
        self.assertEqual(c.bbox_norm, (0.1, 0.2, 0.5, 0.6))
        self.assertEqual(c.to_dict()["bbox_norm"], [0.1, 0.2, 0.5, 0.6])

    def test_validate_catches_mutation(self):
        c = Citation.from_dict(cit())
        c.bbox_norm = (0, 0, 2, 1)
        with self.assertRaises(ContractError):
            c.validate()

    def test_sha256_hex(self):
        self.assertEqual(sha256_hex("abc"), sha256_hex(b"abc"))
        self.assertEqual(sha256_hex(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_bad_json(self):
        with self.assertRaises(ContractError):
            Citation.from_json("{nope")
        with self.assertRaises(ContractError):
            Citation.from_json('{"doc_id": "a", "sha256_span_hash": "%s", "page": NaN}' % H)


class Adversarial(Base):
    def test_bbox(self):
        for i, v in [(1, 1.01), (0, -0.0001), (3, float("nan")), (2, float("inf"))]:
            with self.subTest(v=v):
                b = [0.1, 0.2, 0.5, 0.6]
                b[i] = v
                self.bad(Citation, cit(bbox_norm=b), f"Citation.bbox_norm[{i}]")
        self.bad(Citation, cit(bbox_norm=[0.6, 0, 0.5, 1]), "Citation.bbox_norm[2]", "x0")
        self.bad(Citation, cit(bbox_norm=[0, 0.6, 1, 0.5]), "Citation.bbox_norm[3]", "y0")
        self.bad(Citation, cit(bbox_norm=[0, 0, 1]), "Citation.bbox_norm")
        Citation.from_dict(cit(bbox_norm=[0, 0, 1, 1]))
        Citation.from_dict(cit(bbox_norm=None, page=None))

    def test_hash(self):
        for h in (H[:63], H + "0", H.upper(), "g" * 64, H + "\n", ""):
            with self.subTest(h=h):
                self.bad(Citation, cit(sha256_span_hash=h), "Citation.sha256_span_hash")
        self.bad(GridCell, {**SAMPLES[GridCell], "content_hash": H.upper()}, "GridCell.content_hash")
        self.bad(ModelManifest, {**manifest(), "workbook_sha256": "ab"}, "ModelManifest.workbook_sha256")

    def test_bool_is_not_int_or_number(self):
        self.bad(Citation, cit(page=True), "Citation.page", "integer")
        self.bad(Citation, cit(page=0), "Citation.page", ">= 1")
        self.bad(Citation, cit(page=1.0), "Citation.page")
        self.bad(Job, {"id": "j", "kind": "k", "attempts": True}, "Job.attempts")
        self.bad(Job, {"id": "j", "kind": "k", "cost_usd": False}, "Job.cost_usd")
        self.bad(ModelSpec, {**SAMPLES[ModelSpec], "years": [2024, True]}, "ModelSpec.years[1]")
        self.bad(ValidationReport, {"target": "t", "passed": 1}, "ValidationReport.passed", "boolean")

    def test_nan_inf(self):
        for v in (float("nan"), float("inf"), float("-inf")):
            self.bad(Job, {"id": "j", "kind": "k", "cost_usd": v}, "Job.cost_usd", "finite")
            self.bad(GridCell, {**SAMPLES[GridCell], "confidence": v}, "GridCell.confidence")
            self.bad(ModelSpec, {**SAMPLES[ModelSpec], "assumptions": {"w": {"x": [v]}}},
                     "ModelSpec.assumptions['w']['x'][0]")
            self.bad(WorkbookGraph, {"nodes": {"A!A1": {"value": v}}}, "WorkbookGraph.nodes['A!A1'].value")

    def test_enums(self):
        self.bad(Job, {"id": "j", "kind": "k", "status": "done"}, "Job.status", "one of")
        self.bad(ModelSpec, {**SAMPLES[ModelSpec], "model_type": "DCF"}, "ModelSpec.model_type")
        self.bad(SlideRepairPatch, {"slide_index": 0, "ops": [{"op": "move", "target": "a"},
                                                              {"op": "explode", "target": "a"}]},
                 "SlideRepairPatch.ops[1].op")
        f = copy.deepcopy(SAMPLES[ValidationReport])
        f["findings"].append({"rule": "r", "severity": "warn", "message": "m"})
        self.bad(ValidationReport, f, "ValidationReport.findings[1].severity")

    def test_deep_path(self):
        m = manifest(3)
        m["outputs"][2]["citations"][0]["bbox_norm"] = [0, 1.01, 1, 1]
        self.bad(ModelManifest, m, "ModelManifest.outputs[2].citations[0].bbox_norm[1]", "<= 1")

    def test_duplicate_ids(self):
        m = manifest(3)
        m["outputs"][2]["id"] = "o0"
        self.bad(ModelManifest, m, "ModelManifest.outputs[2].id", "duplicate")
        d = copy.deepcopy(SAMPLES[DeckSpec])
        d["slides"][1]["id"] = "s1"
        self.bad(DeckSpec, d, "DeckSpec.slides[1].id")
        self.bad(GridSpec, {"grid_id": "g", "documents": ["a", "a"]}, "GridSpec.documents[1]")
        self.bad(ModelSpec, {**SAMPLES[ModelSpec], "scenarios": ["a", "a"]}, "ModelSpec.scenarios[1]")

    def test_unknown_and_missing_keys(self):
        self.bad(Citation, cit(extra=1), "Citation.extra", "unknown")
        m = manifest(1)
        m["outputs"][0]["citations"][0]["bogus"] = 1
        self.bad(ModelManifest, m, "ModelManifest.outputs[0].citations[0].bogus", "unknown")
        self.bad(Citation, {"doc_id": "x"}, "Citation.sha256_span_hash", "required")
        self.bad(Job, [], "Job", "object")
        self.bad(Job, {"id": "j", "kind": "k", "steps": {}}, "Job.steps", "list")

    def test_range_and_sign_checks(self):
        self.bad(Job, {"id": "j", "kind": "k", "attempts": -1}, "Job.attempts")
        self.bad(Job, {"id": "j", "kind": "k", "cost_usd": -0.01}, "Job.cost_usd")
        self.bad(Job, {"id": "j", "kind": "k", "tokens": 1.5}, "Job.tokens")
        self.bad(Citation, cit(source_url="javascript:alert(1)"), "Citation.source_url")
        self.bad(Citation, cit(cell="b4"), "Citation.cell")
        self.bad(ModelSpec, {**SAMPLES[ModelSpec], "years": [2025, 2024]}, "ModelSpec.years")
        self.bad(ModelSpec, {**SAMPLES[ModelSpec], "ticker": "aapl"}, "ModelSpec.ticker")
        self.bad(ModelManifest, {**manifest(1), "outputs": [{**manifest(1)["outputs"][0], "ref": "C5:"}]},
                 "ModelManifest.outputs[0].ref")

    def test_layout_boxes(self):
        def lay(**box):
            b = {"id": "b", "kind": "body", "x": 0, "y": 0, "w": 0.5, "h": 0.5}
            b.update(box)
            return {"slide_id": "s", "boxes": [b]}
        self.bad(SolvedSlideLayout, lay(w=-0.1), "SolvedSlideLayout.boxes[0].w")
        self.bad(SolvedSlideLayout, lay(x=-1), "SolvedSlideLayout.boxes[0].x")
        self.bad(SolvedSlideLayout, lay(x=0.6), "SolvedSlideLayout.boxes[0].w", "exceeds")
        self.bad(SolvedSlideLayout, lay(kind="blob"), "SolvedSlideLayout.boxes[0].kind")
        SolvedSlideLayout.from_dict({"slide_id": "s", "unit": "emu", "width": 12192000, "height": 6858000,
                                     "boxes": [{"id": "b", "kind": "body", "x": 0, "y": 0, "w": 12192000, "h": 1}]})
        self.bad(SolvedSlideLayout, {"slide_id": "s", "unit": "emu", "width": 100, "height": 100,
                                     "boxes": [{"id": "b", "kind": "body", "x": 50, "y": 0, "w": 51, "h": 1}]},
                 "SolvedSlideLayout.boxes[0].w")

    def test_graph(self):
        self.bad(WorkbookGraph, {"nodes": {"A1": {}}}, "WorkbookGraph.nodes['A1']", "match")
        self.bad(WorkbookGraph, {"nodes": {"S!A1": {"formula": "A1+1"}}}, "WorkbookGraph.nodes['S!A1'].formula")
        self.bad(WorkbookGraph, {"nodes": {"S!A1": {}}, "edges": {"S!B1": ["S!A1"]}}, "WorkbookGraph.edges['S!B1']")
        self.bad(WorkbookGraph, {"nodes": {"S!A1": {}}, "edges": {"S!A1": ["S!A1", "S!A1"]}},
                 "WorkbookGraph.edges['S!A1'][1]")
        self.bad(WorkbookGraph, {"nodes": {"S!A1": {"value": [1]}}}, "WorkbookGraph.nodes['S!A1'].value")

    def test_report_and_memory(self):
        self.bad(ValidationReport, {"target": "t", "passed": True, "findings": [
            {"rule": "r", "severity": "high", "message": "m"}]}, "ValidationReport.passed")
        ValidationReport.from_dict({"target": "t", "passed": True, "findings": [
            {"rule": "r", "severity": "low", "message": "m"}]})
        d = copy.deepcopy(SAMPLES[DealMemory])
        d["versions"][1]["version"] = 1
        self.bad(DealMemory, d, "DealMemory.versions[1].version")
        d["versions"][1].update(version=2, created_at="yesterday")
        self.bad(DealMemory, d, "DealMemory.versions[1].created_at")
        self.bad(DealMemory, {**SAMPLES[DealMemory], "definitions": {"a": 1}}, "DealMemory.definitions['a']")
        self.bad(SlideRepairPatch, {"slide_index": -1, "ops": [{"op": "move", "target": "a"}]},
                 "SlideRepairPatch.slide_index")
        self.bad(SlideRepairPatch, {"slide_index": 0, "ops": []}, "SlideRepairPatch.ops")


if __name__ == "__main__":
    unittest.main()
