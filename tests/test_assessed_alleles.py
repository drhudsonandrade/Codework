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
from unittest.mock import patch

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

    #: Every provenance label a verdict may carry. `ClinVar (fallback)` covers genes CPIC
    #: does not publish — BCHE — where the definitions live in the PGx registry but did not
    #: come from CPIC. Labelling those "CPIC" because they came out of that file
    #: misattributed exactly the entries whose provenance is unusual.
    SOURCES = {
        "CPIC",
        "ClinVar",
        "ClinVar (fallback)",
        "GWAS Catalog",
        "CPIC + dbSNP frequency",
        "ClinVar + dbSNP frequency",
        "ClinVar (fallback) + dbSNP frequency",
    }

    def test_every_verdict_states_which_source_decided_it(self):
        for record in self.evidence["results"]:
            with self.subTest(rsid=record["rsid"]):
                self.assertTrue(record["reason"])
                if record["status"] == "VERIFICADO":
                    self.assertIn(record["source"], self.SOURCES)

    def test_a_clinvar_fallback_gene_is_not_labelled_cpic(self):
        """BCHE's definitions came from ClinVar; the registry file is not the provenance."""
        for rsid in ("rs1799807", "rs1803274"):
            with self.subTest(rsid=rsid):
                self.assertEqual(self.by_rsid[rsid]["source"], "ClinVar (fallback)")
        target = next(t for t in self.targets["targets"] if t["rsid"] == "rs1799807")
        self.assertEqual(target["assessed_allele_source"], "ClinVar (fallback)")

    def test_a_contradiction_in_the_literature_is_recorded_as_such(self):
        """rs4307059: the GWAS Catalogue reports opposite risk alleles across studies."""
        record = self.by_rsid["rs4307059"]
        self.assertEqual(record["status"], "NÃO DISPONÍVEL")
        self.assertEqual(record["source"], "GWAS Catalog")
        self.assertIn("disagree", record["reason"])
        self.assertGreater(len(record["gwas_catalog"]["risk_alleles"]), 1)

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

    def test_clinvar_assertion_classification_uses_complete_terms(self):
        from scripts.curate_assessed_alleles import _is_asserting_classification

        self.assertTrue(_is_asserting_classification("Pathogenic/Likely pathogenic"))
        self.assertTrue(_is_asserting_classification("Drug response"))
        self.assertFalse(
            _is_asserting_classification(
                "Conflicting classifications of pathogenicity"
            )
        )
        self.assertFalse(_is_asserting_classification("Benign; drug response"))

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

    def test_provenance_is_read_from_the_gene_not_the_file_it_lives_in(self):
        """The PGx registry holds both CPIC data and a ClinVar fallback; only the gene knows."""
        from scripts.curate_assessed_alleles import registry_source

        cpic = {"genes": {"TPMT": {"alleles": {"TPMT*3C": {"defining": [{"rsid": "rs1142345", "allele": "C"}]}}}}}
        fallback = {
            "genes": {
                "BCHE": {
                    "variant_source": "NCBI ClinVar via E-utilities",
                    "alleles": {"BCHE x": {"defining": [{"rsid": "rs1799807", "allele": "C"}]}},
                }
            }
        }
        self.assertEqual(registry_source("rs1142345", cpic), "CPIC")
        self.assertEqual(registry_source("rs1799807", fallback), "ClinVar (fallback)")
        self.assertEqual(registry_source("rs999999", cpic), "CPIC")
        self.assertEqual(registry_source("rs1", None), "CPIC")

    def test_the_shipped_registry_marks_its_fallback_gene(self):
        registry = json.loads(PGX_PATH.read_text(encoding="utf-8"))
        self.assertTrue(registry["genes"]["BCHE"].get("variant_source"))
        self.assertNotIn("variant_source", registry["genes"]["CYP2C19"])

    def test_a_benign_classification_is_not_a_clinical_assertion(self):
        from scripts import curate_assessed_alleles as curation

        def record(classification: str) -> dict:
            return {
                "uid": "1",
                "accession": "VCV000000001",
                "variation_set": [
                    {"canonical_spdi": "NC_000001.11:100:A:T"}
                ],
                "germline_classification": {"description": classification},
            }

        placement = {
            "GRCh38": {
                "seq_id": "NC_000001.11",
                "chromosome": "1",
                "position": 101,
                "reference_allele": "A",
            }
        }
        for classification in (
            "Benign",
            "Conflicting classifications of pathogenicity",
            "Pathogenic; Benign",
        ):
            with (
                self.subTest(classification=classification),
                patch.object(curation, "fetch_refsnp", return_value={}),
                patch.object(curation, "placements", return_value=placement),
                patch.object(curation, "clinvar_records", return_value=[record(classification)]),
                patch.object(curation, "frequency_alleles", return_value={}),
                patch.object(curation, "clinvar_citations", return_value=[]),
                patch.object(curation, "cpic_variant_alleles", return_value={}),
                patch.object(
                    curation,
                    "gwas_risk_alleles",
                    return_value={"available": False, "risk_alleles": {}, "studies": 0},
                ),
                patch.object(curation.time, "sleep"),
            ):
                result = curation.curate_target("rs1")
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertIsNone(result["assessed_allele"])

        with (
            patch.object(curation, "fetch_refsnp", return_value={}),
            patch.object(curation, "placements", return_value=placement),
            patch.object(curation, "clinvar_records", return_value=[record("Pathogenic")]),
            patch.object(curation, "frequency_alleles", return_value={}),
            patch.object(curation, "clinvar_citations", return_value=[]),
            patch.object(curation, "cpic_variant_alleles", return_value={}),
            patch.object(curation.time, "sleep"),
        ):
            asserted = curation.curate_target("rs1")
        self.assertEqual(asserted["status"], "VERIFICADO")
        self.assertEqual(asserted["assessed_allele"], "T")


    def test_apply_writes_verified_status_with_the_allele(self):
        from scripts.curate_assessed_alleles import _apply_target_assessment

        target = {
            "rsid": "rs1",
            "assessed_allele_status": "NÃO DISPONÍVEL",
            "assessed_allele_reason": "old refusal",
        }
        _apply_target_assessment(
            target,
            {
                "assessed_allele": "T",
                "status": "VERIFICADO",
                "source": "ClinVar",
                "references": {},
            },
            "evidence.json",
        )
        self.assertEqual(target["assessed_allele"], "T")
        self.assertEqual(target["assessed_allele_status"], "VERIFICADO")
        self.assertNotIn("assessed_allele_reason", target)


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


