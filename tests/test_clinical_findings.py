"""Screening must not become diagnosis, and a text match must not become a coordinate match.

The clinical join is where a genotype acquires a meaning, so every step that adds meaning has
a guard here and every guard has a negative control — a fixture where it must fire, so that a
passing test proves the check works rather than proving the fixture was easy.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.clinical_findings import (
    ACHADO_PRELIMINAR,
    ACIONAVEL,
    GENOTIPO_DE_RISCO,
    MOI_UNKNOWN,
    NAO_INTERROGADO,
    NEGATIVO,
    PORTADOR,
    SEM_INTERPRETACAO,
    ClinicalEvidenceError,
    build_clinical_findings,
    normalised_moi,
)

MATRIX = {
    "schema": "genoma-genome-completeness-matrix-v1",
    "operational_status": "VERIFICADO",
    "case_id": "CASE-1",
    "input_sha256": "abc",
    "sha256": "matrix-sha",
    "qc_gate_passed": True,
    "negative_statement_policy": "Só NÃO DETECTADO admite afirmação de ausência.",
    "entries": [],
}


def _entry(rsid, gene, classification="OBSERVADO", genotype="AG", scope="CLINICO"):
    return {
        "rsid": rsid,
        "gene": gene,
        "scope": scope,
        "classification": classification,
        "basis": "fixture",
        "interpretable": classification in ("OBSERVADO", "NÃO DETECTADO"),
        "genotype": genotype if classification in ("OBSERVADO", "NÃO DETECTADO") else None,
        "genotype_withheld": classification not in ("OBSERVADO", "NÃO DETECTADO"),
        "assessed_allele": "A",
    }


def _validity(
    *,
    clingen=(),
    gencc=(),
    panelapp=None,
    constraint=None,
):
    extra: dict = {}
    if panelapp is not None:
        extra["panelapp"] = panelapp
    if constraint is not None:
        extra["gnomad_constraint"] = constraint
    return {
        **extra,
        "clingen": {
            "status": "VERIFICADO" if clingen else "NÃO DISPONÍVEL",
            "curations": list(clingen),
            "classifications": sorted({c["classification"] for c in clingen}),
            "modes_of_inheritance": sorted(
                {normalised_moi(c["mode_of_inheritance"]) for c in clingen
                 if c["classification"] in ("Definitive", "Strong")}
            ),
            "established": any(c["classification"] in ("Definitive", "Strong") for c in clingen),
        },
        "gencc": {
            "status": "VERIFICADO" if gencc else "NÃO DISPONÍVEL",
            "groups": list(gencc),
            "established_groups": [g for g in gencc if g.get("established")],
            "modes_of_inheritance": sorted(
                {normalised_moi(g["mode_of_inheritance"]) for g in gencc if g.get("established")}
            ),
            "diseases": sorted({g["disease"] for g in gencc if g.get("established")}),
            "established": any(g.get("established") for g in gencc),
            "mode_of_inheritance_conflicts": [],
        },
    }


def _evidence(gene_validity, loci):
    return {
        "schema": "genoma-gene-disease-validity-v1",
        "sha256": "evidence-sha",
        "curated_at": "2026-08-19T00:00:00Z",
        "clingen_file_created": "2026-08-19",
        "sources": ["fixture de teste"],
        "gene_validity": gene_validity,
        "loci": loci,
    }


def _locus(rsid, gene, records):
    return {"rsid": rsid, "gene": gene, "clinvar": {"records": records}, "gwas": {"traits": []}}


def _record(accession, classification, conditions=(), review="criteria provided, multiple submitters, no conflicts"):
    return {
        "accession": accession,
        "title": f"{accession} title",
        "classification": classification,
        "review_status": review,
        "last_evaluated": "2026/01/01",
        "conditions": [
            {"name": name, "xrefs": {"MONDO": mondo} if mondo else {}}
            for name, mondo in conditions
        ],
        "genes": [gene for gene in ()],
    }


def _assessed(rsid, accessions):
    return {
        "results": [
            {
                "rsid": rsid,
                "clinvar_records_at_this_coordinate": [{"accession": a} for a in accessions],
            }
        ]
    }


def _run(entries, gene_validity, loci, assessed):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        matrix = dict(MATRIX, entries=entries)
        (root / "m.json").write_text(json.dumps(matrix), encoding="utf-8")
        (root / "e.json").write_text(json.dumps(_evidence(gene_validity, loci)), encoding="utf-8")
        (root / "a.json").write_text(json.dumps(assessed), encoding="utf-8")
        return build_clinical_findings(root / "m.json", root / "e.json", root / "a.json")


AR_CLINGEN = ({"disease": "hemochromatosis type 1", "mondo": "MONDO:0021001",
               "mode_of_inheritance": "AR", "classification": "Definitive"},)
AD_CLINGEN = ({"disease": "thrombophilia", "mondo": "MONDO:0008560",
               "mode_of_inheritance": "AD", "classification": "Definitive"},)


class CoordinateJoinTest(unittest.TestCase):
    """ClinVar is joined by verified accession, never by the rsid text search that found it."""

    def test_an_accession_outside_the_verified_set_is_discarded(self):
        result = _run(
            [_entry("rs1", "HFE")],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [_locus("rs1", "HFE", [
                _record("VCV000001", "Pathogenic", [("hemochromatosis type 1", "MONDO:0021001")]),
                _record("VCV999999", "Pathogenic", [("unrelated disease", "MONDO:9999999")]),
            ])],
            _assessed("rs1", ["VCV000001"]),
        )
        finding = result["findings"][0]
        self.assertEqual(finding["clinvar"]["accessions_discarded_by_coordinate"], 1)
        self.assertEqual([r["accession"] for r in finding["clinvar"]["records"]], ["VCV000001"])

    def test_no_verified_accession_means_no_clinvar_evidence(self):
        # Negative control: if the coordinate check were skipped, this locus would come back
        # Pathogenic on the strength of a text match alone.
        result = _run(
            [_entry("rs1", "HFE")],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [_locus("rs1", "HFE", [_record("VCV999999", "Pathogenic")])],
            _assessed("rs1", ["VCV000001"]),
        )
        finding = result["findings"][0]
        self.assertEqual(finding["clinvar"]["status"], "NÃO DISPONÍVEL")
        self.assertFalse(finding["clinvar"]["asserts_pathogenic"])
        self.assertEqual(finding["interpretation"], SEM_INTERPRETACAO)


class InterpretationTest(unittest.TestCase):
    def test_heterozygous_pathogenic_in_a_recessive_condition_is_a_carrier(self):
        result = _run(
            [_entry("rs1", "HFE", genotype="AG")],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [_locus("rs1", "HFE", [
                _record("V1", "Pathogenic", [("hemochromatosis type 1", "MONDO:0021001")])
            ])],
            _assessed("rs1", ["V1"]),
        )
        self.assertEqual(result["findings"][0]["interpretation"], PORTADOR)

    def test_heterozygous_pathogenic_in_a_dominant_condition_is_actionable(self):
        result = _run(
            [_entry("rs1", "F5", genotype="AG")],
            {"F5": _validity(clingen=AD_CLINGEN)},
            [_locus("rs1", "F5", [_record("V1", "Pathogenic", [("thrombophilia", "MONDO:0008560")])])],
            _assessed("rs1", ["V1"]),
        )
        self.assertEqual(result["findings"][0]["interpretation"], ACIONAVEL)

    def test_the_condition_clinvar_names_decides_the_mode_not_the_gene_union(self):
        # F5 is dominant for thrombophilia and recessive for factor V deficiency. Taking the
        # union over the gene would refuse both; matching the variant's own condition by
        # MONDO gets the right one.
        both = (
            {"disease": "thrombophilia", "mondo": "MONDO:0008560",
             "mode_of_inheritance": "AD", "classification": "Definitive"},
            {"disease": "factor V deficiency", "mondo": "MONDO:0009210",
             "mode_of_inheritance": "AR", "classification": "Definitive"},
        )
        result = _run(
            [_entry("rs1", "F5", genotype="AG")],
            {"F5": _validity(clingen=both)},
            [_locus("rs1", "F5", [_record("V1", "Pathogenic", [("thrombophilia", "MONDO:0008560")])])],
            _assessed("rs1", ["V1"]),
        )
        finding = result["findings"][0]
        self.assertEqual(finding["interpretation"], ACIONAVEL)
        self.assertIn("thrombophilia", finding["interpretation_basis"])

    def test_an_unmatched_condition_falls_back_to_the_gene_union_and_says_so(self):
        both = (
            {"disease": "thrombophilia", "mondo": "MONDO:0008560",
             "mode_of_inheritance": "AD", "classification": "Definitive"},
            {"disease": "factor V deficiency", "mondo": "MONDO:0009210",
             "mode_of_inheritance": "AR", "classification": "Definitive"},
        )
        result = _run(
            [_entry("rs1", "F5", genotype="AG")],
            {"F5": _validity(clingen=both)},
            [_locus("rs1", "F5", [_record("V1", "Pathogenic", [("some other thing", "MONDO:1111111")])])],
            _assessed("rs1", ["V1"]),
        )
        finding = result["findings"][0]
        self.assertEqual(finding["interpretation"], GENOTIPO_DE_RISCO)
        self.assertIn("nenhuma condição do ClinVar coincide", finding["interpretation_basis"])

    def test_homozygous_pathogenic_is_a_risk_genotype_not_a_diagnosis(self):
        result = _run(
            [_entry("rs1", "HFE", genotype="AA")],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [_locus("rs1", "HFE", [
                _record("V1", "Pathogenic", [("hemochromatosis type 1", "MONDO:0021001")])
            ])],
            _assessed("rs1", ["V1"]),
        )
        finding = result["findings"][0]
        self.assertEqual(finding["interpretation"], GENOTIPO_DE_RISCO)
        self.assertIn("não diagnóstico", finding["interpretation_basis"])
        self.assertNotIn("afetado", finding["interpretation_basis"])

    def test_pathogenic_without_established_validity_is_not_a_finding(self):
        result = _run(
            [_entry("rs1", "SERPINA1", genotype="AG")],
            {"SERPINA1": _validity()},
            [_locus("rs1", "SERPINA1", [_record("V1", "Pathogenic")])],
            _assessed("rs1", ["V1"]),
        )
        finding = result["findings"][0]
        self.assertEqual(finding["interpretation"], SEM_INTERPRETACAO)
        self.assertIn("nenhum dos registros curados", finding["interpretation_basis"])
        for registry in ("ClinGen", "GenCC", "PanelApp"):
            self.assertIn(registry, finding["interpretation_basis"])

    def test_gencc_alone_can_establish_validity(self):
        # The bug this pins: `_gencc_summary` once returned no `established` key, so the
        # aggregate was fetched, grouped, and then ignored by the caller.
        gencc = (
            {"disease": "alpha 1-antitrypsin deficiency", "disease_curie": "MONDO:0013282",
             "mode_of_inheritance": "Autosomal recessive", "established": True,
             "submitters": ["A", "B"], "classifications": ["Strong"]},
        )
        result = _run(
            [_entry("rs1", "SERPINA1", genotype="AG")],
            {"SERPINA1": _validity(gencc=gencc)},
            [_locus("rs1", "SERPINA1", [
                _record("V1", "Pathogenic", [("alpha 1-antitrypsin deficiency", "MONDO:0013282")])
            ])],
            _assessed("rs1", ["V1"]),
        )
        finding = result["findings"][0]
        self.assertEqual(finding["interpretation"], PORTADOR)
        self.assertEqual(finding["validity"]["established_by"], ["GenCC"])

    def test_benign_is_reported_as_benign_not_as_absence_of_evidence(self):
        result = _run(
            [_entry("rs1", "HFE", genotype="AG")],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [_locus("rs1", "HFE", [_record("V1", "Benign")])],
            _assessed("rs1", ["V1"]),
        )
        finding = result["findings"][0]
        self.assertEqual(finding["interpretation"], SEM_INTERPRETACAO)
        self.assertIn("benigna", finding["interpretation_basis"])

    def test_an_unrecognised_clinvar_label_is_surfaced_and_is_not_pathogenic(self):
        result = _run(
            [_entry("rs1", "HFE", genotype="AG")],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [_locus("rs1", "HFE", [_record("V1", "Probably quite bad")])],
            _assessed("rs1", ["V1"]),
        )
        finding = result["findings"][0]
        self.assertFalse(finding["clinvar"]["asserts_pathogenic"])
        self.assertEqual(finding["clinvar"]["unrecognised_classifications"], ["Probably quite bad"])
        self.assertEqual(finding["interpretation"], SEM_INTERPRETACAO)


class CoverageClassTest(unittest.TestCase):
    def test_not_detected_licenses_a_negative_only_for_that_locus(self):
        result = _run(
            [_entry("rs1", "HFE", classification="NÃO DETECTADO", genotype="GG")],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [_locus("rs1", "HFE", [_record("V1", "Pathogenic")])],
            _assessed("rs1", ["V1"]),
        )
        finding = result["findings"][0]
        self.assertEqual(finding["interpretation"], NEGATIVO)
        self.assertIn("apenas para este locus", finding["interpretation_basis"])

    def test_non_interpretable_classes_license_nothing(self):
        for classification in ("NÃO TESTADO", "NO-CALL", "NÃO REPORTÁVEL"):
            with self.subTest(classification=classification):
                result = _run(
                    [_entry("rs1", "HFE", classification=classification)],
                    {"HFE": _validity(clingen=AR_CLINGEN)},
                    [_locus("rs1", "HFE", [_record("V1", "Pathogenic")])],
                    _assessed("rs1", ["V1"]),
                )
                self.assertEqual(result["findings"][0]["interpretation"], NAO_INTERROGADO)


class ModeNormalisationTest(unittest.TestCase):
    def test_clingen_abbreviations_and_gencc_labels_are_the_same_mode(self):
        self.assertEqual(normalised_moi("AR"), normalised_moi("Autosomal recessive"))
        self.assertEqual(normalised_moi("AD"), normalised_moi("Autosomal dominant"))

    def test_an_unknown_label_does_not_become_a_recognised_mode(self):
        for label in (None, "", "digenic", "mitochondrial"):
            self.assertEqual(normalised_moi(label), "DESCONHECIDO", label)


class ContractTest(unittest.TestCase):
    def test_evidence_without_sources_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "m.json").write_text(json.dumps(MATRIX), encoding="utf-8")
            evidence = _evidence({}, [])
            evidence["sources"] = []
            (root / "e.json").write_text(json.dumps(evidence), encoding="utf-8")
            (root / "a.json").write_text(json.dumps({"results": []}), encoding="utf-8")
            with self.assertRaises(ClinicalEvidenceError):
                build_clinical_findings(root / "m.json", root / "e.json", root / "a.json")

    def test_the_join_is_never_stronger_than_the_matrix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            matrix = dict(MATRIX, operational_status="NÃO DISPONÍVEL", entries=[_entry("rs1", "HFE")])
            (root / "m.json").write_text(json.dumps(matrix), encoding="utf-8")
            (root / "e.json").write_text(json.dumps(_evidence({}, [])), encoding="utf-8")
            (root / "a.json").write_text(json.dumps({"results": []}), encoding="utf-8")
            result = build_clinical_findings(root / "m.json", root / "e.json", root / "a.json")
        self.assertEqual(result["operational_status"], "NÃO DISPONÍVEL")

    def test_totals_are_counted_not_asserted(self):
        result = _run(
            [
                _entry("rs1", "HFE", genotype="AG"),
                _entry("rs2", "HFE", classification="NÃO DETECTADO", genotype="GG"),
                _entry("rs3", "HFE", classification="NO-CALL"),
            ],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [
                _locus("rs1", "HFE", [
                    _record("V1", "Pathogenic", [("hemochromatosis type 1", "MONDO:0021001")])
                ]),
                _locus("rs2", "HFE", []),
                _locus("rs3", "HFE", []),
            ],
            {"results": [{"rsid": "rs1", "clinvar_records_at_this_coordinate": [{"accession": "V1"}]}]},
        )
        totals = result["totals"]
        self.assertEqual(totals["loci"], 3)
        self.assertEqual(totals[f"kind_{PORTADOR}"], 1)
        self.assertEqual(totals[f"kind_{NEGATIVO}"], 1)
        self.assertEqual(totals[f"kind_{NAO_INTERROGADO}"], 1)
        self.assertEqual(totals["confirmation_required"], 1)


class ReviewLevelTest(unittest.TestCase):
    """One submitter is one laboratory's opinion, whatever the gene's validity."""

    def _run_with_review(self, review: str):
        return _run(
            [_entry("rs1", "HFE", genotype="AG")],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [_locus("rs1", "HFE", [
                _record("V1", "Pathogenic",
                        [("hemochromatosis type 1", "MONDO:0021001")], review=review)
            ])],
            _assessed("rs1", ["V1"]),
        )["findings"][0]

    def test_two_stars_or_better_can_become_a_carrier_finding(self):
        for review in (
            "criteria provided, multiple submitters, no conflicts",
            "reviewed by expert panel",
            "practice guideline",
        ):
            with self.subTest(review=review):
                finding = self._run_with_review(review)
                self.assertEqual(finding["interpretation"], PORTADOR)
                self.assertTrue(finding["clinvar"]["meets_review_threshold"])

    def test_one_star_is_preliminary_and_never_a_carrier_finding(self):
        # The negative control for the whole one-star expansion: without this the registry
        # would report tens of thousands of single-submitter assertions as carrier findings.
        for review in (
            "criteria provided, single submitter",
            "criteria provided, conflicting classifications",
        ):
            with self.subTest(review=review):
                finding = self._run_with_review(review)
                self.assertEqual(finding["interpretation"], ACHADO_PRELIMINAR)
                self.assertFalse(finding["clinvar"]["meets_review_threshold"])
                self.assertIn("submetente único", finding["interpretation_basis"])

    def test_no_assertion_criteria_scores_zero_stars(self):
        finding = self._run_with_review("no assertion criteria provided")
        self.assertEqual(finding["clinvar"]["review_stars"], 0)
        self.assertEqual(finding["interpretation"], ACHADO_PRELIMINAR)

    def test_an_unrecognised_review_status_scores_zero_rather_than_passing(self):
        finding = self._run_with_review("reviewed by a friend")
        self.assertEqual(finding["clinvar"]["review_stars"], 0)
        self.assertEqual(finding["clinvar"]["unrecognised_review_statuses"], ["reviewed by a friend"])
        self.assertEqual(finding["interpretation"], ACHADO_PRELIMINAR)

    def test_a_well_reviewed_benign_record_does_not_lend_its_stars_to_a_weak_pathogenic_one(self):
        # Stars are taken from the records that assert pathogenicity. A four-star benign
        # record says nothing about how well reviewed the pathogenic claim is.
        finding = _run(
            [_entry("rs1", "HFE", genotype="AG")],
            {"HFE": _validity(clingen=AR_CLINGEN)},
            [_locus("rs1", "HFE", [
                _record("V1", "Pathogenic", [("hemochromatosis type 1", "MONDO:0021001")],
                        review="criteria provided, single submitter"),
                _record("V2", "Benign", [], review="practice guideline"),
            ])],
            _assessed("rs1", ["V1", "V2"]),
        )["findings"][0]
        self.assertEqual(finding["clinvar"]["review_stars"], 1)
        self.assertEqual(finding["interpretation"], ACHADO_PRELIMINAR)

    def test_a_preliminary_finding_still_requires_confirmation(self):
        finding = self._run_with_review("criteria provided, single submitter")
        self.assertTrue(finding["confirmation_required"])


GREEN_PANELAPP = {
    "status": "VERIFICADO",
    "established": True,
    "established_by": ["Genomics England PanelApp"],
    "green_panel_count": 2,
    "modes_of_inheritance": ["AR"],
}
AMBER_PANELAPP = {
    "status": "NÃO DISPONÍVEL",
    "established": False,
    "established_by": [],
    "green_panel_count": 0,
    "modes_of_inheritance": [],
}


class PanelAppAndConstraintTest(unittest.TestCase):
    """A third registry may establish a gene; a constraint metric may not."""

    def _run_with(self, validity):
        return _run(
            [_entry("rs1", "HFE", genotype="AG")],
            {"HFE": validity},
            [_locus("rs1", "HFE", [
                _record("V1", "Pathogenic", [("hemochromatosis type 1", "MONDO:0021001")])
            ])],
            _assessed("rs1", ["V1"]),
        )["findings"][0]

    def test_a_panelapp_green_gene_carries_a_carrier_call_on_its_own(self):
        finding = self._run_with(_validity(panelapp=GREEN_PANELAPP))
        self.assertEqual(finding["validity"]["established_by"], ["PanelApp"])
        self.assertEqual(finding["interpretation"], PORTADOR)
        # No MONDO-anchored disease came from PanelApp, so the basis must say the mode is the
        # gene-level union rather than implying a matched condition.
        self.assertIn("união do gene", finding["interpretation_basis"])

    def test_an_amber_gene_does_not_carry_anything(self):
        finding = self._run_with(_validity(panelapp=AMBER_PANELAPP))
        self.assertEqual(finding["validity"]["established_by"], [])
        self.assertEqual(finding["interpretation"], SEM_INTERPRETACAO)

    def test_the_registry_is_named_in_the_basis_text(self):
        finding = self._run_with(_validity(panelapp=GREEN_PANELAPP))
        self.assertIn("PanelApp", finding["interpretation_basis"])

    def test_constraint_alone_establishes_nothing(self):
        # The failure this guards against: a pLI of 1.0 is a population observation about a
        # gene rarely broken in healthy people, not an assertion that this variant means
        # something. Letting it establish would convert every constrained gene into a report.
        finding = self._run_with(
            _validity(constraint={"status": "VERIFICADO", "pli": 1.0, "loeuf": 0.08})
        )
        self.assertEqual(finding["validity"]["established_by"], [])
        self.assertFalse(finding["validity"]["established"])
        self.assertEqual(finding["interpretation"], SEM_INTERPRETACAO)
        # Carried anyway, so a "no established validity" line can still say the gene is
        # constrained.
        self.assertEqual(finding["validity"]["gnomad_constraint"]["pli"], 1.0)

    def test_the_gencc_overlap_reaches_the_finding(self):
        gencc = ({"disease": "hemochromatosis type 1", "disease_curie": "MONDO:0021001",
                  "mode_of_inheritance": "AR", "classification": "Definitive",
                  "submitters": ["Ambry", "Labcorp"], "established": True},)
        validity = _validity(gencc=gencc, panelapp=GREEN_PANELAPP)
        validity["panelapp_overlaps_gencc"] = True
        finding = self._run_with(validity)
        self.assertEqual(finding["validity"]["established_by"], ["GenCC", "PanelApp"])
        self.assertTrue(finding["validity"]["panelapp_overlaps_gencc"])

    def test_a_gene_with_no_registry_at_all_still_reports_a_shape(self):
        finding = self._run_with(_validity())
        self.assertEqual(finding["validity"]["panelapp_green_panels"], 0)
        self.assertEqual(finding["validity"]["gnomad_constraint"]["status"], "NÃO DISPONÍVEL")

    def test_a_panelapp_mode_of_unknown_shape_does_not_license_a_carrier_call(self):
        # DESCONHECIDO must not equal AR. If it did, every gene PanelApp lists with an
        # unparsed mode would produce carrier findings.
        panel = dict(GREEN_PANELAPP, modes_of_inheritance=["mode we do not recognise"])
        finding = self._run_with(_validity(panelapp=panel))
        self.assertEqual(finding["validity"]["modes_of_inheritance"], [MOI_UNKNOWN])
        self.assertEqual(finding["interpretation"], GENOTIPO_DE_RISCO)


if __name__ == "__main__":
    unittest.main()
