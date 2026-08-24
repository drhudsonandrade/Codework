from __future__ import annotations

import unittest

from reporting.template_fill import _resolve


class TemplateFillAssayTest(unittest.TestCase):
    def test_wgs_projection_uses_projection_assay_and_qc(self):
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
        payload = {
            "case_id": "CASE",
            "input": {"schema": "raw_snp_array_v1"},
            "execution_manifest": {"ARRAY_QC_SHA256": "a" * 64},
        }
        self.assertEqual(_resolve("01", "RELATORIO_QC", payload), "a" * 64)
        self.assertIn("array", _resolve("01", "METODO", payload))

    def test_clinical_counts_use_their_declared_fields(self):
        payload = {
            "findings": [
                {
                    "priority": "P1",
                    "confirmation_required": True,
                    "source": "clinical",
                },
                {
                    "priority": "P3",
                    "confirmation_required": False,
                    "source": "structural_blind_spots",
                },
            ]
        }
        self.assertEqual(_resolve("01", "N_ACHADOS_P1_P2", payload), "1")
        self.assertEqual(_resolve("01", "N_CONFIRMACOES", payload), "1")
        self.assertEqual(_resolve("09", "N_CEGOS", payload), "1")

    def test_missing_count_fields_remain_unavailable(self):
        payload = {"findings": [{"id": "finding"}]}
        failures: list[dict[str, str]] = []
        self.assertIsNone(_resolve("01", "N_ACHADOS_P1_P2", payload, failures))
        self.assertIsNone(_resolve("01", "N_CONFIRMACOES", payload, failures))
        self.assertIsNone(_resolve("09", "N_CEGOS", payload, failures))
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
