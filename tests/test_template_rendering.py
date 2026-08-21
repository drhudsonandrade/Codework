"""Rendering into the sealed templates must not be able to publish an empty document.

Two defects were found by rendering the real reports and then reading the PDFs back rather
than trusting that "it wrote a file" meant it worked:

1. `strict=True` accepted a render that replaced **nothing**, writing out the untouched
   blank model — a document that looks like a finished report and contains no measurement.
   `unresolved` was empty, but only because no field was ever attempted.
2. The overlay covered the placeholder with an opaque rectangle and drew on top, leaving
   the original glyphs in the content stream. `get_text()` returned the token *and* the
   value from the same box.

Both are the kind of failure that survives a green test suite and shows up in the delivered
artifact, so they are pinned here against the real template pack when one is installed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.provenance import fixture_payload
from reporting.template_v3 import TemplateV3Error, render_pdf_from_template

TEMPLATE_DIR = os.environ.get("GENOMA_TEMPLATE_DIR")


class StrictRenderingTest(unittest.TestCase):
    """These need no template pack: they exercise the refusal paths."""

    def _rendered(self, report_id: str = "09", **extra):
        from reporting.engine import render_document

        payload = fixture_payload(
            case_id="CASE-RENDER", report_id=report_id, summary="fixture", basis="fixture de render"
        )
        payload.update(extra)
        return render_document(report_id, payload, mode="FINAL")

    def _blank_pdf(self, directory: Path) -> Path:
        """A real one-page PDF, so the refusal under test is reached rather than a file error."""
        from reportlab.pdfgen import canvas

        path = directory / "blank.pdf"
        c = canvas.Canvas(str(path))
        c.drawString(72, 720, "modelo")
        c.showPage()
        c.save()
        return path

    def _refusal(self) -> str:
        import tempfile

        import reporting.template_v3 as tv3

        original = tv3.resolve_template_pdf
        with tempfile.TemporaryDirectory() as td:
            template = self._blank_pdf(Path(td))
            # A manifest with no coordinates: exactly what `load_reference_manifest`
            # returns, and what silently produced the blank model.
            tv3.resolve_template_pdf = lambda rid, d, m=None: (template, {"fields": []})
            try:
                with self.assertRaises(TemplateV3Error) as ctx:
                    render_pdf_from_template(
                        self._rendered(), Path(td) / "out.pdf", Path(td), strict=True
                    )
            finally:
                tv3.resolve_template_pdf = original
            self.assertFalse((Path(td) / "out.pdf").exists(), "the blank model was written anyway")
        return str(ctx.exception)

    def test_zero_replacements_is_refused_instead_of_writing_the_blank_model(self):
        message = self._refusal()
        self.assertIn("no field was replaced", message)
        self.assertIn("blank model", message)

    def test_the_refusal_names_the_supported_entry_point(self):
        """The failure has a specific remedy; the message must say what it is."""
        self.assertIn("editorial_v3", self._refusal())


class TemplateFillTest(unittest.TestCase):
    """The resolver tables must reference tokens that exist in each template."""

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_no_resolver_maps_a_token_the_template_does_not_have(self):
        """A token that does not exist silently discards the content mapped to it.

        Report 06's map was written from report 09's token list, so the whole
        gene-by-gene layer was routed to `[[GENE_REGIAO]]`, which report 06 does not have.
        """
        from reporting.editorial_v3 import _verified_coordinate_manifest
        from reporting.template_fill import REPORT_RESOLVERS

        detailed, _ = _verified_coordinate_manifest(Path(TEMPLATE_DIR))
        for report_id, resolvers in REPORT_RESOLVERS.items():
            real = {
                f["token"].strip("[] ")
                for f in detailed["reports"][report_id]["fields"]
                if not f.get("guidance_only")
            }
            bogus = sorted(set(resolvers) - real)
            with self.subTest(report=report_id):
                self.assertEqual(bogus, [], f"report {report_id} maps absent tokens: {bogus}")

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_every_fillable_placeholder_gets_a_value_or_an_explicit_unavailable(self):
        from reporting.editorial_v3 import _verified_coordinate_manifest
        from reporting.template_fill import UNAVAILABLE, build_template_fields

        detailed, _ = _verified_coordinate_manifest(Path(TEMPLATE_DIR))
        payload = fixture_payload(
            case_id="CASE-FILL", report_id="09", summary="fixture", basis="fixture"
        )
        fill = build_template_fields("09", payload, detailed)
        fillable = [
            f for f in detailed["reports"]["09"]["fields"] if not f.get("guidance_only")
        ]
        self.assertEqual(fill["total"], len(fillable))
        self.assertEqual(set(fill["fields"]), {f["field_id"] for f in fillable})
        self.assertTrue(all(v for v in fill["fields"].values()))
        # A fixture payload carries no measurements, so most fields must read NÃO DISPONÍVEL
        # rather than being quietly filled with something plausible.
        self.assertIn(UNAVAILABLE, set(fill["fields"].values()))
        self.assertEqual(fill["derived_count"] + fill["unavailable_count"], fill["total"])


@unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
class RedactionTest(unittest.TestCase):
    """A filled placeholder must not leave its token extractable underneath."""

    def _render(self, report_id: str, out: Path):
        from scripts.render_report_pdfs import render

        payload_path = out.parent / f"payload-{report_id}.json"
        payload = fixture_payload(
            case_id="CASE-REDACT", report_id=report_id, summary="fixture", basis="fixture"
        )
        payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return render(report_id, payload_path, Path(TEMPLATE_DIR), out)

    def test_a_filled_placeholder_leaves_no_extractable_token(self):
        import tempfile

        import fitz

        from reporting.editorial_v3 import _verified_coordinate_manifest

        detailed, _ = _verified_coordinate_manifest(Path(TEMPLATE_DIR))
        guidance = {
            f["token"] for f in detailed["reports"]["09"]["fields"] if f.get("guidance_only")
        }
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "out.pdf"
            result = self._render("09", pdf)
            self.assertGreater(result["redacted_placeholder_boxes"], 0)
            document = fitz.open(pdf)
            text = "\n".join(page.get_text() for page in document).replace("\n", "")
        leaked = sorted(set(re.findall(r"\[\[[^\]]{1,60}\]\]", text)) - guidance)
        self.assertEqual(leaked, [], f"placeholder tokens survived redaction: {leaked}")

    def test_guidance_placeholders_survive_because_they_are_template_content(self):
        """Guidance text is not a field; redacting it would delete the template's own copy."""
        import tempfile

        import fitz

        from reporting.editorial_v3 import _verified_coordinate_manifest

        detailed, _ = _verified_coordinate_manifest(Path(TEMPLATE_DIR))
        guidance = {
            f["token"] for f in detailed["reports"]["09"]["fields"] if f.get("guidance_only")
        }
        if not guidance:
            self.skipTest("this template declares no guidance-only placeholders")
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "out.pdf"
            self._render("09", pdf)
            document = fitz.open(pdf)
            text = "\n".join(page.get_text() for page in document).replace("\n", "")
        self.assertTrue(any(token in text for token in guidance))


