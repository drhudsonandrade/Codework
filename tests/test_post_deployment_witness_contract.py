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
        # The structured evidence the two booleans above summarise. `bootstrap_verified: true`
        # is a self-declaration; this is what the live smoke actually recorded, including
        # which commit was deployed.
        "bootstrap_attestation_sha256": "b" * 64,
        "bootstrap_verification": {
            "status": "VERIFICADO",
            "file_sha256": "b" * 64,
            "source_commit_sha": "c" * 40,
        },
        "project_instructions_attestation_sha256": "d" * 64,
        "project_instructions_verification": {
            "status": "VERIFICADO",
            "file_sha256": "d" * 64,
        },
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


class WitnessNamesTheDeploymentItVerifiedTest(unittest.TestCase):
    """`bootstrap_verified: true` is a claim; the commit it was verified against is a fact.

    The ceremony contract asks for "a verified ruleset-bootstrap attestation tied to the exact
    deployment Git SHA" and "authenticated evidence that the persistent Project Instructions
    are installed". Both arrived here as bare booleans, so a witness taken against one
    deployment certified any other with the same ruleset, target class and freshness window —
    the two conditions that name *which* deployment were the two reduced to `true`.

    `scripts/run_live_post_deployment_smoke.py` already writes the structured evidence:
    `bootstrap_verification` carries the `source_commit_sha` that
    `scripts/bootstrap_attestation.verify_bootstrap_attestation` resolved, and
    `project_instructions_verification` carries the attestation's own digest. Nothing read
    them.

    **What this does not do.** It binds; it does not authenticate. A caller able to write the
    witness can write a well-formed SHA into it, and this repository has no signing scheme to
    tell a witness the deployment produced from one composed afterwards. That is recorded in
    the PR as an open design question rather than improvised, for the same reason as the
    policy-evaluation binding. What it removes is the *transfer*: a witness must now name the
    commit it verified, and a boolean can no longer disagree with the evidence beside it.
    """

    def test_the_bound_witness_passes(self):
        """The accepting case, so the refusals below are not passing vacuously."""
        verdict = provenance.witness_verdict(_complete_witness(), sha256="a" * 64)
        self.assertEqual(verdict["status"], "PASS", verdict.get("basis"))

    def test_a_witness_with_no_bootstrap_verification_at_all_is_refused(self):
        """The block itself missing: the boolean has nothing to agree with."""
        for verification in (None, {}, "VERIFICADO", []):
            with self.subTest(bootstrap_verification=verification):
                witness = _complete_witness()
                witness["bootstrap_verification"] = verification
                verdict = provenance.witness_verdict(witness, sha256="a" * 64)
                self.assertEqual(verdict["status"], "PENDENTE")
                self.assertIn("bootstrap_verification", verdict["basis"])

    def test_a_witness_that_names_no_deployed_commit_is_refused(self):
        """The block present and verified, but silent about which commit it verified."""
        for verification in (
            {"status": "VERIFICADO", "file_sha256": "b" * 64},
            {"status": "VERIFICADO", "file_sha256": "b" * 64, "source_commit_sha": None},
            {"status": "VERIFICADO", "file_sha256": "b" * 64, "source_commit_sha": ""},
        ):
            with self.subTest(bootstrap_verification=verification):
                witness = _complete_witness()
                witness["bootstrap_verification"] = verification
                verdict = provenance.witness_verdict(witness, sha256="a" * 64)
                self.assertEqual(verdict["status"], "PENDENTE")
                self.assertIn("commit", verdict["basis"])

    def test_a_commit_that_is_not_a_git_sha_is_not_a_commit(self):
        """`UNKNOWN`, a short SHA and an uppercase one are the shapes that show up."""
        for value in ("UNKNOWN", "c" * 39, "c" * 41, ("C" * 40), "not-a-sha", 40, True):
            with self.subTest(source_commit_sha=value):
                witness = _complete_witness()
                witness["bootstrap_verification"] = {
                    "status": "VERIFICADO",
                    "file_sha256": "b" * 64,
                    "source_commit_sha": value,
                }
                verdict = provenance.witness_verdict(witness, sha256="a" * 64)
                self.assertEqual(verdict["status"], "PENDENTE")

    def test_the_boolean_may_not_disagree_with_the_evidence_beside_it(self):
        """`bootstrap_verified: true` beside a verification that did not verify."""
        for status in ("PENDENTE", "NÃO DISPONÍVEL", "FAIL", None):
            with self.subTest(status=status):
                witness = _complete_witness()
                witness["bootstrap_verification"] = {
                    "status": status,
                    "file_sha256": "b" * 64,
                    "source_commit_sha": "c" * 40,
                }
                verdict = provenance.witness_verdict(witness, sha256="a" * 64)
                self.assertEqual(verdict["status"], "PENDENTE")

    def test_the_attestation_digest_must_match_the_file_the_witness_names(self):
        """Two fields for the same file; if they differ, one of them is about something else."""
        witness = _complete_witness()
        witness["bootstrap_verification"] = {
            "status": "VERIFICADO",
            "file_sha256": "e" * 64,
            "source_commit_sha": "c" * 40,
        }
        verdict = provenance.witness_verdict(witness, sha256="a" * 64)
        self.assertEqual(verdict["status"], "PENDENTE")

    def test_the_project_instructions_evidence_is_required_the_same_way(self):
        """`project_bootstrap_installed: true` gets the same treatment as the bootstrap flag."""
        for verification in (
            None,
            {},
            {"status": "PENDENTE", "file_sha256": "d" * 64},
            {"status": "VERIFICADO", "file_sha256": "f" * 64},
        ):
            with self.subTest(project_instructions_verification=verification):
                witness = _complete_witness()
                witness["project_instructions_verification"] = verification
                verdict = provenance.witness_verdict(witness, sha256="a" * 64)
                self.assertEqual(verdict["status"], "PENDENTE")

    def test_the_verdict_carries_the_commit_it_certified(self):
        """A reader must be able to tell which deployment this PASS is about."""
        verdict = provenance.witness_verdict(_complete_witness(), sha256="a" * 64)
        self.assertEqual("c" * 40, verdict["deployment_commit_sha"])
        self.assertIn("c" * 40, verdict["basis"])

    def test_the_layout_fixture_is_still_exempt_and_says_so(self):
        """QA renders the PASS face without a deployment; it must not claim a commit."""
        verdict = provenance.witness_verdict(
            {
                **{key: value for key, value in WITNESS_REQUIRED_ITEMS},
                "post_deployment_gate": {"gate": "POST_DEPLOYMENT_GATE", "state": "PASS"},
            },
            sha256="a" * 64,
            fixture=True,
        )
        self.assertEqual(verdict["status"], "PASS")
        self.assertIsNone(verdict["deployment_commit_sha"])
        self.assertIn("nenhuma implantação foi contatada", verdict["basis"])


    def test_the_live_smoke_writes_every_field_this_verdict_now_requires(self):
        """Producer and gate are a pair: a gate demanding a field nobody writes is dead.

        Asserted against the source rather than by running the smoke, which needs a live
        deployment. What it establishes is that the new conditions read fields
        `scripts/run_live_post_deployment_smoke.py` already emits — the binding reads
        evidence that exists, rather than inventing a schema the producer would have to be
        taught.
        """
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "run_live_post_deployment_smoke.py"
        ).read_text(encoding="utf-8")
        for field in (
            '"bootstrap_verification": bootstrap_evidence,',
            '"bootstrap_attestation_sha256": bootstrap_evidence["file_sha256"],',
            '"project_instructions_verification": project_snapshot_evidence,',
            '"project_instructions_attestation_sha256": project_snapshot_evidence["file_sha256"],',
        ):
            with self.subTest(field=field):
                self.assertIn(field, source)
        # And the commit itself comes from the attestation verifier, not from the CLI.
        attestation = (
            Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_attestation.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"source_commit_sha": recorded_source_revision,', attestation)


WITNESS_REQUIRED_ITEMS = tuple(provenance.WITNESS_REQUIRED.items())


if __name__ == "__main__":
    unittest.main()
