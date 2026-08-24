from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from array_pipeline.completeness import (
    NO_CALL,
    OBSERVADO,
    _classify,
    build_completeness_matrix,
)


class CompletenessRegressionTest(unittest.TestCase):
    def test_multibase_assessed_alleles_are_not_compared_character_by_character(self):
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
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_path = root / "array.csv"
            input_path.write_text("fixture", encoding="utf-8")
            qc_path = root / "qc.json"
            qc_path.write_text(json.dumps({
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
            }), encoding="utf-8")
            targets_path = root / "targets.json"
            targets_path.write_text(json.dumps({
                "schema": "genoma-partial-genome-targets-v1",
                "targets": [{
                    "rsid": "rs1",
                    "scope": "CLINICO",
                    "queries": {},
                    "assessed_allele": "A",
                }],
            }), encoding="utf-8")
            rows = iter([
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "AA"}),
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "--"}),
            ])
            with (
                patch("array_pipeline.completeness.sha256_file", return_value="fixture-sha"),
                patch(
                    "array_pipeline.completeness._header_of",
                    return_value=["RSID", "CHROMOSOME", "POSITION", "RESULT"],
                ),
                patch("array_pipeline.completeness._row_reader", return_value=rows),
            ):
                result = build_completeness_matrix(input_path, qc_path, targets_path)

        entry = result["entries"][0]
        self.assertEqual(entry["classification"], OBSERVADO)
        self.assertNotIn("divergentes", entry["basis"])

    def test_no_call_before_valid_duplicate_preserves_the_valid_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_path = root / "array.csv"
            input_path.write_text("fixture", encoding="utf-8")
            qc_path = root / "qc.json"
            qc_path.write_text(json.dumps({
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
            }), encoding="utf-8")
            targets_path = root / "targets.json"
            targets_path.write_text(json.dumps({
                "schema": "genoma-partial-genome-targets-v1",
                "targets": [{
                    "rsid": "rs1",
                    "scope": "CLINICO",
                    "queries": {},
                    "assessed_allele": "A",
                }],
            }), encoding="utf-8")
            rows = iter([
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "--"}),
                ("raw_snp_array_v1", {"RSID": "rs1", "RESULT": "AA"}),
            ])
            with (
                patch("array_pipeline.completeness.sha256_file", return_value="fixture-sha"),
                patch(
                    "array_pipeline.completeness._header_of",
                    return_value=["RSID", "CHROMOSOME", "POSITION", "RESULT"],
                ),
                patch("array_pipeline.completeness._row_reader", return_value=rows),
            ):
                result = build_completeness_matrix(input_path, qc_path, targets_path)

        entry = result["entries"][0]
        self.assertEqual(entry["classification"], OBSERVADO)
        self.assertEqual(entry["genotype"], "AA")

    def test_duplicate_rows_with_no_valid_call_remain_no_call(self):
        classification, _basis = _classify(
            {"RESULT": "--", "__orientation_status": "VERIFICADO"},
            "raw_snp_array_v1",
            {"assessed_allele": "A"},
            "raw_snp_array_v1",
        )
        self.assertEqual(classification, NO_CALL)


if __name__ == "__main__":
    unittest.main()
