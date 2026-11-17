"""S3.9: ModelManifest <-> deck sync with no LLM and no network."""
from __future__ import annotations

import io
import socket
import unittest
import zipfile
from unittest import mock

try:
    import pptx, PIL, fontTools, openpyxl  # noqa: F401
except ImportError as e:
    raise unittest.SkipTest(f"deck deps missing: {e}")

from pptx import Presentation

from om.contracts import ManifestOutput, ModelManifest
from om.deck.model import Element, Para, Run, SolvedSlide, TextSpec
from om.deck.render import render
from om.deck.sync import SyncError, bindings, format_value, resync
from om.deck.theme import Theme

SHA = "a" * 64
CATS = ["FY24", "FY25", "FY26"]


def manifest(units_ev="$bn") -> ModelManifest:
    return ModelManifest(workbook_sha256=SHA, outputs=[
        ManifestOutput(id="rev_series", sheet="IS", ref="B2:D2", units="$m"),
        ManifestOutput(id="ebitda_fy25", sheet="IS", ref="C10", units="$m"),
        ManifestOutput(id="ev", sheet="DCF", ref="B20", units=units_ev),
        ManifestOutput(id="margin", sheet="IS", ref="C12", units="%")])


def deck(ev_units="$bn", ev_manifest_units="$bn") -> bytes:
    chart = Element(id="s1.chart", kind="chart", role="chart", x=1, y=1.5, w=8, h=4,
                    chart={"type": "column", "categories": CATS, "number_format": "0.0", "labels": True,
                           "series": [{"name": "Revenue", "values": [100.0, 110.0, 125.0],
                                       "point_colors": {2: "accent"}}]},
                    binding={"manifest_id": "rev_series", "kind": "chart", "format": "0.0", "units": "$m"})
    other = Element(id="s1.note", kind="text", role="note", x=1, y=6, w=5, h=0.4,
                    text=TextSpec([Para([Run("Static note")])], 12))
    table = Element(id="s2.table", kind="table", role="table", x=1, y=1.5, w=8, h=2,
                    table={"columns": ["Metric", "FY25", "Margin"],
                           "rows": [["EBITDA", "$50.0m", "20.0%"], ["Capex", "$9.0m", "3.0%"]]},
                    binding={"kind": "table", "bindings": {"0,1": "ebitda_fy25", "0,2": "margin"},
                             "format": {"0,1": "$#,##0.0m", "0,2": "0.0%"}})
    kpi = Element(id="s3.kpi", kind="text", role="kpi", x=1, y=2, w=5, h=1.2,
                  text=TextSpec([Para([Run("Enterprise value "), Run("$12.0bn", b=True)])], 40),
                  binding={"manifest_id": "ev", "kind": "value", "format": "$#,##0.0bn", "units": ev_units, "run": 1})
    slides = [SolvedSlide(1, "chart", [chart, other]), SolvedSlide(2, "table", [table]), SolvedSlide(3, "kpi", [kpi])]
    return render(slides, Theme.house(), title="t")


