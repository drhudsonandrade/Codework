from __future__ import annotations

import json
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_without_optional_numpy():
    """Load the narrow helpers under test without adding NumPy to the static CI image."""
    module_path = Path(__file__).resolve().parents[1] / "array_pipeline" / "ancestry.py"
    with patch.dict(sys.modules, {"numpy": types.ModuleType("numpy")}):
        return runpy.run_path(str(module_path))


class AncestryRegressionTest(unittest.TestCase):
    def test_panel_rejects_inconsistent_loading_dimensions(self):
        namespace = _load_without_optional_numpy()
        error = namespace["AncestryPanelError"]
        load_panel = namespace["load_panel"]
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
            with self.assertRaisesRegex(error, "loadings.*same length"):
                load_panel(path)

    def test_case_reader_closes_row_generator(self):
        namespace = _load_without_optional_numpy()
        read_case_genotypes = namespace["read_case_genotypes"]
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

    def test_panel_rejects_centroids_with_a_different_dimension(self):
        namespace = _load_without_optional_numpy()
        error = namespace["AncestryPanelError"]
        load_panel = namespace["load_panel"]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "panel.json"
            path.write_text(json.dumps({
                "schema": "genoma-ancestry-reference-panel-v1",
                "sources": ["fixture"],
                "markers": [{"rsid": "rs1", "loadings": [0.1, 0.2]}],
                "population_centroids": {"EUR": [0.1]},
            }), encoding="utf-8")
            with self.assertRaisesRegex(error, "centroid.*2 components"):
                load_panel(path)


if __name__ == "__main__":
    unittest.main()
