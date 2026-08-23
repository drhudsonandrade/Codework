import tempfile
import unittest
from pathlib import Path

RULESET = {
    "status": "VIGENTE",
    "version": "v3.4",
    "effective_date": "17/08/2026",
    "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
}


def passing_policy_evaluation():
    return {
        "ready_for_requested_operation": True,
        "planes": {
            "policy_control": {"state": "PASS"},
            "scientific_data": {"state": "PASS"},
            "evidence": {"state": "PASS"},
            "audit": {"state": "PASS"},
        },
        "gates": [
            {"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True},
            {"gate": "POST_DEPLOYMENT_GATE", "state": "PENDING", "blocking": False},
        ],
    }


class ReportEngineTest(unittest.TestCase):
    def assert_release_rejected(self, callable_):
        from reporting.engine import ReportReleaseError

        try:
            callable_()
        except ReportReleaseError:
            return
        self.fail("expected ReportReleaseError")

    def test_catalog_contains_all_eleven_v3_models(self):
        from reporting.engine import load_catalog

        catalog = load_catalog()
        self.assertEqual(sorted(catalog), [f"{i:02d}" for i in range(1, 12)])
        self.assertEqual(catalog["01"]["slug"], "genoma-clinico")
        self.assertEqual(catalog["11"]["slug"], "guia-editorial-matriz-preenchimento")

    def test_model_mode_is_explicitly_non_result(self):
        from reporting.engine import render_document

        result = render_document("01", {}, mode="MODEL")
        self.assertIn("MODELO — NÃO É RESULTADO GENÉTICO", result["markdown"])
        self.assertEqual(result["metadata"]["mode"], "MODEL")
        self.assertEqual(result["metadata"]["ruleset_required"], RULESET)

    def test_final_mode_fails_closed_without_publication_gate(self):
        from reporting.engine import render_document

        self.assert_release_rejected(lambda: render_document("01", {"case_id": "CASE-001"}, mode="FINAL"))

    def test_final_mode_rejects_wrong_ruleset_digest(self):
        from reporting.engine import render_document

        bad_ruleset = dict(RULESET)
        bad_ruleset["sha256"] = "0" * 64
        data = {
            "case_id": "CASE-001",
            "ruleset": bad_ruleset,
            "publication_gate": {
                "passed": True,
                "consent_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
            },
            "policy_evaluation": passing_policy_evaluation(),
        }
        self.assert_release_rejected(lambda: render_document("01", data, mode="FINAL"))

    def test_final_mode_rejects_unready_policy_evaluation(self):
        from reporting.engine import render_document

        data = {
            "case_id": "CASE-001",
            "ruleset": dict(RULESET),
            "publication_gate": {
                "passed": True,
                "consent_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
            },
            "policy_evaluation": {"ready_for_requested_operation": False, "planes": {}, "gates": []},
        }
        self.assert_release_rejected(lambda: render_document("01", data, mode="FINAL"))

    def test_final_mode_requires_final_audit_pass(self):
        from reporting.engine import render_document

        policy = passing_policy_evaluation()
        policy["gates"] = [{"gate": "FINAL_AUDIT_GATE", "state": "FAIL", "blocking": True}]
        data = {
            "case_id": "CASE-001",
            "ruleset": dict(RULESET),
            "publication_gate": {
                "passed": True,
                "consent_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
            },
            "policy_evaluation": policy,
        }
        self.assert_release_rejected(lambda: render_document("01", data, mode="FINAL"))

    def test_final_mode_writes_json_markdown_and_html_when_gate_passes(self):
        from reporting.engine import render_document, write_bundle

        data = {
            "case_id": "CASE-001",
            "summary": "Nenhum achado fictício é inserido pelo motor.",
            "ruleset": dict(RULESET),
            "publication_gate": {
                "passed": True,
                "consent_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
            },
            "policy_evaluation": passing_policy_evaluation(),
            "post_deployment_status": "PENDENTE",
        }
        rendered = render_document("01", data, mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_bundle(rendered, Path(td), stem="case-001-genoma-clinico")
            self.assertEqual(set(paths), {"json", "markdown", "html"})
            self.assertTrue(all(path.is_file() for path in paths.values()))
            self.assertNotIn("[[", paths["markdown"].read_text(encoding="utf-8"))
            markdown = paths["markdown"].read_text(encoding="utf-8")
            self.assertIn("POST-DEPLOYMENT: PENDENTE", markdown)
            self.assertIn("Ruleset: v3.4 / VIGENTE / 17/08/2026", markdown)
            self.assertIn(RULESET["sha256"], markdown)


if __name__ == "__main__":
    unittest.main()
