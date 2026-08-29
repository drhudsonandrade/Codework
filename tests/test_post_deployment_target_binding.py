"""A POST-DEPLOYMENT witness must name what it reached, and reaching itself is not enough.

`deployment_target` computed a network class and even recorded
`reachable_beyond_this_machine`, but nothing enforced it: `refusal` only checked that the
declared class matched the addresses the witness itself recorded. A run against 127.0.0.1
was internally coherent, so it passed, and certified POST-DEPLOYMENT for a service nobody
but the verifier could reach. The producer, meanwhile, wrote no `target` block at all.
"""
from __future__ import annotations

import unittest

from reporting import deployment_target


def _target(addresses: list[str]) -> dict[str, object]:
    """A witness target block that is internally honest about its own addresses."""
    return {
        "network_class": deployment_target.aggregate(addresses),
        "resolved_addresses": addresses,
    }


class DeploymentTargetRefusalTest(unittest.TestCase):
    def test_a_witness_without_a_target_is_refused(self):
        self.assertIsNotNone(deployment_target.refusal(None))
        self.assertIsNotNone(deployment_target.refusal("loopback"))

    def test_loopback_cannot_certify_a_deployment(self):
        refusal = deployment_target.refusal(_target(["127.0.0.1"]))
        self.assertIsNotNone(refusal)
        self.assertIn("PENDENTE", refusal)

    def test_unresolved_cannot_certify_a_deployment(self):
        refusal = deployment_target.refusal(_target([]))
        self.assertIsNotNone(refusal)
        self.assertIn("PENDENTE", refusal)

    def test_reachable_classes_pass_this_particular_gate(self):
        for addresses in (["10.0.0.5"], ["93.184.216.34"]):
            with self.subTest(addresses=addresses):
                self.assertIsNone(deployment_target.refusal(_target(addresses)))

    def test_a_tampered_network_class_is_refused(self):
        """Claiming a reachable class over loopback addresses must not buy a PASS."""
        tampered = {"network_class": "public-host", "resolved_addresses": ["127.0.0.1"]}
        refusal = deployment_target.refusal(tampered)
        self.assertIsNotNone(refusal)
        self.assertIn("classificam como", refusal)

    def test_every_refusable_class_is_covered_by_the_reachability_rule(self):
        """The rule is expressed over the vocabulary, not over a hardcoded pair."""
        for network_class in deployment_target.NETWORK_CLASSES:
            with self.subTest(network_class=network_class):
                reachable = network_class in deployment_target.REACHABLE_BEYOND_THIS_MACHINE
                self.assertEqual(
                    reachable,
                    network_class in (deployment_target.PRIVATE, deployment_target.PUBLIC),
                )


class WitnessProducerRecordsTargetTest(unittest.TestCase):
    def test_the_live_smoke_records_the_target_it_ran_against(self):
        """Producer and gate are a pair: a gate demanding a field nobody writes is dead.

        Asserted against the source rather than by running the smoke, which needs a live
        deployment; the point is that the field is populated from `classify(base_url)` and
        not from a constant or the CLI's own `--deployment-id`.
        """
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "run_live_post_deployment_smoke.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from reporting import deployment_target", source)
        self.assertIn('"target": deployment_target.classify(args.base_url)', source)


if __name__ == "__main__":
    unittest.main()
