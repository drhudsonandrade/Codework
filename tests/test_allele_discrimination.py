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
    """Run the discrimination analysis for the fixture gene against these inputs."""
    return analyse_gene("G", spec, classifications, findings, heterozygous)


class FunctionBucketTest(unittest.TestCase):
    """An unrecognised CPIC label must never be read as normal function."""

    def test_cpic_vocabulary_maps_to_the_expected_buckets(self):
        """Each CPIC function label maps to the bucket the residual arithmetic expects."""
        self.assertEqual(function_bucket("Normal function"), NORMAL)
        for label in ("No function", "Decreased function", "Increased function"):
            self.assertEqual(function_bucket(label), ALTERED)
        for label in ("Uncertain function", "Unknown function"):
            self.assertEqual(function_bucket(label), UNCERTAIN)

    def test_an_unknown_label_is_uncertain_not_normal(self):
        """An unrecognised label is UNCERTAIN, so a CPIC rename grows the residual instead of shrinking it."""
        # Negative control for the fail-open direction: if CPIC renames a status, the
        # residual must grow, not shrink.
        for label in (None, "", "Diminished activity", "função reduzida"):
            self.assertEqual(function_bucket(label), UNCERTAIN, label)

    def test_analysis_surfaces_labels_it_did_not_recognise(self):
        """The analysis surfaces the labels it did not recognise, rather than absorbing them silently."""
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
    """Which alleles the array can actually tell apart, given what was interrogated."""
    def test_an_allele_is_discriminable_only_when_every_position_is_interpretable(self):
        """An allele is discriminable only when every one of its defining positions is interpretable."""
        partition = partition_alleles(SPEC, {"rs1": "OBSERVADO", "rs2": "OBSERVADO"})
        self.assertEqual(partition["discriminable"], ["G*2"])
        self.assertEqual(partition["indiscriminable"], ["G*3"])
        # rs3 was never read, so it is the gap; rs2 was, so it is not.
        self.assertEqual(partition["positions_missing"], ["rs3"])

    def test_non_interpretable_classes_do_not_count_as_interrogated(self):
        """NO-CALL, NÃO TESTADO and NÃO REPORTÁVEL do not count as interrogated."""
        for classification in ("NO-CALL", "NÃO TESTADO", "NÃO REPORTÁVEL"):
            partition = partition_alleles(SPEC, {"rs1": classification})
            self.assertEqual(partition["discriminable"], [], classification)

    def test_an_allele_with_no_defining_positions_is_never_discriminable(self):
        """An allele with no defining positions is never discriminable, despite all([]) being True."""
        # Vacuous truth: `all()` over an empty requirement is True, which would have made an
        # allele with no definition at all look fully covered.
        spec = {"reference_allele": "G*1", "alleles": {"G*9": {"defining": []}}}
        partition = partition_alleles(spec, {})
        self.assertEqual(partition["discriminable"], [])
        self.assertEqual(partition["indiscriminable"], ["G*9"])


