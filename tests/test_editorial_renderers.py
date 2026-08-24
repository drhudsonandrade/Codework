import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ruleset_test_support import RULESET


def final_data(report_id="01"):
    from reporting.provenance import fixture_payload

    data = fixture_payload(
        case_id="CASE-VISUAL-001",
        report_id=report_id,
        summary="Conteúdo rastreável para teste editorial.",
        sections={
            "Resumo clínico executivo":
                "Teste de conteúdo sem interpretação genética nova."
        },
        basis="Fixture editorial; não representa paciente.",
    )
    data["ruleset"] = dict(RULESET)
    data["publication_gate"]["placeholders_resolved"] = True
    return data


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
            self.assertEqual(render_document(report_id, final_data(report_id), mode="FINAL")["metadata"]["accent"], accent)

    def test_payload_cannot_self_authorize_a_programmatic_final_render(self):
        from reporting.editorial_v3 import UnapprovedRendererError, write_editorial_bundle
        from reporting.engine import render_document

        rendered = render_document("01", final_data(), mode="FINAL")
        rendered["data"]["allow_programmatic_final"] = True
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UnapprovedRendererError):
                write_editorial_bundle(rendered, Path(td), stem="refused")

    def test_programmatic_disclosure_preserves_anchored_limitations(self):
        from reporting.editorial_v3 import _disclose_programmatic_render
        from reporting.engine import render_document

        rendered = render_document("01", final_data(), mode="FINAL")
        limitations = rendered["data"]["limitations"]
        disclosed = _disclose_programmatic_render(
            rendered, final_authorization="unit-test visual QA"
        )
        self.assertEqual(disclosed["data"]["limitations"], limitations)
        self.assertEqual(
            disclosed["data"]["execution_manifest"]["PROGRAMMATIC_FINAL_AUTHORIZATION"],
            "unit-test visual QA",
        )

    def test_disclosure_is_present_in_json_bundle_too(self):
        from reporting.editorial_v3 import prepare_editorial_render
        from reporting.engine import render_document, write_bundle

        rendered = prepare_editorial_render(
            render_document("01", final_data(), mode="FINAL"),
            programmatic_final_authorization="unit-test visual QA",
        )
        with tempfile.TemporaryDirectory() as td:
            paths = write_bundle(rendered, Path(td), stem="disclosed")
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        manifest = payload["data"]["execution_manifest"]
        for key in (
            "RENDERER",
            "TEMPLATE_PACK_V3",
            "PARIDADE_VISUAL",
            "PROGRAMMATIC_FINAL_AUTHORIZATION",
        ):
            self.assertIn(key, manifest)

    def test_final_report_writes_real_pdf_and_editable_docx(self):
        from reporting.engine import render_document
        from reporting.editorial_v3 import write_editorial_bundle

        rendered = render_document("01", final_data(), mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_editorial_bundle(
                rendered,
                Path(td),
                stem="case-visual-001",
                programmatic_final_authorization="unit-test visual QA",
            )
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
                self.assertIn("unit-test visual QA", document_xml)
                self.assertIn("aproximação programática", document_xml)


if __name__ == "__main__":
    unittest.main()
