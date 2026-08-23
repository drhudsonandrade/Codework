"""What a POST-DEPLOYMENT run certified must be measured, not declared.

The ceremony workflow started a container on the GitHub runner, pointed the smoke at
`127.0.0.1:8787`, and wrote the fixed string "live HTTP execution against a real container
instance" into the evidence. That string was true, and useless: it said exactly the same
thing for a run against a deployed clinical host. A report reading POST-DEPLOYMENT:
VERIFICADO could not distinguish the two, so section 260 was satisfied by a service that
ceased to exist when the CI job ended.

These tests hold three lines:

1. the class is computed from the address the run dialled, so a loopback run records
   loopback whatever its operator intended;
2. a witness that does not say what it certified does not certify anything;
3. a witness whose declared class contradicts its own recorded addresses is refused —
   the class is recomputed on read, not believed.
"""
from __future__ import annotations

import datetime
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import normative
from reporting import deployment_target
from reporting.deployment_target import (
    LOOPBACK,
    PRIVATE,
    PUBLIC,
    UNRESOLVED,
    aggregate,
    authority,
    classify,
    refusal,
)
from reporting.provenance import witness_verdict


class TheTargetClassIsReadOffTheAddressTest(unittest.TestCase):
    def test_loopback_literals_classify_as_loopback(self):
        for url in ("http://127.0.0.1:8787", "http://localhost:8787", "http://[::1]:8787"):
            with self.subTest(url=url):
                self.assertEqual(LOOPBACK, classify(url)["network_class"])

    def test_loopback_is_not_reported_as_a_private_network_host(self):
        """`ipaddress` calls 127.0.0.1 private as well as loopback; the order matters,
        because 'private-network' would read as a deployment behind a firewall."""
        self.assertEqual(LOOPBACK, aggregate(["127.0.0.1"]))

    def test_rfc1918_and_link_local_classify_as_private(self):
        for address in ("10.0.0.4", "192.168.1.10", "172.16.0.1", "169.254.1.1", "fd00::1"):
            with self.subTest(address=address):
                self.assertEqual(PRIVATE, aggregate([address]))

    def test_documentation_ranges_are_not_public_hosts(self):
        """TEST-NET-3 and friends are reserved; nothing is deployed there to certify."""
        for address in ("203.0.113.10", "192.0.2.1", "2001:db8::1"):
            with self.subTest(address=address):
                self.assertNotEqual(PUBLIC, aggregate([address]))

    def test_routable_addresses_classify_as_public(self):
        for address in ("8.8.8.8", "9.9.9.9", "2606:4700::1111"):
            with self.subTest(address=address):
                self.assertEqual(PUBLIC, aggregate([address]))

    def test_a_name_resolving_to_nothing_is_unresolved_not_assumed_local(self):
        self.assertEqual(UNRESOLVED, aggregate([]))
        self.assertEqual(UNRESOLVED, aggregate(["not-an-address"]))

    def test_a_mixed_answer_takes_the_weakest_class(self):
        """Which of several addresses the smoke connected to is not recorded, so the only
        defensible statement is the one that holds whichever it was."""
        self.assertEqual(LOOPBACK, aggregate(["8.8.8.8", "127.0.0.1"]))
        self.assertEqual(PRIVATE, aggregate(["8.8.8.8", "10.0.0.4"]))

    def test_only_public_and_private_count_as_reachable_beyond_this_machine(self):
        self.assertFalse(classify("http://127.0.0.1:8787")["reachable_beyond_this_machine"])

    def test_the_authority_drops_credentials_out_of_the_published_evidence(self):
        """The evidence bundle is uploaded and, on main, committed to a branch."""
        target = classify("https://operator:hunter2@127.0.0.1:8443/v1/ruleset")
        self.assertEqual("https://127.0.0.1:8443", target["authority"])
        self.assertNotIn("hunter2", json.dumps(target))

    def test_the_default_port_comes_from_the_scheme(self):
        self.assertEqual(443, classify("https://127.0.0.1")["port"])
        self.assertEqual(80, classify("http://127.0.0.1")["port"])

    def test_authority_normalises_so_the_same_host_compares_equal(self):
        self.assertEqual(
            authority("http://Localhost:8787/"),
            authority("http://localhost:8787/v1/ruleset"),
        )

    def test_authority_distinguishes_scheme_host_and_port(self):
        base = authority("http://127.0.0.1:8787")
        for other in ("https://127.0.0.1:8787", "http://127.0.0.1:9999", "http://10.0.0.4:8787"):
            with self.subTest(other=other):
                self.assertNotEqual(base, authority(other))


