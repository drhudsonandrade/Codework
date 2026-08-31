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
    """One reference-panel marker with these PCA loadings."""
    return {
        "rsid": rsid,
        "reference_allele": "A",
        "effect_allele": "G",
        "effect_allele_frequency": 0.25,
        "loadings": loadings,
    }


def _panel(markers: list[dict], centroids: dict | None = None) -> dict:
    """A reference panel wrapping these markers and centroids."""
    return {
        "schema": "genoma-ancestry-reference-panel-v1",
        "sources": ["fixture"],
        "markers": markers,
        "population_centroids": centroids or {"EUR": [0.1, 0.2]},
    }


class AncestryRegressionTest(unittest.TestCase):
    """The ancestry panel's validation, exercised with numpy deliberately absent."""
    def _load(self, payload: dict):
        """Load this panel payload through the module imported without numpy."""
        namespace = _load_without_optional_numpy()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "panel.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return namespace, path, namespace["load_panel"](path)

    def test_panel_rejects_inconsistent_loading_dimensions(self):
        """A panel whose markers carry different numbers of loadings is refused."""
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
        """The case reader closes its row iterator explicitly, rather than leaving it to the GC."""
        namespace = _load_without_optional_numpy()
        closed: list[bool] = []

        class Rows:
            """A row iterator that records whether it was closed."""
            def __init__(self):
                """Start undrained."""
                self._done = False

            def __iter__(self):
                """The iterator is its own iterable."""
                return self

            def __next__(self):
                """Yield one row, then stop."""
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
                """Record that the consumer closed this iterator."""
                closed.append(True)

        with patch("array_pipeline.completeness._row_reader", return_value=Rows()):
            genotypes, _stats = namespace["read_case_genotypes"](
                Path("unused.csv"), {"rs1"}
            )
        self.assertEqual(genotypes, {"rs1": "AA"})
        self.assertEqual(closed, [True])

    def test_panel_rejects_centroids_with_a_different_dimension(self):
        """A panel whose centroids have a different dimension from its loadings is refused."""
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
        """Each marker field is validated: mutating any one of them alone is refused."""
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
        """A panel with no non-admixed reference centroid is refused."""
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
        """The module imports with numpy absent."""
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def refuse_numpy(name, *args, **kwargs):
            """An __import__ that refuses numpy and passes everything else through."""
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
        """Without numpy the projection refuses with a reason instead of raising."""
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

    def test_the_whole_load_then_project_path_runs_with_numpy_absent(self):
        """The refusal is only reachable if everything before it is NumPy-free.

        The test above hands `project_case` a panel dict built inline, so it never touched
        `load_panel` — and `load_panel` validated marker frequencies, loadings and centroids
        with `np.isfinite`. With `np = None` that is `AttributeError: 'NoneType' object has
        no attribute 'isfinite'`, raised before the projection's refusal can be reached: a
        caller without NumPy got a crash from the validator instead of a status from the
        projection, which is the import-time failure moved rather than removed.

        The helper `_load_without_optional_numpy` installs a *stub* numpy carrying `isfinite`,
        so every other test in this file exercised the validator with the attribute present.
        This one runs the real entry sequence with the name bound to None.
        """
        namespace = _load_without_optional_numpy()
        globals_of_module = namespace["load_panel"].__globals__
        self.addCleanup(globals_of_module.__setitem__, "np", globals_of_module["np"])
        globals_of_module["np"] = None

        payload = _panel([_marker(f"rs{i}", [0.1, 0.2]) for i in range(10)])
        payload["build"] = "GRCh37"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "panel.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            panel = namespace["load_panel"](path)

        self.assertEqual(10, len(panel["markers"]))
        result = namespace["project_case"](panel, {}, case_build="GRCh37")
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIn("NumPy", result["reason"])

    def test_a_malformed_panel_is_still_refused_by_name_with_numpy_absent(self):
        """Dropping NumPy out of the validator must not drop the validation with it."""
        namespace = _load_without_optional_numpy()
        globals_of_module = namespace["load_panel"].__globals__
        self.addCleanup(globals_of_module.__setitem__, "np", globals_of_module["np"])
        globals_of_module["np"] = None
        error = namespace["AncestryPanelError"]

        cases = {
            "finite numeric loadings": lambda p: p["markers"][0].update(
                {"loadings": [0.1, float("nan")]}
            ),
            "two distinct A/C/G/T alleles": lambda p: p["markers"][0].update(
                {"effect_allele": "A"}
            ),
            "finite components": lambda p: p.update(
                {"population_centroids": {"EUR": [0.1, float("inf")]}}
            ),
        }
        for expected, mutate in cases.items():
            with self.subTest(expected=expected):
                payload = _panel([_marker(f"rs{i}", [0.1, 0.2]) for i in range(3)])
                payload["build"] = "GRCh37"
                mutate(payload)
                with tempfile.TemporaryDirectory() as td:
                    path = Path(td) / "panel.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(error, expected):
                        namespace["load_panel"](path)


if __name__ == "__main__":
    unittest.main()
