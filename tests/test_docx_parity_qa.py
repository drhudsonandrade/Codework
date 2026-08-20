"""DOCX parity: measure what is preserved, and never call it pixel parity.

The DOCX artifact previously carried a prose claim of "alta fidelidade visual" with no
measurement behind it. These tests pin the two things the measurement must keep separate:
structural parity is a gate (page count and geometry), visual similarity is an observation
(recorded, bounded only to catch catastrophic regressions).
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

from scripts.run_docx_parity_qa import (
    GEOMETRY_TOLERANCE_PT,
    MAX_DIFFERING_FRACTION,
    MAX_RMSE,
    _compare,
)

def _newest_evidence(pattern: str) -> Path:
    """The most recent matching evidence artefact, not a hard-coded date.

    Pinning a filename means the test keeps validating evidence for a template pack that may
    no longer exist: re-running the QA writes a new dated artefact and the assertions stay on
    the old one, which then passes while describing something that is not shipped. The names
    carry ISO dates, so lexicographic order is chronological.
    """
    found = sorted((ROOT / "docs/evidence").glob(pattern))
    if not found:
        raise AssertionError(f"no evidence artefact matches {pattern}")
    return found[-1]


EVIDENCE = _newest_evidence("EDITORIAL_V3_DOCX_PARITY_150DPI_*.json")


def _doc(width=595.3, height=841.9, fill=None, pages=1):
    document = fitz.open()
    for _ in range(pages):
        page = document.new_page(width=width, height=height)
        page.insert_text((40, 60), "CONTEUDO DO MODELO", fontsize=11)
        if fill:
            page.draw_rect(fitz.Rect(0, 0, width, height), color=fill, fill=fill)
    return document


class DocxComparisonTest(unittest.TestCase):
    def test_identical_render_reports_no_difference(self):
        result = _compare(_doc(), _doc(), 100)
        self.assertTrue(result["geometry_preserved"])
        self.assertEqual(result["worst_differing_pixel_fraction"], 0.0)
        self.assertEqual(result["worst_rmse"], 0.0)

    def test_changed_page_geometry_fails_structural_parity(self):
        result = _compare(_doc(), _doc(width=500), 100)
        self.assertFalse(result["geometry_preserved"])

    def test_lost_visual_plate_exceeds_the_regression_envelope(self):
        result = _compare(_doc(), _doc(fill=(1, 0, 0)), 100)
        self.assertGreater(result["worst_differing_pixel_fraction"], MAX_DIFFERING_FRACTION)
        self.assertGreater(result["worst_rmse"], MAX_RMSE)

    def test_geometry_tolerance_is_sub_point(self):
        """Tolerance absorbs rounding, not a real page-size change."""
        self.assertGreater(GEOMETRY_TOLERANCE_PT, 0)
        self.assertLessEqual(GEOMETRY_TOLERANCE_PT, 1.0)


class DocxParityEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_structural_parity_is_the_gated_claim(self):
        self.assertEqual(self.payload["schema"], "genoma-editorial-docx-parity-v1")
        self.assertEqual(self.payload["status"], "VERIFICADO")
        self.assertEqual(self.payload["aggregate"]["structural_parity"], "PASS")
        self.assertEqual(self.payload["aggregate"]["reports"], 11)
        for report in self.payload["reports"].values():
            self.assertTrue(report["structural_parity"]["page_count_matches"])
            self.assertTrue(report["structural_parity"]["geometry_preserved"])

    def test_page_counts_match_the_pinned_reference(self):
        index = json.loads((ROOT / "reporting/reference_v3_manifest.json").read_text(encoding="utf-8"))
        for rid, meta in index["reports"].items():
            self.assertEqual(self.payload["reports"][rid]["pages"], meta["page_count"])
            self.assertEqual(self.payload["reports"][rid]["sha256"], meta["sha256"])

    def test_visual_similarity_is_reported_not_claimed_as_parity(self):
        """A residual difference is expected; the evidence must not read as pixel parity."""
        aggregate = self.payload["aggregate"]
        self.assertGreater(aggregate["worst_differing_pixel_fraction"], 0.0)
        self.assertTrue(aggregate["within_envelope"])
        self.assertIn("never", self.payload["contract"])
        self.assertIn("not a parity claim", self.payload["envelope"]["purpose"])
        joined = " ".join(self.payload["limitations"]).lower()
        self.assertIn("renderer-dependent", joined)
        self.assertIn("authoritative", joined)

    def test_evidence_names_the_engine_it_measured(self):
        self.assertIn("LibreOffice", self.payload["renderer"]["engine"])


if __name__ == "__main__":
    unittest.main()
