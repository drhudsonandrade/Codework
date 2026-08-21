"""Only the policy engine may declare a run authorised.

An external audit named this the root architectural defect, and it was right. Nine report
builders passed their own `publication_gate` and `policy_evaluation` into `compile`:
`consent_verified` was `bool(case_id)`, `evidence_verified` was the literal `True`, and all
four planes plus FINAL_AUDIT_GATE went to PASS whenever a local variable called `verified`
was true. The component that produced the report also declared it authorised.

Measured on a real case, the two authorities disagreed exactly as expected: `genoma_policy`
returned `ready_for_requested_operation: False` for the same run whose payloads all carried
`True` — and the array manifest, by omitting its `operation` block, had silently switched
DATA_PROVENANCE_GATE, CONSENT_GATE, QC_GATE and RUNTIME_RESOURCE_GATE off while the plane
that contains them reported PASS.

The verdict is no longer a parameter. It is copied from a registered policy evaluation with
that artifact's SHA-256 beside it, and a payload that registers none refuses.
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

from reporting.provenance import (
    POLICY_EVALUATION_ARTIFACT,
    REQUIRED_PLANES,
    Artifact,
    PayloadCompiler,
)

ARTIFACT = {"metrics": {"call_rate": 0.99, "rows": 10}}

PASS_VERDICT = {
    "ready_for_requested_operation": True,
    "planes": {name: {"state": "PASS"} for name in REQUIRED_PLANES},
    "gates": [
        {"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True},
        {"gate": "CONSENT_GATE", "state": "PASS", "blocking": True},
        {"gate": "QC_GATE", "state": "PASS", "blocking": True},
    ],
}


def _verdict_file(verdict: dict) -> Path:
    path = Path(tempfile.mkdtemp()) / "policy-evaluation.json"
    path.write_text(json.dumps(verdict), encoding="utf-8")
    return path


def _payload(verdict: dict | None) -> dict:
    compiler = PayloadCompiler(
        case_id="CASO-AUT", report_id="09",
        policy_evaluation=_verdict_file(verdict) if verdict is not None else None,
    )
    compiler.register(Artifact.from_payload("array-qc", ARTIFACT))
    compiler.derive(
        "summary", artifact="array-qc", locator="metrics.call_rate",
        status="VERIFICADO", basis="call rate",
    )
    compiler.state("sources", ["array-qc"], kind="case_control", basis="set", status="VERIFICADO")
    compiler.state("limitations", "escopo", kind="case_control", basis="escopo", status="VERIFICADO")
    return compiler.compile()


class NoVerdictMeansNoAuthorityTest(unittest.TestCase):
    def test_a_payload_without_an_evaluation_grants_nothing(self):
        data = _payload(None)
        self.assertIs(data["publication_gate"]["passed"], False)
        self.assertIs(data["publication_gate"]["consent_verified"], False)
        self.assertIs(data["publication_gate"]["evidence_verified"], False)
        self.assertIs(data["policy_evaluation"]["ready_for_requested_operation"], False)
        for plane in REQUIRED_PLANES:
            self.assertEqual(data["policy_evaluation"]["planes"][plane]["state"], "BLOCKED")

    def test_the_refusal_names_the_artifact_that_would_change_it(self):
        source = _payload(None)["policy_evaluation"]["source"]
        self.assertEqual(source["status"], "NÃO DISPONÍVEL")
        self.assertIn(POLICY_EVALUATION_ARTIFACT, source["reason"])

    def test_the_reserved_artifact_name_cannot_be_registered(self):
        """The door the first version of this fix left open.

        Moving the verdict out of `compile`'s parameters closed one route and left another:
        `register(Artifact.from_payload("policy-evaluation", {...ready: True...}))` installed
        an invented verdict under the reserved name and published FINAL with
        `operational_status: VERIFICADO`. Verified by doing it before closing it.
        """
        from reporting.provenance import ProvenanceError

        compiler = PayloadCompiler(case_id="CASO-AUT", report_id="09")
        with self.assertRaises(ProvenanceError) as caught:
            compiler.register(Artifact.from_payload(POLICY_EVALUATION_ARTIFACT, PASS_VERDICT))
        message = str(caught.exception)
        self.assertIn("not a registrable artifact", message)
        self.assertIn("policy_evaluation=<path>", message)

    def test_a_fixture_verdict_cannot_carry_measured_values(self):
        """Layout QA may render FINAL; it may not publish a measurement on that authority."""
        from reporting.provenance import ProvenanceError, fixture_payload

        # The legitimate use: every value a fixture, status floored at NÃO DISPONÍVEL.
        data = fixture_payload(case_id="CASO-QA", report_id="09", summary="s", basis="qa")
        self.assertEqual(data["operational_status"], "NÃO DISPONÍVEL")
        self.assertEqual(data["policy_evaluation"]["source"]["origin"], "fixture")

        compiler = PayloadCompiler(case_id="CASO-QA", report_id="09")
        compiler._install_verdict(
            Artifact.from_payload(POLICY_EVALUATION_ARTIFACT, PASS_VERDICT), fixture=True
        )
        compiler.register(Artifact.from_payload("array-qc", ARTIFACT))
        compiler.derive(
            "summary", artifact="array-qc", locator="metrics.call_rate",
            status="VERIFICADO", basis="uma medição real",
        )
        compiler.state("sources", ["array-qc"], kind="case_control", basis="s", status="VERIFICADO")
        compiler.state("limitations", "x", kind="case_control", basis="l", status="VERIFICADO")
        with self.assertRaises(ProvenanceError) as caught:
            compiler.compile()
        self.assertIn("fixture policy verdict cannot carry measured values", str(caught.exception))

    def test_a_builder_can_no_longer_hand_compile_a_verdict(self):
        compiler = PayloadCompiler(case_id="CASO-AUT", report_id="09")
        with self.assertRaises(TypeError):
            compiler.compile(policy_evaluation=PASS_VERDICT)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            compiler.compile(publication_gate={"passed": True})  # type: ignore[call-arg]


class VerdictIsCopiedNotComposedTest(unittest.TestCase):
    def test_a_pass_verdict_is_carried_with_the_hash_of_its_artifact(self):
        data = _payload(PASS_VERDICT)
        self.assertIs(data["publication_gate"]["passed"], True)
        self.assertIs(data["publication_gate"]["consent_verified"], True)
        self.assertIs(data["publication_gate"]["qc_verified"], True)
        source = data["policy_evaluation"]["source"]
        self.assertEqual(source["status"], "VERIFICADO")
        self.assertTrue(source["sha256"])
        self.assertEqual(source["origin"], "policy-engine-output")
        self.assertTrue(source["path"])

    def test_a_refused_verdict_is_carried_verbatim(self):
        """The builder cannot upgrade what the engine withheld."""
        blocked = {
            "ready_for_requested_operation": False,
            "planes": {
                "policy_control": {"state": "PASS"}, "scientific_data": {"state": "FAIL"},
                "evidence": {"state": "PASS"}, "audit": {"state": "PASS"},
            },
            "gates": [{"gate": "CONSENT_GATE", "state": "FAIL", "blocking": True}],
        }
        data = _payload(blocked)
        self.assertIs(data["publication_gate"]["passed"], False)
        self.assertIs(data["publication_gate"]["consent_verified"], False)
        self.assertEqual(data["policy_evaluation"]["planes"]["scientific_data"]["state"], "FAIL")

    def test_a_plane_the_evaluation_omits_is_blocked_not_assumed(self):
        partial = {"ready_for_requested_operation": True, "planes": {"audit": {"state": "PASS"}}, "gates": []}
        data = _payload(partial)
        self.assertEqual(data["policy_evaluation"]["planes"]["evidence"]["state"], "BLOCKED")
        self.assertEqual(data["policy_evaluation"]["planes"]["audit"]["state"], "PASS")

    def test_consent_comes_from_the_consent_gate_not_from_the_case_id(self):
        """`bool(case_id)` was the old test; an identifier is not a consent instrument."""
        no_consent = dict(PASS_VERDICT, gates=[
            {"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True},
            {"gate": "CONSENT_GATE", "state": "FAIL", "blocking": True},
        ])
        data = _payload(no_consent)
        self.assertTrue(data["case_id"])
        self.assertIs(data["publication_gate"]["consent_verified"], False)


class RenderRefusesAnUnauthorisedPayloadTest(unittest.TestCase):
    def test_final_publication_is_blocked_without_a_verdict(self):
        from reporting.engine import ReportReleaseError, render_document

        with self.assertRaises(ReportReleaseError) as caught:
            render_document("09", _payload(None), mode="FINAL")
        message = str(caught.exception)
        self.assertIn("policy_evaluation:ready_for_requested_operation", message)
        self.assertIn("publication_gate:passed", message)

    def test_final_publication_proceeds_on_a_real_verdict(self):
        from reporting.engine import render_document

        rendered = render_document("09", _payload(PASS_VERDICT), mode="FINAL")
        self.assertIn("markdown", rendered)


class ArrayManifestAnswersItsGatesTest(unittest.TestCase):
    """The manifest must not silence the scientific-data plane by omission."""

    def _manifest(self, consent=None):
        from scripts.build_array_case_manifest import build_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            qc_path = root / "qc.json"
            annotation_path = root / "annotation.json"
            qc = {
                "case_id": "CASO-AUT", "operational_status": "VERIFICADO",
                "gates": {"LIMITED_INTERPRETATION_GATE": {"state": "PASS"}},
                "input": {"sha256": "a" * 64, "build": "GRCh37", "strand": "forward"},
                "metrics": {"unique_rsids": 10, "call_rate": 0.99}, "limitations": [],
            }
            annotation = {
                "case_id": "CASO-AUT", "input_sha256": "a" * 64, "mode": "plan-only",
                "operational_status": "PROPOSTO", "evidence_gate": {"state": "BLOCKED"},
                "observations": [], "evidence_retrievals": [], "limitations": [],
            }
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
            return build_manifest(qc, annotation, qc_path, annotation_path, consent=consent)

    def test_the_operation_block_is_declared_so_the_gates_run(self):
        manifest = self._manifest()
        self.assertTrue(manifest["session_id"])
        self.assertIs(manifest["operation"]["analysis_relevant"], True)
        self.assertIs(manifest["operation"]["requires_real_calling"], False)
        self.assertEqual(manifest["operation"]["output"], "ANALYSIS")
        self.assertIsInstance(manifest["section_attestations"], list)

    def test_the_session_id_is_bound_to_the_bytes_analysed(self):
        self.assertIn("a" * 16, self._manifest()["session_id"])

    def test_consent_is_unverified_when_no_record_was_supplied(self):
        consent = self._manifest()["consent"]
        self.assertIs(consent["verified"], False)
        self.assertIn("nenhum registro de consentimento", consent["basis"])

    def test_a_supplied_consent_record_is_carried_not_invented(self):
        consent = self._manifest(
            {"verified": True, "version": "v2", "authorized_domains": ["CLÍNICO"]}
        )["consent"]
        self.assertIs(consent["verified"], True)
        self.assertEqual(consent["version"], "v2")
        self.assertEqual(consent["authorized_domains"], ["CLÍNICO"])

    def test_the_inputs_carry_provenance_for_the_provenance_gate(self):
        for artifact in self._manifest()["inputs"]:
            for field in ("id", "kind", "source", "sha256"):
                self.assertTrue(artifact.get(field), artifact)
            if artifact.get("transformed"):
                self.assertTrue(artifact.get("parent_sha256"))


if __name__ == "__main__":
    unittest.main()


class OrchestratorAsksTheEngineTest(unittest.TestCase):
    """`run_full_case` had no policy plane at all — the engine could never disagree."""

    def test_the_entrypoint_runs_the_engine_and_threads_its_verdict(self):
        source = (ROOT / "scripts/run_full_case.py").read_text(encoding="utf-8")
        self.assertIn("def evaluate_policy(", source)
        self.assertIn('"genoma_policy", "evaluate"', source)
        # Every builder receives the same evaluation; none composes one.
        for call in ("p05(qc_path, matrix_path, probe_path, policy_path)",
                     "p09(matrix_path, qc_path, policy_path)",
                     "p01(findings_path, matrix_path, qc_path, policy_path)"):
            self.assertIn(call, source)

    def test_the_plaintext_ruleset_is_removed_after_the_evaluation(self):
        source = (ROOT / "scripts/run_full_case.py").read_text(encoding="utf-8")
        self.assertIn("stale.unlink(missing_ok=True)", source)

    def test_consent_is_an_input_the_operator_supplies(self):
        source = (ROOT / "scripts/run_full_case.py").read_text(encoding="utf-8")
        self.assertIn('"--consent"', source)