class ResidualTest(unittest.TestCase):
    """The residual risk left by the alleles that could not be excluded."""
    def test_the_residual_is_the_summed_frequency_of_what_could_not_be_excluded(self):
        """The residual is the summed frequency of what could not be excluded, per population group."""
        partition = partition_alleles(SPEC, {"rs1": "OBSERVADO"})
        residual = residual_risk(partition)
        self.assertTrue(residual["computable"])
        self.assertTrue(residual["bounded"])
        # G*3 is the only indiscriminable allele; European 0.05 exceeds African 0.01, and the
        # worst group is reported because ancestry is not established.
        self.assertEqual(residual["worst_population"], "European")
        self.assertEqual(residual["worst_altered"], 0.05)

    def test_a_zero_residual_from_full_coverage_is_marked_computable(self):
        """A zero residual from full coverage is computable and bounded."""
        partition = partition_alleles(SPEC, {"rs1": "OBSERVADO", "rs2": "OBSERVADO", "rs3": "OBSERVADO"})
        residual = residual_risk(partition)
        self.assertEqual(residual["worst_altered"], 0.0)
        self.assertTrue(residual["computable"])
        self.assertTrue(residual["bounded"])

    def test_a_zero_residual_from_missing_frequencies_is_not_computable(self):
        """A zero residual from missing frequencies is not computable: the two zeros mean opposite things."""
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
        """A residual priced for only some of its alleles is reported as a lower bound."""
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
        """A population group priced elsewhere in the gene is still reported here, as unpriced."""
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
        """A null frequency is dropped rather than read as zero."""
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
        """Uncertain function is counted apart from altered, not folded into it."""
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
    """The conditional diplotype: what can be said without claiming the reference haplotype."""
    def test_a_heterozygous_carrier_gets_a_conditional_call_not_a_reference_call(self):
        """A heterozygous carrier gets a conditional call, never a reference call."""
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        diplotype = result["conditional_diplotype"]
        self.assertEqual(diplotype["status"], "INFERIDO")
        self.assertEqual(diplotype["value"], "G*2/[NÃO DETECTADO]")
        # The reference haplotype is never claimed: that is the whole point of the class.
        self.assertNotIn("G*1", diplotype["value"])
        self.assertIn("G*1", diplotype["reference_allele_not_claimed"])
        self.assertEqual(diplotype["alleles_not_excluded"], 1)

    def test_nothing_interrogated_yields_no_conditional_call(self):
        """Nothing interrogated yields no conditional call, not a reference/reference call."""
        # Negative control for the substitution report 09 exists to prevent: an empty tested
        # set must not produce a reference/reference call.
        result = _analyse({}, [], [])
        diplotype = result["conditional_diplotype"]
        self.assertEqual(diplotype["status"], UNAVAILABLE)
        self.assertTrue(any("nenhum alelo do CPIC" in r for r in diplotype["reasons"]))

    def test_an_unreadable_zygosity_blocks_the_call_instead_of_defaulting(self):
        """One observed allele is not evidence about the second chromosome.

        The branch reads zygosity to choose between "both chromosomes carry this allele" and
        "the other carries none of the tested ones". With zygosity unreadable — a defining
        position called with a single character — neither holds, and falling through to the
        else branch asserts the stronger of the two.
        """
        half_read = dict(
            FINDING_DETECTED_HET,
            zygosity=None,
            zygosity_basis="zigosidade não legível: 1 posição(ões) definidora(s) sem chamada diploide (rs1)",
            positions=[{"rsid": "rs1", "genotype": "G", "interrogable": True}],
        )
        result = _analyse({"rs1": "OBSERVADO"}, [half_read], [])
        diplotype = result["conditional_diplotype"]
        self.assertEqual(diplotype["status"], UNAVAILABLE)
        self.assertIsNone(diplotype["value"])
        self.assertTrue(any("zigosidade não legível" in r for r in diplotype["reasons"]))
        self.assertTrue(any("G*2" in r for r in diplotype["reasons"]))

    def test_two_heterozygous_defining_positions_block_the_call(self):
        """Two heterozygous defining positions block the call: the phase is unresolved."""
        result = _analyse({"rs1": "OBSERVADO", "rs2": "OBSERVADO"}, [FINDING_ABSENT], ["rs1", "rs2"])
        diplotype = result["conditional_diplotype"]
        self.assertEqual(diplotype["status"], UNAVAILABLE)
        self.assertTrue(any("fase não resolvida" in r for r in diplotype["reasons"]))

    def test_two_detected_alleles_block_the_call(self):
        """Two detected alleles block the call rather than being paired by guesswork."""
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
        """An unnamed reference haplotype blocks the call: there is nothing to pair the allele with."""
        spec = dict(SPEC, reference_allele=None)
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"], spec=spec)
        self.assertEqual(result["conditional_diplotype"]["status"], UNAVAILABLE)

    def test_a_structurally_unresolved_gene_is_never_called(self):
        """A structurally unresolved gene is never called."""
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
        """A conditional call is never stronger than INFERIDO."""
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        self.assertEqual(result["conditional_diplotype"]["status"], "INFERIDO")


