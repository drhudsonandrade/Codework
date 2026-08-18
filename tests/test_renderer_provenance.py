"""A report must never hide which renderer produced it.

The programmatic renderer reconstructs a v3.0-like layout without ever opening an approved
template. It previously wrote the same `visual_reference: "GENOMA model suite v3.0"` as the
template path, so a fallback artifact and a real template render were indistinguishable in
their own provenance records — and a FINAL clinical report could be produced by the
fallback silently.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.editorial_v3 import UnapprovedRendererError, write_editorial_bundle
from reporting.engine import render_document

PASSING_POLICY = {
    "ready_for_requested_operation": True,
    "planes": {k: {"state": "PASS"} for k in ("policy_control", "scientific_data", "evidence", "audit")},
    "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
}


def _data(**overrides):
    payload = {
        "case_id": "CASE-PROVENANCE",
        "summary": "fixture",
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
        "sections": {},
        "findings": [],
        "execution_manifest": {"status": "VERIFICADO"},
        "sources": ["fixture"],
        "limitations": "Fixture editorial.",
    }
    payload.update(overrides)
    return payload


class RendererProvenanceTest(unittest.TestCase):
    def test_final_refuses_the_fallback_renderer_without_acknowledgement(self):
        rendered = render_document("01", _data(), mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UnapprovedRendererError):
                write_editorial_bundle(rendered, Path(td), stem="x")

    def test_model_mode_still_renders_without_acknowledgement(self):
        """MODEL output is explicitly not a result, so it needs no opt-in."""
        rendered = render_document("01", _data(), mode="MODEL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_editorial_bundle(rendered, Path(td), stem="m")
            self.assertTrue(paths["pdf"].is_file())

    def test_acknowledged_fallback_declares_itself_in_its_provenance_record(self):
        rendered = render_document("01", _data(allow_programmatic_final=True), mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            write_editorial_bundle(rendered, Path(td), stem="b")
            runtime = json.loads((Path(td) / "b.editorial.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime["renderer"], "programmatic-approximation")
        self.assertEqual(runtime["template_pack_v3"], "NÃO DISPONÍVEL")
        self.assertEqual(runtime["visual_parity"], "NÃO DISPONÍVEL")
        # The bare approved-suite claim must not be reusable as the whole value.
        self.assertNotEqual(runtime["visual_reference"], "GENOMA model suite v3.0")

    def test_acknowledged_fallback_declares_itself_on_the_page(self):
        import fitz

        rendered = render_document("01", _data(allow_programmatic_final=True), mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_editorial_bundle(rendered, Path(td), stem="p")
            text = "".join(page.get_text() for page in fitz.open(paths["pdf"]))
        self.assertIn("RENDERIZAÇÃO PROGRAMÁTICA", text)
        self.assertIn("TEMPLATE_PACK_V3", text)
        self.assertIn("PARIDADE_VISUAL", text)

    def test_disclosure_does_not_mutate_the_caller_payload(self):
        data = _data(allow_programmatic_final=True)
        rendered = render_document("01", data, mode="FINAL")
        original_limitations = rendered["data"]["limitations"]
        with tempfile.TemporaryDirectory() as td:
            write_editorial_bundle(rendered, Path(td), stem="n")
        self.assertEqual(rendered["data"]["limitations"], original_limitations)
        self.assertEqual(data["limitations"], "Fixture editorial.")


if __name__ == "__main__":
    unittest.main()
