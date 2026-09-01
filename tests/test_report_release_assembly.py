import copy
import unittest

from tests.test_policy_evaluation_binding import INPUT_SHA, real_evaluation


def curated(*, consent: bool = True, evidence: bool = True):
    return {
        "case_id": "CASE-1",
        "array_artifacts": {"input_sha256": INPUT_SHA},
        "publication_gate": {
            "consent_verified": consent,
            "qc_verified": True,
            "evidence_verified": evidence,
            "placeholders_resolved": True,
            "passed": False,
        },
    }


class ReportReleaseAssemblyTest(unittest.TestCase):
    def test_reexecuted_policy_plus_verified_prerequisites_releases_reports(self):
        from scripts.prepare_report_release import assemble_release

        policy = real_evaluation()
        result = assemble_release(curated(), policy)
        self.assertTrue(result["publication_gate"]["passed"])
        self.assertEqual(result["policy_evaluation"], policy)
        self.assertEqual(result["policy_evaluation_verification"]["status"], "VERIFICADO")
        self.assertEqual(result["report_release_status"], "VERIFICADO")

    def test_policy_pass_cannot_override_missing_evidence_or_consent(self):
        from scripts.prepare_report_release import assemble_release

        result = assemble_release(curated(consent=False, evidence=False), real_evaluation())
        self.assertFalse(result["publication_gate"]["passed"])
        self.assertEqual(result["report_release_status"], "NÃO DISPONÍVEL")
        self.assertIn("consent_verified", result["report_release_blockers"])
        self.assertIn("evidence_verified", result["report_release_blockers"])

    def test_forged_complete_pass_is_blocked_by_policy_reexecution(self):
        from genoma_policy.models import evaluation_binding
        from scripts.prepare_report_release import assemble_release

        policy = real_evaluation()
        policy["evaluated_manifest"]["qc"]["passed"] = False
        binding = evaluation_binding(policy["evaluated_manifest"])
        policy["binding"] = binding
        for key in ("case_id", "session_id", "input_sha256", "operation", "manifest_sha256"):
            policy[key] = copy.deepcopy(binding[key])
        result = assemble_release(curated(), policy)
        self.assertFalse(result["publication_gate"]["passed"])
        self.assertEqual(result["policy_evaluation_verification"]["status"], "NÃO DISPONÍVEL")
        self.assertIn("policy_evaluation_binding", result["report_release_blockers"])


if __name__ == "__main__":
    unittest.main()
