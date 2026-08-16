import tempfile
import unittest
import zipfile
from pathlib import Path


PASSING_POLICY = {
    "ready_for_requested_operation": True,
    "planes": {
        "policy_control": {"state": "PASS"},
        "scientific_data": {"state": "PASS"},
        "evidence": {"state": "PASS"},
        "audit": {"state": "PASS"},
    },
    "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
}


def final_data():
    return {
        "case_id": "CASE-VISUAL-001",
        "summary": "Conteúdo rastreável para teste editorial.",
        "ruleset": {"status": "VIGENTE", "version": "v3.3", "effective_date": "14/08/2026"},
        "publication_gate": {
            "passed": True,
            "consent_verified": True,
            "qc_verified": True,
            "evidence_verified": True,
            "placeholders_resolved": True,
        },
        "policy_evaluation": PASSING_POLICY,
        "post_deployment_status": "PASS",
        "sections": {"Resumo clínico executivo": "Teste de conteúdo sem interpretação genética nova."},
        "findings": [],
        "execution_manifest": {"status": "VERIFICADO"},
        "sources": ["fixture:test"],
        "limitations": "Fixture editorial; não representa paciente.",
    }


class EditorialRendererTest(unittest.TestCase):
    def test_design_tokens_match_v3_visual_system(self):
        from reporting.editorial_v3 import DESIGN
        self.assertEqual(DESIGN["navy"], "0B1F33")
        self.assertEqual(DESIGN["teal"], "0F766E")
        self.assertEqual(DESIGN["amber"], "A16207")
        self.assertEqual(DESIGN["light_gray"], "F2F4F7")
        self.assertEqual(DESIGN["a4_mm"], (210, 297))

    def test_final_report_writes_real_pdf_and_editable_docx(self):
        from reporting.engine import render_document
        from reporting.editorial_v3 import write_editorial_bundle

        rendered = render_document("01", final_data(), mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_editorial_bundle(rendered, Path(td), stem="case-visual-001")
            self.assertEqual(set(paths), {"pdf", "docx"})
            self.assertGreater(paths["pdf"].stat().st_size, 2000)
            self.assertGreater(paths["docx"].stat().st_size, 5000)
            self.assertEqual(paths["pdf"].read_bytes()[:4], b"%PDF")
            with zipfile.ZipFile(paths["docx"]) as zf:
                names = set(zf.namelist())
                self.assertIn("word/document.xml", names)
                self.assertIn("word/styles.xml", names)
                self.assertIn("word/header1.xml", names)
                self.assertIn("word/footer1.xml", names)
                document_xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("Relatório de Genoma Clínico", document_xml)
                self.assertIn("RESULTADO GENÔMICO", document_xml)


if __name__ == "__main__":
    unittest.main()
