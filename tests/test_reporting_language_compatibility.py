"""Guard English renderer code against changes to established pt-BR report output."""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import inspect
import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_type_hints

from reporting import editorial_v3, editorial_v3_hifi, engine, provenance
from tests.reporting_language_fixtures import (
    BASE_SHA,
    make_payload,
    output_snapshot,
    render_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "tests/fixtures/reporting_language_baseline.json"


class ReportingLanguageCompatibilityTest(unittest.TestCase):
    """Characterize output independently of the new presentation constants."""

    @classmethod
    def setUpClass(cls):
        """Read a recorded pre-migration snapshot rather than recomputing expectations."""
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    def _locale(self):
        """Report missing ownership as an assertion rather than an import failure."""
        self.assertIsNotNone(importlib.util.find_spec("reporting.locale_pt_br"))
        return importlib.import_module("reporting.locale_pt_br")

    def test_presentation_module_preserves_every_inventoried_value(self):
        """English names resolve to exact old display strings, not translated results."""
        locale = self._locale()
        expected = self.baseline["presentation_text"]
        actual = {name: value for name, value in vars(locale).items() if name.isupper()}
        self.assertEqual(actual, expected)
        self.assertTrue(all(isinstance(value, str) for value in actual.values()))

    def test_both_renderers_use_the_explicit_presentation_owner(self):
        """The locale boundary is consumed, not an unused configuration file."""
        locale = self._locale()
        for module in (engine, editorial_v3_hifi):
            with self.subTest(module=module.__name__):
                self.assertIs(getattr(module, "pt_br", None), locale)
                source = Path(module.__file__).read_text(encoding="utf-8")
                used = {
                    node.attr
                    for node in ast.walk(ast.parse(source))
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "pt_br"
                }
                self.assertIn("UNAVAILABLE", used)
                self.assertIn("PENDING", used)
                self.assertTrue(used.issubset(self.baseline["presentation_text"]))
        self.assertEqual(locale.LANGUAGE_TAG, "pt-BR")

    def test_all_eleven_models_keep_exact_text_bundles_and_filenames(self):
        """Public MODEL/FINAL outputs retain Unicode bytes, JSON contracts and hashes."""
        actual = output_snapshot()
        self.assertEqual(self.baseline["base_sha"], BASE_SHA)
        self.assertEqual(actual["cases"], self.baseline["cases"])
        self.assertEqual(len(actual["cases"]), 23)

    def test_existing_safe_defaults_and_value_rendering_do_not_change(self):
        """The presentation boundary cannot modify data or its provenance encoding."""
        values = (0, False, "ação", {"z": 2, "a": 1}, ["fim", {"b": 2, "a": 1}])
        for renderer in (engine, editorial_v3_hifi):
            with self.subTest(renderer=renderer.__name__):
                signature = inspect.signature(renderer._safe)
                self.assertEqual(signature.parameters["default"].default, "NÃO DISPONÍVEL")
                self.assertEqual(renderer._safe(None), "NÃO DISPONÍVEL")
                self.assertEqual(renderer._safe("", "outro"), "outro")
                for value in values:
                    self.assertEqual(renderer._safe(value), provenance.render_value(value))

    def test_reserved_headings_preserve_section_order_and_duplicates(self):
        """Generic captions stay out of the report-specific section list."""
        markdown = "\n".join(
            (
                "## Finalidade",
                "## Público",
                "## Resumo executivo",
                "## Seção A",
                "## Achados estruturados",
                "## Execution Manifest",
                "## Fontes",
                "## Limitações",
                "## Seção B",
                "## Seção A",
            )
        )
        self.assertEqual(
            editorial_v3_hifi._report_sections({"markdown": markdown}), ["Seção A", "Seção B"]
        )

    def test_payload_language_fields_cannot_select_an_unimplemented_locale(self):
        """There is no new locale selector or silent translation fallback."""
        expected = render_fixture("01", "MODEL")
        actual = engine.render_document("01", {"locale": "en-US", "language": "en"})
        self.assertEqual(actual["markdown"], expected["markdown"])
        self.assertEqual(actual["html"], expected["html"])
        self.assertIn("<html lang='pt-BR'>", actual["html"])
        self.assertNotIn("locale", actual["metadata"])

    def test_final_still_refuses_unprovenanced_or_mismatched_payloads(self):
        """Presentation extraction cannot weaken publication or report identity gates."""
        with self.assertRaises(engine.ReportReleaseError):
            engine.render_document("01", {}, mode="FINAL")
        payload = make_payload("01")
        with self.assertRaisesRegex(engine.ReportReleaseError, "report_id:mismatch"):
            engine.render_document("02", payload, mode="FINAL")
        self.assertEqual(payload["report_id"], "01")

    def test_serialization_refuses_mutated_text_before_creating_output(self):
        """Localized text cannot bypass the final derived-view integrity check."""
        rendered = render_fixture("01", "FINAL")
        before = deepcopy(rendered["data"])
        rendered["markdown"] = rendered["markdown"].replace("## Finalidade", "## Purpose")
        with TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist"
            with self.assertRaisesRegex(engine.ReportReleaseError, "markdown no longer matches"):
                engine.write_bundle(rendered, output)
            self.assertFalse(output.exists())
        self.assertEqual(rendered["data"], before)

    def test_programmatic_final_renderer_still_requires_explicit_authorization(self):
        """A locale module is never permission to publish a fallback PDF or DOCX."""
        with TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist"
            with self.assertRaises(editorial_v3.UnapprovedRendererError):
                editorial_v3.write_editorial_bundle(render_fixture("01", "FINAL"), output)
            self.assertFalse(output.exists())

    def test_reference_fixture_and_capture_harness_remain_pinned(self):
        """Candidate expectations cannot silently replace the captured reference bytes."""
        pins = {
            "tests/fixtures/reporting_language_baseline.json": (
                "9cc84c09512dc0c0bea15ef4dc4da1fa41efb387eda61fc4eb727146fe66c2c8"
            ),
            "tests/reporting_language_fixtures.py": (
                "58316c45089f8354cc8ce7007237fa27544185b7f0b550147591ad0eb7318fd0"
            ),
        }
        for relative, expected in pins.items():
            with self.subTest(path=relative):
                self.assertEqual(
                    hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected
                )

    def test_design_tokens_retain_precise_types_and_plain_dictionary_values(self):
        """Typing the mixed design dictionary must not coerce values or change the layout."""
        expected = {
            "navy": "0B1F33",
            "teal": "0F766E",
            "amber": "A16207",
            "cream": "FFFAEB",
            "light_gray": "F2F4F7",
            "border": "D0D5DD",
            "text": "17212B",
            "slate": "667085",
            "pale_blue": "D7E3EF",
            "white": "FFFFFF",
            "a4_mm": (210, 297),
            "cover_left_mm": 18.0,
            "content_width_mm": 174.0,
        }
        self.assertIs(type(editorial_v3_hifi.DESIGN), dict)
        self.assertEqual(editorial_v3_hifi.DESIGN, expected)
        annotations = get_type_hints(editorial_v3_hifi)
        self.assertIn("DESIGN", annotations)
        fields = {
            name: str
            for name in expected
            if name not in ("a4_mm", "cover_left_mm", "content_width_mm")
        }
        fields.update(a4_mm=tuple[int, int], cover_left_mm=float, content_width_mm=float)
        self.assertEqual(get_type_hints(annotations["DESIGN"]), fields)


if __name__ == "__main__":
    unittest.main()