def parts(b: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        return {n: z.read(n) for n in z.namelist()}


def values(**kw) -> dict:
    v = {"rev_series": [100.0, 110.0, 125.0], "ebitda_fy25": 50.0, "ev": 12.0, "margin": 0.2}
    v.update(kw)
    return v


def diff(a: bytes, b: bytes) -> set[str]:
    pa, pb = parts(a), parts(b)
    assert pa.keys() == pb.keys()
    return {n for n in pa if pa[n] != pb[n]}


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.deck = deck()
        self.man = manifest()

    def test_format_value(self):
        self.assertEqual(format_value(12.34, "$#,##0.0bn"), "$12.3bn")
        self.assertEqual(format_value(0.256, "0.0%"), "25.6%")
        self.assertEqual(format_value(14.04, "0.0x"), "14.0x")
        self.assertEqual(format_value(1234567.0, "$#,##0.0m"), "$1,234,567.0m")
        self.assertEqual(format_value(-5.0, "$#,##0.0m"), "-$5.0m")

    def test_bindings_read(self):
        b = bindings(self.deck)
        self.assertEqual(set(b), {"s1.chart", "s2.table", "s3.kpi"})

    def test_no_change_returns_same_bytes(self):
        out, rep = resync(self.deck, self.man, values())
        self.assertEqual(out, self.deck)
        self.assertEqual(rep["changed"], [])

    def test_chart_mutation_only_chart_parts_change(self):
        new = [100.0, 110.0, 140.5]
        out, rep = resync(self.deck, self.man, values(rev_series=new))
        changed = diff(self.deck, out)
        self.assertTrue(any(n.startswith("ppt/charts/chart") and n.endswith(".xml") for n in changed), changed)
        self.assertFalse([n for n in changed if n.startswith("ppt/slides/")], changed)
        self.assertTrue(all(n.startswith("ppt/charts/") or n.startswith("ppt/embeddings/") for n in changed), changed)
        self.assertEqual([c["element"] for c in rep["changed"]], ["s1.chart"])
        self.assertEqual(rep["changed"][0]["old"], [100.0, 110.0, 125.0])
        self.assertEqual(rep["changed"][0]["new"], new)
        prs = Presentation(io.BytesIO(out))
        ch = [s for s in prs.slides[0].shapes if s.has_chart][0].chart
        self.assertEqual(list(ch.plots[0].series[0].values), new)
        # formatting preserved: point colour override still there
        self.assertIn(b"<c:dPt>", parts(out)[next(n for n in changed if n.endswith(".xml") and "charts/chart" in n)])
        # embedded workbook updated
        import openpyxl
        emb = next(n for n in changed if n.startswith("ppt/embeddings/"))
        ws = openpyxl.load_workbook(io.BytesIO(parts(out)[emb])).active
        self.assertEqual([ws.cell(row=r, column=2).value for r in (2, 3, 4)], new)

    def test_table_cell_mutation_only_that_slide_and_cell(self):
        out, rep = resync(self.deck, self.man, values(ebitda_fy25=61.26))
        changed = diff(self.deck, out)
        self.assertEqual(len(changed), 1)
        self.assertTrue(next(iter(changed)).startswith("ppt/slides/slide2"))
        self.assertEqual(rep["changed"][0]["old"], "$50.0m")
        self.assertEqual(rep["changed"][0]["new"], "$61.3m")
        cells = [[c.text for c in r.cells] for r in [s for s in Presentation(io.BytesIO(out)).slides[1].shapes
                                                      if s.has_table][0].table.rows]
        self.assertEqual(cells[1], ["EBITDA", "$61.3m", "20.0%"])
        self.assertEqual(cells[2], ["Capex", "$9.0m", "3.0%"])
        # run formatting kept (size and bold of the original run)
        a = Presentation(io.BytesIO(self.deck)).slides[1]
        b = Presentation(io.BytesIO(out)).slides[1]
        ra = [s for s in a.shapes if s.has_table][0].table.cell(1, 1).text_frame.paragraphs[0].runs[0]
        rb = [s for s in b.shapes if s.has_table][0].table.cell(1, 1).text_frame.paragraphs[0].runs[0]
        self.assertEqual((ra.font.size, ra.font.bold), (rb.font.size, rb.font.bold))

    def test_kpi_text_mutation_replaces_only_bound_run(self):
        out, rep = resync(self.deck, self.man, values(ev=15.678))
        changed = diff(self.deck, out)
        self.assertEqual(len(changed), 1)
        self.assertTrue(next(iter(changed)).startswith("ppt/slides/slide3"))
        sh = [s for s in Presentation(io.BytesIO(out)).slides[2].shapes if s.name == "s3.kpi"][0]
        runs = sh.text_frame.paragraphs[0].runs
        self.assertEqual([r.text for r in runs], ["Enterprise value ", "$15.7bn"])
        self.assertTrue(runs[1].font.bold)
        self.assertEqual(rep["changed"][0]["new"], "$15.7bn")

    def test_only_bound_shape_xml_differs_on_changed_slide(self):
        out, _ = resync(self.deck, self.man, values(rev_series=[1.0, 2.0, 3.0]))
        # slide 1 holds a chart + unbound note; slide XML untouched entirely
        self.assertEqual(parts(self.deck)["ppt/slides/slide1.xml"], parts(out)["ppt/slides/slide1.xml"])
        out2, _ = resync(self.deck, self.man, values(ev=1.0))
        a, b = parts(self.deck)["ppt/slides/slide3.xml"], parts(out2)["ppt/slides/slide3.xml"]
        self.assertNotEqual(a, b)
        self.assertEqual(parts(self.deck)["acretia/bindings.json"], parts(out2)["acretia/bindings.json"])

    def test_unbound_mutation_changes_nothing(self):
        out, rep = resync(self.deck, self.man, values(some_unbound_metric=999.0))
        self.assertEqual(out, self.deck)
        self.assertEqual(rep["changed"], [])

    def test_unknown_manifest_id_raises_naming_element_and_id(self):
        man = ModelManifest(workbook_sha256=SHA, outputs=[o for o in self.man.outputs if o.id != "ev"])
        with self.assertRaises(SyncError) as cm:
            resync(self.deck, man, values())
        self.assertIn("s3.kpi", str(cm.exception))
        self.assertIn("ev", str(cm.exception))

    def test_missing_value_reported_no_change(self):
        v = values()
        del v["ev"]
        out, rep = resync(self.deck, self.man, v)
        self.assertEqual(out, self.deck)
        self.assertEqual(rep["missing"], [{"element": "s3.kpi", "manifest_id": "ev"}])

    def test_units_mismatch_is_error(self):
        with self.assertRaises(SyncError) as cm:
            resync(self.deck, manifest(units_ev="$m"), values())
        self.assertIn("units", str(cm.exception))
        self.assertIn("s3.kpi", str(cm.exception))

    def test_chart_length_mismatch_is_error(self):
        with self.assertRaises(SyncError):
            resync(self.deck, self.man, values(rev_series=[1.0, 2.0]))

    def test_no_network(self):
        def boom(*a, **k):
            raise AssertionError("network used during resync")
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom):
            out, rep = resync(self.deck, self.man, values(rev_series=[9.0, 8.0, 7.0], ev=3.0, ebitda_fy25=1.5))
        self.assertEqual(len(rep["changed"]), 3)
        # deck is still a valid pptx
        self.assertEqual(len(Presentation(io.BytesIO(out)).slides), 3)


if __name__ == "__main__":
    unittest.main()
