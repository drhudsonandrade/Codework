from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from array_pipeline.clinical_findings import (
    GENOTIPO_DE_RISCO,
    _interpretation,
    _validity_for,
    build_clinical_findings,
)
from reporting.case_dossier import SEX_FEMALE, SEX_INTERSEX, SEX_NOT_RECORDED


def _pathogenic_x_linked(genotype: str, sex: str | None):
    return _interpretation(
        {
            "classification": "OBSERVADO",
            "genotype": genotype,
            "scope": "CLINICO",
            "assessed_allele": "A",
        },
        {
            "asserts_pathogenic": True,
            "meets_review_threshold": True,
            "classifications": ["Pathogenic"],
            "condition_xrefs": {},
        },
        {
            "established": True,
            "established_by": ["ClinGen"],
            "modes_of_inheritance": ["XL"],
            "diseases_by_mondo": {},
            "diseases_by_name": {},
        },
        sex,
    )


class ClinicalFindingsRegressionTest(unittest.TestCase):
    def test_clingen_disease_lists_normalise_the_mode_of_inheritance(self):
        validity = _validity_for("GENE", {
            "gene_validity": {
                "GENE": {
                    "clingen": {
                        "curations": [{
                            "classification": "Strong",
                            "disease": "Fixture disease",
                            "mode_of_inheritance": "Autosomal recessive",
                        }]
                    }
                }
            }
        })
        self.assertEqual(validity["recessive_diseases"], ["Fixture disease"])

    def test_unknown_female_zygosity_is_not_described_as_homozygous(self):
        result = _pathogenic_x_linked("DI", SEX_FEMALE)
        self.assertEqual(result["kind"], GENOTIPO_DE_RISCO)
        self.assertIn("zigosidade não foi determinada", result["basis"])
        self.assertNotIn("homozigoto", result["basis"].lower())

    def test_intersex_has_its_own_x_linked_refusal(self):
        result = _pathogenic_x_linked("AG", SEX_INTERSEX)
        self.assertIn("intersexo", result["basis"])
        self.assertNotIn("não registra o sexo", result["basis"])
        self.assertNotIn("Preencha", result["basis"])

    def test_explicit_not_recorded_is_distinct_from_an_absent_field(self):
        explicit = _pathogenic_x_linked("AG", SEX_NOT_RECORDED)["basis"]
        absent = _pathogenic_x_linked("AG", None)["basis"]
        self.assertIn("explicitamente", explicit)
        self.assertNotIn("Preencha", explicit)
        self.assertIn("Preencha", absent)

    def test_qc_reservations_travel_with_the_clinical_payload(self):
        reservations = [{"gate": "LIMITED_INTERPRETATION_GATE", "state": "BLOCKED"}]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            matrix = root / "matrix.json"
            matrix.write_text(json.dumps({
                "schema": "genoma-genome-completeness-matrix-v1",
                "case_id": "CASE",
                "operational_status": "NÃO DISPONÍVEL",
                "qc_reservations": reservations,
                "entries": [],
            }), encoding="utf-8")
            evidence = root / "evidence.json"
            evidence.write_text(json.dumps({
                "schema": "genoma-gene-disease-validity-v1",
                "sources": ["fixture"],
                "gene_validity": {},
                "loci": [],
            }), encoding="utf-8")
            assessed = root / "assessed.json"
            assessed.write_text(json.dumps({"results": []}), encoding="utf-8")
            result = build_clinical_findings(matrix, evidence, assessed)
        self.assertEqual(result["qc_reservations"], reservations)


if __name__ == "__main__":
    unittest.main()
