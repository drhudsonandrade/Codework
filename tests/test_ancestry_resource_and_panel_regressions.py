from __future__ import annotations

import json
import math
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_without_optional_numpy():
    """Load the narrow helpers under test without adding NumPy to the static CI image."""
    numpy = types.ModuleType("numpy")
    numpy.isfinite = math.isfinite
    with patch.dict(sys.modules, {"numpy": numpy}):
        return runpy.run_path(
            str(Path(__file__).resolve().parents[1] / "array_pipeline" / "ancestry.py")
        )


def _marker(rsid: str, loadings: list[float]) -> dict:
    return {
        "rsid": rsid,
        "reference_allele": "A",
        "effect_allele": "G",
        "effect_allele_frequency": 0.25,
        "loadings": loadings,
    }


def _panel(markers: list[dict], centroids: dict | None = None) -> dict:
    return {
        "schema": "genoma-ancestry-reference-panel-v1",
        "sources": ["fixture"],
        "markers": markers,
        "population_centroids": centroids or {"EUR": [0.1, 0.2]},
    }


class AncestryRegressionTest(unittest.TestCase):
    def _load(self, payload: dict):
        namespace = _load_without_optional_numpy()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "panel.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return namespace, path, namespace["load_panel"](path)

    def test_panel_rejects_inconsistent_loading_dimensions(self):
        namespace = _load_without_optional_numpy()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "panel.json"
            path.write_text(
                json.dumps(
                    _panel(
                        [_marker("rs1", [0.1, 0.2]), _marker("rs2", [0.3])],
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                namespace["AncestryPanelError"], "loadings.*same length"
            ):
                namespace["load_panel"](path)

    def test_case_reader_closes_row_iterator_explicitly(self):
        namespace = _load_without_optional_numpy()
        closed: list[bool] = []

        class Rows:
            def __init__(self):
                self._done = False

            def __iter__(self):
                return self

            def __next__(self):
                if self._done:
                    raise StopIteration
                self._done = True
                return "raw_snp_array_v1", {
                    "RSID": "rs1",
                    "CHROMOSOME": "1",
                    "POSITION": "1",
                    "RESULT": "AA",
                }

            def close(self):
                closed.append(True)

        with patch("array_pipeline.completeness._row_reader", return_value=Rows()):
            genotypes, _stats = namespace["read_case_genotypes"](
                Path("unused.csv"), {"rs1"}
            )
        self.assertEqual(genotypes, {"rs1": "AA"})
        self.assertEqual(closed, [True])

    def test_panel_rejects_centroids_with_a_different_dimension(self):
        namespace = _load_without_optional_numpy()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "panel.json"
            path.write_text(
                json.dumps(
                    _panel(
                        [_marker("rs1", [0.1, 0.2])],
                        {"EUR": [0.1]},
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                namespace["AncestryPanelError"], "centroid.*2.*components"
            ):
                namespace["load_panel"](path)

    def test_panel_rejects_malformed_marker_fields(self):
        namespace = _load_without_optional_numpy()
        error = namespace["AncestryPanelError"]
        valid = _marker("rs1", [0.1, 0.2])
        mutations = (
            ("rsid", None),
            ("reference_allele", "N"),
            ("effect_allele", "A"),
            ("effect_allele_frequency", 1.5),
            ("effect_allele_frequency", float("nan")),
            ("loadings", [0.1, float("inf")]),
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "panel.json"
            for field, value in mutations:
                marker = dict(valid)
                marker[field] = value
                path.write_text(json.dumps(_panel([marker])), encoding="utf-8")
                with self.subTest(field=field, value=value):
                    with self.assertRaises(error):
                        namespace["load_panel"](path)

    def test_panel_requires_a_non_admixed_reference_centroid(self):
        namespace = _load_without_optional_numpy()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "panel.json"
            path.write_text(
                json.dumps(
                    _panel(
                        [_marker("rs1", [0.1, 0.2])],
                        {"AMR": [0.1, 0.2]},
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                namespace["AncestryPanelError"], "non-admixed"
            ):
                namespace["load_panel"](path)


if __name__ == "__main__":
    unittest.main()
