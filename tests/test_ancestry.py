"""An ancestry estimate is the easiest number in this suite to publish and to get wrong.

Report 02 refused for as long as no reference panel existed. Now that one does, every guard
that replaces the refusal is pinned here with a negative control — a case that must be turned
away — because a projection always returns *some* point, and a wrong one looks exactly like a
right one.
"""
from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from array_pipeline.ancestry import (
    MIN_MARKERS,
    MIN_OVERLAP_FOR_PROPORTIONS,
    UNAVAILABLE,
    AncestryPanelError,
    _dosage,
    _fit_proportions,
    _project_simplex,
    load_panel,
    project_case,
)


def _panel(n_markers: int = 3000, components: int = 4) -> dict:
    """A synthetic panel whose first component separates two named populations."""
    rng = np.random.default_rng(7)
    loadings = rng.normal(size=(components, n_markers))
    loadings /= np.linalg.norm(loadings, axis=1, keepdims=True)
    markers = []
    for i in range(n_markers):
        markers.append(
            {
                "rsid": f"rs{1000 + i}",
                "chromosome": "1",
                "position": 10000 + i * 100,
                "reference_allele": "A",
                "effect_allele": "G",
                "effect_allele_frequency": 0.3,
                "loadings": [float(loadings[k, i]) for k in range(components)],
            }
        )
    return {
        "schema": "genoma-ancestry-reference-panel-v1",
        "id": "TEST-PANEL",
        "version": "t1",
        "sha256": "deadbeef",
        "build": "GRCh37",
        "sources": ["fixture de teste; não é um painel real"],
        "markers": markers,
        "explained_variance_ratio": [0.1] * components,
        "population_centroids": {
            "ALFA": [10.0] + [0.0] * (components - 1),
            "BETA": [-10.0] + [0.0] * (components - 1),
            "GAMA": [0.0, 10.0] + [0.0] * (components - 2),
        },
        "population_counts": {"ALFA": 100, "BETA": 100, "GAMA": 100},
        "limitations": ["fixture"],
    }


def _genotypes(panel: dict, count: int, genotype: str = "AG") -> dict[str, str]:
    return {m["rsid"]: genotype for m in panel["markers"][:count]}


class PanelContractTest(unittest.TestCase):
    def test_a_panel_without_sources_is_refused(self):
        panel = _panel(10)
        panel["sources"] = []
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "p.json"
            path.write_text(json.dumps(panel), encoding="utf-8")
            with self.assertRaises(AncestryPanelError):
                load_panel(path)

    def test_a_panel_with_no_markers_is_refused(self):
        panel = _panel(10)
        panel["markers"] = []
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "p.json"
            path.write_text(json.dumps(panel), encoding="utf-8")
            with self.assertRaises(AncestryPanelError):
                load_panel(path)

    def test_a_gzipped_panel_loads(self):
        panel = _panel(10)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "p.json.gz"
            path.write_bytes(gzip.compress(json.dumps(panel).encode("utf-8")))
            self.assertEqual(load_panel(path)["id"], "TEST-PANEL")


class BuildGuardTest(unittest.TestCase):
    def test_a_build_mismatch_refuses_rather_than_projecting(self):
        # The join is by rsid, so a GRCh38 case would project without error and be subtly
        # wrong wherever an rsid moved between builds.
        panel = _panel()
        with self.assertRaises(AncestryPanelError) as raised:
            project_case(panel, _genotypes(panel, 3000), case_build="GRCh38")
        self.assertIn("GRCh38", str(raised.exception))

    def test_the_matching_build_projects(self):
        panel = _panel()
        result = project_case(panel, _genotypes(panel, 3000), case_build="GRCh37", bootstrap=5)
        self.assertEqual(result["status"], "INFERIDO")


class MarkerThresholdTest(unittest.TestCase):
    def test_too_few_markers_yields_nothing(self):
        panel = _panel()
        result = project_case(panel, _genotypes(panel, MIN_MARKERS - 1), case_build="GRCh37")
        self.assertEqual(result["status"], UNAVAILABLE)
        self.assertIsNone(result["coordinates"])
        self.assertIsNone(result["proportions"])
        self.assertIn(str(MIN_MARKERS), result["reason"])

    def test_low_overlap_keeps_affinity_but_withholds_proportions(self):
        # Shrinkage grows as the overlap falls; affinity is a direction and survives it,
        # proportions are a magnitude and do not.
        panel = _panel(n_markers=5000)
        count = int(5000 * (MIN_OVERLAP_FOR_PROPORTIONS - 0.1))
        result = project_case(panel, _genotypes(panel, count), case_build="GRCh37")
        self.assertEqual(result["status"], "INFERIDO")
        self.assertTrue(result["affinity"])
        self.assertIsNone(result["proportions"])
        self.assertIn("encolh", result["proportions_reason"])

    def test_full_overlap_emits_proportions_with_intervals(self):
        panel = _panel()
        result = project_case(panel, _genotypes(panel, 3000), case_build="GRCh37", bootstrap=20)
        self.assertIsNotNone(result["proportions"])
        total = sum(p["proportion"] for p in result["proportions"])
        self.assertAlmostEqual(total, 1.0, places=3)
        for entry in result["proportions"]:
            self.assertGreaterEqual(entry["proportion"], 0.0)
            self.assertEqual(len(entry["interval_95"]), 2)
            self.assertLessEqual(entry["interval_95"][0], entry["interval_95"][1])

    def test_the_proportions_never_claim_to_be_admixture(self):
        panel = _panel()
        result = project_case(panel, _genotypes(panel, 3000), case_build="GRCh37", bootstrap=5)
        self.assertIn("não é ADMIXTURE", result["proportions_method"])


