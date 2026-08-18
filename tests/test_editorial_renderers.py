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
        "ruleset": {"status": "VIGENTE", "version": "v3.4", "effective_date": "17/08/2026"},
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

    def test_engine_exposes_exact_v3_cover_metadata(self):
        from reporting.engine import render_document

        rendered = render_document("01", final_data(), mode="FINAL")
        meta = rendered["metadata"]
        self.assertEqual(meta["code"], "GCL")
        self.assertEqual(meta["accent"], "0F766E")
        self.assertEqual(meta["tagline"], "Achados acionáveis, diagnósticos, predisposições e pontos cegos")
        self.assertIn("Pessoa avaliada", meta["audience"])
        self.assertIn("Organizar achados germinativos", meta["purpose"])

    def test_report_specific_accents_follow_v3_models(self):
        from reporting.engine import render_document

        expected = {"01": "0F766E", "02": "2563EB", "03": "7C3AED", "04": "166534", "05": "475467", "06": "B42318", "07": "A16207", "08": "0F766E", "09": "475467", "10": "0B1F33", "11": "0B1F33"}
        for report_id, accent in expected.items():
            self.assertEqual(render_document(report_id, final_data(), mode="FINAL")["metadata"]["accent"], accent)

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
                self.assertIn("Achados acionáveis, diagnósticos, predisposições e pontos cegos", document_xml)
                self.assertIn("Finalidade", document_xml)
                self.assertIn("Público", document_xml)


if __name__ == "__main__":
    unittest.main()
