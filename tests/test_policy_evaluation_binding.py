"""Policy Control Plane evaluations are data until re-executed at publication."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_ROOT = ROOT / "policy_engine"
if str(POLICY_ROOT) not in sys.path:
    sys.path.insert(0, str(POLICY_ROOT))

from genoma_policy.engine import PolicyEngine
from genoma_policy.gates_common import CRITICAL_FINAL_AUDIT_KEYS
from genoma_policy.models import evaluation_binding
from genoma_policy.ruleset import load_ruleset
from genoma_policy.scaffold import scaffold_manifest

from reporting.provenance import (
    POLICY_EVALUATION_ARTIFACT,
    REQUIRED_PLANES,
    Artifact,
    PayloadCompiler,
    ProvenanceError,
    fixture_payload,
)
from scripts.materialize_ruleset import materialize
from tests.attestations import consent_file, policy_evaluation_file

INPUT_SHA = "a" * 64


_RULESET_TD = tempfile.TemporaryDirectory()


@lru_cache(maxsize=1)
def _ruleset():
    """Load the canonical ruleset while keeping its verified materialization alive."""
    ruleset_path, _evidence = materialize(Path(_RULESET_TD.name))
    return load_ruleset(ruleset_path)


def _manifest(*, case_id: str = "CASE-1", input_sha256: str = INPUT_SHA) -> dict:
    """A policy manifest that genuinely passes a FINAL_AUDITED_REPORT evaluation."""
    manifest = scaffold_manifest(_ruleset(), case_id=case_id)
    manifest["session_id"] = "SESSION-1"
    manifest["operation"]["output"] = "FINAL_AUDITED_REPORT"
    manifest["inputs"] = [
        {"id": "input-1", "kind": "array", "source": "fixture", "sha256": input_sha256}
    ]
    manifest["consent"] = {
        "verified": True,
        "version": "test-v1",
        "authorized_domains": ["research"],
    }
    manifest["qc"] = {
        "status": "EXECUTADO",
        "passed": True,
        "evidence_refs": ["fixture:qc"],
    }
    manifest["sources"] = [
        {
            "id": "fixture:attestation",
            "mutable": False,
            "status": "VERIFICADO",
            "accessible": True,
            "locator": "fixture://attestation",
            "retrieval_evidence": {"method": "fixture", "result_digest": "sha256:fixture"},
        }
    ]
    for attestation in manifest["section_attestations"]:
        attestation.update(
            {
                "applicability": "NOT_APPLICABLE",
                "status": "VERIFICADO",
                "decision": "NOT_APPLICABLE",
                "justification": "not triggered by this fixture",
                "evidence_refs": [],
            }
        )
        attestation["trace"].update(
            {"run_id": "SESSION-1", "created_at": "2026-08-22T18:46:00-03:00"}
        )
    manifest["final_audit"] = {key: True for key in CRITICAL_FINAL_AUDIT_KEYS}
    return manifest


def real_evaluation(*, case_id: str = "CASE-1", input_sha256: str = INPUT_SHA) -> dict:
    """The exact envelope emitted by the real Policy Control Plane for a passing manifest."""
    report = PolicyEngine(_ruleset()).evaluate(_manifest(case_id=case_id, input_sha256=input_sha256))
    if not report.ready:
        failures = [g.to_dict() for g in report.gates if g.blocking and g.state.value != "PASS"]
        raise AssertionError(f"policy fixture is not actually ready: {failures}")
    return report.to_internal_dict()


def _verdict_for(payload: dict, *, case_id: str = "CASE-1", input_sha256: str = INPUT_SHA):
    """Compile one verdict with a scientific artifact bound to the same primary input."""
    with tempfile.TemporaryDirectory() as td:
        compiler = PayloadCompiler(
            case_id=case_id,
            report_id="01",
            policy_evaluation=policy_evaluation_file(Path(td), payload),
        )
        compiler.register(Artifact.from_payload("subject-input", {"input_sha256": input_sha256}))
        return compiler.policy_verdict()


class PolicyEvaluationBindingTest(unittest.TestCase):
    """Only a re-executed, identity-bound Policy Control verdict may authorize publication."""

    def test_real_engine_output_serializes_required_identity(self):
        evaluation = real_evaluation()
        self.assertEqual(evaluation["schema"], "genoma-policy-evaluation-v2")
        self.assertEqual(evaluation["producer"]["id"], "genoma-policy-engine")
        self.assertTrue(evaluation["producer"]["version"])
        self.assertEqual(evaluation["case_id"], "CASE-1")
        self.assertEqual(evaluation["session_id"], "SESSION-1")
        self.assertEqual(evaluation["input_sha256"], INPUT_SHA)
        self.assertEqual(evaluation["operation"]["output"], "FINAL_AUDITED_REPORT")
        self.assertRegex(evaluation["manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(evaluation["binding"], evaluation_binding(evaluation["evaluated_manifest"]))

    def test_public_evaluation_omits_manifest_and_case_identity(self):
        report = PolicyEngine(_ruleset()).evaluate(_manifest())
        public = report.to_dict()
        self.assertRegex(public["manifest_sha256"], r"^[0-9a-f]{64}$")
        for sensitive in (
            "case_id",
            "session_id",
            "input_sha256",
            "operation",
            "binding",
            "evaluated_manifest",
        ):
            self.assertNotIn(sensitive, public)

    def test_a_genuine_matching_evaluation_is_reexecuted_and_accepted(self):
        verdict = _verdict_for(real_evaluation())
        self.assertTrue(verdict["ready_for_requested_operation"])
        self.assertEqual(verdict["source"]["status"], "VERIFICADO")
        self.assertEqual(verdict["source"]["origin"], "policy-control-reexecution")

    def test_nested_input_hash_binds_consent_and_policy_to_the_same_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            compiler = PayloadCompiler(
                case_id="CASE-1",
                report_id="01",
                policy_evaluation=policy_evaluation_file(root, real_evaluation()),
                consent=consent_file(root, case_id="CASE-1", input_sha256=INPUT_SHA),
            )
            compiler.register(
                Artifact.from_payload("subject-input", {"input": {"sha256": INPUT_SHA}})
            )

            self.assertTrue(compiler.consent_scope()["covers"])
            self.assertTrue(compiler.policy_verdict()["ready_for_requested_operation"])

    def test_fixture_policy_source_is_never_reported_as_verified(self):
        payload = fixture_payload(
            case_id="CASE-1",
            report_id="01",
            summary="fixture",
            basis="layout QA fixture",
        )

        self.assertEqual(payload["policy_evaluation"]["source"]["status"], "NÃO DISPONÍVEL")

    def test_legacy_minimal_hand_written_pass_is_refused(self):
        payload = {
            "ready_for_requested_operation": True,
            "ruleset": {"sha256": _ruleset().sha256},
            "planes": {name: {"state": "PASS"} for name in REQUIRED_PLANES},
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
        }
        verdict = _verdict_for(payload)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertEqual(verdict["source"]["status"], "NÃO DISPONÍVEL")

    def test_complete_manual_pass_with_correct_digest_is_reexecuted_and_refused(self):
        payload = real_evaluation()
        payload["evaluated_manifest"]["qc"]["passed"] = False
        binding = evaluation_binding(payload["evaluated_manifest"])
        payload["binding"] = binding
        for key in ("case_id", "session_id", "input_sha256", "operation", "manifest_sha256"):
            payload[key] = copy.deepcopy(binding[key])
        # The forged PASS bits are deliberately left untouched.  A digest and plausible
        # producer metadata do not make them authority; re-execution must disagree and block.
        self.assertTrue(payload["ready_for_requested_operation"])
        verdict = _verdict_for(payload)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("re-execution", verdict["source"]["reason"])

    def test_cross_case_evaluation_is_not_transferable(self):
        verdict = _verdict_for(real_evaluation(case_id="CASE-OTHER"), case_id="CASE-1")
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("CASE-OTHER", verdict["source"]["reason"])

    def test_cross_input_evaluation_is_not_transferable(self):
        verdict = _verdict_for(real_evaluation(input_sha256="b" * 64), input_sha256=INPUT_SHA)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("input SHA-256", verdict["source"]["reason"])

    def test_missing_session_identity_is_refused_even_with_pass_bits(self):
        payload = real_evaluation()
        payload["evaluated_manifest"]["session_id"] = ""
        binding = evaluation_binding(payload["evaluated_manifest"])
        payload["binding"] = binding
        for key in ("case_id", "session_id", "input_sha256", "operation", "manifest_sha256"):
            payload[key] = copy.deepcopy(binding[key])
        verdict = _verdict_for(payload)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("session_id", verdict["source"]["reason"])

    def test_analysis_operation_cannot_authorize_final_report_publication(self):
        payload = real_evaluation()
        payload["evaluated_manifest"]["operation"]["output"] = "ANALYSIS"
        binding = evaluation_binding(payload["evaluated_manifest"])
        payload["binding"] = binding
        for key in ("case_id", "session_id", "input_sha256", "operation", "manifest_sha256"):
            payload[key] = copy.deepcopy(binding[key])
        verdict = _verdict_for(payload)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("FINAL_AUDITED_REPORT", verdict["source"]["reason"])

    def test_a_non_object_never_reaches_policy_verification(self):
        for payload in ([], "PASS", None, 7):
            with self.subTest(payload=payload):
                with self.assertRaises(ProvenanceError):
                    Artifact.from_payload(POLICY_EVALUATION_ARTIFACT, payload)


if __name__ == "__main__":
    unittest.main()
