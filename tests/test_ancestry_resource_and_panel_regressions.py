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


class AncestryOptionalNumpyTest(unittest.TestCase):
    """NumPy is an optional adapter here, and absence must be a status, not an ImportError.

    `array_pipeline/ancestry.py` imported NumPy at module scope while it was declared in
    neither `environment.yml`, `reporting/requirements.txt` nor `locks/runtime-lock.json` —
    an undeclared, unpinned core runtime dependency. Importing the module at all failed
    wherever it was missing, so a caller died at import time instead of reading a refusal,
    and the rest of the array pipeline went down with the optional part. The helper above
    exists precisely because NumPy is not in the CI image, which is the evidence that the
    absence is the real case and not a hypothetical one.
    """

    def test_the_module_imports_with_numpy_absent(self):
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def refuse_numpy(name, *args, **kwargs):
            if name == "numpy" or name.startswith("numpy."):
                raise ImportError("No module named 'numpy'")
            return real_import(name, *args, **kwargs)

        with patch.dict(sys.modules), patch("builtins.__import__", side_effect=refuse_numpy):
            sys.modules.pop("numpy", None)
            namespace = runpy.run_path(
                str(Path(__file__).resolve().parents[1] / "array_pipeline" / "ancestry.py")
            )
        self.assertIsNone(namespace["np"])

    def test_projection_refuses_with_a_reason_instead_of_raising(self):
        namespace = _load_without_optional_numpy()
        # `runpy.run_path` hands back a *copy* of the module globals, while the functions it
        # created still close over the original dict. Assigning into the copy changes
        # nothing, so the binding has to be replaced where `project_case` actually reads it.
        globals_of_module = namespace["project_case"].__globals__
        self.addCleanup(globals_of_module.__setitem__, "np", globals_of_module["np"])
        globals_of_module["np"] = None
        panel = {
            "id": "panel", "version": "1", "sha256": "0" * 64, "build": "GRCh37",
            "markers": [_marker(f"rs{i}", [0.1, 0.2]) for i in range(10)],
            "population_counts": {}, "sources": ["fixture"], "limitations": [],
            "population_centroids": {"EUR": [0.0, 0.0]},
        }
        result = namespace["project_case"](panel, {}, case_build="GRCh37")
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIn("NumPy", result["reason"])
        self.assertIsNone(result["proportions"])
        self.assertIsNone(result["coordinates"])
        self.assertEqual(result["affinity"], [])
        # The refusal keeps the same shape as every other refusal here, so a caller does not
        # need a special case for this one.
        self.assertEqual(result["panel"]["build"], "GRCh37")


if __name__ == "__main__":
    unittest.main()
