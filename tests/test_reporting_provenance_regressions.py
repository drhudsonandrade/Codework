from __future__ import annotations

import unittest

from reporting.provenance import (
    FINDING_FIELDS,
    PayloadCompiler,
    ProvenanceError,
    fixture_payload,
    provenance_blockers,
)


class ReportingProvenanceRegressionTest(unittest.TestCase):
    def test_extra_cannot_replace_the_compiled_report_identity(self):
        compiler = PayloadCompiler(case_id="CASE-1", report_id="01")
        compiler.state(
            "summary", "fixture", kind="case_control", basis="test", status="VERIFICADO"
        )
        compiler.state(
            "sources", ["fixture"], kind="case_control", basis="test", status="VERIFICADO"
        )
        compiler.state(
            "limitations", "fixture", kind="case_control", basis="test", status="VERIFICADO"
        )
        with self.assertRaisesRegex(ProvenanceError, "report_id"):
            compiler.compile(extra={"report_id": "02"})

    def test_post_compile_publication_gate_edit_is_detected(self):
        payload = fixture_payload(
            case_id="CASE-1",
            report_id="01",
            summary="fixture",
            basis="fixture de regressão",
        )
        payload["publication_gate"]["passed"] = False
        self.assertIn(
            "provenance:mismatch:publication_gate",
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
