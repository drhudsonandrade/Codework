"""OBSERVADO means "chamado". It only means "presente" when a base was named to test for.

`completeness._classify` returns OBSERVADO in two unrelated situations:

* the registry named an assessed allele and the called genotype contains it — the variant is
  present;
* the registry named none, so nothing could be compared — the locus was merely called.

`clinical_findings._interpretation` read the class alone and graded both as presence, so a
plain reference call could be reported as GENÓTIPO DE RISCO — "homozigoto para variante
patogênica" in APC, familial adenomatous polyposis, in a person carrying nothing.

This docstring used to quantify that over a real consumer array. The counts are removed: no
artifact, hash or reproducible procedure in this repository supports them, and the synthetic
fixtures below do not demonstrate them. The defect and the defences are what the tests
establish; the scale of one historical run is not something this file can attest.

The cause was upstream: when ClinVar asserts more than one alternate base at a coordinate the
expander declines to name a single `assessed_allele` and records them all under
`clinvar_alternate_alleles`, which the classifier never read. At one coordinate a single
alternate base *is* a single variant, so the genotype answers presence for each of them
independently, and such a locus is NÃO DETECTADO once the whole set is compared.

Two defences, tested separately, because either alone leaves a hole: the classifier tests the
full set, and the classification logic refuses to grade a locus where nothing could be tested.
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

from array_pipeline.completeness import (
    NAO_DETECTADO,
    OBSERVADO,
    assessed_bases,
    build_completeness_matrix,
)
from array_pipeline.qc import inspect_array
from tests.attestations import provenance_for

HEADER = (
    "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,"
    "MYHERITAGE_RESULT,SOURCES\n"
)

#: rs1 declares one alternate; rs2 declares several; rs3 declares none at all.
TARGETS = {
    "schema": "genoma-partial-genome-targets-v1",
    "id": "TEST-ASSESSED",
    "version": "test.1",
    "targets": [
        {"rsid": "rs1", "gene": "G1", "scope": "CLINICO", "label": "um alternativo",
         "assessed_allele": "A", "queries": {"clinvar": {"term": "rs1"}}},
        {"rsid": "rs2", "gene": "G2", "scope": "CLINICO", "label": "multialélico",
         "clinvar_alternate_alleles": ["A", "G"], "queries": {"clinvar": {"term": "rs2"}}},
        {"rsid": "rs3", "gene": "G3", "scope": "CLINICO", "label": "sem base declarada",
         "queries": {"clinvar": {"term": "rs3"}}},
    ],
}


class AssessedBasesTest(unittest.TestCase):
    """Which bases a target counts as assessed."""
    def test_a_single_declared_allele_is_the_whole_set(self):
        """A single declared allele is the whole assessed set."""
        self.assertEqual(assessed_bases({"assessed_allele": "A"}), {"A"})

    def test_the_multi_allelic_list_is_read_when_no_single_allele_is_named(self):
        """The multi-allelic list is read when no single allele is named,
        and normalised to upper case.
        """
        self.assertEqual(
            assessed_bases({"clinvar_alternate_alleles": ["A", "g"]}), {"A", "G"}
        )

    def test_the_named_allele_wins_over_the_list(self):
        """The curated singular field is the verified one; the list is the fallback."""
        self.assertEqual(
            assessed_bases({"assessed_allele": "T", "clinvar_alternate_alleles": ["A", "G"]}),
            {"T"},
        )

    def test_a_target_naming_nothing_yields_an_empty_set(self):
        """A target naming nothing yields an empty set, not a set containing nothing meaningful."""
        self.assertEqual(assessed_bases({}), set())
        self.assertEqual(assessed_bases({"clinvar_alternate_alleles": []}), set())


class MultiAllelicClassificationTest(unittest.TestCase):
    """How a multi-allelic locus is classified against the genotype actually read."""
    def _matrix(self, rows: str):
        """The completeness matrix entries produced by these array rows."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = root / "array.csv.gz"
            with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
                fh.write(HEADER)
                fh.write(rows)
            qc = inspect_array(array, case_id="SYN-ASSESSED", **provenance_for(array))
            qc_path = root / "qc.json"
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            targets = root / "targets.json"
            targets.write_text(json.dumps(TARGETS), encoding="utf-8")
            matrix = build_completeness_matrix(array, qc_path, targets)
        return {e["rsid"]: e for e in matrix["entries"]}

    def test_a_genotype_sharing_no_base_with_any_alternate_is_a_real_negative(self):
        """The defect's core: TT against alternates A/G is absence, not "cannot say"."""
        entries = self._matrix(
            "rs1,1,100,TT,consensus,TT,TT,GM\n"
            "rs2,1,200,TT,consensus,TT,TT,GM\n"
            "rs3,1,300,TT,consensus,TT,TT,GM\n"
        )
        self.assertEqual(entries["rs2"]["classification"], NAO_DETECTADO)
        self.assertIn("A, G", entries["rs2"]["basis"])
        self.assertEqual(entries["rs2"]["assessed_alleles"], ["A", "G"])

    def test_a_genotype_carrying_one_of_the_alternates_is_observado(self):
        """A genotype carrying one of the declared alternates is OBSERVADO."""
        entries = self._matrix(
            "rs1,1,100,TT,consensus,TT,TT,GM\n"
            "rs2,1,200,AT,consensus,AT,AT,GM\n"
            "rs3,1,300,TT,consensus,TT,TT,GM\n"
        )
        self.assertEqual(entries["rs2"]["classification"], OBSERVADO)
        self.assertIn("contém o alelo avaliado A", entries["rs2"]["basis"])

    def test_a_locus_naming_no_base_stays_observado_and_says_so(self):
        """A locus naming no base stays OBSERVADO and records why it could not be read further."""
        entries = self._matrix(
            "rs1,1,100,TT,consensus,TT,TT,GM\n"
            "rs2,1,200,TT,consensus,TT,TT,GM\n"
            "rs3,1,300,TT,consensus,TT,TT,GM\n"
        )
        self.assertEqual(entries["rs3"]["classification"], OBSERVADO)
        self.assertEqual(entries["rs3"]["assessed_alleles"], [])
        self.assertIn("não declara o alelo avaliado", entries["rs3"]["basis"])

    def test_the_single_allele_path_is_unchanged(self):
        """Negative control: the single-allele path is unchanged."""
        entries = self._matrix(
            "rs1,1,100,AG,consensus,AG,AG,GM\n"
            "rs2,1,200,TT,consensus,TT,TT,GM\n"
            "rs3,1,300,TT,consensus,TT,TT,GM\n"
        )
        self.assertEqual(entries["rs1"]["classification"], OBSERVADO)
        self.assertEqual(entries["rs1"]["assessed_alleles"], ["A"])


