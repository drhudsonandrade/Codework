import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ruleset_test_support import RULESET


def final_data(report_id="01"):
    """A payload complete enough for a FINAL render of this report."""
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
    """What the editorial renderer produces, and what it refuses to produce unattended."""
    def test_design_tokens_match_v3_visual_system(self):
        """The design tokens are the v3 visual system's, not arbitrary colours."""
        from reporting.editorial_v3 import DESIGN
        self.assertEqual(DESIGN["navy"], "0B1F33")
        self.assertEqual(DESIGN["teal"], "0F766E")
        self.assertEqual(DESIGN["amber"], "A16207")
        self.assertEqual(DESIGN["light_gray"], "F2F4F7")
        self.assertEqual(DESIGN["a4_mm"], (210, 297))

    def test_engine_exposes_exact_v3_cover_metadata(self):
        """The engine exposes exactly the v3 cover metadata."""
        from reporting.engine import render_document

        rendered = render_document("01", final_data(), mode="FINAL")
        meta = rendered["metadata"]
        self.assertEqual(meta["code"], "GCL")
        self.assertEqual(meta["accent"], "0F766E")
        self.assertEqual(meta["tagline"], "Achados acionáveis, diagnósticos, predisposições e pontos cegos")
        self.assertIn("Pessoa avaliada", meta["audience"])
        self.assertIn("Organizar achados germinativos", meta["purpose"])

    def test_report_specific_accents_follow_v3_models(self):
        """Each report carries the accent colour its v3 model declares."""
        from reporting.engine import render_document

        expected = {"01": "0F766E", "02": "2563EB", "03": "7C3AED", "04": "166534", "05": "475467", "06": "B42318", "07": "A16207", "08": "0F766E", "09": "475467", "10": "0B1F33", "11": "0B1F33"}
        for report_id, accent in expected.items():
            self.assertEqual(render_document(report_id, final_data(report_id), mode="FINAL")["metadata"]["accent"], accent)

    def test_payload_cannot_self_authorize_a_programmatic_final_render(self):
        """A payload cannot authorize its own programmatic FINAL render."""
        from reporting.editorial_v3 import UnapprovedRendererError, write_editorial_bundle
        from reporting.engine import render_document

        rendered = render_document("01", final_data(), mode="FINAL")
        rendered["data"]["allow_programmatic_final"] = True
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UnapprovedRendererError):
                write_editorial_bundle(rendered, Path(td), stem="refused")

    def test_programmatic_disclosure_preserves_anchored_limitations(self):
        """The programmatic-render disclosure preserves the limitations already anchored in the payload."""
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
        """The disclosure reaches the JSON bundle too, not only the rendered page."""
        from reporting.editorial_v3 import prepare_editorial_render
        from reporting.engine import render_document, write_bundle

        rendered = prepare_editorial_render(
            render_document("01", final_data(), mode="FINAL"),
            programmatic_final_authorization="unit-test visual QA",
        )
        with tempfile.TemporaryDirectory() as td:
            paths = write_bundle(rendered, Path(td), stem="disclosed")
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            markdown = paths["markdown"].read_text(encoding="utf-8")
            html = paths["html"].read_text(encoding="utf-8")
        manifest = payload["data"]["execution_manifest"]
        for key in (
            "RENDERER",
            "TEMPLATE_PACK_V3",
            "PARIDADE_VISUAL",
            "PROGRAMMATIC_FINAL_AUTHORIZATION",
        ):
            self.assertIn(key, manifest)
        # The JSON was never the problem. `render_document` builds markdown and html from
        # `data` *before* disclosure, and disclosure only edits `data`, so the two artifacts
        # a reader actually opens carried no trace of the programmatic approximation while
        # the JSON beside them declared it. All three must agree.
        for artifact, text in (("markdown", markdown), ("html", html)):
            with self.subTest(artifact=artifact):
                self.assertIn("aproximação programática", text)
                self.assertIn("PROGRAMMATIC_FINAL_AUTHORIZATION", text)

    def test_disclosure_is_idempotent_and_keeps_the_authorization(self):
        """Two callers prepare the same payload; the second must not lose the opt-in.

        `generate_report.py` calls `prepare_editorial_render` and then `write_editorial_bundle`
        calls it again on the same payload, without the caller's authorization. The second
        pass therefore refused an already-authorized FINAL render with UnapprovedRendererError.
        """
        from reporting.engine import render_document
        from reporting.editorial_v3 import prepare_editorial_render

        rendered = render_document("01", final_data(), mode="FINAL")
        once = prepare_editorial_render(
            rendered, programmatic_final_authorization="unit-test visual QA"
        )
        twice = prepare_editorial_render(
            once, programmatic_final_authorization="unit-test visual QA"
        )
        self.assertEqual(
            twice["data"]["execution_manifest"]["PROGRAMMATIC_FINAL_AUTHORIZATION"],
            "unit-test visual QA",
        )
        self.assertEqual(once["data"]["execution_manifest"], twice["data"]["execution_manifest"])

    def test_idempotency_is_not_a_way_around_the_final_opt_in(self):
        """A payload that pre-sets the marker must not skip the authorization gate."""
        from reporting.engine import render_document
        from reporting.editorial_v3 import prepare_editorial_render, UnapprovedRendererError

        rendered = render_document("01", final_data(), mode="FINAL")
        rendered["data"]["execution_manifest"] = {
            "RENDERER": "aproximação programática (fora do pacote de modelos aprovado)"
        }
        with self.assertRaises(UnapprovedRendererError):
            prepare_editorial_render(rendered)

    def test_payload_cannot_supply_its_own_final_authorization(self):
        """Both publishable disclosure fields remain untrusted without caller opt-in."""
        from reporting.engine import render_document
        from reporting.editorial_v3 import prepare_editorial_render, UnapprovedRendererError

        rendered = render_document("01", final_data(), mode="FINAL")
        rendered["data"]["execution_manifest"].update(
            {
                "RENDERER": "aproximação programática (fora do pacote de modelos aprovado)",
                "PROGRAMMATIC_FINAL_AUTHORIZATION": "forged in payload",
            }
        )
        with self.assertRaises(UnapprovedRendererError):
            prepare_editorial_render(rendered)

    def test_mutating_final_mode_after_render_is_refused(self):
        """Changing only public metadata cannot downgrade a FINAL payload to MODEL."""
        from reporting.engine import ReportReleaseError, render_document
        from reporting.editorial_v3 import prepare_editorial_render

        rendered = render_document("01", final_data(), mode="FINAL")
        rendered["metadata"]["mode"] = "MODEL"
        with self.assertRaisesRegex(ReportReleaseError, "mode was mutated"):
            prepare_editorial_render(rendered)

    def test_mutating_final_ruleset_after_render_is_refused(self):
        """The full publication gate is repeated at the serialization boundary."""
        from reporting.engine import ReportReleaseError, render_document
        from reporting.editorial_v3 import prepare_editorial_render

        rendered = render_document("01", final_data(), mode="FINAL")
        rendered["data"]["ruleset"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ReportReleaseError, "publication gate failed"):
            prepare_editorial_render(
                rendered,
                programmatic_final_authorization="unit-test visual QA",
            )

    def test_final_report_writes_real_pdf_and_editable_docx(self):
        """A FINAL report writes a real PDF and an editable DOCX."""
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
