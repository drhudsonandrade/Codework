"""Post-compile edits and back doors into an already-anchored payload.

Each test here corresponds to a refusal in `reporting/provenance.py` whose docstring used to
justify itself with "Verified by doing it." — true when written, and unfalsifiable afterwards:
nothing would have failed if the refusal were deleted. The two doors are now controlled here.
"""
from __future__ import annotations

import unittest

from reporting import provenance
from reporting.provenance import (
    DERIVED_BLOCKS,
    FINDING_FIELDS,
    POLICY_EVALUATION_ARTIFACT,
    POST_DEPLOYMENT_WITNESS_ARTIFACT,
    Artifact,
    PayloadCompiler,
    ProvenanceError,
    fixture_payload,
    provenance_blockers,
)


def _anchored_compiler(case_id: str = "CASE-1", report_id: str = "01") -> PayloadCompiler:
    """A compiler with the three mandatory scalar fields anchored and nothing else."""
    compiler = PayloadCompiler(case_id=case_id, report_id=report_id)
    for name, value in (
        ("summary", "fixture"),
        ("sources", ["fixture"]),
        ("limitations", "fixture"),
    ):
        compiler.state(name, value, kind="case_control", basis="test", status="VERIFICADO")
    return compiler


class ReportingProvenanceRegressionTest(unittest.TestCase):
    def test_extra_cannot_replace_the_compiled_report_identity(self):
        compiler = _anchored_compiler()
        with self.assertRaisesRegex(ProvenanceError, "report_id"):
            compiler.compile(extra={"report_id": "02"})

    def test_extra_cannot_supply_any_block_compile_derives_from_artifacts(self):
        """`publication_gate` was the live exploit; every derived block is closed the same way.

        Anchored fields were refused and the derived authority blocks were not, so
        ``extra={"publication_gate": {"passed": True, ...}}`` published a report the policy
        engine had blocked — `reporting.engine._publication_blockers` reads that block to
        decide whether a FINAL document may be produced. Each name is asserted on its own:
        a refusal that covered only the one block that was exploited would leave the rest.
        """
        for block in DERIVED_BLOCKS:
            with self.subTest(block=block):
                compiler = _anchored_compiler()
                with self.assertRaisesRegex(ProvenanceError, block):
                    compiler.compile(extra={block: {"passed": True}})

    def test_the_derived_block_guard_is_reached_and_not_shadowed_by_the_anchor_guard(self):
        """The guard has to be the one refusing, or it could be deleted with nothing failing.

        `policy_evaluation` is also an `AUTHORITY_FIELDS` anchor, so the earlier
        anchored-fields refusal fires for it first and the test above would pass with the
        derived-blocks guard removed. `publication_gate` is anchored per key
        (`publication_gate.passed`), never under its bare name, so it reaches this guard —
        which is exactly why it was the block that could be written from outside.
        """
        compiler = _anchored_compiler()
        with self.assertRaises(ProvenanceError) as caught:
            compiler.compile(extra={"publication_gate": {"passed": True}})
        self.assertIn("derived blocks", str(caught.exception))
        self.assertIn("publication_gate", str(caught.exception))

    def test_a_derived_block_is_refused_even_beside_acceptable_keys(self):
        """A caller cannot smuggle one past by burying it in an otherwise valid `extra`."""
        compiler = _anchored_compiler()
        with self.assertRaisesRegex(ProvenanceError, "publication_gate"):
            compiler.compile(
                extra={"nota_editorial": "texto livre", "publication_gate": {"passed": True}}
            )

    def test_extra_that_touches_no_reserved_name_still_works(self):
        """The accepting case, so the refusals above are not passing vacuously."""
        payload = _anchored_compiler().compile(extra={"nota_editorial": "texto livre"})
        self.assertEqual("texto livre", payload["nota_editorial"])

    def test_the_reserved_verdict_artifacts_cannot_be_registered(self):
        """`register()` is the other door onto the two artifacts a caller may not compose.

        Moving the verdict out of `compile`'s parameters closed the door a builder used to
        grant itself a PASS and left this one open:
        ``register(Artifact.from_payload("policy-evaluation", {...ready: True...}))``
        installed an invented verdict under the reserved name and published FINAL with
        `operational_status: VERIFICADO`. The witness is the same shape of claim — an
        in-memory object asserting a service it never contacted behaved correctly.
        """
        for name in (POLICY_EVALUATION_ARTIFACT, POST_DEPLOYMENT_WITNESS_ARTIFACT):
            with self.subTest(artifact=name):
                compiler = _anchored_compiler()
                artifact = Artifact.from_payload(
                    name,
                    {
                        "ready_for_requested_operation": True,
                        "post_deployment_status": "PASS",
                    },
                )
                with self.assertRaisesRegex(ProvenanceError, name):
                    compiler.register(artifact)
                self.assertNotIn(name, compiler._artifacts)

    def test_an_ordinary_artifact_still_registers(self):
        """The accepting case: only the two reserved names are refused."""
        compiler = _anchored_compiler()
        artifact = compiler.register(
            Artifact.from_payload("qc-metrics", {"call_rate": 0.99})
        )
        self.assertEqual("qc-metrics", artifact.name)
        self.assertIs(artifact, compiler.artifact("qc-metrics"))

    def test_free_text_cannot_be_introduced_through_a_derived_kind(self):
        """`state()` is the only way in for text, and it may not claim a measurement.

        A derived kind asserts the value was read out of a registered artifact. Letting
        `state()` carry one would let a caller type a number and label it measured, which is
        the whole distinction this module draws.
        """
        for kind in provenance.DERIVED_KINDS:
            with self.subTest(kind=kind):
                compiler = PayloadCompiler(case_id="CASE-1", report_id="01")
                with self.assertRaisesRegex(ProvenanceError, "derive"):
                    compiler.state(
                        "summary", "texto", kind=kind, basis="test", status="VERIFICADO"
                    )

    def test_derive_refuses_a_kind_that_is_not_derived(self):
        """And the reverse door: `derive()` may not launder a stated kind through a read."""
        compiler = _anchored_compiler()
        compiler.register(Artifact.from_payload("qc-metrics", {"call_rate": 0.99}))
        with self.assertRaisesRegex(ProvenanceError, "derived kind"):
            compiler.derive(
                "call_rate",
                artifact="qc-metrics",
                locator="call_rate",
                kind="fixture",
                basis="test",
                status="VERIFICADO",
            )

    def test_a_restated_floor_or_distribution_is_recomputed_and_refused(self):
        """The block cannot reassure about itself: both are derived from the same anchors.

        A payload that simply *wrote* `operational_status_floor: VERIFICADO` over a floor of
        NÃO DISPONÍVEL would otherwise present as verified while every value in it was a
        fixture.
        """
        payload = fixture_payload(
            case_id="CASE-1", report_id="01", summary="fixture", basis="fixture de regressão"
        )
        self.assertEqual([], provenance_blockers(payload))

        edited = fixture_payload(
            case_id="CASE-1", report_id="01", summary="fixture", basis="fixture de regressão"
        )
        edited["provenance"]["operational_status_floor"] = "VERIFICADO"
        self.assertIn("provenance:floor_mismatch", provenance_blockers(edited))

        edited = fixture_payload(
            case_id="CASE-1", report_id="01", summary="fixture", basis="fixture de regressão"
        )
        edited["provenance"]["status_distribution"]["VERIFICADO"] += 5
        self.assertIn("provenance:distribution_mismatch", provenance_blockers(edited))

    def test_a_status_declared_above_the_floor_is_refused(self):
        """The payload's own `operational_status` may not read stronger than its weakest value."""
        payload = fixture_payload(
            case_id="CASE-1", report_id="01", summary="fixture", basis="fixture de regressão"
        )
        self.assertEqual("NÃO DISPONÍVEL", payload["provenance"]["operational_status_floor"])
        for declared in ("VERIFICADO", "EXECUTADO", "INFERIDO", "PROPOSTO"):
            with self.subTest(declared=declared):
                payload["operational_status"] = declared
                self.assertIn("provenance:status_above_floor", provenance_blockers(payload))
        payload["operational_status"] = "NÃO DISPONÍVEL"
        self.assertEqual([], provenance_blockers(payload))

    def test_post_compile_publication_gate_edit_is_detected(self):
        payload = fixture_payload(
            case_id="CASE-1",
            report_id="01",
            summary="fixture",
            basis="fixture de regressão",
        )
        payload["publication_gate"]["passed"] = False
        self.assertIn(
            "provenance:mismatch:publication_gate.passed",
            provenance_blockers(payload),
        )

    def test_removed_section_is_detected_from_its_remaining_anchor(self):
        payload = fixture_payload(
            case_id="CASE-1",
            report_id="01",
            summary="fixture",
            sections={"Resumo": "conteúdo"},
            basis="fixture de regressão",
        )
        del payload["sections"]["Resumo"]
        self.assertIn(
            "provenance:missing_value:sections[Resumo]", provenance_blockers(payload)
        )

    def test_removed_finding_uncertainties_is_detected(self):
        compiler = PayloadCompiler(case_id="CASE-1", report_id="01")
        for name, value in (
            ("summary", "fixture"),
            ("sources", ["fixture"]),
            ("limitations", "fixture"),
        ):
            compiler.state(
                name, value, kind="case_control", basis="test", status="VERIFICADO"
            )
        finding = compiler.finding("F-1", basis="test")
        for key in FINDING_FIELDS:
            finding.stated(
                key,
                f"fixture-{key}",
                kind="case_control",
                basis="test",
                status="VERIFICADO",
            )
        finding.add()
        payload = compiler.compile()
        del payload["findings"][0]["uncertainties"]
        self.assertIn(
            "provenance:missing_value:findings[F-1].uncertainties",
            provenance_blockers(payload),
        )


if __name__ == "__main__":
    unittest.main()
