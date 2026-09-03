from __future__ import annotations

import unittest

from reporting.template_fill import _resolve


class TemplateFillAssayTest(unittest.TestCase):
    """Which artifact each template placeholder resolves against."""
    def test_wgs_projection_uses_projection_assay_and_qc(self):
        """A WGS projection resolves against the projection assay and its QC."""
        payload = {
            "case_id": "CASE",
            "input": {"schema": "wgs_vcf_projection_v1"},
            "execution_manifest": {"PROJECTION_QC_SHA256": "q" * 64},
        }
        self.assertIn("VCF", _resolve("01", "METODO", payload))
        self.assertIn("DP", _resolve("01", "CALLER_ENSAIO", payload))
        self.assertEqual(_resolve("01", "RELATORIO_QC", payload), "q" * 64)
        self.assertIn("VCF", _resolve("01", "TIPO_AMOSTRA_E_IDENTIFICADOR", payload))

    def test_array_uses_array_qc(self):
        """An array input resolves against the array QC."""
        payload = {
            "case_id": "CASE",
            "input": {"schema": "raw_snp_array_v1"},
            "execution_manifest": {"ARRAY_QC_SHA256": "a" * 64},
        }
        self.assertEqual(_resolve("01", "RELATORIO_QC", payload), "a" * 64)
        self.assertIn("array", _resolve("01", "METODO", payload))

    def test_array_manifest_list_exposes_array_qc_evidence_id(self):
        """A manifest given as a list still exposes the array QC evidence id."""
        payload = {
            "case_id": "CASE",
            "input": {"schema": "raw_snp_array_v1"},
            "execution_manifest": [
                {
                    "step": "SNP-array ingest/QC",
                    "status": "EXECUTADO",
                    "evidence_refs": ["array-qc"],
                }
            ],
        }
        self.assertEqual(_resolve("01", "RELATORIO_QC", payload), "array-qc")

    def test_pgx_manifest_exposes_both_bound_artifacts(self):
        """A pharmacogenomic manifest exposes both bound artifacts, not only the passport."""
        payload = {
            "case_id": "CASE",
            "input": {"schema": "raw_snp_array_v1"},
            "execution_manifest": {
                "PGX_PASSPORT_SHA256": "p" * 64,
                "COMPLETENESS_MATRIX_SHA256": "m" * 64,
            },
        }
        self.assertEqual(
            _resolve("06", "RELATORIO_QC", payload),
            {
                "PGX_PASSPORT_SHA256": "p" * 64,
                "COMPLETENESS_MATRIX_SHA256": "m" * 64,
            },
        )

    def test_wgs_does_not_fall_back_to_pgx_artifacts_for_qc(self):
        """A WGS report without WGS QC cannot cite unrelated PGx artifacts as its QC."""
        payload = {
            "case_id": "CASE",
            "input": {"schema": "wgs_vcf_projection_v1"},
            "execution_manifest": {
                "PGX_PASSPORT_SHA256": "p" * 64,
                "COMPLETENESS_MATRIX_SHA256": "m" * 64,
            },
        }
        failures: list[dict[str, str]] = []
        self.assertIsNone(_resolve("01", "RELATORIO_QC", payload, failures))
        self.assertEqual(failures, [])

    def test_pgx_qc_requires_both_bound_artifacts(self):
        """Neither half of the report 06 evidence pair resolves on its own."""
        for key in ("PGX_PASSPORT_SHA256", "COMPLETENESS_MATRIX_SHA256"):
            with self.subTest(only=key):
                payload = {
                    "case_id": "CASE",
                    "input": {"schema": "raw_snp_array_v1"},
                    "execution_manifest": {key: "a" * 64},
                }
                failures: list[dict[str, str]] = []
                self.assertIsNone(_resolve("06", "RELATORIO_QC", payload, failures))
                self.assertEqual(failures, [])

    def test_only_counts_defined_by_the_finding_contract_are_derived(self):
        """Dead aliases outside the compiled finding contract remain explicitly unavailable."""
        payload = {
            "findings": [
                {
                    "priority": "P1",
                    "confirmation": "método ortogonal requerido",
                },
                {
                    "priority": "P3",
                    "confirmation": "não requerido",
                },
            ]
        }
        failures: list[dict[str, str]] = []
        self.assertEqual(_resolve("01", "N_ACHADOS_P1_P2", payload, failures), "1")
        self.assertIsNone(_resolve("01", "N_CONFIRMACOES", payload, failures))
        self.assertIsNone(_resolve("09", "N_CEGOS", payload, failures))
        self.assertEqual(failures, [])

    def test_missing_input_is_unavailable_without_a_resolver_failure(self):
        """No input block means no assay fact; it is not an unknown declared schema."""
        failures: list[dict[str, str]] = []
        self.assertIsNone(_resolve("01", "METODO", {"case_id": "CASE"}, failures))
        self.assertIsNone(_resolve("01", "CALLER_ENSAIO", {"case_id": "CASE"}, failures))
        self.assertIsNone(
            _resolve("01", "TIPO_AMOSTRA_E_IDENTIFICADOR", {"case_id": "CASE"}, failures)
        )
        self.assertEqual(failures, [])

    def test_missing_count_fields_remain_unavailable(self):
        """A missing count field stays unavailable rather than resolving to zero."""
        payload = {"findings": [{"id": "finding"}]}
        failures: list[dict[str, str]] = []
        self.assertIsNone(_resolve("01", "N_ACHADOS_P1_P2", payload, failures))
        self.assertIsNone(_resolve("01", "N_CONFIRMACOES", payload, failures))
        self.assertIsNone(_resolve("09", "N_CEGOS", payload, failures))
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
