import tempfile
import unittest
from pathlib import Path


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

    def test_final_mode_writes_json_markdown_and_html_when_gate_passes(self):
        from reporting.engine import render_document, write_bundle

        data = {
            "case_id": "CASE-001",
            "summary": "Nenhum achado fictício é inserido pelo motor.",
            "ruleset": {"status": "VIGENTE", "version": "v3.3", "effective_date": "14/08/2026"},
            "publication_gate": {
                "passed": True,
                "consent_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
            },
            "post_deployment_status": "PASS",
        }
        rendered = render_document("01", data, mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_bundle(rendered, Path(td), stem="case-001-genoma-clinico")
            self.assertEqual(set(paths), {"json", "markdown", "html"})
            self.assertTrue(all(path.is_file() for path in paths.values()))
            self.assertNotIn("[[", paths["markdown"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