class StrandAndAlleleTest(unittest.TestCase):
    def test_a_matching_genotype_counts_the_effect_allele(self):
        self.assertEqual(_dosage("AG", "A", "G"), (1, False))
        self.assertEqual(_dosage("GG", "A", "G"), (2, False))
        self.assertEqual(_dosage("AA", "A", "G"), (0, False))

    def test_the_complement_is_resolved_and_reported_as_a_flip(self):
        # A/G on the panel is T/C on the other strand; the dosage must survive the flip and
        # the flip must be counted, because many flips mean the case is on the other strand.
        self.assertEqual(_dosage("TC", "A", "G"), (1, True))
        self.assertEqual(_dosage("CC", "A", "G"), (2, True))

    def test_an_allele_pair_matching_neither_is_dropped(self):
        self.assertEqual(_dosage("AT", "A", "G"), (None, False))
        self.assertEqual(_dosage("--", "A", "G"), (None, False))
        self.assertEqual(_dosage("", "A", "G"), (None, False))

    def test_dropped_and_flipped_markers_are_counted_on_the_result(self):
        panel = _panel()
        genotypes = {m["rsid"]: "AG" for m in panel["markers"]}
        for marker in panel["markers"][:100]:
            genotypes[marker["rsid"]] = "TC"          # other strand
        for marker in panel["markers"][100:150]:
            genotypes[marker["rsid"]] = "AT"          # neither
        result = project_case(panel, genotypes, case_build="GRCh37", bootstrap=5)
        self.assertEqual(result["markers_strand_flipped"], 100)
        self.assertEqual(result["markers_allele_mismatch"], 50)
        self.assertEqual(result["markers_used"], 3000 - 50)


class SimplexTest(unittest.TestCase):
    def test_the_projection_lands_on_the_simplex(self):
        for vector in (np.array([2.0, -1.0, 0.5]), np.array([0.1, 0.1, 0.1]), np.array([-5.0, -5.0, 9.0])):
            projected = _project_simplex(vector)
            self.assertAlmostEqual(float(projected.sum()), 1.0, places=6)
            self.assertTrue((projected >= -1e-9).all())

    def test_a_point_on_a_centroid_fits_almost_entirely_to_it(self):
        centroids = np.array([[10.0, 0.0], [-10.0, 0.0], [0.0, 10.0]])
        weights = _fit_proportions(centroids, np.array([10.0, 0.0]))
        self.assertGreater(weights[0], 0.95)

    def test_a_point_between_two_centroids_splits_between_them(self):
        centroids = np.array([[10.0, 0.0], [-10.0, 0.0], [0.0, 10.0]])
        weights = _fit_proportions(centroids, np.array([0.0, 0.0]))
        self.assertAlmostEqual(float(weights[0]), float(weights[1]), places=2)
        self.assertGreater(weights[0] + weights[1], 0.8)


