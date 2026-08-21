"""The printed report must be derivable from the artifacts, not from the operator.

Before PROVENANCE_GATE, `scripts/generate_report.py` accepted "already-curated JSON": the
scientific content of a FINAL report was whatever a human typed. Every test here is a
negative control — each one proves a specific way of stating something the data does not
support is now refused rather than published.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.provenance import (
    Anchor,
    Artifact,
    PayloadCompiler,
    ProvenanceError,
    fixture_payload,
    provenance_blockers,
    render_value,
    weakest_status,
)

ARTIFACT = {
    "metrics": {"call_rate": 0.9871, "rows": 700000},
    "observations": [
        {"rsid": "rs1799807", "genotype": "AG", "orientation_operational_status": "VERIFICADO"},
        {"rsid": "rs1803274", "genotype": None, "orientation_operational_status": "NÃO DISPONÍVEL"},
    ],
}


def _compiler() -> PayloadCompiler:
    compiler = PayloadCompiler(case_id="CASE-PROV", report_id="09")
    compiler.register(Artifact.from_payload("array-qc", ARTIFACT))
    return compiler


def _minimal(compiler: PayloadCompiler) -> dict:
    compiler.derive(
        "summary",
        artifact="array-qc",
        locator="metrics.call_rate",
        status="VERIFICADO",
        basis="QC call rate",
    )
    compiler.state("sources", ["array-qc"], kind="case_control", basis="artifact set", status="VERIFICADO")
    compiler.state("limitations", "Somente loci ensaiados.", kind="case_control", basis="scope", status="VERIFICADO")
    return compiler.compile(
        publication_gate={
            "passed": True, "consent_verified": True, "qc_verified": True,
            "evidence_verified": True, "placeholders_resolved": True,
        },
        policy_evaluation={
            "ready_for_requested_operation": True,
            "planes": {k: {"state": "PASS"} for k in ("policy_control", "scientific_data", "evidence", "audit")},
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
        },
    )


class CompileTimeBindingTest(unittest.TestCase):
    """Stage 1: a value must exist in the artifact it claims to come from."""

    def test_a_value_is_read_from_the_artifact_not_supplied_by_the_caller(self):
        compiler = _compiler()
        value = compiler.derive(
            "summary", artifact="array-qc", locator="observations[0].genotype",
            status="VERIFICADO", basis="array call",
        )
        self.assertEqual(value, "AG")
        self.assertEqual(compiler.anchors["summary"].observed_value, "AG")

    def test_a_locator_absent_from_the_artifact_is_refused(self):
        with self.assertRaises(ProvenanceError) as ctx:
            _compiler().derive(
                "summary", artifact="array-qc", locator="observations[0].pathogenicity",
                status="VERIFICADO", basis="invented",
            )
        self.assertIn("no key 'pathogenicity'", str(ctx.exception))

    def test_an_out_of_range_index_is_refused(self):
        with self.assertRaises(ProvenanceError):
            _compiler().derive(
                "summary", artifact="array-qc", locator="observations[9].genotype",
                status="VERIFICADO", basis="invented",
            )

    def test_an_empty_locator_cannot_anchor_the_whole_artifact(self):
        """An empty path resolved to the entire artifact, naming no measurement at all."""
        for locator in ("", "   "):
            with self.subTest(locator=locator), self.assertRaises(ProvenanceError) as ctx:
                _compiler().derive(
                    "summary", artifact="array-qc", locator=locator,
                    status="VERIFICADO", basis="whole artifact",
                )
            self.assertIn("must name a path", str(ctx.exception))

    def test_an_unregistered_artifact_cannot_be_anchored_to(self):
        with self.assertRaises(ProvenanceError):
            _compiler().derive(
                "summary", artifact="whole-genome", locator="metrics.rows",
                status="EXECUTADO", basis="never registered",
            )

    def test_free_text_cannot_enter_through_derive(self):
        """derive() has no value parameter; a derived kind must read the artifact."""
        with self.assertRaises(ProvenanceError):
            _compiler().state("summary", "AG", kind="observation", basis="typed", status="VERIFICADO")

    def test_a_fixture_anchor_can_never_claim_a_measurement(self):
        for status in ("EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO"):
            with self.subTest(status=status), self.assertRaises(ProvenanceError):
                _compiler().state("summary", "texto", kind="fixture", basis="qa", status=status)

    def test_registering_the_same_artifact_name_with_different_content_is_refused(self):
        compiler = _compiler()
        with self.assertRaises(ProvenanceError):
            compiler.register(Artifact.from_payload("array-qc", {"metrics": {"call_rate": 0.5}}))

    def test_compile_requires_the_mandatory_fields_to_be_anchored(self):
        compiler = _compiler()
        compiler.derive("summary", artifact="array-qc", locator="metrics.rows", status="VERIFICADO", basis="rows")
        with self.assertRaises(ProvenanceError) as ctx:
            compiler.compile(publication_gate={}, policy_evaluation={})
        self.assertIn("sources", str(ctx.exception))


class RenderTimeBindingTest(unittest.TestCase):
    """Stage 2: the text about to be printed must still equal what was measured."""

    def test_a_correctly_compiled_payload_passes(self):
        self.assertEqual(provenance_blockers(_minimal(_compiler())), [])

    def test_a_value_edited_after_compilation_is_caught(self):
        data = _minimal(_compiler())
        data["summary"] = "0.9999"
        self.assertIn("provenance:mismatch:summary", provenance_blockers(data))

    def test_a_payload_without_provenance_is_refused(self):
        data = _minimal(_compiler())
        del data["provenance"]
        self.assertEqual(provenance_blockers(data), ["provenance:absent"])

    def test_an_injected_section_is_caught_as_unanchored(self):
        data = _minimal(_compiler())
        data["sections"]["Achados clínicos e diagnósticos"] = "Paciente é portador de variante patogênica."
        self.assertIn(
            "provenance:unanchored:sections[Achados clínicos e diagnósticos]",
            provenance_blockers(data),
        )

    def test_an_injected_finding_is_caught_as_unanchored(self):
        data = _minimal(_compiler())
        data["findings"].append({"id": "F-FAKE", "interpretation": "risco elevado confirmado"})
        blockers = provenance_blockers(data)
        self.assertIn("provenance:unanchored:findings[F-FAKE].id", blockers)
        self.assertIn("provenance:unanchored:findings[F-FAKE].interpretation", blockers)

    def test_tampering_with_the_anchor_block_breaks_its_own_digest(self):
        data = _minimal(_compiler())
        data["provenance"]["fields"]["summary"]["observed_value"] = "0.9999"
        data["summary"] = "0.9999"
        # The text now matches the anchor, but the anchor no longer matches its digest.
        self.assertIn("provenance:sha256", provenance_blockers(data))

    def test_declaring_a_status_above_the_weakest_anchor_is_refused(self):
        compiler = _compiler()
        compiler.derive("summary", artifact="array-qc", locator="metrics.call_rate", status="VERIFICADO", basis="qc")
        compiler.state("sources", ["array-qc"], kind="case_control", basis="set", status="VERIFICADO")
        compiler.unavailable("limitations", basis="não declaradas")
        data = compiler.compile(publication_gate={}, policy_evaluation={})
        self.assertEqual(data["operational_status"], "NÃO DISPONÍVEL")
        data["operational_status"] = "EXECUTADO"
        self.assertIn("provenance:status_above_floor", provenance_blockers(data))

    def test_a_restated_floor_is_recomputed_not_trusted(self):
        compiler = _compiler()
        compiler.derive("summary", artifact="array-qc", locator="metrics.call_rate", status="VERIFICADO", basis="qc")
        compiler.state("sources", ["array-qc"], kind="case_control", basis="set", status="VERIFICADO")
        compiler.unavailable("limitations", basis="não declaradas")
        data = compiler.compile(publication_gate={}, policy_evaluation={})
        data["provenance"]["operational_status_floor"] = "VERIFICADO"
        blockers = provenance_blockers(data)
        self.assertIn("provenance:floor_mismatch", blockers)

    def test_a_restated_distribution_is_recomputed_not_trusted(self):
        data = _minimal(_compiler())
        data["provenance"]["status_distribution"]["EXECUTADO"] = 99
        self.assertIn("provenance:distribution_mismatch", provenance_blockers(data))

    def test_the_distribution_shows_what_the_floor_hides(self):
        compiler = _compiler()
        compiler.derive("summary", artifact="array-qc", locator="metrics.call_rate", status="VERIFICADO", basis="qc")
        compiler.state("sources", ["array-qc"], kind="case_control", basis="set", status="VERIFICADO")
        compiler.unavailable("limitations", basis="não declaradas")
        data = compiler.compile(publication_gate={}, policy_evaluation={})
        distribution = data["provenance"]["status_distribution"]
        self.assertEqual(data["provenance"]["operational_status_floor"], "NÃO DISPONÍVEL")
        self.assertEqual(distribution["VERIFICADO"], 4)
        self.assertEqual(distribution["NÃO DISPONÍVEL"], 1)

    def test_a_fixture_anchor_promoted_after_the_fact_is_caught(self):
        data = fixture_payload(case_id="C", report_id="01", summary="s", basis="qa")
        data["provenance"]["fields"]["summary"]["operational_status"] = "VERIFICADO"
        self.assertIn("provenance:fixture_overclaim:summary", provenance_blockers(data))


class FindingBuilderTest(unittest.TestCase):
    def test_a_finding_must_state_every_field_including_the_absent_ones(self):
        compiler = _compiler()
        builder = compiler.finding("F-1", basis="registro de alvos")
        builder.derived(
            "observed_data", artifact="array-qc", locator="observations[0].genotype",
            status="VERIFICADO", basis="chamada do array",
        )
        with self.assertRaises(ProvenanceError) as ctx:
            builder.add()
        # Silence would read as "no uncertainties"; section 6 requires it to be said.
        self.assertIn("uncertainties", str(ctx.exception))

    def test_a_complete_finding_renders_and_passes_the_gate(self):
        compiler = _compiler()
        builder = compiler.finding("F-1", basis="registro de alvos")
        builder.derived(
            "observed_data", artifact="array-qc", locator="observations[0].genotype",
            status="VERIFICADO", basis="chamada do array",
        )
        for key in ("domain", "nature", "priority", "qc", "evidence_refs",
                    "interpretation", "uncertainties", "confirmation", "status"):
            builder.unavailable(key, basis="não estabelecido nesta execução")
        builder.add()
        data = _minimal(compiler)
        self.assertEqual(provenance_blockers(data), [])
        self.assertEqual(data["findings"][0]["observed_data"], "AG")

    def test_an_unknown_finding_field_is_refused(self):
        builder = _compiler().finding("F-1", basis="b")
        with self.assertRaises(ProvenanceError):
            builder.unavailable("diagnosis", basis="not a field of the report model")


class RenderingAgreementTest(unittest.TestCase):
    def test_render_value_agrees_with_the_engine_printer(self):
        """The gate compares printed text to the anchor; the two renderers must agree."""
        from reporting.engine import _safe

        for value in (None, "", "texto", 0.5, 12, ["a", "b"], {"k": "v"}, ("x",)):
            with self.subTest(value=value):
                self.assertEqual(render_value(value), _safe(value))

    def test_weakest_status_is_the_floor_not_the_average(self):
        anchors = [
            Anchor("observation", "a", "0" * 64, "l", "v", "EXECUTADO", "b"),
            Anchor("observation", "a", "0" * 64, "l", "v", "INFERIDO", "b"),
        ]
        self.assertEqual(weakest_status(anchors), "INFERIDO")
        self.assertEqual(weakest_status([]), "NÃO DISPONÍVEL")


class EngineIntegrationTest(unittest.TestCase):
    def test_the_engine_refuses_a_final_report_with_no_provenance(self):
        from reporting.engine import ReportReleaseError, render_document

        data = _minimal(_compiler())
        del data["provenance"]
        with self.assertRaises(ReportReleaseError) as ctx:
            render_document("09", data, mode="FINAL")
        self.assertIn("provenance:absent", str(ctx.exception))

    def test_the_engine_publishes_a_compiled_payload(self):
        from reporting.engine import render_document

        rendered = render_document("09", _minimal(_compiler()), mode="FINAL")
        self.assertIn("0.9871", rendered["markdown"])

    def test_the_engine_refuses_a_hand_edited_genotype(self):
        from reporting.engine import ReportReleaseError, render_document

        compiler = _compiler()
        compiler.section_derived(
            "Identificação e controle", artifact="array-qc",
            locator="observations[0].genotype", status="VERIFICADO", basis="array call",
        )
        data = _minimal(compiler)
        data["sections"]["Identificação e controle"] = "GG"
        with self.assertRaises(ReportReleaseError) as ctx:
            render_document("09", data, mode="FINAL")
        self.assertIn("provenance:mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
