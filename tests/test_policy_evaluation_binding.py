"""A registered file is not a policy verdict just because a caller pointed at it.

`PayloadCompiler.policy_verdict()` copied `ready_for_requested_operation`, the plane states
and the gate list out of whatever JSON `--policy-evaluation` named, recorded that file's
SHA-256 beside them, and labelled the result `origin: policy-engine-output` with
`status: VERIFICADO`. Nothing checked which ruleset the evaluation judged or which case it
belonged to. So a hand-written object with four PASS planes and one `true` became publication
authority, and a real evaluation produced for one case authorised every other.

The hash never helped: it is computed from the file after reading it, so it proves the file
was read, not where it came from.

What these tests pin is the binding, not authorship. A caller able to write the file can copy
the ruleset hash too — proving origin needs a signing scheme this repository does not have,
and that is recorded in the PR as an open design question rather than improvised. The binding
still removes the trivial forgery and the cross-case reuse.
"""
from __future__ import annotations

import unittest

import normative
from reporting.provenance import (
    POLICY_EVALUATION_ARTIFACT,
    REQUIRED_PLANES,
    Artifact,
    PayloadCompiler,
)


def _evaluation(**overrides):
    """A bound evaluation of the shape the real engine emits."""
    payload = {
        "ready_for_requested_operation": True,
        "ruleset": {"sha256": normative.RAW_SHA256},
        "planes": {name: {"state": "PASS"} for name in REQUIRED_PLANES},
        "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
    }
    payload.update(overrides)
    return payload


def _verdict_for(payload, *, case_id="CASE-1"):
    """The verdict a compiler reaches for this policy evaluation."""
    compiler = PayloadCompiler(case_id=case_id, report_id="01")
    compiler._install_verdict(
        Artifact.from_payload(POLICY_EVALUATION_ARTIFACT, payload)
    )
    return compiler.policy_verdict()


class PolicyEvaluationBindingTest(unittest.TestCase):
    """What binds a policy evaluation to the case and ruleset it may authorise."""
    def test_a_bound_evaluation_is_accepted(self):
        """The accepting case, so the refusals below are not passing vacuously."""
        verdict = _verdict_for(_evaluation())
        self.assertTrue(verdict["ready_for_requested_operation"])
        self.assertEqual(verdict["source"]["status"], "VERIFICADO")

    def test_the_minimal_hand_written_object_is_refused(self):
        """Exactly the shape that used to become publication authority."""
        verdict = _verdict_for(
            {
                "ready_for_requested_operation": True,
                "planes": {name: {"state": "PASS"} for name in REQUIRED_PLANES},
                "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
            }
        )
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertEqual(verdict["source"]["status"], "NÃO DISPONÍVEL")
        self.assertIn("ruleset", verdict["source"]["reason"])

    def test_an_evaluation_for_another_ruleset_does_not_authorise_this_one(self):
        """An evaluation for another ruleset does not authorise this one."""
        verdict = _verdict_for(_evaluation(ruleset={"sha256": "b" * 64}))
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertEqual(verdict["source"]["status"], "NÃO DISPONÍVEL")

    def test_an_evaluation_for_another_case_is_not_transferable(self):
        """A real, correctly-bound evaluation still belongs to the case it judged."""
        verdict = _verdict_for(_evaluation(case_id="CASE-OTHER"), case_id="CASE-1")
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("CASE-OTHER", verdict["source"]["reason"])

    def test_an_evaluation_naming_this_case_is_accepted(self):
        """An evaluation naming this case is accepted."""
        verdict = _verdict_for(_evaluation(case_id="CASE-1"), case_id="CASE-1")
        self.assertTrue(verdict["ready_for_requested_operation"])

    def test_an_empty_evaluation_object_is_refused(self):
        """An empty evaluation object is refused rather than read as no objection."""
        verdict = _verdict_for({})
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertEqual(verdict["source"]["status"], "NÃO DISPONÍVEL")

    def test_a_non_object_never_reaches_the_verdict_at_all(self):
        """Registration refuses it first, which is the earlier and better place.

        Asserted rather than assumed: `policy_verdict` is written to cope with a non-dict
        payload, but `Artifact.from_payload` rejects one before it can arrive. Both layers
        are meant to hold, and a test that only exercised the later one would not notice if
        the earlier guard were removed.
        """
        from reporting.provenance import ProvenanceError

        for payload in ([], "PASS", None, 7):
            with self.subTest(payload=payload):
                with self.assertRaises(ProvenanceError):
                    Artifact.from_payload(POLICY_EVALUATION_ARTIFACT, payload)

    def test_a_refusal_blocks_every_plane_rather_than_passing_some_through(self):
        """A partial refusal would let a forged evaluation still tilt the payload."""
        verdict = _verdict_for(_evaluation(ruleset={"sha256": "c" * 64}))
        self.assertEqual(
            {name: {"state": "BLOCKED"} for name in REQUIRED_PLANES}, verdict["planes"]
        )


if __name__ == "__main__":
    unittest.main()
