"""POST-DEPLOYMENT is a claim about a running service, so a payload may not make it.

Section 260 reserves this verdict for evidence that a *deployed* service behaved correctly.
It reached the payload as a keyword argument on `PayloadCompiler.compile`:

    def compile(self, *, execution_manifest=None, post_deployment_status="PENDENTE", extra=None)

Honest by default, and forgeable by anyone who typed a different string — `compile(...,
post_deployment_status="PASS")` printed POST-DEPLOYMENT PASS on the face of a FINAL report
for a system with no deployment at all. The one verdict the project reserved for external
evidence was, in the payload, whatever the caller chose.

It is now read from a witness file that `scripts/run_live_post_deployment_smoke.py` writes
after driving 15 safety scenarios over HTTP against a live instance. Four conditions must all
hold, the witness must have been taken against this ruleset, and it must be recent — because a
witness with no expiry is a token: run the ceremony once and cite it forever, which is exactly
the inherited PASS section 259 forbids.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative
from reporting.provenance import (
    MAX_WITNESS_AGE_DAYS,
    POST_DEPLOYMENT_WITNESS_ARTIFACT,
    Artifact,
    PayloadCompiler,
    ProvenanceError,
    UNAVAILABLE,
    fixture_payload,
    provenance_blockers,
)

ARTIFACT = {"metrics": {"call_rate": 0.99}}


def witness(**overrides) -> dict:
    """A witness shaped like the one the live smoke run writes."""
    payload = {
        "suite": "GENOMA v3.4 section-260 LIVE post-deployment smoke",
        "classification": "live HTTP execution against a real container instance",
        "deployment_id": "loopback-teste",
        "ruleset": {"version": normative.VERSION, "sha256": normative.RAW_SHA256},
        "bootstrap_verified": True,
        "passed": 15,
        "total": 15,
        "critical_failures": 0,
        "all_pass": True,
        "post_deployment_status": "PASS",
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload.update(overrides)
    return payload


def witness_file(payload: dict) -> Path:
    path = Path(tempfile.mkdtemp()) / "post-deployment-witness.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def compiler(**kwargs) -> PayloadCompiler:
    built = PayloadCompiler(case_id="CASO-PD", report_id="09", **kwargs)
    built.register(Artifact.from_payload("array-qc", ARTIFACT))
    built.derive(
        "summary", artifact="array-qc", locator="metrics.call_rate",
        status="VERIFICADO", basis="call rate",
    )
    built.state("sources", ["array-qc"], kind="case_control", basis="s", status="VERIFICADO")
    built.state("limitations", "escopo", kind="case_control", basis="e", status="VERIFICADO")
    return built


class NoWitnessMeansPendenteTest(unittest.TestCase):
    def test_a_payload_with_no_witness_declares_pendente_and_says_why(self):
        data = compiler().compile()
        self.assertEqual(data["post_deployment_status"], "PENDENTE")
        self.assertEqual(data["post_deployment"]["status"], "PENDENTE")
        self.assertIn("nenhuma testemunha", data["post_deployment"]["basis"])
        self.assertEqual([], provenance_blockers(data))

    def test_compile_no_longer_accepts_a_status_from_its_caller(self):
        """The defect itself: the verdict used to be a string the caller typed."""
        with self.assertRaises(TypeError):
            compiler().compile(post_deployment_status="PASS")

    def test_the_witness_cannot_be_composed_in_memory(self):
        """`register` was the door the first version of the policy fix left open."""
        with self.assertRaises(ProvenanceError) as raised:
            compiler().register(
                Artifact.from_payload(POST_DEPLOYMENT_WITNESS_ARTIFACT, witness())
            )
        self.assertIn("post_deployment_witness=<path>", str(raised.exception))

    def test_extra_cannot_stamp_the_status_onto_a_pendente_payload(self):
        with self.assertRaises(ProvenanceError):
            compiler().compile(extra={"post_deployment_status": "PASS"})

    def test_extra_cannot_supply_the_detail_block_either(self):
        with self.assertRaises(ProvenanceError) as raised:
            compiler().compile(extra={"post_deployment": {"status": "PASS"}})
        self.assertIn("post_deployment", str(raised.exception))


class AWitnessMustCarryItsOwnEvidenceTest(unittest.TestCase):
    def test_a_complete_witness_grants_pass_and_names_its_hash(self):
        path = witness_file(witness())
        data = compiler(post_deployment_witness=path).compile()
        self.assertEqual(data["post_deployment_status"], "PASS")
        self.assertEqual(data["post_deployment"]["origin"], "live-deployment-witness")
        self.assertEqual(
            data["post_deployment"]["witness_sha256"],
            data["artifacts"][POST_DEPLOYMENT_WITNESS_ARTIFACT]["sha256"],
        )
        # The printed verdict is anchored to the witness by locator, so the report names the
        # document that says PASS rather than merely agreeing with it.
        anchor = data["provenance"]["fields"]["post_deployment_status"]
        self.assertEqual(anchor["artifact"], POST_DEPLOYMENT_WITNESS_ARTIFACT)
        self.assertEqual(anchor["locator"], "post_deployment_status")
        self.assertEqual(anchor["observed_value"], "PASS")
        self.assertEqual([], provenance_blockers(data))

    def test_each_required_condition_is_checked_individually(self):
        """`all(...)` over a truncated dict is True; each key is named on its own."""
        for key, bad in (
            ("post_deployment_status", "FAIL"),
            ("all_pass", False),
            ("bootstrap_verified", False),
            ("critical_failures", 3),
        ):
            with self.subTest(key=key):
                path = witness_file(witness(**{key: bad}))
                data = compiler(post_deployment_witness=path).compile()
                self.assertEqual(data["post_deployment_status"], "PENDENTE")
                self.assertIn(key, data["post_deployment"]["basis"])

    def test_a_witness_missing_a_condition_entirely_does_not_pass_by_omission(self):
        payload = witness()
        del payload["bootstrap_verified"]
        path = witness_file(payload)
        data = compiler(post_deployment_witness=path).compile()
        self.assertEqual(data["post_deployment_status"], "PENDENTE")
        self.assertIn("bootstrap_verified", data["post_deployment"]["basis"])

    def test_a_pendente_payload_records_the_witness_it_refused(self):
        path = witness_file(witness(all_pass=False))
        data = compiler(post_deployment_witness=path).compile()
        self.assertTrue(data["post_deployment"]["witness_sha256"])


class AWitnessIsBoundToThisDeploymentTest(unittest.TestCase):
    """Four PASS conditions say the run succeeded, not what it ran against or when."""

    def test_a_witness_taken_against_another_ruleset_is_refused(self):
        path = witness_file(witness(ruleset={"version": "v3.1", "sha256": "0" * 64}))
        data = compiler(post_deployment_witness=path).compile()
        self.assertEqual(data["post_deployment_status"], "PENDENTE")
        self.assertIn("implantações distintas", data["post_deployment"]["basis"])

    def test_a_witness_with_no_ruleset_block_is_refused(self):
        payload = witness()
        del payload["ruleset"]
        data = compiler(post_deployment_witness=witness_file(payload)).compile()
        self.assertEqual(data["post_deployment_status"], "PENDENTE")

    def test_a_stale_witness_is_refused_by_section_259(self):
        old = datetime.now(timezone.utc) - timedelta(days=MAX_WITNESS_AGE_DAYS + 1)
        path = witness_file(witness(completed_at=old.isoformat().replace("+00:00", "Z")))
        data = compiler(post_deployment_witness=path).compile()
        self.assertEqual(data["post_deployment_status"], "PENDENTE")
        self.assertIn("259", data["post_deployment"]["basis"])

    def test_a_witness_inside_the_window_still_certifies(self):
        recent = datetime.now(timezone.utc) - timedelta(days=MAX_WITNESS_AGE_DAYS - 1)
        path = witness_file(witness(completed_at=recent.isoformat().replace("+00:00", "Z")))
        data = compiler(post_deployment_witness=path).compile()
        self.assertEqual(data["post_deployment_status"], "PASS")

    def test_a_witness_dated_in_the_future_is_refused(self):
        ahead = datetime.now(timezone.utc) + timedelta(days=2)
        path = witness_file(witness(completed_at=ahead.isoformat().replace("+00:00", "Z")))
        data = compiler(post_deployment_witness=path).compile()
        self.assertEqual(data["post_deployment_status"], "PENDENTE")
        self.assertIn("futuro", data["post_deployment"]["basis"])

    def test_an_unreadable_timestamp_is_refused_rather_than_ignored(self):
        for bad in (None, "", "ontem", 17):
            with self.subTest(completed_at=bad):
                data = compiler(
                    post_deployment_witness=witness_file(witness(completed_at=bad))
                ).compile()
                self.assertEqual(data["post_deployment_status"], "PENDENTE")

    def test_the_window_is_measured_against_the_clock_not_the_file(self):
        """A witness valid today is refused once the window has passed."""
        path = witness_file(witness())
        later = datetime.now(timezone.utc) + timedelta(days=MAX_WITNESS_AGE_DAYS + 2)
        with mock.patch("reporting.provenance._now", return_value=later):
            data = compiler(post_deployment_witness=path).compile()
        self.assertEqual(data["post_deployment_status"], "PENDENTE")


class TheHeaderAndTheBlockMustAgreeTest(unittest.TestCase):
    def test_editing_the_printed_status_is_caught(self):
        data = compiler(post_deployment_witness=witness_file(witness())).compile()
        data["post_deployment_status"] = "PENDENTE"
        self.assertIn(
            "provenance:mismatch:post_deployment_status", provenance_blockers(data)
        )

    def test_editing_the_detail_block_is_caught(self):
        data = compiler(post_deployment_witness=witness_file(witness())).compile()
        data["post_deployment"]["status"] = "PENDENTE"
        self.assertIn(
            "provenance:post_deployment_disagreement", provenance_blockers(data)
        )

    def test_stamping_pass_onto_a_pendente_payload_is_caught(self):
        data = compiler().compile()
        data["post_deployment_status"] = "PASS"
        data["post_deployment"]["status"] = "PASS"
        self.assertIn(
            "provenance:mismatch:post_deployment_status", provenance_blockers(data)
        )


class TheEngineIsToldWhatTheReportPrintsTest(unittest.TestCase):
    """POST_DEPLOYMENT_GATE reads `manifest["post_deployment"]`, a key nothing wrote.

    The case manifest carried a top-level `post_deployment_status: "PENDING"` string beside a
    gate that reads a different key entirely, so the gate reported unmet criteria on every run
    regardless of evidence and the string next to it was decoration. Feeding the gate the block
    the live run was actually judged on is what lets the engine and the report agree.
    """

    def _manifest(self, witness_payload=None):
        from scripts.build_array_case_manifest import build_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            qc_path, annotation_path = root / "qc.json", root / "annotation.json"
            qc = {
                "case_id": "CASO-PD", "operational_status": "VERIFICADO",
                "gates": {"LIMITED_INTERPRETATION_GATE": {"state": "PASS"}},
                "input": {"sha256": "a" * 64, "build": "GRCh37", "strand": "forward",
                          "schema": "harmonized_genera_myheritage_v1"},
                "metrics": {"unique_rsids": 10, "call_rate": 0.99}, "limitations": [],
            }
            annotation = {
                "case_id": "CASO-PD", "input_sha256": "a" * 64, "mode": "plan-only",
                "operational_status": "PROPOSTO", "evidence_gate": {"state": "BLOCKED"},
                "observations": [], "evidence_retrievals": [], "limitations": [],
            }
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
            return build_manifest(
                qc, annotation, qc_path, annotation_path, witness=witness_payload
            )

    def test_no_witness_declares_no_claim_at_all(self):
        manifest = self._manifest()
        self.assertEqual(manifest["post_deployment_status"], "PENDING")
        self.assertNotIn("post_deployment", manifest)

    def test_a_live_witness_submits_the_block_the_live_gate_ruled_on(self):
        claim = {
            "single_active_ruleset": True, "bootstrap_installed": True,
            "live_smoke_passed": True, "live_smoke_count": 15,
            "critical_failures": 0, "identity_recovered": normative.IDENTITY_STRING,
        }
        manifest = self._manifest(witness(post_deployment_claim=claim))
        self.assertEqual(manifest["post_deployment_status"], "PASS")
        self.assertEqual(manifest["post_deployment"], claim)

    def test_a_witness_that_does_not_hold_up_submits_nothing(self):
        claim = {"single_active_ruleset": True, "bootstrap_installed": True}
        for broken in (
            witness(all_pass=False, post_deployment_claim=claim),
            witness(ruleset={"version": "v3.1", "sha256": "0" * 64}, post_deployment_claim=claim),
            witness(completed_at="ontem", post_deployment_claim=claim),
        ):
            with self.subTest(basis=broken.get("completed_at")):
                manifest = self._manifest(broken)
                self.assertEqual(manifest["post_deployment_status"], "PENDING")
                self.assertNotIn("post_deployment", manifest)

    def test_a_passing_witness_with_no_claim_block_submits_nothing(self):
        """The verdict is not the claim: without the block there is nothing to submit."""
        manifest = self._manifest(witness())
        self.assertEqual(manifest["post_deployment_status"], "PENDING")
        self.assertNotIn("post_deployment", manifest)

    def test_the_engine_and_the_report_judge_the_witness_with_one_function(self):
        import scripts.build_array_case_manifest as builder
        from reporting import provenance

        self.assertIs(builder.witness_verdict, provenance.witness_verdict)


class LayoutQaMayRenderThePassFaceWithoutClaimingItTest(unittest.TestCase):
    """Visual QA has to measure both faces of the header. It may print, not assert."""

    def test_the_fixture_pass_face_is_anchored_as_a_fixture(self):
        data = fixture_payload(
            case_id="QA", report_id="09", summary="s", basis="fixture", post_deployment_status="PASS",
        )
        self.assertEqual(data["post_deployment_status"], "PASS")
        self.assertEqual(data["post_deployment"]["origin"], "fixture")
        anchor = data["provenance"]["fields"]["post_deployment_status"]
        self.assertEqual(anchor["kind"], "fixture")
        self.assertEqual(anchor["operational_status"], UNAVAILABLE)
        self.assertEqual(data["operational_status"], UNAVAILABLE)
        self.assertEqual([], provenance_blockers(data))

    def test_the_fixture_basis_does_not_claim_a_live_bootstrap(self):
        data = fixture_payload(
            case_id="QA", report_id="09", summary="s", basis="fixture", post_deployment_status="PASS",
        )
        basis = data["provenance"]["fields"]["post_deployment_status"]["basis"]
        self.assertIn("nenhuma implantação foi contatada", basis)
        self.assertNotIn("bootstrap verificado ao vivo", basis)

    def test_a_fixture_may_not_invent_a_third_face(self):
        with self.assertRaises(ProvenanceError):
            fixture_payload(
                case_id="QA", report_id="09", summary="s", basis="fixture",
                post_deployment_status="VERIFICADO",
            )

    def test_a_fixture_witness_cannot_sit_beside_a_measured_value(self):
        built = compiler()  # `summary` is derived from a real artifact
        built._install_witness(
            Artifact.from_payload(POST_DEPLOYMENT_WITNESS_ARTIFACT, witness()), fixture=True
        )
        with self.assertRaises(ProvenanceError):
            built.compile()


if __name__ == "__main__":
    unittest.main()