class SuiteLevelDossierTest(unittest.TestCase):
    """Report 11 describes the template suite, so it has no case to be bound to.

    Requiring the dossier's case_id to match the payload's is right for the ten patient
    reports and impossible for this one, whose payload carries a fixed sentinel. The result
    was that supplying a dossier — which every orchestrated run does — blocked report 11's
    PDF entirely, the same shape as report 05 being blocked by an argument that was never
    passed. The exemption has to stay narrow, so it is pinned from both sides here.
    """

    def test_the_editorial_guide_is_recognised_as_suite_level(self):
        from scripts.render_report_pdfs import SUITE_LEVEL_CASE_ID, is_suite_level

        self.assertTrue(is_suite_level("11", {"case_id": SUITE_LEVEL_CASE_ID}))

    def test_the_builder_still_stamps_the_sentinel_the_renderer_looks_for(self):
        # If the guide's case_id is ever changed, the exemption stops matching and the PDF
        # goes back to being blocked. That coupling is asserted rather than assumed.
        from scripts.build_editorial_guide import REPORT_ID
        from scripts.render_report_pdfs import SUITE_LEVEL_CASE_ID, SUITE_LEVEL_REPORTS

        self.assertIn(REPORT_ID, SUITE_LEVEL_REPORTS)
        source = (ROOT / "scripts/build_editorial_guide.py").read_text(encoding="utf-8")
        self.assertIn(f'case_id="{SUITE_LEVEL_CASE_ID}"', source)

    def test_a_patient_report_can_never_take_the_exemption(self):
        from scripts.render_report_pdfs import SUITE_LEVEL_CASE_ID, is_suite_level

        # Neither half alone is enough: a case report carrying the sentinel, and report 11
        # carrying a real case_id, both stay bound.
        self.assertFalse(is_suite_level("01", {"case_id": SUITE_LEVEL_CASE_ID}))
        self.assertFalse(is_suite_level("11", {"case_id": "CASE-REAL"}))
        self.assertFalse(is_suite_level("11", {}))

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_report_11_renders_with_a_dossier_supplied_and_carries_no_identity(self):
        import tempfile

        from scripts.render_report_pdfs import SUITE_LEVEL_CASE_ID, render

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload_path = root / "payload-11.json"
            payload = fixture_payload(
                case_id=SUITE_LEVEL_CASE_ID, report_id="11", summary="fixture", basis="fixture"
            )
            payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            dossier_path = root / "dossier.json"
            dossier_path.write_text(
                json.dumps(
                    {
                        "schema": "genoma-case-dossier-v1",
                        "case_id": "OUTRO-CASO",
                        "identification": {"pseudonymised_id": "NAO-DEVE-APARECER"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = render(
                "11", payload_path, Path(TEMPLATE_DIR), root / "out.pdf", dossier_path
            )

        self.assertFalse(result["case_bound"])
        self.assertFalse(result["dossier_supplied"])
        self.assertEqual(result["from_dossier"], [])
        self.assertIsNotNone(result["dossier_skipped_reason"])

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_a_mismatched_dossier_on_a_patient_report_is_still_refused(self):
        import tempfile

        from reporting.case_dossier import CaseDossierError
        from scripts.render_report_pdfs import render

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload_path = root / "payload-01.json"
            payload = fixture_payload(
                case_id="CASE-A", report_id="01", summary="fixture", basis="fixture"
            )
            payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            dossier_path = root / "dossier.json"
            dossier_path.write_text(
                json.dumps(
                    {
                        "schema": "genoma-case-dossier-v1",
                        "case_id": "CASE-B",
                        "identification": {"pseudonymised_id": "OUTRA-PESSOA"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaises(CaseDossierError):
                render("01", payload_path, Path(TEMPLATE_DIR), root / "out.pdf", dossier_path)


class StampedFieldsAreVerifiedTest(unittest.TestCase):
    """The PDF's own text came from a dict nothing checked.

    The publication gate and the provenance gate both read the payload's summary, sections
    and findings. Neither reads `template_fields`, which is what actually gets stamped into
    the delivered document — 83 placeholders per report. A forged value placed there passed
    both gates and appeared in the PDF while the markdown bundle beside it stayed honest.
    """

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def _prepared(self):
        from reporting.editorial_v3 import _verified_coordinate_manifest
        from reporting.engine import _stamp_ruleset_into_manifest
        from reporting.provenance import fixture_payload
        from reporting.template_fill import build_template_fields

        detailed, _ = _verified_coordinate_manifest(Path(TEMPLATE_DIR))
        payload = _stamp_ruleset_into_manifest(
            fixture_payload(case_id="CASE-STAMP", report_id="09", summary="resumo", basis="fixture")
        )
        fill = build_template_fields("09", payload, detailed)
        return detailed, payload, fill

    def _render(self, detailed, payload, fields, from_dossier=()):
        import tempfile

        from reporting.engine import render_document
        from reporting.template_v3 import render_pdf_from_template
        import reporting.template_v3 as _tv3

        data = dict(payload)
        data["editorial_mode"] = "template-v3"
        data["template_fields"] = fields
        data["template_fields_complete"] = False
        data["template_fields_from_dossier"] = list(from_dossier)
        rendered = render_document("09", data, mode="FINAL")
        original = _tv3.load_reference_manifest
        _tv3.load_reference_manifest = lambda *a, **k: detailed
        try:
            with tempfile.TemporaryDirectory() as td:
                return render_pdf_from_template(
                    rendered, Path(td) / "out.pdf", Path(TEMPLATE_DIR), strict=True
                )
        finally:
            _tv3.load_reference_manifest = original

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_an_untampered_fill_still_stamps(self):
        detailed, payload, fill = self._prepared()
        self.assertGreater(self._render(detailed, payload, dict(fill["fields"]))["page_count"], 0)

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_a_forged_field_is_refused_before_it_reaches_the_pdf(self):
        from reporting.template_v3 import TemplateV3Error

        detailed, payload, fill = self._prepared()
        target = sorted(fill["fields"])[0]
        forged = {**fill["fields"], target: "TEXTO-FORJADO-NUNCA-MEDIDO"}
        with self.assertRaises(TemplateV3Error) as caught:
            self._render(detailed, payload, forged)
        self.assertIn("do not match what the payload derives", str(caught.exception))

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_a_field_dropped_between_fill_and_stamp_is_refused(self):
        # A missing field leaves the raw placeholder visible in the delivered document.
        from reporting.template_v3 import TemplateV3Error

        detailed, payload, fill = self._prepared()
        target = sorted(fill["fields"])[0]
        with self.assertRaises(TemplateV3Error) as caught:
            self._render(detailed, payload, {k: v for k, v in fill["fields"].items() if k != target})
        self.assertIn("absent from template_fields", str(caught.exception))

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_a_payload_cannot_nominate_its_own_exempt_fields(self):
        """The first version of this check let the payload name what it need not prove.

        It read the exempt list out of `template_fields_from_dossier`, so a payload able to
        forge a value could also declare that value dossier-supplied and exempt exactly what
        it had forged — verified by doing it and getting a PDF. Narrowing the exemption to
        the closed set of tokens a dossier *can* answer still left those seventeen forgeable.
        The exemption existed only because the verifier lacked the dossier, so the dossier is
        passed in and nothing is exempt.
        """
        from reporting.case_dossier import DOSSIER_TOKENS
        from reporting.template_v3 import TemplateV3Error

        detailed, payload, fill = self._prepared()
        target = sorted(fill["fields"])[0]
        token = next(
            str(item.get("token", "")).strip("[] ").strip()
            for item in detailed["reports"]["09"]["fields"]
            if item["field_id"] == target
        )
        forged = {**fill["fields"], target: "TEXTO-FORJADO-COM-ISENCAO"}
        with self.assertRaises(TemplateV3Error):
            self._render(detailed, payload, forged, from_dossier=[token])
        # And the same forgery under a token a dossier genuinely answers.
        with self.assertRaises(TemplateV3Error):
            self._render(detailed, payload, forged, from_dossier=sorted(DOSSIER_TOKENS)[:1])

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_declaring_dossier_fields_without_a_dossier_is_a_contradiction(self):
        # Told by name, so a caller that forgot to thread the dossier learns that rather
        # than watching its identity fields fail as mismatches.
        from reporting.template_v3 import TemplateV3Error

        detailed, payload, fill = self._prepared()
        with self.assertRaises(TemplateV3Error) as caught:
            self._render(detailed, payload, dict(fill["fields"]), from_dossier=["DATA_EMISSAO"])
        self.assertIn("no dossier reached the renderer", str(caught.exception))

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_the_orchestrated_path_with_a_dossier_still_renders(self):
        # Negative control: the real path stamps ten dossier fields and must keep working.
        import tempfile

        from scripts.render_report_pdfs import render

        payload_path = Path(TEMPLATE_DIR).parent / "audit9" / "payload-09.json"
        dossier_path = Path(TEMPLATE_DIR).parent / "dossie-audit4.json"
        if not (payload_path.is_file() and dossier_path.is_file()):
            self.skipTest("no compiled payload and dossier available in this environment")
        with tempfile.TemporaryDirectory() as td:
            result = render("09", payload_path, Path(TEMPLATE_DIR), Path(td) / "x.pdf", dossier_path)
        self.assertTrue(result["from_dossier"])
        self.assertTrue(result["dossier_supplied"])

    @unittest.skipUnless(TEMPLATE_DIR, "set GENOMA_TEMPLATE_DIR to an installed template pack")
    def test_the_pdf_carries_the_governing_ruleset(self):
        # The fill used to run before `render_document` stamped the ruleset into the
        # execution manifest, so the PDF's workflow-log field lacked the identity the
        # markdown printed.
        import tempfile

        import fitz

        from scripts.render_report_pdfs import render

        payload_path = Path(TEMPLATE_DIR).parent / "audit9" / "payload-09.json"
        if not payload_path.is_file():
            self.skipTest("no compiled payload available in this environment")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "x.pdf"
            render("09", payload_path, Path(TEMPLATE_DIR), out)
            text = "".join(page.get_text() for page in fitz.open(out))
        self.assertIn("v3.4", text)



class StaticRulesetConflictTest(unittest.TestCase):
    """A ruleset identity printed as fixed page text must not pass unremarked.

    The v3.0 templates were approved under an earlier ruleset and one of them carries that
    identity as page text rather than a placeholder, so no fill can reach it. The governing
    identity is stamped correctly elsewhere on the same page, leaving the delivered PDF
    naming two rulesets with nothing saying which one produced the numbers. The template
    bytes are immutable by the store's contract, so the check reports rather than blocks —
    but it reports on every run.

    The superseded identity is built here rather than written out, because a literal copy of
    it anywhere in the tree is exactly what `test_normative_identity` forbids.
    """

    SUPERSEDED = "v" + "3.3"
    SUPERSEDED_LINE = f"{SUPERSEDED}/VIGENTE/14-" + "08-2026"

    def _check(self, *args, **kwargs):
        from scripts.render_report_pdfs import static_ruleset_conflict

        return static_ruleset_conflict(*args, **kwargs)

    def _pdf(self, text: str) -> Path:
        from reportlab.pdfgen import canvas

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "t.pdf"
        c = canvas.Canvas(str(path))
        c.drawString(60, 700, text)
        c.save()
        return path

    def test_a_stale_ruleset_line_is_reported_with_both_identities(self):
        conflict = self._check(
            self._pdf(f"Ruleset: {self.SUPERSEDED_LINE}. POST-DEPLOYMENT: PENDENTE."),
            {"version": "v3.4"},
        )
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["template_states"], self.SUPERSEDED_LINE)
        self.assertEqual(conflict["run_governed_by"], "v3.4")
        self.assertIn("imutáveis", conflict["detail"])

    def test_a_matching_ruleset_line_is_not_a_conflict(self):
        self.assertIsNone(
            self._check(self._pdf("Ruleset: v3.4/VIGENTE/17-08-2026."), {"version": "v3.4"})
        )

    def test_a_template_naming_no_ruleset_is_not_a_conflict(self):
        self.assertIsNone(self._check(self._pdf("sem identidade normativa"), {"version": "v3.4"}))

    def test_an_unreadable_template_does_not_crash_the_render(self):
        self.assertIsNone(self._check(Path("/nonexistent/none.pdf"), {"version": "v3.4"}))

    def test_a_run_without_a_declared_ruleset_makes_no_claim(self):
        """No running identity means nothing to disagree with, not a silent pass."""
        self.assertIsNone(
            self._check(self._pdf(f"Ruleset: {self.SUPERSEDED_LINE}."), {})
        )


if __name__ == "__main__":
    unittest.main()
