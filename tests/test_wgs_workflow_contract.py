import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WgsWorkflowContractTest(unittest.TestCase):
    def test_main_is_dispatcher_for_canary_and_real_wgs(self):
        main = (ROOT / "main.nf").read_text(encoding="utf-8")
        self.assertIn("params.mode", main)
        self.assertIn("WGS_PRODUCTION", main)
        self.assertIn("CANARY", main)
        self.assertIn("runtime_gate_manifest", main)
        self.assertIn("freshness_state_manifest", main)

    def test_real_wgs_workflow_has_fail_closed_scientific_planes(self):
        workflow = (ROOT / "workflows/wgs.nf").read_text(encoding="utf-8")
        for token in (
            "VERIFY_RUNTIME_GATE",
            "REFRESH_FRESHNESS_GATE",
            "VERIFY_CONSENT_PROVENANCE",
            "INGEST_AND_QC",
            "ALIGN_OR_STAGE",
            "RERUN_SAMPLE_RUNTIME_GATE",
            "CALL_SHORT_VARIANTS",
            "NORMALIZE_VARIANTS",
            "ADAPTER_CAPABILITY_INVENTORY",
            "BUILD_CURATED_MANIFEST",
            "POLICY_EVALUATE",
            "GENERATE_REPORTS",
        ):
            self.assertIn(token, workflow)
        self.assertIn("ready_for_first_dna_read", workflow)
        self.assertIn("unsupported_variant_classes", workflow)

    def test_wgs_does_not_claim_specialized_classes_from_generic_vcf(self):
        workflow = (ROOT / "workflows/wgs.nf").read_text(encoding="utf-8")
        self.assertIn("CNV", workflow)
        self.assertIn("SV", workflow)
        self.assertIn("CYP2D6", workflow)
        self.assertIn("NÃO DISPONÍVEL", workflow)


if __name__ == "__main__":
    unittest.main()
