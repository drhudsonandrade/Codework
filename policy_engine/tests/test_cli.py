from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from genoma_policy.version import __version__


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

    def test_scaffold_writes_a_manifest_matching_the_execution_schema(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "manifest.json"
            result = self.run_cli("scaffold", "--case-id", "CASE-SCAFFOLD-1", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text())

            self.assertEqual(payload["case_id"], "CASE-SCAFFOLD-1")
            self.assertEqual(payload["session_id"], "SESSION-ID")
            self.assertEqual(
                payload["ruleset"],
                {
                    "status": "VIGENTE",
                    "version": "v3.4",
                    "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
                    "effective_date": "17/08/2026",
                },
            )
            self.assertEqual(
                payload["operation"],
                {
                    "name": "genomic_analysis",
                    "analysis_relevant": True,
                    "requires_real_calling": False,
                    "output": "ANALYSIS",
                },
            )

            # A scaffold is a starting point, never a pre-approved manifest.
            self.assertFalse(payload["consent"]["verified"])
            self.assertEqual(payload["qc"]["status"], "PROPOSTO")
            self.assertFalse(payload["post_deployment"]["live_smoke_passed"])
            self.assertEqual(len(payload["section_attestations"]), 263)
            first = payload["section_attestations"][0]
            self.assertEqual(first["rule_id"], "GENOMA-V3.4-S000")
            self.assertEqual(first["status"], "PROPOSTO")
            self.assertEqual(first["decision"], "UNRESOLVED")
            self.assertEqual(first["trace"]["actor_id"], "genoma-policy-engine-scaffold")
            self.assertEqual(first["trace"]["tool_versions"]["genoma-policy-engine"], __version__)

            # The scaffold must satisfy the published execution-manifest contract, so a
            # renamed or dropped field is caught here rather than at evaluation time.
            schema = json.loads(
                (ROOT / "policy" / "schema" / "execution-manifest.schema.json").read_text(encoding="utf-8")
            )
            for key in schema["required"]:
                self.assertIn(key, payload, f"scaffold is missing schema-required key {key}")
            ruleset_contract = schema["properties"]["ruleset"]
            for key in ruleset_contract["required"]:
                self.assertIn(key, payload["ruleset"])
            self.assertEqual(payload["ruleset"]["status"], ruleset_contract["properties"]["status"]["const"])

    def test_scaffold_default_case_id_is_used_when_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "manifest.json"
            result = self.run_cli("scaffold", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["case_id"], "CASE-ID")

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
