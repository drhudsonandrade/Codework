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

    def test_scaffold_emits_a_manifest_that_satisfies_the_execution_schema(self):
        """The scaffold is the starting point every execution manifest is built from.

        It is also the surface where canonical_filename was missing: a scaffold
        that omits a required identity field hands every downstream consumer a
        manifest the gates will reject, and nothing tested the CLI path that
        produces it.
        """
        schema = json.loads(
            (ROOT / "policy" / "schema" / "execution-manifest.schema.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "scaffold.json"
            result = self.run_cli("scaffold", "--case-id", "CLI-CASE", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))

        for key in schema["required"]:
            self.assertIn(key, manifest, f"scaffold omits required top-level key {key}")

        ruleset_schema = schema["properties"]["ruleset"]
        for key in ruleset_schema["required"]:
            self.assertIn(key, manifest["ruleset"], f"scaffold omits required ruleset key {key}")
        for key, spec in ruleset_schema["properties"].items():
            if "const" in spec:
                self.assertEqual(manifest["ruleset"][key], spec["const"], f"scaffold ruleset.{key} is not canonical")

        self.assertEqual(manifest["case_id"], "CLI-CASE")
        self.assertEqual(len(manifest["section_attestations"]), 263)

    def test_scaffold_is_inert_until_a_human_fills_it_in(self):
        """A scaffold must never be a manifest that would pass the gates as emitted."""
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "scaffold.json"
            self.assertEqual(self.run_cli("scaffold", "--output", str(output)).returncode, 0)
            manifest = json.loads(output.read_text(encoding="utf-8"))

            evaluated = Path(td) / "report.json"
            result = self.run_cli("evaluate", str(output), "--output", str(evaluated))
            report = json.loads(evaluated.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 2, "an unfilled scaffold must not be reported ready")
        self.assertFalse(report["ready_for_requested_operation"])
        self.assertFalse(manifest["consent"]["verified"])
        self.assertFalse(manifest["qc"]["passed"])
        for attestation in manifest["section_attestations"]:
            self.assertEqual(attestation["decision"], "UNRESOLVED")

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
