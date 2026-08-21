"""A homozygosity estimate is a number that always comes back, so every guard needs a control.

F_ROH cannot fail loudly: a sparse array, a low call rate or an unsorted input all produce a
finite fraction that looks like a measurement. Each of those is pinned here with a fixture
where the guard must fire.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.homozygosity import (
    AUTOSOME_KB,
    CHROMOSOME_KB,
    MAX_GAP_KB,
    MIN_CALLED_MARKERS,
    MIN_TRACT_KB,
    MIN_TRACT_MARKERS,
    analyse,
    MAX_TRACT_SPACING_FACTOR,
    find_tracts,
    median_spacing_kb,
)


def _run(chromosome: str, start: int, count: int, step: int, genotype: str):
    return [(chromosome, start + i * step, genotype) for i in range(count)]


#: Spacing used by both the filler and the synthetic tracts. A real array is roughly
#: uniform, and the density guard compares a tract against the sample's own median — so a
#: fixture whose filler is fifty times denser than its tracts would have the guard reject
#: the very runs the test is about, which is a property of the fixture and not of the code.
FIXTURE_STEP = 10_000


def _padding(count: int, *, chromosome: str | None = None, start: int = 1_000_000):
    """Heterozygous filler at the fixture's density, so call-rate and density guards pass.

    Spread across chromosomes 10-22 rather than piled onto one: a hundred thousand markers
    at this spacing is a gigabase, which does not fit on any single chromosome, and a filler
    running past the end of its own chromosome would trip the assembly guard instead.
    """
    if chromosome is not None:
        return [(chromosome, start + i * FIXTURE_STEP, "AG") for i in range(count)]
    out = []
    for name in (str(c) for c in range(10, 23)):
        # Bounded by the chromosome's real length, or the filler runs past its own end and
        # the assembly guard refuses the estimate before the test reaches its subject.
        room = int(CHROMOSOME_KB[name] * 1000) - start - FIXTURE_STEP
        fits = max(0, room // FIXTURE_STEP)
        out += [(name, start + i * FIXTURE_STEP, "AG") for i in range(min(fits, count - len(out)))]
        if len(out) >= count:
            break
    return out[:count]


class TractDetectionTest(unittest.TestCase):
    def test_a_long_dense_homozygous_run_is_a_tract(self):
        tracts, _rejected = find_tracts(_run("1", 1_000_000, 400, 10_000, "AA"))
        self.assertEqual(len(tracts), 1)
        self.assertEqual(tracts[0]["chromosome"], "1")
        self.assertGreaterEqual(tracts[0]["length_kb"], MIN_TRACT_KB)

    def test_a_long_run_with_too_few_markers_is_not_a_tract(self):
        # The density trap: 4 Mb spanned by 20 markers is not a measured run, it is a gap.
        self.assertEqual(find_tracts(_run("1", 1_000_000, 20, 200_000, "AA"))[0], [])

    def test_a_dense_run_that_is_too_short_is_not_a_tract(self):
        self.assertEqual(find_tracts(_run("1", 1_000_000, 300, 1_000, "AA"))[0], [])

    def test_a_gap_larger_than_the_limit_breaks_the_tract(self):
        left = _run("1", 1_000_000, 300, 10_000, "AA")
        right = _run("1", 1_000_000 + 300 * 10_000 + int(MAX_GAP_KB * 1000) + 50_000, 300, 10_000, "AA")
        tracts, _rejected = find_tracts(left + right)
        self.assertEqual(len(tracts), 2, "an uninterrogated gap was absorbed into one run")

    def test_a_heterozygote_run_is_never_a_tract(self):
        self.assertEqual(find_tracts(_run("1", 1_000_000, 400, 10_000, "AG"))[0], [])

    def test_one_heterozygote_is_tolerated_but_two_split_the_run(self):
        base = _run("1", 1_000_000, 400, 10_000, "AA")
        one = list(base)
        one[200] = (one[200][0], one[200][1], "AG")
        self.assertEqual(len(find_tracts(one)[0]), 1)

        two = list(base)
        two[200] = (two[200][0], two[200][1], "AG")
        two[201] = (two[201][0], two[201][1], "AG")
        self.assertEqual(len(find_tracts(two)[0]), 2)

    def test_unsorted_input_does_not_become_one_giant_tract(self):
        # Sorting is done inside; assuming sorted input would make a shuffled file report
        # F_ROH near one, which reads as a dramatic finding rather than as a bug.
        ordered = _run("1", 1_000_000, 400, 10_000, "AA")
        shuffled = ordered[::-1]
        self.assertEqual(find_tracts(shuffled), find_tracts(ordered))

    def test_tracts_do_not_span_chromosomes(self):
        markers = _run("1", 1_000_000, 300, 10_000, "AA") + _run("2", 1_000_000, 300, 10_000, "AA")
        tracts, _rejected = find_tracts(markers)
        self.assertEqual({t["chromosome"] for t in tracts}, {"1", "2"})

    def test_a_tract_begins_and_ends_on_a_homozygous_call(self):
        markers = _run("1", 1_000_000, 300, 10_000, "AA")
        markers.append(("1", 1_000_000 + 300 * 10_000, "AG"))
        tract = find_tracts(markers)[0][0]
        self.assertEqual(tract["end"], 1_000_000 + 299 * 10_000)


class RefusalTest(unittest.TestCase):
    """Too little data must refuse, because the estimator returns a number regardless."""

    def test_a_sparse_array_is_refused(self):
        result = analyse(_run("1", 1_000_000, 5_000, 10_000, "AA"))
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIsNone(result["f_roh"])
        self.assertTrue(any("marcadores autossômicos chamados" in r for r in result["refusals"]))

    def test_a_low_call_rate_is_refused(self):
        markers = _padding(MIN_CALLED_MARKERS + 1000)
        result = analyse(markers, total_autosomal_markers=int(len(markers) / 0.5))
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("taxa de chamada" in r for r in result["refusals"]))

    def test_a_refusal_names_every_guard_that_fired(self):
        result = analyse(_run("1", 1_000_000, 100, 10_000, "AA"), total_autosomal_markers=100_000)
        self.assertEqual(len(result["refusals"]), 2)

    def test_missing_genotypes_are_not_counted_as_homozygous(self):
        # The failure this guards against: a no-call read as homozygous extends every tract
        # through exactly the regions the array could not read.
        called = _run("1", 1_000_000, 400, 10_000, "AA")
        nocalls = [("1", 5_000_000 + i * 10_000, "--") for i in range(400)]
        self.assertEqual(find_tracts(called + nocalls), find_tracts(called))


class AssemblyGuardTest(unittest.TestCase):
    """A fraction of the genome cannot exceed the genome, and the code must notice."""

    def test_a_coordinate_past_the_end_of_its_chromosome_is_refused(self):
        # A position beyond the chromosome means the file is on another assembly or is
        # corrupt. Skipping such markers quietly would leave every tract length wrong.
        markers = _padding(MIN_CALLED_MARKERS, chromosome="1")
        beyond = CHROMOSOME_KB["21"] * 1000 + 5_000_000
        markers += [("21", beyond + i * 10_000, "AA") for i in range(100)]
        result = analyse(markers)
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("além do fim do próprio cromossomo" in r for r in result["refusals"]))

    def test_an_unrecognised_autosome_is_refused(self):
        markers = _padding(MIN_CALLED_MARKERS, chromosome="1")
        markers += [("47", 1_000 + i * 10_000, "AA") for i in range(100)]
        result = analyse(markers)
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("não reconhecidos" in r for r in result["refusals"]))

    def test_a_burden_larger_than_the_autosome_is_refused_not_clamped(self):
        # Clamping to 1.0 would hide the same fault behind a plausible-looking number.
        markers: list = []
        for chromosome, kb in CHROMOSOME_KB.items():
            step = (kb * 1000) // 20_000
            markers += [(chromosome, 1 + i * step, "AA") for i in range(20_000)]
        result = analyse(markers)
        if result["status"] == "INFERIDO":
            self.assertLessEqual(result["f_roh"], 1.0)
        else:
            self.assertIsNone(result["f_roh"])

    def test_the_autosome_denominator_matches_the_per_chromosome_table(self):
        # The two are stated separately and must agree, or F_ROH is scaled by the difference.
        self.assertAlmostEqual(sum(CHROMOSOME_KB.values()) / AUTOSOME_KB, 1.0, places=2)


class EstimateTest(unittest.TestCase):
    def _dense(self, homozygous_kb: float):
        """A synthetic genome with a known homozygous burden and enough density to pass.

        The burden is spread across chromosomes rather than piled onto one: a tract longer
        than its own chromosome is refused by the assembly guard, which is correct, and an
        unphysical fixture would then be testing the guard instead of the estimate.
        """
        markers = _padding(MIN_CALLED_MARKERS)
        remaining = homozygous_kb
        for chromosome in ("1", "2", "3", "4", "5", "6", "7", "8"):
            if remaining <= 0:
                break
            # Stay well inside the shortest of these chromosomes (chr8, 146 Mb).
            take = min(remaining, 120_000.0)
            count = max(MIN_TRACT_MARKERS, int(take / 10) + 1)
            markers += _run(chromosome, 1_000_000, count, 10_000, "AA")
            remaining -= take
        return markers

    def test_no_tracts_gives_zero_and_says_what_that_does_not_prove(self):
        result = analyse(self._dense(0))
        self.assertEqual(result["status"], "INFERIDO")
        self.assertEqual(result["f_roh"], 0.0)
        self.assertIn("não é prova dela", result["interpretation"]["reading"])

    def test_f_roh_is_the_tract_burden_over_the_autosome(self):
        result = analyse(self._dense(30_000))
        self.assertGreater(result["f_roh"], 0)
        expected = result["total_roh_kb"] / result["autosome_kb"]
        self.assertAlmostEqual(result["f_roh"], round(expected, 5), places=5)

    def test_a_high_burden_never_claims_a_relationship(self):
        # 25% of the autosome homozygous is far beyond first cousins, and the text must still
        # refuse to name a relationship: population isolation produces the same tracts.
        result = analyse(self._dense(0.25 * 2_875_001))
        self.assertGreater(result["f_roh"], 0.0625)
        text = result["interpretation"]["reading"] + result["interpretation"]["not_established"]
        self.assertIn("não estabelece grau de parentesco", text)
        self.assertIn("fundador", text)
        for forbidden in ("primos de primeiro grau confirmad", "incesto", "pais são"):
            self.assertNotIn(forbidden, text)

    def test_the_method_cites_its_estimator(self):
        result = analyse(self._dense(20_000))
        self.assertIn("McQuillan", result["method"])
        self.assertIn(str(MIN_TRACT_MARKERS), result["method"])

    def test_reference_expectations_are_offered_for_scale_not_as_thresholds(self):
        result = analyse(self._dense(20_000))
        relationships = {e["relationship"] for e in result["reference_expectations"]}
        self.assertIn("primos de primeiro grau", relationships)
        self.assertTrue(all(0 < e["expected_f_roh"] <= 0.25 for e in result["reference_expectations"]))


if __name__ == "__main__":
    unittest.main()


class SparseTractIsNotAMeasuredRunTest(unittest.TestCase):
    """A run the array spanned without tiling is a coverage hole, not homozygosity.

    `MIN_TRACT_MARKERS` bounds the count and never the density, so fifty homozygous calls
    scattered over five megabases satisfied it — the module's own preamble calls that "a 2 Mb
    gap with four markers in it". Measured on the first real array: the two longest tracts
    averaged 98.7 and 70.1 kb between markers against a sample median of 2.11 kb, and
    together they were 68% of the reported F_ROH. Both lay on chromosome 9, over the
    pericentromeric heterochromatin that arrays barely tile.
    """

    def _sample(self, tract_step: int):
        """Dense filler plus one long run at the requested spacing."""
        markers = _padding(MIN_CALLED_MARKERS)
        markers += _run("1", 1_000_000, 400, tract_step, "AA")
        return markers

    def test_the_median_spacing_is_read_from_the_sample(self):
        median = median_spacing_kb(_padding(1_000))
        self.assertAlmostEqual(median, FIXTURE_STEP / 1000.0, places=2)

    def test_an_empty_sample_has_no_median(self):
        self.assertIsNone(median_spacing_kb([]))

    def test_a_run_at_the_sample_density_is_kept(self):
        result = analyse(self._sample(FIXTURE_STEP))
        self.assertEqual(result["status"], "INFERIDO")
        self.assertEqual(result["tract_count"], 1)
        self.assertEqual(result["tracts_rejected_sparse_count"], 0)

    def test_a_run_far_sparser_than_the_sample_is_rejected(self):
        # 50x the sample's spacing: the span was crossed, not interrogated.
        result = analyse(self._sample(FIXTURE_STEP * 50))
        self.assertEqual(result["tract_count"], 0)
        self.assertEqual(result["f_roh"], 0.0)
        self.assertEqual(result["tracts_rejected_sparse_count"], 1)

    def test_the_rejection_is_reported_with_its_measured_density(self):
        result = analyse(self._sample(FIXTURE_STEP * 50))
        rejected = result["tracts_rejected_sparse"][0]
        self.assertIn("atravessado, não interrogado", rejected["rejected"])
        self.assertGreater(rejected["mean_spacing_kb"], result["max_tract_mean_spacing_kb"])
        self.assertGreater(result["tracts_rejected_sparse_kb"], 0)

    def test_the_sample_median_and_the_derived_limit_are_published(self):
        result = analyse(self._sample(FIXTURE_STEP))
        self.assertAlmostEqual(result["sample_median_spacing_kb"], FIXTURE_STEP / 1000.0, places=2)
        self.assertAlmostEqual(
            result["max_tract_mean_spacing_kb"],
            result["sample_median_spacing_kb"] * MAX_TRACT_SPACING_FACTOR,
            places=2,
        )

    def test_every_kept_tract_carries_its_spacing(self):
        for tract in analyse(self._sample(FIXTURE_STEP))["tracts"]:
            self.assertIn("mean_spacing_kb", tract)
            self.assertLessEqual(tract["mean_spacing_kb"], analyse(self._sample(FIXTURE_STEP))["max_tract_mean_spacing_kb"])

    def test_the_method_text_states_the_density_rule(self):
        result = analyse(self._sample(FIXTURE_STEP))
        self.assertIn("espaçamento médio", result["method"])
        self.assertIn("atravessado, não interrogado", result["method"])
