"""The pixel-QA comparison must actually be able to fail.

The repository previously shipped a stored pixel-QA PASS with no code that could produce
it, so the claim could not be re-derived or challenged. `scripts/run_editorial_pixel_qa.py`
is the producer; these tests pin the property that makes its PASS meaningful: differences
inside the declared dynamic/control masks are ignored, and differences anywhere else are
detected, down to a fraction of a glyph.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz

from scripts.run_editorial_pixel_qa import MASK_PADDING_PT, _compare_page, _mask_rects

MASK = [fitz.Rect(100, 100, 200, 140)]
DPI = 200


def _page(rect=None, color=(1, 0, 0)):
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 30), "TEXTO ESTATICO DO MODELO", fontsize=9)
    if rect is not None:
        page.draw_rect(fitz.Rect(*rect), color=color, fill=color)
    return doc, page


class PixelComparisonTest(unittest.TestCase):
    def test_identical_pages_report_no_change(self):
        _, a = _page()
        _, b = _page()
        result = _compare_page(a, b, MASK, DPI)
        self.assertTrue(result["comparable"])
        self.assertEqual(result["outside_changed_pixels"], 0)
        self.assertEqual(result["max_channel_diff"], 0)

    def test_change_inside_a_mask_is_ignored(self):
        """Placeholders are supposed to differ; that is the whole point of the masks."""
        _, a = _page()
        _, b = _page(rect=(110, 110, 190, 135))
        result = _compare_page(a, b, MASK, DPI)
        self.assertEqual(result["outside_changed_pixels"], 0)

    def test_change_outside_a_mask_is_detected(self):
        _, a = _page()
        _, b = _page(rect=(20, 160, 60, 180))
        result = _compare_page(a, b, MASK, DPI)
        self.assertGreater(result["outside_changed_pixels"], 0)
        self.assertGreater(result["max_channel_diff"], 0)

    def test_sub_glyph_change_outside_a_mask_is_still_detected(self):
        """A PASS is only worth something if the check is sensitive."""
        _, a = _page()
        _, b = _page(rect=(20, 160, 20.4, 160.4))
        result = _compare_page(a, b, MASK, DPI)
        self.assertGreater(result["outside_changed_pixels"], 0)

    def test_mismatched_raster_size_is_not_reported_as_passing(self):
        _, a = _page()
        doc = fitz.open()
        wider = doc.new_page(width=400, height=200)
        result = _compare_page(a, wider, MASK, DPI)
        self.assertFalse(result["comparable"])
        self.assertIsNone(result["outside_changed_pixels"])

    def test_masks_cover_fields_and_controlled_spans_of_the_requested_page(self):
        meta = {
            "fields": [
                {"page": 1, "bbox": [1, 1, 2, 2], "cell_bbox": [0, 0, 3, 3]},
                {"page": 2, "bbox": [9, 9, 10, 10]},
            ],
            "controlled_spans": [
                {"page": 1, "bbox": [5, 5, 6, 6]},
                {"page": 3, "bbox": [7, 7, 8, 8]},
            ],
        }
        rects = _mask_rects(meta, 1)
        self.assertEqual(len(rects), 3)
        self.assertNotIn(fitz.Rect(9, 9, 10, 10), rects)
        self.assertNotIn(fitz.Rect(7, 7, 8, 8), rects)

    def test_mask_padding_is_declared_and_small(self):
        """Padding absorbs antialiasing at mask edges; it must not hide real drift."""
        self.assertGreater(MASK_PADDING_PT, 0)
        self.assertLessEqual(MASK_PADDING_PT, 2.0)


class PixelQaEvidenceTest(unittest.TestCase):
    EVIDENCE = ROOT / "docs/evidence/EDITORIAL_V3_STATIC_PIXEL_QA_200DPI_2026-08-18.json"

    def test_committed_evidence_is_a_real_measured_pass(self):
        payload = json.loads(self.EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "genoma-editorial-static-pixel-qa-v2")
        self.assertEqual(payload["status"], "VERIFICADO")
        self.assertEqual(payload["aggregate"]["result"], "PASS")
        self.assertEqual(payload["aggregate"]["outside_changed_pixels"], 0)
        self.assertEqual(payload["aggregate"]["reports"], 11)
        self.assertEqual(payload["aggregate"]["reference_pages"], 100)
        self.assertEqual(payload["template_pack"]["verified_reports"], 11)

    def test_evidence_matches_the_pinned_reference_identities(self):
        payload = json.loads(self.EVIDENCE.read_text(encoding="utf-8"))
        index = json.loads((ROOT / "reporting/reference_v3_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            payload["coordinate_compiler"]["manifest_sha256"],
            index["generated_coordinate_manifest"]["sha256"],
        )
        for rid, meta in index["reports"].items():
            self.assertEqual(payload["reports"][rid]["sha256"], meta["sha256"])
            self.assertEqual(payload["reports"][rid]["pages"], meta["page_count"])
            self.assertEqual(
                payload["coordinate_compiler"]["field_counts"][rid], meta["placeholder_count"]
            )


if __name__ == "__main__":
    unittest.main()
