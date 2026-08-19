"""A quantified residual must not become a way to publish an unquantified one.

`array_pipeline/allele_discrimination.py` exists to turn an all-or-nothing refusal into a
measurement, which means it emits diplotypes and phenotypes the previous code refused. Every
one of those emissions is a new place a partial panel could be read as a complete one, so
each guard here is paired with a negative control: a fixture where the guard *must* fire, so
that a passing test proves the check works rather than proving the fixture was easy.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.allele_discrimination import (
    ALTERED,
    NORMAL,
    UNAVAILABLE,
    UNCERTAIN,
    analyse_gene,
    conditional_diplotype,
    conditional_phenotype,
    function_bucket,
    partition_alleles,
    residual_risk,
    sequencing_requisition,
)

#: Two alleles: *2 defined by one position, *3 by two. A panel carrying only rs1 can
#: discriminate *2 and cannot discriminate *3.
SPEC = {
    "reference_allele": "G*1",
    "phenotype_map": {
        "*2/*1": {"phenotype": "Intermediate Metabolizer", "activity_score": "1.0"},
        "*1/*1": {"phenotype": "Normal Metabolizer", "activity_score": "2.0"},
        "*2/*2": {"phenotype": "Poor Metabolizer", "activity_score": "0.0"},
    },
    "alleles": {
        "G*2": {
            "defining": [{"rsid": "rs1", "allele": "A", "position": 100, "chromosome": "chr1"}],
            "cpic_clinical_function": "No function",
            "cpic_frequency": {"European": 0.15, "African": 0.20},
        },
        "G*3": {
            "defining": [
                {"rsid": "rs2", "allele": "T", "position": 200, "chromosome": "chr1"},
                {"rsid": "rs3", "allele": "C", "position": 300, "chromosome": "chr1"},
            ],
            "cpic_clinical_function": "Decreased function",
            "cpic_frequency": {"European": 0.05, "African": 0.01},
        },
    },
}

FINDING_DETECTED_HET = {
    "allele": "G*2",
    "status": "DETECTADO",
    "zygosity": "HETEROZIGOTO",
    "positions": [{"rsid": "rs1", "genotype": "GA", "interrogable": True}],
}
FINDING_ABSENT = {
    "allele": "G*2",
    "status": "NÃO DETECTADO",
    "zygosity": None,
    "positions": [{"rsid": "rs1", "genotype": "GG", "interrogable": True}],
}


def _analyse(classifications, findings, heterozygous, spec=SPEC):
    return analyse_gene("G", spec, classifications, findings, heterozygous)


class FunctionBucketTest(unittest.TestCase):
    """An unrecognised CPIC label must never be read as normal function."""

    def test_cpic_vocabulary_maps_to_the_expected_buckets(self):
        self.assertEqual(function_bucket("Normal function"), NORMAL)
        for label in ("No function", "Decreased function", "Increased function"):
            self.assertEqual(function_bucket(label), ALTERED)
        for label in ("Uncertain function", "Unknown function"):
            self.assertEqual(function_bucket(label), UNCERTAIN)

    def test_an_unknown_label_is_uncertain_not_normal(self):
        # Negative control for the fail-open direction: if CPIC renames a status, the
        # residual must grow, not shrink.
        for label in (None, "", "Diminished activity", "função reduzida"):
            self.assertEqual(function_bucket(label), UNCERTAIN, label)

    def test_analysis_surfaces_labels_it_did_not_recognise(self):
        spec = {
            "reference_allele": "G*1",
            "alleles": {
                "G*2": {
                    "defining": [{"rsid": "rs1", "allele": "A"}],
                    "cpic_clinical_function": "Mildly diminished",
                }
            },
        }
        result = _analyse({"rs1": "OBSERVADO"}, [], [], spec=spec)
        self.assertEqual(result["unrecognised_function_labels"], ["Mildly diminished"])


class PartitionTest(unittest.TestCase):
    def test_an_allele_is_discriminable_only_when_every_position_is_interpretable(self):
        partition = partition_alleles(SPEC, {"rs1": "OBSERVADO", "rs2": "OBSERVADO"})
        self.assertEqual(partition["discriminable"], ["G*2"])
        self.assertEqual(partition["indiscriminable"], ["G*3"])
        # rs3 was never read, so it is the gap; rs2 was, so it is not.
        self.assertEqual(partition["positions_missing"], ["rs3"])

    def test_non_interpretable_classes_do_not_count_as_interrogated(self):
        for classification in ("NO-CALL", "NÃO TESTADO", "NÃO REPORTÁVEL"):
            partition = partition_alleles(SPEC, {"rs1": classification})
            self.assertEqual(partition["discriminable"], [], classification)

    def test_an_allele_with_no_defining_positions_is_never_discriminable(self):
        # Vacuous truth: `all()` over an empty requirement is True, which would have made an
        # allele with no definition at all look fully covered.
        spec = {"reference_allele": "G*1", "alleles": {"G*9": {"defining": []}}}
        partition = partition_alleles(spec, {})
        self.assertEqual(partition["discriminable"], [])
        self.assertEqual(partition["indiscriminable"], ["G*9"])


class ResidualTest(unittest.TestCase):
    def test_the_residual_is_the_summed_frequency_of_what_could_not_be_excluded(self):
        partition = partition_alleles(SPEC, {"rs1": "OBSERVADO"})
        residual = residual_risk(partition)
        self.assertTrue(residual["computable"])
        self.assertTrue(residual["bounded"])
        # G*3 is the only indiscriminable allele; European 0.05 exceeds African 0.01, and the
        # worst group is reported because ancestry is not established.
        self.assertEqual(residual["worst_population"], "European")
        self.assertEqual(residual["worst_altered"], 0.05)

    def test_a_zero_residual_from_full_coverage_is_marked_computable(self):
        partition = partition_alleles(SPEC, {"rs1": "OBSERVADO", "rs2": "OBSERVADO", "rs3": "OBSERVADO"})
        residual = residual_risk(partition)
        self.assertEqual(residual["worst_altered"], 0.0)
        self.assertTrue(residual["computable"])
        self.assertTrue(residual["bounded"])

    def test_a_zero_residual_from_missing_frequencies_is_not_computable(self):
        # The negative control that matters most: two zeros that mean opposite things.
        spec = {
            "reference_allele": "G*1",
            "alleles": {
                "G*2": {"defining": [{"rsid": "rs1", "allele": "A"}], "cpic_clinical_function": "No function"},
                "G*3": {"defining": [{"rsid": "rs9", "allele": "T"}], "cpic_clinical_function": "No function"},
            },
        }
        residual = residual_risk(partition_alleles(spec, {"rs1": "OBSERVADO"}))
        self.assertFalse(residual["computable"])
        self.assertIsNone(residual["worst_altered"])
        self.assertEqual(residual["unpriced_altered"], ["G*3"])

    def test_a_partly_priced_residual_is_a_lower_bound(self):
        spec = {
            "reference_allele": "G*1",
            "alleles": {
                "G*2": {"defining": [{"rsid": "rs1", "allele": "A"}], "cpic_clinical_function": "No function"},
                "G*3": {
                    "defining": [{"rsid": "rs9", "allele": "T"}],
                    "cpic_clinical_function": "No function",
                    "cpic_frequency": {"European": 0.02},
                },
                "G*4": {"defining": [{"rsid": "rs8", "allele": "T"}], "cpic_clinical_function": "No function"},
            },
        }
        residual = residual_risk(partition_alleles(spec, {"rs1": "OBSERVADO"}))
        self.assertTrue(residual["computable"])
        self.assertFalse(residual["bounded"])
        self.assertEqual(residual["unpriced_altered"], ["G*4"])

    def test_a_group_priced_elsewhere_in_the_gene_is_still_reported_as_unpriced_here(self):
        # The fail-open this guards: if the group universe came only from the alleles that
        # could not be excluded, African would vanish from the output entirely, and a missing
        # group reads exactly like a group with no residual.
        spec = {
            "reference_allele": "G*1",
            "alleles": {
                "G*2": {
                    "defining": [{"rsid": "rs1", "allele": "A"}],
                    "cpic_clinical_function": "No function",
                    "cpic_frequency": {"European": 0.15, "African": 0.20},
                },
                "G*3": {
                    "defining": [{"rsid": "rs9", "allele": "T"}],
                    "cpic_clinical_function": "No function",
                    "cpic_frequency": {"European": 0.02},
                },
            },
        }
        residual = residual_risk(partition_alleles(spec, {"rs1": "OBSERVADO"}))
        self.assertIn("African", residual["populations"])
        self.assertEqual(residual["populations"]["African"]["unpriced_alleles"], ["G*3"])
        self.assertFalse(residual["populations"]["African"]["bounded"])
        self.assertFalse(residual["bounded"])

    def test_a_null_frequency_is_dropped_rather_than_read_as_zero(self):
        spec = {
            "reference_allele": "G*1",
            "alleles": {
                "G*2": {"defining": [{"rsid": "rs1", "allele": "A"}], "cpic_clinical_function": "No function"},
                "G*3": {
                    "defining": [{"rsid": "rs9", "allele": "T"}],
                    "cpic_clinical_function": "No function",
                    "cpic_frequency": {"European": 0.02, "African": None},
                },
            },
        }
        residual = residual_risk(partition_alleles(spec, {"rs1": "OBSERVADO"}))
        self.assertNotIn("African", residual["populations"])
        self.assertEqual(residual["populations"]["European"]["altered"], 0.02)

    def test_uncertain_function_is_counted_apart_from_altered(self):
        spec = {
            "reference_allele": "G*1",
            "alleles": {
                "G*2": {"defining": [{"rsid": "rs1", "allele": "A"}], "cpic_clinical_function": "No function"},
                "G*3": {
                    "defining": [{"rsid": "rs9", "allele": "T"}],
                    "cpic_clinical_function": "Uncertain function",
                    "cpic_frequency": {"European": 0.30},
                },
            },
        }
        residual = residual_risk(partition_alleles(spec, {"rs1": "OBSERVADO"}))
        self.assertEqual(residual["populations"]["European"]["altered"], 0.0)
        self.assertEqual(residual["populations"]["European"]["uncertain"], 0.30)


class ConditionalDiplotypeTest(unittest.TestCase):
    def test_a_heterozygous_carrier_gets_a_conditional_call_not_a_reference_call(self):
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        diplotype = result["conditional_diplotype"]
        self.assertEqual(diplotype["status"], "INFERIDO")
        self.assertEqual(diplotype["value"], "G*2/[NÃO DETECTADO]")
        # The reference haplotype is never claimed: that is the whole point of the class.
        self.assertNotIn("G*1", diplotype["value"])
        self.assertIn("G*1", diplotype["reference_allele_not_claimed"])
        self.assertEqual(diplotype["alleles_not_excluded"], 1)

    def test_nothing_interrogated_yields_no_conditional_call(self):
        # Negative control for the substitution report 09 exists to prevent: an empty tested
        # set must not produce a reference/reference call.
        result = _analyse({}, [], [])
        diplotype = result["conditional_diplotype"]
        self.assertEqual(diplotype["status"], UNAVAILABLE)
        self.assertTrue(any("nenhum alelo do CPIC" in r for r in diplotype["reasons"]))

    def test_two_heterozygous_defining_positions_block_the_call(self):
        result = _analyse({"rs1": "OBSERVADO", "rs2": "OBSERVADO"}, [FINDING_ABSENT], ["rs1", "rs2"])
        diplotype = result["conditional_diplotype"]
        self.assertEqual(diplotype["status"], UNAVAILABLE)
        self.assertTrue(any("fase não resolvida" in r for r in diplotype["reasons"]))

    def test_two_detected_alleles_block_the_call(self):
        other = dict(FINDING_DETECTED_HET, allele="G*3")
        spec = {
            "reference_allele": "G*1",
            "alleles": {
                "G*2": {"defining": [{"rsid": "rs1", "allele": "A"}]},
                "G*3": {"defining": [{"rsid": "rs2", "allele": "T"}]},
            },
        }
        result = _analyse(
            {"rs1": "OBSERVADO", "rs2": "OBSERVADO"},
            [FINDING_DETECTED_HET, other],
            ["rs1"],
            spec=spec,
        )
        diplotype = result["conditional_diplotype"]
        self.assertEqual(diplotype["status"], UNAVAILABLE)
        self.assertTrue(any("genótipo composto" in r for r in diplotype["reasons"]))

    def test_an_unnamed_reference_haplotype_blocks_the_call(self):
        spec = dict(SPEC, reference_allele=None)
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"], spec=spec)
        self.assertEqual(result["conditional_diplotype"]["status"], UNAVAILABLE)

    def test_a_structurally_unresolved_gene_is_never_called(self):
        diplotype = conditional_diplotype(
            "G",
            SPEC,
            partition_alleles(SPEC, {"rs1": "OBSERVADO"}),
            residual_risk(partition_alleles(SPEC, {"rs1": "OBSERVADO"})),
            [FINDING_DETECTED_HET],
            ["rs1"],
            structurally_unresolved=True,
        )
        self.assertEqual(diplotype["status"], UNAVAILABLE)

    def test_a_conditional_call_is_never_stronger_than_inferido(self):
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        self.assertEqual(result["conditional_diplotype"]["status"], "INFERIDO")


class ConditionalPhenotypeTest(unittest.TestCase):
    def test_a_bounded_residual_yields_a_phenotype_carrying_its_assumption(self):
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        phenotype = result["conditional_phenotype"]
        self.assertEqual(phenotype["status"], "INFERIDO")
        self.assertEqual(phenotype["value"], "Intermediate Metabolizer")
        self.assertTrue(phenotype["residual_bounded"])
        self.assertIn("condicional", phenotype["caveat"])

    def test_an_unpriceable_residual_yields_no_phenotype(self):
        spec = {
            "reference_allele": "G*1",
            "phenotype_map": {"*2/*1": {"phenotype": "Intermediate Metabolizer"}},
            "alleles": {
                "G*2": {"defining": [{"rsid": "rs1", "allele": "A"}], "cpic_clinical_function": "No function"},
                "G*3": {"defining": [{"rsid": "rs9", "allele": "T"}], "cpic_clinical_function": "No function"},
            },
        }
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"], spec=spec)
        self.assertEqual(result["conditional_diplotype"]["status"], "INFERIDO")
        self.assertEqual(result["conditional_phenotype"]["status"], UNAVAILABLE)

    def test_a_lower_bound_residual_is_declared_on_the_phenotype(self):
        spec = {
            "reference_allele": "G*1",
            "phenotype_map": {"*2/*1": {"phenotype": "Intermediate Metabolizer"}},
            "alleles": {
                "G*2": {"defining": [{"rsid": "rs1", "allele": "A"}], "cpic_clinical_function": "No function"},
                "G*3": {
                    "defining": [{"rsid": "rs9", "allele": "T"}],
                    "cpic_clinical_function": "No function",
                    "cpic_frequency": {"European": 0.02},
                },
                "G*4": {"defining": [{"rsid": "rs8", "allele": "C"}], "cpic_clinical_function": "No function"},
            },
        }
        phenotype = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"], spec=spec)[
            "conditional_phenotype"
        ]
        self.assertEqual(phenotype["status"], "INFERIDO")
        self.assertFalse(phenotype["residual_bounded"])
        self.assertEqual(phenotype["residual_unpriced_alleles"], 1)
        self.assertIn("limite inferior", phenotype["caveat"])

    def test_a_diplotype_absent_from_the_table_yields_no_nearest_match(self):
        spec = dict(SPEC, phenotype_map={"*9/*9": {"phenotype": "Poor Metabolizer"}})
        phenotype = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"], spec=spec)[
            "conditional_phenotype"
        ]
        self.assertEqual(phenotype["status"], UNAVAILABLE)
        self.assertIn("não consta", phenotype["reason"])

    def test_no_diplotype_means_no_phenotype(self):
        phenotype = conditional_phenotype("G", SPEC, {"status": UNAVAILABLE, "value": None}, {})
        self.assertEqual(phenotype["status"], UNAVAILABLE)


class SequencingRequisitionTest(unittest.TestCase):
    def test_the_requisition_names_the_uncovered_positions_with_coordinates(self):
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        requisition = result["sequencing_requisition"]
        self.assertEqual(requisition["status"], "PROPOSTO")
        self.assertEqual({s["rsid"] for s in requisition["positions"]}, {"rs2", "rs3"})
        for step in requisition["positions"]:
            self.assertEqual(step["chromosome"], "chr1")
            self.assertIsNotNone(step["position"])

    def test_the_last_position_of_an_allele_is_the_one_credited_with_its_frequency(self):
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        steps = result["sequencing_requisition"]["positions"]
        # G*3 needs both rs2 and rs3; only the second one sequenced unlocks it, so exactly
        # one step may claim the recovered frequency.
        credited = [s for s in steps if s["frequency_recovered"] > 0]
        self.assertEqual(len(credited), 1)
        self.assertEqual(credited[0]["frequency_recovered"], 0.05)
        self.assertEqual(steps[-1]["residual_altered_after"], 0.0)

    def test_full_coverage_produces_no_requisition(self):
        result = _analyse(
            {"rs1": "OBSERVADO", "rs2": "OBSERVADO", "rs3": "OBSERVADO"},
            [FINDING_ABSENT],
            [],
        )
        self.assertEqual(result["sequencing_requisition"]["status"], UNAVAILABLE)

    def test_positions_are_ordered_by_the_frequency_mass_they_recover(self):
        spec = {
            "reference_allele": "G*1",
            "alleles": {
                "G*2": {"defining": [{"rsid": "rs1", "allele": "A"}], "cpic_clinical_function": "No function"},
                "rare": {
                    "defining": [{"rsid": "rs_rare", "allele": "T"}],
                    "cpic_clinical_function": "No function",
                    "cpic_frequency": {"European": 0.001},
                },
                "common": {
                    "defining": [{"rsid": "rs_common", "allele": "T"}],
                    "cpic_clinical_function": "No function",
                    "cpic_frequency": {"European": 0.40},
                },
            },
        }
        requisition = _analyse({"rs1": "OBSERVADO"}, [FINDING_ABSENT], [], spec=spec)[
            "sequencing_requisition"
        ]
        self.assertEqual([s["rsid"] for s in requisition["positions"]], ["rs_common", "rs_rare"])
        self.assertEqual(requisition["positions"][0]["cumulative_frequency_recovered"], 0.40)

    def test_the_requisition_states_what_sequencing_still_cannot_resolve(self):
        spec = dict(SPEC, structural_alleles_excluded=["G*5xN"])
        requisition = sequencing_requisition(
            "G",
            spec,
            partition_alleles(spec, {"rs1": "OBSERVADO"}),
            residual_risk(partition_alleles(spec, {"rs1": "OBSERVADO"})),
        )
        self.assertEqual(requisition["structural_alleles_excluded"], ["G*5xN"])
        self.assertIn("fase", requisition["scope_note"])


class AnalysisShapeTest(unittest.TestCase):
    def test_a_gene_with_no_curated_alleles_is_reported_unavailable(self):
        self.assertEqual(analyse_gene("X", None, {}, [], [])["status"], UNAVAILABLE)
        self.assertEqual(analyse_gene("X", {"alleles": {}}, {}, [], [])["status"], UNAVAILABLE)

    def test_coverage_fraction_counts_positions_not_alleles(self):
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_ABSENT], [])
        self.assertEqual(result["positions_total"], 3)
        self.assertEqual(result["positions_interpretable"], 1)
        self.assertAlmostEqual(result["coverage_fraction"], 1 / 3)


if __name__ == "__main__":
    unittest.main()
