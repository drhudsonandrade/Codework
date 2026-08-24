from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

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

    def test_runtime_lock_uses_container_digests(self):
        payload = json.loads((ROOT / "locks/runtime-lock.json").read_text())
        self.assertIn("@sha256:", payload["base_image"]["reference"])
        self.assertIn("@sha256:", payload["secret_scanner"]["reference"])


if __name__ == "__main__":
    unittest.main()