class AWitnessMustSayWhatItCertifiedTest(unittest.TestCase):
    def _witness(self, target) -> dict:
        return {
            "post_deployment_status": "PASS",
            "all_pass": True,
            "bootstrap_verified": True,
            "critical_failures": 0,
            "ruleset": {"sha256": normative.RAW_SHA256},
            "target": target,
            "completed_at": datetime.datetime.now(datetime.timezone.utc)
            .isoformat().replace("+00:00", "Z"),
        }

    def _loopback(self) -> dict:
        return {
            "authority": "http://127.0.0.1:8787",
            "resolved_addresses": ["127.0.0.1"],
            "network_class": LOOPBACK,
        }

    def test_a_witness_naming_its_target_passes(self):
        self.assertEqual("PASS", witness_verdict(self._witness(self._loopback()))["status"])

    def test_a_witness_with_no_target_certifies_nothing(self):
        verdict = witness_verdict(self._witness(None))
        self.assertEqual("PENDENTE", verdict["status"])
        self.assertIn("contêiner efêmero de CI", verdict["basis"])

    def test_the_declared_class_is_recomputed_from_the_recorded_addresses(self):
        """Editing "public-host" into a witness taken against 127.0.0.1 must not survive."""
        forged = self._loopback() | {"network_class": PUBLIC}
        verdict = witness_verdict(self._witness(forged))
        self.assertEqual("PENDENTE", verdict["status"])
        self.assertIn(PUBLIC, verdict["basis"])
        self.assertIn(LOOPBACK, verdict["basis"])

    def test_a_class_outside_the_vocabulary_is_refused(self):
        verdict = witness_verdict(self._witness(self._loopback() | {"network_class": "producao"}))
        self.assertEqual("PENDENTE", verdict["status"])
        self.assertIn("vocabulário", verdict["basis"])

    def test_a_target_with_no_addresses_to_recompute_from_is_refused(self):
        verdict = witness_verdict(self._witness({"network_class": PUBLIC, "authority": "https://x"}))
        self.assertEqual("PENDENTE", verdict["status"])
        self.assertIn("endereços", verdict["basis"])

    def test_the_pass_verdict_carries_the_target_to_whoever_prints_it(self):
        verdict = witness_verdict(self._witness(self._loopback()))
        self.assertEqual(LOOPBACK, verdict["target"]["network_class"])
        self.assertIn(LOOPBACK, verdict["basis"])

    def test_the_layout_fixture_carries_no_target_because_it_contacted_nothing(self):
        verdict = witness_verdict({"post_deployment_status": "PASS", "all_pass": True,
                                   "bootstrap_verified": True, "critical_failures": 0},
                                  fixture=True)
        self.assertEqual("PASS", verdict["status"])
        self.assertIsNone(verdict["target"])
        self.assertIn("nenhuma implantação foi contatada", verdict["basis"])


