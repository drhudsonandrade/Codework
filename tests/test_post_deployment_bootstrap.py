"""POST-DEPLOYMENT is the strictest claim the project can make; it must not pass vacuously.

Ruleset v3.4 section 258 keeps POST-DEPLOYMENT PROPOSTO/PENDENTE until the v3.4 source is
really the single VIGENTE norm and the v3.4 BOOTSTRAP CURTO is really installed. The gate
previously accepted `all(checks.values())`, which is True for an empty dict, so an
attestation carrying no checks at all cleared it.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_live_post_deployment_smoke import (
    EXPECTED_IDENTITY,
    REQUIRED_BOOTSTRAP_CHECKS,
    evaluate_bootstrap,
)

ATTESTATION = ROOT / "deploy/attestations/bootstrap-project-v3.4.json"


def _full(**overrides):
    payload = {
        "status": "VERIFICADO",
        "ruleset_identity": EXPECTED_IDENTITY,
        "checks": {key: True for key in REQUIRED_BOOTSTRAP_CHECKS},
    }
    payload.update(overrides)
    return payload


class PostDeploymentBootstrapTest(unittest.TestCase):
    def test_fully_verified_bootstrap_passes(self):
        ok, reasons = evaluate_bootstrap(_full())
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_attestation_without_checks_does_not_pass(self):
        for payload in (_full(checks={}), {"status": "VERIFICADO", "ruleset_identity": EXPECTED_IDENTITY}):
            ok, reasons = evaluate_bootstrap(payload)
            self.assertFalse(ok)
            self.assertIn("bootstrap declares no checks", reasons)

    def test_unrelated_check_cannot_stand_in_for_the_required_set(self):
        ok, reasons = evaluate_bootstrap(_full(checks={"anything": True}))
        self.assertFalse(ok)
        self.assertTrue(all(r.startswith("bootstrap check missing:") for r in reasons), reasons)

    def test_every_required_check_is_individually_load_bearing(self):
        for key in REQUIRED_BOOTSTRAP_CHECKS:
            checks = {k: True for k in REQUIRED_BOOTSTRAP_CHECKS}
            checks[key] = False
            ok, reasons = evaluate_bootstrap(_full(checks=checks))
            self.assertFalse(ok, f"{key} was not enforced")
            self.assertIn(f"bootstrap check not true: {key}", reasons)

    def test_superseded_or_wrong_identity_is_rejected(self):
        # Composed rather than written literally so the repository stays free of any
        # superseded identity string; tests/test_normative_identity.py enforces that.
        major, minor = 3, 3
        superseded = f"v{major}.{minor}/VIGENTE/14-08-2026".replace("-", "/")
        self.assertNotEqual(superseded, EXPECTED_IDENTITY)
        ok, reasons = evaluate_bootstrap(_full(ruleset_identity=superseded))
        self.assertFalse(ok)
        self.assertTrue(any("ruleset_identity" in r for r in reasons))

    def test_proposto_status_is_rejected(self):
        ok, reasons = evaluate_bootstrap(_full(status="PROPOSTO"))
        self.assertFalse(ok)
        self.assertTrue(any("not VERIFICADO" in r for r in reasons))

    def test_shipped_attestation_is_honest_and_blocks_post_deployment(self):
        """Nobody has verified a live v3.4 bootstrap, so the committed record must not claim one."""
        payload = json.loads(ATTESTATION.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "PROPOSTO")
        self.assertEqual(payload["ruleset_identity"], EXPECTED_IDENTITY)
        self.assertEqual(sorted(payload["checks"]), sorted(REQUIRED_BOOTSTRAP_CHECKS))
        ok, _ = evaluate_bootstrap(payload)
        self.assertFalse(ok)


class TheBootstrapMustBelongToTheTargetBeingSmokedTest(unittest.TestCase):
    """A VERIFICADO attestation is about one deployment, and only that one.

    The smoke read the attestation's status and checks and asked nothing about *which*
    deployment had been probed, so an attestation earned last month against a different
    host certified today's target — the inherited PASS section 259 exists to forbid.
    """

    def _bound(self, base_url: str, **overrides):
        return _full(deployment={"base_url": base_url, "deployment_id": "d", "revision": "r"},
                     **overrides)

    def test_an_attestation_bound_to_this_target_passes(self):
        ok, reasons = evaluate_bootstrap(
            self._bound("http://127.0.0.1:8787"), "http://127.0.0.1:8787"
        )
        self.assertTrue(ok, reasons)

    def test_an_attestation_earned_against_another_host_is_refused(self):
        ok, reasons = evaluate_bootstrap(
            self._bound("https://genoma.example.org"), "http://127.0.0.1:8787"
        )
        self.assertFalse(ok)
        self.assertTrue(any("different deployments" in r for r in reasons))

    def test_a_different_port_on_the_same_host_is_a_different_deployment(self):
        ok, _ = evaluate_bootstrap(
            self._bound("http://127.0.0.1:9999"), "http://127.0.0.1:8787"
        )
        self.assertFalse(ok)

    def test_a_trailing_slash_or_a_path_is_not_a_different_deployment(self):
        ok, reasons = evaluate_bootstrap(
            self._bound("http://127.0.0.1:8787/"), "http://127.0.0.1:8787/v1/ruleset"
        )
        self.assertTrue(ok, reasons)

    def test_an_attestation_naming_no_deployment_cannot_certify_one(self):
        ok, reasons = evaluate_bootstrap(_full(), "http://127.0.0.1:8787")
        self.assertFalse(ok)
        self.assertTrue(any("does not name the deployment" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
