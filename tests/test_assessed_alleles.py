"""The assessed allele decides whether absence can be stated, so it must be sourced.

Before curation all 29 targets sat in OBSERVADO and the completeness matrix could never say
"tested and absent" about anything. After it, 19 of them are NÃO DETECTADO — which means the
curation is now load-bearing for a clinical claim, and a wrong entry would assert absence of
the wrong variant.

These tests pin the shipped registry to the recorded evidence offline, and pin the
decision rules that produced it. They need no network.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGETS_PATH = ROOT / "config/partial_genome_annotation_targets.json"
EVIDENCE_PATH = ROOT / "docs/evidence/ASSESSED_ALLELES_CLINVAR.json"
PGX_PATH = ROOT / "config/pgx_allele_definitions.json"


class AssessedAlleleEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.targets = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
        cls.evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.by_rsid = {r["rsid"]: r for r in cls.evidence["results"]}

    def test_the_registry_cites_its_sources(self):
        curation = self.targets["assessed_allele_curation"]
        joined = " ".join(curation["sources"])
        self.assertIn("dbSNP", joined)
        self.assertIn("ClinVar", joined)
        self.assertIn("CPIC", joined)
        self.assertIn("ASSESSED_ALLELES_CLINVAR.json", curation["evidence"])

    def test_every_declared_allele_matches_the_recorded_evidence(self):
        for target in self.targets["targets"]:
            rsid = str(target["rsid"]).lower()
            record = self.by_rsid[rsid]
            with self.subTest(rsid=rsid):
                if "assessed_allele" in target:
                    self.assertEqual(record["status"], "VERIFICADO")
                    self.assertEqual(target["assessed_allele"], record["assessed_allele"])
                    self.assertEqual(target["assessed_allele_source"], record["source"])
                else:
                    self.assertEqual(record["status"], "NÃO DISPONÍVEL")
                    self.assertTrue(target["assessed_allele_reason"])

    def test_an_assessed_allele_is_never_the_reference_base(self):
        """Declaring the reference as the thing being looked for would invert every verdict."""
        for record in self.evidence["results"]:
            if record.get("assessed_allele"):
                with self.subTest(rsid=record["rsid"]):
                    self.assertNotEqual(record["assessed_allele"], record["reference_allele"])
                    self.assertIn(record["assessed_allele"], set("ACGT"))

    def test_every_verdict_states_which_source_decided_it(self):
        for record in self.evidence["results"]:
            with self.subTest(rsid=record["rsid"]):
                self.assertTrue(record["reason"])
                if record["status"] == "VERIFICADO":
                    self.assertIn(
                        record["source"],
                        {"CPIC", "ClinVar", "CPIC + dbSNP frequency", "ClinVar + dbSNP frequency"},
                    )

    def test_a_target_without_a_source_assertion_stays_unavailable(self):
        """rs4307059 is a GWAS association with no ClinVar assertion; absence is not claimable."""
        record = self.by_rsid["rs4307059"]
        self.assertEqual(record["status"], "NÃO DISPONÍVEL")
        self.assertIsNone(record["assessed_allele"])
        target = next(t for t in self.targets["targets"] if t["rsid"] == "rs4307059")
        self.assertNotIn("assessed_allele", target)

    def test_disambiguation_by_frequency_is_recorded_not_silent(self):
        """Where two alternates were asserted, the record must show how one was chosen."""
        disambiguated = [
            r for r in self.evidence["results"] if r.get("source", "").endswith("dbSNP frequency")
        ]
        self.assertTrue(disambiguated, "no target was resolved by frequency; the rule is untested")
        for record in disambiguated:
            with self.subTest(rsid=record["rsid"]):
                # The two branches word it differently — ClinVar's says "frequency", CPIC's
                # says "observes ... in a population cohort" — so the check is on the claim,
                # not the phrasing.
                reason = record["reason"].lower()
                self.assertTrue(
                    "frequenc" in reason or "cohort" in reason,
                    f"{record['rsid']}: the reason does not say how one allele was chosen",
                )
                self.assertGreater(record["dbsnp_frequencies"][record["assessed_allele"]], 0.0)
                # And the alternatives it rejected must genuinely lack population support.
                rejected = set(record.get("cpic_defined_alleles") or {}) | {
                    m["alternate"]
                    for m in record.get("clinvar_records_at_this_coordinate", [])
                    if m["asserts_clinical_relevance"]
                }
                for allele in rejected - {record["assessed_allele"]}:
                    self.assertEqual(record["dbsnp_frequencies"].get(allele, 0.0), 0.0)


class DecisionRuleTest(unittest.TestCase):
    """The rules themselves, exercised without the network."""

    def _target(self, **overrides):
        from scripts.curate_assessed_alleles import cpic_variant_alleles

        return cpic_variant_alleles

    def test_cpic_lookup_finds_every_allele_a_position_defines(self):
        from scripts.curate_assessed_alleles import cpic_variant_alleles

        registry = {
            "genes": {
                "TPMT": {
                    "alleles": {
                        "TPMT*3A": {"defining": [{"rsid": "rs1142345", "allele": "C"}]},
                        "TPMT*3C": {"defining": [{"rsid": "rs1142345", "allele": "C"}]},
                        "TPMT*41": {"defining": [{"rsid": "rs1142345", "allele": "G"}]},
                    }
                }
            }
        }
        found = cpic_variant_alleles("rs1142345", registry)
        self.assertEqual(found["C"], ["TPMT*3A", "TPMT*3C"])
        self.assertEqual(found["G"], ["TPMT*41"])

    def test_an_absent_registry_yields_nothing_rather_than_failing(self):
        from scripts.curate_assessed_alleles import cpic_variant_alleles

        self.assertEqual(cpic_variant_alleles("rs1142345", None), {})

    def test_a_benign_classification_is_not_a_clinical_assertion(self):
        from scripts.curate_assessed_alleles import ASSERTING, NON_ASSERTING

        self.assertIn("pathogenic", ASSERTING)
        self.assertIn("drug response", ASSERTING)
        self.assertIn("benign", NON_ASSERTING)


class BcheFallbackTest(unittest.TestCase):
    """CPIC publishes no BCHE table; ClinVar supplies the variants, with citation."""

    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(PGX_PATH.read_text(encoding="utf-8"))
        cls.bche = cls.registry["genes"]["BCHE"]

    def test_bche_now_carries_variant_definitions(self):
        self.assertTrue(self.bche["alleles"], "the ClinVar fallback produced no definitions")
        for allele, definition in self.bche["alleles"].items():
            with self.subTest(allele=allele):
                self.assertTrue(definition["defining"])
                self.assertTrue(definition["clinvar_accessions"])
                for accession in definition["clinvar_accessions"]:
                    self.assertRegex(accession, r"^VCV\d+$")

    def test_the_gap_and_its_reason_are_still_recorded(self):
        """The variants exist, but ClinVar is not an allele-definition registry."""
        self.assertFalse(self.bche["complete_panel"])
        self.assertIn("ClinVar", self.bche["complete_panel_scope"])
        self.assertIn("PharmVar", self.bche["definitions_unavailable"])
        self.assertIn("nomenclatura estrela", self.bche["definitions_unavailable"])

    def test_no_star_nomenclature_is_invented_for_bche(self):
        """`BCHE*2` is not in a verifiable public registry, so it is not written."""
        for allele in self.bche["alleles"]:
            with self.subTest(allele=allele):
                self.assertNotIn("*", allele.replace("BCHE ", ""))

    def test_bche_still_yields_no_diplotype_or_phenotype(self):
        from array_pipeline.pharmacogenomics import _diplotype_for

        result = _diplotype_for("BCHE", self.bche, [], [], [])
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("CPIC não publica" in r for r in result["reasons"]))
        self.assertEqual(self.bche["phenotype_map"], {})

    def test_the_anaesthesia_note_survives_the_fallback(self):
        self.assertTrue(self.bche["anesthesia_relevant"])
        self.assertIn("succinilcolina", self.bche["anesthesia_note"])


if __name__ == "__main__":
    unittest.main()