class InterpretationRefusesUntestedLociTest(unittest.TestCase):
    """The backstop: even a matrix that names nothing must not yield a clinical finding."""

    CLINVAR = {
        "asserts_pathogenic": True, "asserts_benign": False, "classifications": ["Pathogenic"],
        "meets_review_threshold": True, "review_stars": 2, "conditions": [], "records": [],
    }
    VALIDITY = {
        "established": True, "established_by": ["ClinGen"], "classifications": ["Definitive"],
        "modes_of_inheritance": ["AD"], "diseases_by_mode": {},
    }

    def _interpret(self, entry):
        """The clinical interpretation of this matrix entry."""
        from array_pipeline import clinical_findings as cf

        return cf._interpretation(entry, self.CLINVAR, self.VALIDITY, sex_at_birth=None)

    def test_observado_without_any_assessed_base_is_never_a_finding(self):
        """OBSERVADO without any assessed base is never a finding."""
        from array_pipeline.clinical_findings import SEM_INTERPRETACAO

        result = self._interpret({
            "classification": "OBSERVADO", "genotype": "TT", "scope": "CLINICO",
            "assessed_alleles": [], "assessed_allele": None,
            "basis": (
                "genótipo chamado; ausência não pode ser afirmada porque o registro não "
                "declara o alelo avaliado"
            ),
        })
        self.assertEqual(result["kind"], SEM_INTERPRETACAO)
        self.assertIn("nem presença nem ausência", result["basis"])

    def test_a_homozygous_reference_call_is_not_a_homozygous_pathogenic_variant(self):
        """The exact sentence the defect produced, on the exact shape that produced it."""
        from array_pipeline.clinical_findings import SEM_INTERPRETACAO

        result = self._interpret({
            "classification": "OBSERVADO", "genotype": "TT", "scope": "CLINICO",
            "assessed_alleles": [], "assessed_allele": None, "basis": "genótipo chamado",
        })
        self.assertEqual(result["kind"], SEM_INTERPRETACAO)
        self.assertNotIn("homozigoto para variante patogênica", result["basis"])

    def test_a_named_base_still_reaches_the_clinical_reading(self):
        """A named base still reaches the clinical reading."""
        from array_pipeline.clinical_findings import GENOTIPO_DE_RISCO

        result = self._interpret({
            "classification": "OBSERVADO", "genotype": "AA", "scope": "CLINICO",
            "assessed_comparison": "APLICÁVEL",
            "assessed_alleles": ["A"], "assessed_allele": "A", "basis": "contém o alelo avaliado A",
        })
        self.assertEqual(result["kind"], GENOTIPO_DE_RISCO)

    def test_named_base_with_non_applicable_comparison_is_not_interpreted(self):
        """A named allele does not override an explicit non-applicable comparison."""
        from array_pipeline.clinical_findings import SEM_INTERPRETACAO

        result = self._interpret({
            "classification": "OBSERVADO",
            "genotype": "AA",
            "scope": "CLINICO",
            "assessed_comparison": "NÃO APLICÁVEL",
            "assessed_alleles": ["A"],
            "assessed_allele": "A",
            "basis": "alelo multibase incompatível com chamada SNP",
        })
        self.assertEqual(result["kind"], SEM_INTERPRETACAO)
        self.assertIn("nenhuma comparação aplicável", result["basis"])

    def test_the_multi_allelic_set_alone_is_enough_to_grade(self):
        """A locus the classifier could test only through the list is still gradable."""
        from array_pipeline.clinical_findings import GENOTIPO_DE_RISCO

        result = self._interpret({
            "classification": "OBSERVADO", "genotype": "AA", "scope": "CLINICO",
            "assessed_comparison": "APLICÁVEL",
            "assessed_alleles": ["A", "G"], "assessed_allele": None,
            "basis": "contém o alelo avaliado A",
        })
        self.assertEqual(result["kind"], GENOTIPO_DE_RISCO)


class ShippedRegistryTest(unittest.TestCase):
    """The shipped registry, measured rather than assumed."""
    def test_most_multi_allelic_targets_can_now_be_answered(self):
        """Measured, not assumed: the fix has to actually reach the shipped registry."""
        with gzip.open(
            ROOT / "config/targets_merged_panel_1star.json.gz", "rt", encoding="utf-8"
        ) as handle:
            targets = json.load(handle)["targets"]
        multi = [t for t in targets if not t.get(
            "assessed_allele") and t.get("clinvar_alternate_alleles")]
        blank = [t for t in targets if not assessed_bases(t)]
        self.assertGreater(len(multi), 5_000)
        for target in multi:
            self.assertGreaterEqual(len(assessed_bases(target)), 2)
        # Some loci genuinely name nothing; they are the ones the backstop above covers.
        self.assertLess(len(blank), len(multi))


if __name__ == "__main__":
    unittest.main()