class ConditionalPhenotypeTest(unittest.TestCase):
    """The conditional phenotype, and the assumption it has to carry."""
    def test_a_bounded_residual_yields_a_phenotype_carrying_its_assumption(self):
        """A bounded residual yields a phenotype that states the assumption it rests on."""
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        phenotype = result["conditional_phenotype"]
        self.assertEqual(phenotype["status"], "INFERIDO")
        self.assertEqual(phenotype["value"], "Intermediate Metabolizer")
        self.assertTrue(phenotype["residual_bounded"])
        self.assertIn("condicional", phenotype["caveat"])

    def test_an_unpriceable_residual_yields_no_phenotype(self):
        """A residual that cannot be priced yields no phenotype."""
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
        """A lower-bound residual is declared as such on the phenotype that rests on it."""
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
        self.assertIn("limites inferiores", phenotype["caveat"])
        # Both axes are priced next to the label, not only the altered one.
        self.assertIn("função incerta", phenotype["caveat"])

    def test_a_diplotype_absent_from_the_table_yields_no_nearest_match(self):
        """A diplotype absent from the phenotype table yields no phenotype, never a nearest match."""
        spec = dict(SPEC, phenotype_map={"*9/*9": {"phenotype": "Poor Metabolizer"}})
        phenotype = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"], spec=spec)[
            "conditional_phenotype"
        ]
        self.assertEqual(phenotype["status"], UNAVAILABLE)
        self.assertIn("não consta", phenotype["reason"])

    def test_no_diplotype_means_no_phenotype(self):
        """No diplotype means no phenotype."""
        phenotype = conditional_phenotype("G", SPEC, {"status": UNAVAILABLE, "value": None}, {})
        self.assertEqual(phenotype["status"], UNAVAILABLE)


class SequencingRequisitionTest(unittest.TestCase):
    """The sequencing requisition: what would still have to be read, and what it would recover."""
    def test_the_requisition_names_the_uncovered_positions_with_coordinates(self):
        """The requisition names each uncovered position with its coordinates."""
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        requisition = result["sequencing_requisition"]
        self.assertEqual(requisition["status"], "PROPOSTO")
        self.assertEqual({s["rsid"] for s in requisition["positions"]}, {"rs2", "rs3"})
        for step in requisition["positions"]:
            self.assertEqual(step["chromosome"], "chr1")
            self.assertIsNotNone(step["position"])

    def test_the_last_position_of_an_allele_is_the_one_credited_with_its_frequency(self):
        """Only the last position an allele needs is credited with the frequency it recovers."""
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_DETECTED_HET], ["rs1"])
        steps = result["sequencing_requisition"]["positions"]
        # G*3 needs both rs2 and rs3; only the second one sequenced unlocks it, so exactly
        # one step may claim the recovered frequency.
        credited = [s for s in steps if s["frequency_recovered"] > 0]
        self.assertEqual(len(credited), 1)
        self.assertEqual(credited[0]["frequency_recovered"], 0.05)
        self.assertEqual(steps[-1]["residual_altered_after"], 0.0)

    def test_full_coverage_produces_no_requisition(self):
        """Full coverage produces no requisition."""
        result = _analyse(
            {"rs1": "OBSERVADO", "rs2": "OBSERVADO", "rs3": "OBSERVADO"},
            [FINDING_ABSENT],
            [],
        )
        self.assertEqual(result["sequencing_requisition"]["status"], UNAVAILABLE)

    def test_positions_are_ordered_by_the_frequency_mass_they_recover(self):
        """Positions are ordered by the frequency mass sequencing them would recover."""
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
        """The requisition states what sequencing still would not resolve."""
        spec = dict(SPEC, structural_alleles_excluded=["G*5xN"])
        requisition = sequencing_requisition(
            "G",
            spec,
            partition_alleles(spec, {"rs1": "OBSERVADO"}),
            residual_risk(partition_alleles(spec, {"rs1": "OBSERVADO"})),
        )
        self.assertEqual(requisition["structural_alleles_excluded"], ["G*5xN"])
        self.assertIn("fase", requisition["scope_note"])

    def test_each_axis_uses_its_own_population_and_uncertainty_does_not_reduce_altered_residual(self):
        """Each axis uses its own population, and uncertainty never reduces the altered residual."""
        spec = {
            "alleles": {
                "altered": {
                    "defining": [{"rsid": "rs_altered", "allele": "A"}],
                    "cpic_clinical_function": "No function",
                    "cpic_frequency": {"A": 0.20, "B": 0.01},
                },
                "uncertain": {
                    "defining": [{"rsid": "rs_uncertain", "allele": "G"}],
                    "cpic_clinical_function": "Uncertain function",
                    "cpic_frequency": {"A": 0.00, "B": 0.90},
                },
            }
        }
        partition = partition_alleles(spec, {})
        requisition = sequencing_requisition("G", spec, partition, residual_risk(partition))
        steps = requisition["positions"]

        self.assertEqual([step["rsid"] for step in steps], ["rs_uncertain", "rs_altered"])
        self.assertEqual(steps[0]["frequency_recovered"], 0.90)
        self.assertEqual(steps[0]["residual_altered_after"], 0.20)
        self.assertEqual(steps[1]["residual_altered_after"], 0.0)


