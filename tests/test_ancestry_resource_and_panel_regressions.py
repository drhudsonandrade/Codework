from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from array_pipeline.ancestry import AncestryPanelError, load_panel, read_case_genotypes


class AncestryRegressionTest(unittest.TestCase):
    def test_panel_rejects_inconsistent_loading_dimensions(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "panel.json"
            path.write_text(json.dumps({
                "schema": "genoma-ancestry-reference-panel-v1",
                "sources": ["fixture"],
                "markers": [
                    {"rsid": "rs1", "loadings": [0.1, 0.2]},
                    {"rsid": "rs2", "loadings": [0.3]},
                ],
            }), encoding="utf-8")
            with self.assertRaisesRegex(AncestryPanelError, "loadings.*same length"):
                load_panel(path)

    def test_case_reader_closes_row_generator(self):
        closed = []

        def rows():
            try:
                yield "raw_snp_array_v1", {
                    "RSID": "rs1", "CHROMOSOME": "1", "POSITION": "1", "RESULT": "AA"
                }
            finally:
                closed.append(True)

        with patch("array_pipeline.completeness._row_reader", return_value=rows()):
            read_case_genotypes(Path("unused.csv"), {"rs1"})
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
