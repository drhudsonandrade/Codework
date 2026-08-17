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
        "post_deployment_status": "PENDENTE",
        "sections": {"Resumo clínico executivo": "Teste de conteúdo sem interpretação genética nova."},
        "findings": [],
        "execution_manifest": {"status": "VERIFICADO"},
        "sources": ["fixture:test"],
        "limitations": "Fixture editorial; não representa paciente.",
    }


class EditorialRendererTest(unittest.TestCase):
    def test_design_tokens_match_visual_system(self):
        from reporting.editorial_v3 import DESIGN

        self.assertEqual(DESIGN["navy"], "0B1F33")
        self.assertEqual(DESIGN["teal"], "0F766E")
        self.assertEqual(DESIGN["amber"], "A16207")
        self.assertEqual(DESIGN["light_gray"], "F2F4F7")
        self.assertEqual(DESIGN["a4_mm"], (210, 297))

    def test_engine_exposes_exact_v31_cover_metadata(self):
        from reporting.engine import render_document

        rendered = render_document("01", final_data(), mode="FINAL")
        meta = rendered["metadata"]
        self.assertEqual(meta["code"], "GCL")
        self.assertEqual(meta["accent"], "0F766E")
        self.assertEqual(meta["template_suite"], "v3.1")
        self.assertEqual(meta["ruleset_required"]["version"], "v3.4")
        self.assertEqual(meta["ruleset_required"]["effective_date"], "17/08/2026")
        self.assertEqual(meta["tagline"], "Achados acionáveis, diagnósticos, predisposições e pontos cegos")
        self.assertIn("Pessoa avaliada", meta["audience"])
        self.assertIn("Organizar achados germinativos", meta["purpose"])

    def test_v33_fixture_is_rejected_by_release_gate(self):
        from reporting.engine import ReportReleaseError, render_document

        data = final_data()
        data["ruleset"] = {"status": "VIGENTE", "version": "v3.3", "effective_date": "14/08/2026"}
        with self.assertRaises(ReportReleaseError):
            render_document("01", data, mode="FINAL")

    def test_report_specific_accents_follow_models(self):
        from reporting.engine import render_document

        expected = {
            "01": "0F766E", "02": "2563EB", "03": "7C3AED", "04": "166534",
            "05": "475467", "06": "B42318", "07": "A16207", "08": "0F766E",
            "09": "475467", "10": "0B1F33", "11": "0B1F33",
        }
        for report_id, accent in expected.items():
            self.assertEqual(render_document(report_id, final_data(), mode="FINAL")["metadata"]["accent"], accent)

    def test_v31_replacements_remove_template_only_labels(self):
        from reporting import template_v3
        from reporting.editorial_v3 import V31_SYSTEM_REPLACEMENTS, _configure_v31_replacements

        _configure_v31_replacements()
        self.assertEqual(template_v3.SYSTEM_REPLACEMENTS, V31_SYSTEM_REPLACEMENTS)
        for token in ("MODELO EDITÁVEL", "NÃO INSERIDOS", "MODELO SEM DADOS PESSOAIS"):
            self.assertIn(token, template_v3.SYSTEM_REPLACEMENTS)
            self.assertNotEqual(token, template_v3.SYSTEM_REPLACEMENTS[token])

    def test_final_report_writes_real_pdf_docx_and_manifest(self):
        from pypdf import PdfReader
        from reporting.engine import render_document
        from reporting.editorial_v3 import write_editorial_bundle

        rendered = render_document("01", final_data(), mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_editorial_bundle(rendered, Path(td), stem="case-visual-001")
            self.assertEqual(set(paths), {"pdf", "docx", "editorial_manifest"})
            self.assertGreater(paths["pdf"].stat().st_size, 2000)
            self.assertGreater(paths["docx"].stat().st_size, 5000)
            self.assertGreater(paths["editorial_manifest"].stat().st_size, 50)
            self.assertEqual(paths["pdf"].read_bytes()[:4], b"%PDF")

            pdf_text = "\n".join((p.extract_text() or "") for p in PdfReader(str(paths["pdf"])).pages)
            for forbidden in ("MODELO EDITÁVEL", "NÃO INSERIDOS", "MODELO SEM DADOS PESSOAIS", "v3.3", "14/08/2026"):
                self.assertNotIn(forbidden, pdf_text)

            with zipfile.ZipFile(paths["docx"]) as zf:
                names = set(zf.namelist())
                self.assertIn("word/document.xml", names)
                document_xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("Relatório de Genoma Clínico", document_xml)
                self.assertIn("RESULTADO GENÔMICO", document_xml)
                for forbidden in ("MODELO EDITÁVEL", "NÃO INSERIDOS", "MODELO SEM DADOS PESSOAIS", "v3.3", "14/08/2026"):
                    self.assertNotIn(forbidden, document_xml)


if __name__ == "__main__":
    unittest.main()
