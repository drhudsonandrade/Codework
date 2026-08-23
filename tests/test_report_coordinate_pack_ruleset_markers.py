from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fitz

from scripts.build_report_coordinate_pack import (
    CANONICAL_RULESET_CONTROL,
    _controls,
    _ruleset_control_sources,
    compile_pack,
)


class ReportCoordinatePackRulesetMarkerTests(unittest.TestCase):
    def test_canonical_marker_is_accepted(self) -> None:
        self.assertEqual(
            _ruleset_control_sources(f"control={CANONICAL_RULESET_CONTROL}"),
            [CANONICAL_RULESET_CONTROL],
        )

    def test_malformed_marker_is_rejected_even_after_valid_marker(self) -> None:
        text = f"{CANONICAL_RULESET_CONTROL}\nGENOMA-HUDSON-RULESET-v"
        with self.assertRaisesRegex(RuntimeError, "malformed GENOMA ruleset control marker"):
            _ruleset_control_sources(text)

    def test_noncanonical_marker_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "noncanonical GENOMA ruleset control marker"):
            _ruleset_control_sources("GENOMA-HUDSON-RULESET-v3.3")

    def test_multiline_canonical_marker_becomes_one_controlled_span(self) -> None:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "GENOMA-HUDSON-RULESET-", fontsize=12)
        page.insert_text((72, 90), "v3.4", fontsize=12)
        try:
            first_line = page.search_for("GENOMA-HUDSON-RULESET-")[0]
            second_line = page.search_for("v3.4")[0]
            controls = [item for item in _controls(page) if item[0] == CANONICAL_RULESET_CONTROL]
        finally:
            doc.close()
        self.assertEqual(len(controls), 1)
        _, rect, _ = controls[0]
        self.assertLessEqual(rect.y0, first_line.y0)
        self.assertGreaterEqual(rect.y1, second_line.y1)

    def test_compile_pack_fails_closed_if_canonical_occurrence_lacks_controlled_span(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            template_dir = root / "templates"
            template_dir.mkdir()
            pdf = template_dir / "report.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), CANONICAL_RULESET_CONTROL, fontsize=12)
            doc.save(pdf)
            doc.close()

            raw = pdf.read_bytes()
            reference = root / "reference.json"
            reference.write_text(
                json.dumps(
                    {
                        "reports": {
                            "01": {
                                "filename": pdf.name,
                                "sha256": hashlib.sha256(raw).hexdigest(),
                                "size_bytes": len(raw),
                                "page_count": 1,
                                "page_size_pt": [595.0, 842.0],
                                "placeholder_count": 0,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch("scripts.build_report_coordinate_pack._controls", return_value=[]):
                with self.assertRaisesRegex(RuntimeError, "canonical ruleset controlled-span mismatch"):
                    compile_pack(template_dir, reference)


if __name__ == "__main__":
    unittest.main()