class ReferencesTest(unittest.TestCase):
    """A curated allele must be traceable to primary literature, not just to this file."""

    @classmethod
    def setUpClass(cls):
        cls.targets = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
        cls.evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.by_rsid = {r["rsid"]: r for r in cls.evidence["results"]}

    def test_the_curation_cites_every_source_it_consulted(self):
        joined = " ".join(self.evidence["sources"])
        for source in ("dbSNP", "ClinVar", "CPIC", "GWAS Catalog", "PubMed"):
            self.assertIn(source, joined)

    def test_every_assessed_target_carries_references(self):
        for target in self.targets["targets"]:
            if "assessed_allele" not in target:
                continue
            with self.subTest(rsid=target["rsid"]):
                references = target["references"]
                self.assertTrue(
                    references["clinvar_accessions"]
                    or references["clinvar_pubmed"]
                    or references["cpic_pubmed"],
                    "an assessed allele with no reference at all is untraceable",
                )

    def test_clinvar_accessions_are_well_formed(self):
        for record in self.evidence["results"]:
            for accession in record.get("references", {}).get("clinvar_accessions", []):
                with self.subTest(rsid=record["rsid"], accession=accession):
                    self.assertRegex(accession, r"^VCV\d+$")

    def test_pubmed_ids_are_numeric_and_bounded(self):
        from scripts.curate_assessed_alleles import MAX_CITATIONS

        for record in self.evidence["results"]:
            references = record.get("references", {})
            for key in ("clinvar_pubmed", "cpic_pubmed"):
                pmids = references.get(key, [])
                with self.subTest(rsid=record["rsid"], key=key):
                    self.assertLessEqual(len(pmids), MAX_CITATIONS)
                    for pmid in pmids:
                        self.assertRegex(pmid, r"^\d+$")

    def test_references_are_deduplicated(self):
        for record in self.evidence["results"]:
            references = record.get("references", {})
            for key, values in references.items():
                with self.subTest(rsid=record["rsid"], key=key):
                    self.assertEqual(len(values), len(set(values)))

    def test_the_corpus_is_substantial_enough_to_be_worth_citing(self):
        """A reference block that collapsed to nothing would pass every test above."""
        total = sum(
            len(t.get("references", {}).get("clinvar_pubmed", []))
            + len(t.get("references", {}).get("cpic_pubmed", []))
            for t in self.targets["targets"]
        )
        self.assertGreater(total, 100, "the citation harvest produced almost nothing")


if __name__ == "__main__":
    unittest.main()
