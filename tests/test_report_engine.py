import tempfile
import unittest
from pathlib import Path


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

    def test_final_mode_fails_closed_without_publication_gate(self):
        from reporting.engine import ReportReleaseError, render_document

        with self.assertRaises(ReportReleaseError):
            render_document("01", {"case_id": "CASE-001"}, mode="FINAL")

    def test_final_mode_rejects_unready_policy_evaluation(self):
        from reporting.engine import ReportReleaseError, render_document

        data = {
            "case_id": "CASE-001",
            "ruleset": {"status": "VIGENTE", "version": "v3.4", "effective_date": "17/08/2026"},
            "publication_gate": {"passed": True, "consent_verified": True, "qc_verified": True, "evidence_verified": True, "placeholders_resolved": True},
            "policy_evaluation": {"ready_for_requested_operation": False, "planes": {}, "gates": []},
        }
        with self.assertRaises(ReportReleaseError):
            render_document("01", data, mode="FINAL")

    def test_final_mode_requires_final_audit_pass(self):
        from reporting.engine import ReportReleaseError, render_document

        policy = passing_policy_evaluation()
        policy["gates"] = [{"gate": "FINAL_AUDIT_GATE", "state": "FAIL", "blocking": True}]
        data = {
            "case_id": "CASE-001",
            "ruleset": {"status": "VIGENTE", "version": "v3.4", "effective_date": "17/08/2026"},
            "publication_gate": {"passed": True, "consent_verified": True, "qc_verified": True, "evidence_verified": True, "placeholders_resolved": True},
            "policy_evaluation": policy,
        }
        with self.assertRaises(ReportReleaseError):
            render_document("01", data, mode="FINAL")

    def test_final_mode_writes_json_markdown_and_html_when_gate_passes(self):
        from reporting.engine import render_document, write_bundle
        from reporting.provenance import fixture_payload

        data = fixture_payload(
            case_id="CASE-001",
            report_id="01",
            summary="Nenhum achado fictício é inserido pelo motor.",
            basis="fixture de motor",
        )
        rendered = render_document("01", data, mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_bundle(rendered, Path(td), stem="case-001-genoma-clinico")
            self.assertEqual(set(paths), {"json", "markdown", "html"})
            self.assertTrue(all(path.is_file() for path in paths.values()))
            self.assertNotIn("[[", paths["markdown"].read_text(encoding="utf-8"))
            self.assertIn("POST-DEPLOYMENT: PENDENTE", paths["markdown"].read_text(encoding="utf-8"))

    def test_final_report_records_the_governing_ruleset_in_its_execution_manifest(self):
        """A published report must be auditable without CI logs (prompt-fonte 2.4)."""
        import sys
        from pathlib import Path as _Path

        sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
        import normative
        from reporting.engine import render_document
        from reporting.provenance import fixture_payload

        data = fixture_payload(
            case_id="CASE-001", report_id="01", summary="fixture", basis="fixture de motor"
        )
        original_manifest = dict(data["execution_manifest"])
        rendered = render_document("01", data, mode="FINAL")
        manifest = rendered["data"]["execution_manifest"]
        self.assertEqual(manifest["RULESET"], "VERIFICADO")
        self.assertEqual(manifest["VERSÃO"], normative.VERSION)
        self.assertEqual(manifest["VIGÊNCIA"], normative.EFFECTIVE_DATE)
        self.assertEqual(manifest["RULESET_SHA256"], normative.RAW_SHA256)
        self.assertIn(normative.VERSION, rendered["markdown"])
        # The caller's payload must not be mutated by rendering.
        self.assertEqual(data["execution_manifest"], original_manifest)


if __name__ == "__main__":
    unittest.main()
