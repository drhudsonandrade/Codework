"""A POST-DEPLOYMENT witness must satisfy the whole ceremony contract, not four of its parts.

`docs/PRODUCTION_CEREMONY.md` states the condition exactly: "The suite can report PASS only
with `total=15`, `passed=15`, `critical_failures=0`, a verified ruleset-bootstrap attestation
tied to the exact deployment Git SHA, authenticated evidence that the persistent Project
Instructions are installed, `POST_DEPLOYMENT_GATE=PASS`, and `post_deployment_status=PASS`."

`WITNESS_REQUIRED` checked four of those seven. The three it omitted are the ones that say
the suite actually ran: `passed`, `total`, and the installed Project Instructions. A witness
carrying only the four — no case counts at all — was accepted, and the verdict's own basis
string then printed `f"{payload.get('passed')}/{payload.get('total')}"`, asserting "15/15
cases" about numbers it had never required and which could be `None/None`.

This is the artifact the project explicitly refuses to compose for itself, so every condition
gets its own negative control here.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import normative
from reporting import provenance


def _complete_witness() -> dict[str, object]:
    """A witness that satisfies the full documented contract."""
    return {
        "post_deployment_status": "PASS",
        "all_pass": True,
        "bootstrap_verified": True,
        "critical_failures": 0,
        "passed": 15,
        "total": 15,
        "project_bootstrap_installed": True,
        "post_deployment_gate": {"gate": "POST_DEPLOYMENT_GATE", "state": "PASS"},
        "suite": "post-deployment",
        "deployment_id": "deploy-1",
        "target": {"network_class": "public-host", "resolved_addresses": ["93.184.216.34"]},
        "ruleset": {"sha256": normative.RAW_SHA256},
        # Recent, not future: the binding refusal rejects a witness that claims to have
        # completed after now, and a stale one falls outside the freshness window.
        "completed_at": (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat(),
    }


class WitnessContractTest(unittest.TestCase):
    def test_the_complete_witness_passes(self):
        """The accepting case, so the refusals below are not passing vacuously."""
        verdict = provenance.witness_verdict(_complete_witness(), sha256="a" * 64)
        self.assertEqual(verdict["status"], "PASS", verdict.get("basis"))

    def test_the_four_field_witness_that_used_to_pass_is_refused(self):
        """The exact shape the previous contract accepted."""
        verdict = provenance.witness_verdict(
            {
                "post_deployment_status": "PASS",
                "all_pass": True,
                "bootstrap_verified": True,
                "critical_failures": 0,
                "target": {
                    "network_class": "public-host",
                    "resolved_addresses": ["93.184.216.34"],
                },
                "ruleset": {"sha256": normative.RAW_SHA256},
                "completed_at": (
                    datetime.now(timezone.utc) - timedelta(hours=1)
                ).isoformat(),
            },
            sha256="a" * 64,
        )
        self.assertEqual(verdict["status"], "PENDENTE")

    def test_each_contract_field_is_load_bearing_on_its_own(self):
        """Omit one condition at a time; each must be enough to withhold the verdict."""
        for key in provenance.WITNESS_REQUIRED:
            with self.subTest(omitted=key):
                witness = _complete_witness()
                del witness[key]
                verdict = provenance.witness_verdict(witness, sha256="a" * 64)
                self.assertEqual(verdict["status"], "PENDENTE", key)

    def test_a_short_suite_cannot_certify_a_full_one(self):
        """14 of 15 is not the contract, and neither is 15 of 14."""
        for passed, total in ((14, 15), (15, 14), (0, 0)):
            with self.subTest(passed=passed, total=total):
                witness = _complete_witness()
                witness["passed"], witness["total"] = passed, total
                verdict = provenance.witness_verdict(witness, sha256="a" * 64)
                self.assertEqual(verdict["status"], "PENDENTE")

    def test_the_gate_must_be_named_and_passing(self):
        for gate in (
            None,
            {},
            {"gate": "POST_DEPLOYMENT_GATE", "state": "BLOCKED"},
            {"gate": "SOME_OTHER_GATE", "state": "PASS"},
        ):
            with self.subTest(gate=gate):
                witness = _complete_witness()
                witness["post_deployment_gate"] = gate
                verdict = provenance.witness_verdict(witness, sha256="a" * 64)
                self.assertEqual(verdict["status"], "PENDENTE")

    def test_type_confusion_does_not_satisfy_the_counts(self):
        """`True == 1` in Python, so a boolean must not read as a case count."""
        for value in (True, "15", 15.0):
            with self.subTest(passed=value):
                witness = _complete_witness()
                witness["passed"] = value
                verdict = provenance.witness_verdict(witness, sha256="a" * 64)
                self.assertEqual(verdict["status"], "PENDENTE")

    def test_the_basis_only_claims_counts_it_actually_required(self):
        """The PASS basis prints `passed/total`; those are now conditions of reaching it."""
        verdict = provenance.witness_verdict(_complete_witness(), sha256="a" * 64)
        self.assertEqual(verdict["status"], "PASS")
        self.assertIn("15/15", verdict["basis"])


if __name__ == "__main__":
    unittest.main()
