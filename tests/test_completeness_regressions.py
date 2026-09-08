from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from array_pipeline.completeness import (
    COMPARISON_NOT_APPLICABLE,
    NAO_DETECTADO,
    NAO_REPORTAVEL,
    NO_CALL,
    OBSERVADO,
    _classify,
    build_completeness_matrix,
)


class CompletenessRegressionTest(unittest.TestCase):
    """How the completeness matrix classifies genotypes and reconciles duplicate rows."""

    def _entry_for_rows(self, rows):
        """Build the one-target matrix entry for synthetic array rows."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_path = root / "array.csv"
            input_path.write_text("fixture", encoding="utf-8")
            qc_path = root / "qc.json"
            qc_path.write_text(
                json.dumps(
                    {
                        "input": {
                            "sha256": "fixture-sha",
                            "strand": "forward",
                            "strand_evidence_verified": True,
                        },
                        "gates": {
                            "STRUCTURE_GATE": {"state": "PASS"},
                            "LIMITED_INTERPRETATION_GATE": {"state": "PASS"},
                        },
                        "operational_status": "VERIFICADO",
                    }
                ),
                encoding="utf-8",
            )
            targets_path = root / "targets.json"
            targets_path.write_text(
                json.dumps(
                    {
                        "schema": "genoma-partial-genome-targets-v1",
                        "targets": [
                            {
                                "rsid": "rs1",
                                "scope": "CLINICO",
                                "queries": {},
                                "assessed_allele": "A",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch(
                    "array_pipeline.completeness.sha256_file",
                    return_value="fixture-sha",
                ),
                patch(
                    "array_pipeline.completeness._header_of",
                    return_value=["RSID", "CHROMOSOME", "POSITION", "RESULT"],
                ),
                patch(
                    "array_pipeline.completeness._row_reader",
                    return_value=iter(rows),
                ),
            ):
                result = build_completeness_matrix(
                    input_path, qc_path, targets_path
                )
        return result["entries"][0]

    def test_multibase_assessed_alleles_are_not_compared_character_by_character(self):
        """A multi-base assessed allele is compared as a unit, not character by character."""
        classification, basis = _classify(
            {"RESULT": "AA", "__orientation_status": "VERIFICADO"},
            "raw_snp_array_v1",
            {"assessed_allele": "AG"},
            "raw_snp_array_v1",
        )
        self.assertEqual(classification, OBSERVADO)
        self.assertIn("multibase", basis)
        self.assertIn("não é comparável", basis)

    def test_no_call_duplicate_does_not_create_a_divergent_genotype_conflict(self):
        """A no-call duplicate does not create a divergent genotype conflict."""
        entry = self._entry_for_rows([
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "AA"}),
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "--"}),
        ])
        self.assertEqual(entry["classification"], OBSERVADO)
        self.assertNotIn("divergentes", entry["basis"])

    def test_no_call_before_valid_duplicate_preserves_the_valid_call(self):
        """A no-call before a valid duplicate preserves the valid call."""
        entry = self._entry_for_rows([
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "--"}),
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "AA"}),
        ])
        self.assertEqual(entry["classification"], OBSERVADO)
        self.assertEqual(entry["genotype"], "AA")

    def test_duplicate_rows_with_no_valid_call_remain_no_call(self):
        """Duplicate rows with no valid call between them remain a no-call."""
        entry = self._entry_for_rows(
            [
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "--"}),
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "--"}),
            ]
        )
        self.assertEqual(entry["classification"], NO_CALL)

    def test_conflicting_valid_duplicates_are_not_reportable(self):
        """Two different valid calls at one locus fail closed."""
        entry = self._entry_for_rows(
            [
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "AA"}),
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "AG"}),
            ]
        )
        self.assertEqual(entry["classification"], NAO_REPORTAVEL)
        self.assertIn("divergentes", entry["basis"])

    def test_indel_codes_are_not_compared_as_snp_alleles(self):
        """Insertion/deletion call codes cannot satisfy an A/C/G/T assessed allele."""
        for genotype in ("II", "ID", "DI", "DD"):
            with self.subTest(genotype=genotype):
                classification, basis = _classify(
                    {"RESULT": genotype, "__orientation_status": "VERIFICADO"},
                    "raw_snp_array_v1",
                    {"assessed_allele": "A"},
                    "raw_snp_array_v1",
                )
                self.assertEqual(classification, OBSERVADO)
                self.assertIn("SNP diploide", basis)
                self.assertIn("ACGT", basis)

    def test_non_comparable_called_genotype_is_structurally_not_applicable(self):
        """A called indel is not forwarded as an interpretable allele comparison."""
        entry = self._entry_for_rows(
            [("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "ID"})]
        )
        self.assertEqual(entry["assessed_comparison"], COMPARISON_NOT_APPLICABLE)
        self.assertTrue(entry["interpretable"])
        self.assertFalse(entry["genotype_withheld"])

    def test_a_single_base_assessed_allele_absent_from_the_genotype_is_not_detected(self):
        """Positive control: an absent assessed SNP allele remains NÃO DETECTADO."""
        classification, basis = _classify(
            {"RESULT": "GG", "__orientation_status": "VERIFICADO"},
            "raw_snp_array_v1",
            {"assessed_allele": "A"},
            "raw_snp_array_v1",
        )
        self.assertEqual(classification, NAO_DETECTADO)
        self.assertIn("ausência vale apenas para este locus", basis)


if __name__ == "__main__":
    unittest.main()