class AnalysisShapeTest(unittest.TestCase):
    """The shape of the analysis block on every path, including the refusals."""
    def test_a_gene_with_no_curated_alleles_is_reported_unavailable(self):
        """A gene with no curated alleles is reported unavailable, whether the spec is None or empty."""
        self.assertEqual(analyse_gene("X", None, {}, [], [])["status"], UNAVAILABLE)
        self.assertEqual(analyse_gene("X", {"alleles": {}}, {}, [], [])["status"], UNAVAILABLE)

    def test_coverage_fraction_counts_positions_not_alleles(self):
        """The coverage fraction counts defining positions, not alleles."""
        result = _analyse({"rs1": "OBSERVADO"}, [FINDING_ABSENT], [])
        self.assertEqual(result["positions_total"], 3)
        self.assertEqual(result["positions_interpretable"], 1)
        self.assertAlmostEqual(result["coverage_fraction"], 1 / 3)


class WorstGroupPerAxisTest(unittest.TestCase):
    """The two residual axes peak in different populations, and one label served both.

    `worst_population` maximises the *altered* fraction, and `worst_uncertain` used to read
    the uncertain fraction out of that same group. The module's own comment says the worst
    group is reported rather than an average because "an average would understate the risk
    for whichever population the person actually belongs to" — and this understated it, on
    the uncertain axis, for the same reason.
    """

    def _spec(self, freq_a, freq_b):
        """A two-allele spec with these altered and uncertain frequencies per population group."""
        return {
            "alleles": {
                "*2": {
                    "cpic_clinical_function": "No function",
                    "defining": [{"rsid": "rsX", "allele": "T"}],
                    "cpic_frequency": freq_a,
                },
                "*9": {
                    "cpic_clinical_function": "Uncertain function",
                    "defining": [{"rsid": "rsY", "allele": "G"}],
                    "cpic_frequency": freq_b,
                },
            }
        }

    def test_the_uncertain_maximum_is_not_taken_from_the_altered_group(self):
        """The uncertain maximum is taken from its own axis, not from the altered group."""
        # Group A tops the altered axis; group B tops the uncertain axis by a wide margin.
        spec = self._spec({"A": 0.20, "B": 0.01}, {"A": 0.00, "B": 0.90})
        residual = residual_risk(partition_alleles(spec, {}))
        self.assertEqual(residual["worst_population"], "A")
        self.assertEqual(residual["worst_altered"], 0.2)
        self.assertEqual(residual["worst_uncertain"], 0.9)
        self.assertEqual(residual["worst_uncertain_population"], "B")

    def test_the_group_behind_each_number_is_named(self):
        """Each number names the group behind it, so a reader cannot attach both to one label."""
        # A reader given one group label would attach both numbers to it.
        spec = self._spec({"A": 0.20, "B": 0.01}, {"A": 0.00, "B": 0.90})
        residual = residual_risk(partition_alleles(spec, {}))
        self.assertNotEqual(residual["worst_population"], residual["worst_uncertain_population"])

    def test_one_group_peaking_on_both_axes_still_reports_that_group(self):
        """One group peaking on both axes is still reported on both."""
        spec = self._spec({"A": 0.20, "B": 0.01}, {"A": 0.50, "B": 0.10})
        residual = residual_risk(partition_alleles(spec, {}))
        self.assertEqual(residual["worst_population"], "A")
        self.assertEqual(residual["worst_uncertain_population"], "A")

    def test_every_return_path_declares_the_field(self):
        """Every return path declares worst_uncertain_population, so a consumer cannot hit a KeyError."""
        # A consumer reading it must not hit a KeyError on the refusal paths.
        for spec in ({}, {"alleles": {}}):
            with self.subTest(spec=spec):
                self.assertIn(
                    "worst_uncertain_population", residual_risk(partition_alleles(spec, {}))
                )

    def test_the_shipped_registry_no_longer_understates_vkorc1(self):
        """The shipped registry no longer understates the VKORC1 uncertain residual."""
        # VKORC1 dictates warfarin dosing. Its whole residual is uncertainty, and it was
        # reported as 0.101 where East Asian is 0.866.
        import json

        registry = json.loads(
            (ROOT / "config/pgx_allele_definitions.json").read_text(encoding="utf-8")
        )
        residual = residual_risk(partition_alleles(registry["genes"]["VKORC1"], {}))
        populations = residual["populations"]
        self.assertEqual(
            residual["worst_uncertain"],
            max(entry["uncertain"] for entry in populations.values()),
        )
        self.assertGreater(residual["worst_uncertain"], 0.8)

    def test_no_shipped_gene_understates_its_uncertain_residual(self):
        """No shipped gene understates its uncertain residual."""
        import json

        registry = json.loads(
            (ROOT / "config/pgx_allele_definitions.json").read_text(encoding="utf-8")
        )
        for gene, spec in sorted(registry["genes"].items()):
            residual = residual_risk(partition_alleles(spec, {}))
            populations = residual.get("populations") or {}
            if not populations:
                continue
            with self.subTest(gene=gene):
                self.assertEqual(
                    residual["worst_uncertain"],
                    max(entry["uncertain"] for entry in populations.values()),
                )


class VacuousResidualTest(unittest.TestCase):
    """A residual of zero must never come from an empty catalogue."""

    def test_a_gene_with_no_catalogued_alleles_is_not_a_zero_residual(self):
        """A gene with no catalogued alleles is not a zero residual: it is an uncomputable one."""
        residual = residual_risk(partition_alleles({"alleles": {}}, {}))
        self.assertFalse(residual["computable"])
        self.assertIsNone(residual["worst_altered"])
        self.assertIn("ausência de catálogo", residual["basis"])

    def test_a_gene_with_every_allele_discriminable_is_a_measured_zero(self):
        """A gene whose every allele is discriminable is a measured zero, and says so."""
        residual = residual_risk(
            partition_alleles(SPEC, {"rs1": "OBSERVADO", "rs2": "OBSERVADO", "rs3": "OBSERVADO"})
        )
        self.assertTrue(residual["computable"])
        self.assertEqual(residual["worst_altered"], 0.0)
        self.assertIn("por medição", residual["basis"])


if __name__ == "__main__":
    unittest.main()
