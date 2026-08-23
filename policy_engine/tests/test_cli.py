from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "genoma_policy", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_ruleset_check(self):
        result = self.run_cli("ruleset-check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["ruleset"]["section_count"], 263)

    def test_catalog_contains_all_rules(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "catalog.json"
            result = self.run_cli("catalog", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text())
            self.assertEqual(len(payload["rules"]), 263)
            self.assertEqual(payload["rules"][0]["rule_id"], "GENOMA-V3.4-S000")
            self.assertEqual(payload["rules"][-1]["rule_id"], "GENOMA-V3.4-S262")

    def test_ledger_cli_append_and_verify(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = root / "payload.json"
            ledger = root / "audit.jsonl"
            payload.write_text(json.dumps({"ready": False}))
            appended = self.run_cli("ledger-append", str(ledger), "POLICY_EVALUATED", str(payload))
            self.assertEqual(appended.returncode, 0, appended.stderr)
            verified = self.run_cli("ledger-verify", str(ledger))
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