class TheReportHeaderNamesWhatWasCertifiedTest(unittest.TestCase):
    """A reader meets POST-DEPLOYMENT at the top of the document, as one word.

    Both a CI container and a deployed clinical host produce a truthful PASS, so the bare
    word was the last place the distinction could still be lost.
    """

    def _rendered(self, network_class: str, addresses: list[str], authority_: str) -> str:
        import tempfile

        from reporting.engine import render_document
        from reporting.provenance import Artifact, PayloadCompiler

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from attestations import consent_file
        from test_report_engine import passing_policy_evaluation

        root = Path(tempfile.mkdtemp())
        evaluation = passing_policy_evaluation()
        for gate in ("CONSENT_GATE", "QC_GATE", "EVIDENCE_GATE", "PLACEHOLDER_GATE"):
            evaluation["gates"].append({"gate": gate, "state": "PASS", "blocking": True})
        policy = root / "policy.json"
        policy.write_text(json.dumps(evaluation), encoding="utf-8")
        witness = root / "witness.json"
        witness.write_text(json.dumps({
            "post_deployment_status": "PASS", "all_pass": True, "bootstrap_verified": True,
            "critical_failures": 0, "passed": 15, "total": 15,
            "ruleset": {"sha256": normative.RAW_SHA256},
            "target": {"authority": authority_, "resolved_addresses": addresses,
                       "network_class": network_class},
            "completed_at": datetime.datetime.now(datetime.timezone.utc)
            .isoformat().replace("+00:00", "Z"),
        }), encoding="utf-8")

        compiler = PayloadCompiler(
            case_id="CASO-ALVO", report_id="09", post_deployment_witness=witness,
            policy_evaluation=policy, consent=consent_file(root, case_id="CASO-ALVO"),
        )
        compiler.register(Artifact.from_payload("array-qc", {"metrics": {"call_rate": 0.99}}))
        compiler.derive("summary", artifact="array-qc", locator="metrics.call_rate",
                        status="VERIFICADO", basis="call rate")
        compiler.state("sources", ["array-qc"], kind="case_control", basis="s", status="VERIFICADO")
        compiler.state("limitations", "escopo", kind="case_control", basis="e", status="VERIFICADO")
        rendered = render_document("09", compiler.compile(), mode="FINAL")
        return next(
            line for line in rendered["markdown"].splitlines() if "POST-DEPLOYMENT" in line
        )

    def test_a_loopback_pass_says_so_on_the_header(self):
        header = self._rendered(LOOPBACK, ["127.0.0.1"], "http://127.0.0.1:8787")
        self.assertIn("PASS", header)
        self.assertIn("contêiner efêmero", header)
        self.assertIn("não um host implantado", header)

    def test_a_deployed_host_pass_says_that_instead(self):
        header = self._rendered(PUBLIC, ["8.8.8.8"], "https://genoma.example.org:443")
        self.assertIn("PASS", header)
        self.assertIn("host implantado em endereço público", header)
        self.assertIn("genoma.example.org", header)

    def test_the_two_headers_are_not_the_same_sentence(self):
        self.assertNotEqual(
            self._rendered(LOOPBACK, ["127.0.0.1"], "http://127.0.0.1:8787"),
            self._rendered(PUBLIC, ["8.8.8.8"], "https://genoma.example.org:443"),
        )

    def test_a_pendente_header_is_unchanged_because_there_is_no_target(self):
        from reporting.engine import render_document
        from reporting.provenance import fixture_payload

        data = fixture_payload(case_id="C", report_id="01", summary="s", basis="fixture")
        rendered = render_document("01", data, mode="FINAL")
        self.assertIn("POST-DEPLOYMENT: PENDENTE\n", rendered["markdown"])


class TheHeaderClauseCannotBeImprovedByHandTest(unittest.TestCase):
    """The clause is read from the payload block, not from an anchor, so it needs its own
    check: recompute the class from the addresses the block itself carries."""

    def _payload(self) -> dict:
        from reporting.provenance import fixture_payload

        return fixture_payload(case_id="C", report_id="01", summary="s", basis="fixture",
                               post_deployment_status="PASS")

    def test_a_consistent_target_raises_no_blocker(self):
        from reporting.provenance import provenance_blockers

        data = self._payload()
        data["post_deployment"]["target"] = {
            "authority": "http://127.0.0.1:8787",
            "resolved_addresses": ["127.0.0.1"], "network_class": LOOPBACK,
        }
        self.assertNotIn("provenance:post_deployment_target", provenance_blockers(data))

    def test_promoting_loopback_to_public_host_is_caught(self):
        from reporting.provenance import provenance_blockers

        data = self._payload()
        data["post_deployment"]["target"] = {
            "authority": "http://127.0.0.1:8787",
            "resolved_addresses": ["127.0.0.1"], "network_class": PUBLIC,
        }
        self.assertIn("provenance:post_deployment_target", provenance_blockers(data))


class RefusalReadsRatherThanCrashesTest(unittest.TestCase):
    """`refusal` runs against whatever JSON a witness file happens to hold."""

    def test_non_dict_targets_are_refused_without_raising(self):
        for value in (None, "loopback", 42, [], True):
            with self.subTest(value=value):
                self.assertIsNotNone(refusal(value))

    def test_non_string_addresses_are_refused_without_raising(self):
        self.assertIsNotNone(refusal({"network_class": LOOPBACK, "resolved_addresses": [127]}))

    def test_describe_survives_a_missing_target(self):
        self.assertEqual("alvo não registrado", deployment_target.describe(None))


if __name__ == "__main__":
    unittest.main()
