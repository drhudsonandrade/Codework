from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.governance_context_identity import (
    context_digest,
    expected_check_is_well_formed,
    match_expected_check,
    materialize_ruleset_spec,
)

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_CONTEXT = bytes.fromhex(
    "73656375726974792f736e796b20286472687564736f6e616e647261646529"
).decode("ascii")
ACCOUNT_CONTEXT_SHA256 = "13148c18c6ce9155ee89d2c0de0435a9ff86e658bc56851d2a8ec24062134bf7"


class GovernanceContextIdentityTest(unittest.TestCase):
    def test_context_digest_is_exact_sha256(self) -> None:
        self.assertEqual(context_digest(ACCOUNT_CONTEXT), ACCOUNT_CONTEXT_SHA256)

    def test_literal_context_matches_exactly(self) -> None:
        expected = {"context": "static"}
        self.assertTrue(match_expected_check({"context": "static"}, expected))
        self.assertFalse(match_expected_check({"context": "STATIC"}, expected))

    def test_fingerprint_context_matches_without_persisting_plaintext(self) -> None:
        expected = {
            "context_fingerprint": {
                "algorithm": "sha256",
                "digest": ACCOUNT_CONTEXT_SHA256,
                "case_sensitive": True,
                "provider_family": "dependency-security",
            }
        }
        self.assertTrue(match_expected_check({"context": ACCOUNT_CONTEXT}, expected))
        self.assertFalse(match_expected_check({"context": ACCOUNT_CONTEXT + "x"}, expected))

    def test_fingerprint_identity_rejects_any_simultaneous_context_key(self) -> None:
        fingerprint = {
            "algorithm": "sha256",
            "digest": ACCOUNT_CONTEXT_SHA256,
            "case_sensitive": True,
            "provider_family": "dependency-security",
        }
        for invalid_context in ("", None, 123):
            with self.subTest(context=invalid_context):
                expected = {
                    "context": invalid_context,
                    "context_fingerprint": dict(fingerprint),
                }
                self.assertFalse(expected_check_is_well_formed(expected))
                self.assertFalse(
                    match_expected_check({"context": ACCOUNT_CONTEXT}, expected)
                )

    def test_integration_id_is_still_load_bearing_when_present(self) -> None:
        expected = {"context": "GitGuardian Security Checks", "integration_id": 46505}
        self.assertTrue(match_expected_check({"context": "GitGuardian Security Checks", "integration_id": 46505}, expected))
        self.assertFalse(match_expected_check({"context": "GitGuardian Security Checks", "integration_id": 46506}, expected))

    def test_materializer_resolves_fingerprint_from_authenticated_live_state(self) -> None:
        payload = json.loads(
            (ROOT / ".github/governance/main-ruleset.json").read_text(encoding="utf-8")
        )
        live = json.loads(json.dumps(payload))
        status = next(
            rule for rule in live["rules"] if rule["type"] == "required_status_checks"
        )
        fingerprint_index = next(
            index
            for index, item in enumerate(status["parameters"]["required_status_checks"])
            if "context_fingerprint" in item
        )
        status["parameters"]["required_status_checks"][fingerprint_index] = {
            "context": ACCOUNT_CONTEXT
        }

        provider_payload = materialize_ruleset_spec(payload, live)
        self.assertNotIn("schema", provider_payload)
        self.assertNotIn("provider_payload", provider_payload)
        provider_status = next(
            rule
            for rule in provider_payload["rules"]
            if rule["type"] == "required_status_checks"
        )
        checks = provider_status["parameters"]["required_status_checks"]
        self.assertFalse(any("context_fingerprint" in item for item in checks))
        self.assertTrue(any(item.get("context") == ACCOUNT_CONTEXT for item in checks))

    def test_tracked_ruleset_uses_digest_for_account_derived_check(self) -> None:
        payload = json.loads((ROOT / ".github/governance/main-ruleset.json").read_text(encoding="utf-8"))
        status = next(
            (rule for rule in payload["rules"] if rule["type"] == "required_status_checks"),
            None,
        )
        self.assertIsNotNone(status)
        assert status is not None
        fingerprinted = [
            item for item in status["parameters"]["required_status_checks"]
            if "context_fingerprint" in item
        ]
        self.assertEqual(len(fingerprinted), 1)
        self.assertEqual(
            fingerprinted[0]["context_fingerprint"],
            {
                "algorithm": "sha256",
                "digest": ACCOUNT_CONTEXT_SHA256,
                "case_sensitive": True,
                "provider_family": "dependency-security",
            },
        )
        self.assertNotIn("context", fingerprinted[0])


if __name__ == "__main__":
    unittest.main()
