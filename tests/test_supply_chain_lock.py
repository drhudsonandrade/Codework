from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from scripts import verify_supply_chain_lock

ROOT = Path(__file__).resolve().parents[1]
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class SupplyChainLockTest(unittest.TestCase):
    def test_actions_lock_has_full_sha_identities(self):
        payload = json.loads((ROOT / "locks/actions-lock.json").read_text())
        self.assertGreaterEqual(len(payload["actions"]), 10)
        for name, meta in payload["actions"].items():
            self.assertRegex(meta["sha"], SHA40, name)
            self.assertTrue(meta["version"].startswith("v"))

    def test_no_mutable_third_party_action_refs(self):
        allowed = json.loads((ROOT / "locks/actions-lock.json").read_text())["actions"]
        for wf in (ROOT / ".github/workflows").glob("*.yml"):
            for line in wf.read_text().splitlines():
                stripped = line.strip()
                if not stripped.startswith("uses:") and not stripped.startswith("- uses:"):
                    continue
                ref = stripped.split("uses:", 1)[1].split("#", 1)[0].strip()
                if ref.startswith("./"):
                    continue
                name, sep, sha = ref.rpartition("@")
                self.assertEqual(sep, "@", f"{wf}: {ref}")
                self.assertRegex(sha, SHA40, f"{wf}: {ref}")
                self.assertIn(name, allowed, f"{wf}: {name}")
                self.assertEqual(sha, allowed[name]["sha"], f"{wf}: {name}")

    def test_runtime_lock_pins_external_secret_scanner_identity(self):
        payload = json.loads((ROOT / "locks/runtime-lock.json").read_text())
        self.assertIn("@sha256:", payload["base_image"]["reference"])
        scanner = payload["secret_scanner"]
        self.assertEqual(scanner["context"], "GitGuardian Security Checks")
        self.assertEqual(scanner["integration_id"], 46505)
        self.assertEqual(scanner["execution"], "external_github_app")

    def test_external_secret_scanner_identity_matches_governance(self):
        runtime = json.loads((ROOT / "locks/runtime-lock.json").read_text())
        ruleset = json.loads((ROOT / ".github/governance/main-ruleset.json").read_text())
        verify_supply_chain_lock._verify_external_secret_scanner(runtime, ruleset)
        mutated = json.loads(json.dumps(runtime))
        mutated["secret_scanner"]["integration_id"] += 1
        with self.assertRaises(SystemExit):
            verify_supply_chain_lock._verify_external_secret_scanner(mutated, ruleset)

    def test_supply_chain_verifier_does_not_reference_retired_gitleaks(self):
        verifier = (ROOT / "scripts/verify_supply_chain_lock.py").read_text(encoding="utf-8")
        self.assertNotIn("gitleaks", verifier.casefold())

if __name__ == "__main__":
    unittest.main()
