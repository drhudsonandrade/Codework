"""Regression tests for the two remaining PR #30 blockers.

These tests deliberately exercise the shipped curation artifacts and the real publication
writers. They pin the owner-reviewed HFE curation and require every post-render mutation to be
covered by provenance before any JSON/Markdown/HTML/PDF/DOCX artifact is written.

The first CI run of this file is intentionally RED: it proves the tests detect the pre-fix
state before production code is changed.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ruleset_test_support import RULESET

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "config/partial_genome_annotation_targets.json"
EVIDENCE = ROOT / "docs/evidence/ASSESSED_ALLELES_CLINVAR.json"


def _final_data() -> dict:
    """A fully anchored fixture payload suitable for FINAL layout QA."""
    from reporting.provenance import fixture_payload

    data = fixture_payload(
        case_id="CASE-PR30-REGRESSION",
        report_id="01",
        summary="Fixture de regressão; não representa paciente.",
        sections={"Resumo clínico executivo": "Fixture de regressão."},
        basis="Fixture PR30; nenhum dado clínico real.",
    )
    data["ruleset"] = dict(RULESET)
    data["publication_gate"]["placeholders_resolved"] = True
    return data


class HfeCurationRegressionTest(unittest.TestCase):
    """The HFE H63D allele identity remains curated as G."""

    def test_rs1799945_is_g_verified_and_established_count_is_28(self):
        """The source-derived registry and evidence agree on G/VERIFICADO and 28 established."""
        targets = json.loads(TARGETS.read_text(encoding="utf-8"))
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        target = next(t for t in targets["targets"] if t["rsid"] == "rs1799945")
        record = next(r for r in evidence["results"] if r["rsid"] == "rs1799945")

        self.assertEqual(targets["assessed_allele_curation"]["established"], 28)
        self.assertEqual(evidence["assessed_alleles_established"], 28)
        self.assertEqual(target["assessed_allele"], "G")
        self.assertEqual(target["assessed_allele_status"], "VERIFICADO")
        self.assertEqual(record["assessed_allele"], "G")
        self.assertEqual(record["status"], "VERIFICADO")
        self.assertEqual(record["reference_allele"], "C")
        self.assertTrue(
            any(
                item.get("alternate") == "G" and item.get("accession") == "VCV000000010"
                for item in record["clinvar_records_at_this_coordinate"]
            )
        )


class PostRenderProvenanceRegressionTest(unittest.TestCase):
    """Renderer disclosure is provenance-bound and writers fail closed after mutation."""

    def test_prepare_editorial_render_revalidates_its_execution_manifest_mutations(self):
        """Every disclosure key added by the renderer is anchored before serialization."""
        from reporting.editorial_v3 import prepare_editorial_render
        from reporting.engine import render_document
        from reporting.provenance import provenance_blockers

        prepared = prepare_editorial_render(
            render_document("01", _final_data(), mode="FINAL"),
            programmatic_final_authorization="unit-test visual QA",
        )
        self.assertEqual(provenance_blockers(prepared["data"]), [])

    def test_json_markdown_html_writer_refuses_manifest_drift_after_prepare(self):
        """A post-prepare manifest edit cannot reach JSON, Markdown or HTML."""
        from reporting.editorial_v3 import prepare_editorial_render
        from reporting.engine import ReportReleaseError, render_document, write_bundle

        prepared = prepare_editorial_render(
            render_document("01", _final_data(), mode="FINAL"),
            programmatic_final_authorization="unit-test visual QA",
        )
        prepared["data"]["execution_manifest"]["TEMPLATE_PACK_V3"] = "ALTERADO APÓS GATE"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ReportReleaseError):
                write_bundle(prepared, Path(td), stem="must-not-write")
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_pdf_docx_writer_refuses_manifest_drift_after_prepare(self):
        """A post-prepare manifest edit cannot reach PDF or DOCX either."""
        from reporting.editorial_v3 import prepare_editorial_render, write_editorial_bundle
        from reporting.engine import ReportReleaseError, render_document

        prepared = prepare_editorial_render(
            render_document("01", _final_data(), mode="FINAL"),
            programmatic_final_authorization="unit-test visual QA",
        )
        prepared["data"]["execution_manifest"]["TEMPLATE_PACK_V3"] = "ALTERADO APÓS GATE"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ReportReleaseError):
                write_editorial_bundle(prepared, Path(td), stem="must-not-write")
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_writer_refuses_markdown_or_html_that_no_longer_matches_data(self):
        """The serialized views cannot lag behind a caller mutation of the payload."""
        from reporting.editorial_v3 import prepare_editorial_render
        from reporting.engine import ReportReleaseError, render_document, write_bundle

        prepared = prepare_editorial_render(
            render_document("01", _final_data(), mode="FINAL"),
            programmatic_final_authorization="unit-test visual QA",
        )
        prepared["markdown"] += "\ntexto não derivado"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ReportReleaseError, "markdown"):
                write_bundle(prepared, Path(td), stem="must-not-write")
            self.assertEqual(list(Path(td).iterdir()), [])

        prepared = prepare_editorial_render(
            render_document("01", _final_data(), mode="FINAL"),
            programmatic_final_authorization="unit-test visual QA",
        )
        prepared["html"] += "<p>texto não derivado</p>"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ReportReleaseError, "HTML"):
                write_bundle(prepared, Path(td), stem="must-not-write")
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_input_schema_is_checked_in_both_directions(self):
        """Changing or deleting the assay schema leaves a render-time blocker."""
        from reporting.provenance import Artifact, PayloadCompiler, provenance_blockers

        compiler = PayloadCompiler(case_id="CASE", report_id="01")
        compiler.register(Artifact.from_payload(
            "input-artifact", {"input": {"schema": "raw_snp_array_v1"}}
        ))
        for name in ("summary", "sources", "limitations"):
            compiler.state(
                name, "fixture", kind="fixture", basis="regression fixture",
                status="NÃO DISPONÍVEL",
            )
        data = compiler.compile()
        data["input"]["schema"] = "wgs_vcf_projection_v1"
        self.assertIn("provenance:mismatch:input.schema", provenance_blockers(data))

        data = compiler.compile()
        del data["input"]["schema"]
        self.assertIn("provenance:missing_value:input.schema", provenance_blockers(data))

    def test_extra_cannot_replace_the_anchored_input_block(self):
        """The top-level input object is protected although its anchor is input.schema."""
        from reporting.provenance import Artifact, PayloadCompiler, ProvenanceError

        compiler = PayloadCompiler(case_id="CASE", report_id="01")
        compiler.register(Artifact.from_payload(
            "input-artifact", {"input": {"schema": "raw_snp_array_v1"}}
        ))
        for name in ("summary", "sources", "limitations"):
            compiler.state(
                name, "fixture", kind="fixture", basis="regression fixture",
                status="NÃO DISPONÍVEL",
            )
        with self.assertRaisesRegex(ProvenanceError, "input"):
            compiler.compile(extra={"input": {"schema": "wgs_vcf_projection_v1"}})


if __name__ == "__main__":
    unittest.main()