class ShippedPanelTest(unittest.TestCase):
    """If a panel is committed, it must load and describe itself honestly."""

    PATH = ROOT / "config/ancestry_reference_panel.json.gz"

    @unittest.skipUnless(PATH.is_file(), "reference panel not built in this checkout")
    def test_the_shipped_panel_loads_and_cites_its_sources(self):
        panel = load_panel(self.PATH)
        self.assertTrue(panel["markers"])
        self.assertTrue(panel["sources"])
        self.assertEqual(panel["build"], "GRCh37")

    @unittest.skipUnless(PATH.is_file(), "reference panel not built in this checkout")
    def test_the_shipped_panel_carries_a_native_american_reference(self):
        # Without one, a Brazilian genome's indigenous component would be measured against
        # 1000 Genomes AMR, which is itself admixed.
        panel = load_panel(self.PATH)
        native = [p for p in panel["population_centroids"] if p.startswith("AMR-NAT")]
        self.assertTrue(native, "no indigenous American reference in the panel")
        for population in native:
            self.assertGreater(panel["population_counts"][population], 0)

    @unittest.skipUnless(PATH.is_file(), "reference panel not built in this checkout")
    def test_the_indigenous_reference_includes_an_amazonian_group(self):
        # Nahua, Maya, Quechua and Aymara are Mesoamerican and Andean. Measuring a Brazilian
        # genome's indigenous component against only those is measuring it against related
        # but not local peoples, which the panel used to state as an open limitation.
        panel = load_panel(self.PATH)
        self.assertIn("AMR-NAT-AMAZONIA", panel["population_centroids"])
        self.assertGreater(panel["population_counts"]["AMR-NAT-AMAZONIA"], 0)

    @unittest.skipUnless(PATH.is_file(), "reference panel not built in this checkout")
    def test_the_indigenous_groups_are_not_collapsed_into_one(self):
        panel = load_panel(self.PATH)
        native = {p for p in panel["population_centroids"] if p.startswith("AMR-NAT")}
        self.assertGreaterEqual(len(native), 2, f"indigenous groups collapsed: {native}")

    @unittest.skipUnless(PATH.is_file(), "reference panel not built in this checkout")
    def test_the_panel_states_the_measured_size_of_a_spurious_component(self):
        # The number a reader needs in order to know which components mean nothing. It is
        # measured by projecting individuals of known origin, not asserted.
        panel = load_panel(self.PATH)
        summary = panel.get("validation_summary")
        self.assertIsInstance(summary, dict, "panel carries no validation summary")
        self.assertGreater(summary["largest_spurious_component"], 0)
        self.assertTrue(summary["largest_spurious_example"])

    @unittest.skipUnless(PATH.is_file(), "reference panel not built in this checkout")
    def test_the_allele_orientation_was_measured_rather_than_assumed(self):
        panel = load_panel(self.PATH)
        orientation = panel.get("allele_orientation") or {}
        self.assertIn(orientation.get("decision"), {"ALINHADO", "INVERTIDO", "N/A"})
        if orientation.get("decision") in {"ALINHADO", "INVERTIDO"}:
            # Every comparison must be decisive; a near-zero correlation is a wrong join.
            for comparison in orientation["comparisons"]:
                self.assertGreaterEqual(abs(comparison["correlation"]), 0.85)

    @unittest.skipUnless(PATH.is_file(), "reference panel not built in this checkout")
    def test_every_marker_carries_a_loading_per_component(self):
        panel = load_panel(self.PATH)
        expected = len(panel["explained_variance_ratio"])
        for marker in panel["markers"][:200]:
            self.assertEqual(len(marker["loadings"]), expected)

    @unittest.skipUnless(PATH.is_file(), "reference panel not built in this checkout")
    def test_no_palindromic_marker_survived(self):
        panel = load_panel(self.PATH)
        for marker in panel["markers"]:
            pair = {marker["reference_allele"], marker["effect_allele"]}
            self.assertNotIn(pair, ({"A", "T"}, {"C", "G"}), marker["rsid"])


class ProportionThresholdTest(unittest.TestCase):
    """A larger panel must never be harder to use than a smaller one."""

    def test_the_requirement_is_capped_in_absolute_terms(self):
        from array_pipeline.ancestry import (
            MAX_MARKERS_FOR_PROPORTIONS,
            MIN_OVERLAP_FOR_PROPORTIONS,
        )

        def required(panel_markers: int) -> int:
            return min(
                MAX_MARKERS_FOR_PROPORTIONS,
                int(MIN_OVERLAP_FOR_PROPORTIONS * panel_markers),
            )

        # The regression this guards against: growing the reference from 12,914 markers to
        # 60,000 raised a 60%-of-panel bar from 7,748 to 36,000, so an array that earned
        # proportions against the small panel would be refused by the better one.
        small, large = required(12_914), required(60_000)
        self.assertLessEqual(large, small + 1, "a bigger panel became harder to use")
        self.assertLessEqual(large, MAX_MARKERS_FOR_PROPORTIONS)

    def test_a_tiny_panel_still_uses_the_fraction(self):
        from array_pipeline.ancestry import (
            MAX_MARKERS_FOR_PROPORTIONS,
            MIN_OVERLAP_FOR_PROPORTIONS,
        )

        panel_markers = 3000
        required = min(
            MAX_MARKERS_FOR_PROPORTIONS, int(MIN_OVERLAP_FOR_PROPORTIONS * panel_markers)
        )
        # 60% of 3,000 is 1,800 — the fraction binds, not the cap, so a small panel cannot
        # hand out proportions on a handful of markers.
        self.assertEqual(required, 1800)


if __name__ == "__main__":
    unittest.main()
