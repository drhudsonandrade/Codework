import unittest


class ReportReleaseAssemblyTest(unittest.TestCase):
    def test_policy_pass_plus_verified_publication_prerequisites_releases_reports(self):
        from scripts.prepare_report_release import assemble_release

        curated = {
            "publication_gate": {
                "consent_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
                "passed": False,
            }
        }
        policy = {
            "ready_for_requested_operation": True,
            "planes": {name: {"state": "PASS"} for name in ("policy_control", "scientific_data", "evidence", "audit")},
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
        }
        result = assemble_release(curated, policy)
        self.assertTrue(result["publication_gate"]["passed"])
        self.assertEqual(result["policy_evaluation"], policy)
        self.assertEqual(result["report_release_status"], "VERIFICADO")

    def test_policy_pass_cannot_override_missing_evidence_or_consent(self):
        from scripts.prepare_report_release import assemble_release

        curated = {
            "publication_gate": {
                "consent_verified": False,
                "qc_verified": True,
                "evidence_verified": False,
                "placeholders_resolved": True,
                "passed": False,
            }
        }
        policy = {
            "ready_for_requested_operation": True,
            "planes": {name: {"state": "PASS"} for name in ("policy_control", "scientific_data", "evidence", "audit")},
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
        }
        result = assemble_release(curated, policy)
        self.assertFalse(result["publication_gate"]["passed"])
        self.assertEqual(result["report_release_status"], "NÃO DISPONÍVEL")
        self.assertIn("consent_verified", result["report_release_blockers"])
        self.assertIn("evidence_verified", result["report_release_blockers"])

    def test_final_audit_failure_blocks_even_if_other_planes_pass(self):
        from scripts.prepare_report_release import assemble_release

        curated = {
            "publication_gate": {
                "consent_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
                "passed": False,
            }
        }
        policy = {
            "ready_for_requested_operation": False,
            "planes": {name: {"state": "PASS"} for name in ("policy_control", "scientific_data", "evidence", "audit")},
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "FAIL", "blocking": True}],
        }
        result = assemble_release(curated, policy)
        self.assertFalse(result["publication_gate"]["passed"])
        self.assertIn("FINAL_AUDIT_GATE", result["report_release_blockers"])


if __name__ == "__main__":
    unittest.main()
