from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "policy" / "schema" / "execution-manifest.schema.json"


class ExecutionSchemaContractTests(unittest.TestCase):
    def test_ruleset_requires_vigente_status(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        ruleset = schema["properties"]["ruleset"]
        self.assertIn("status", ruleset["required"])
        self.assertEqual(ruleset["properties"]["status"], {"const": "VIGENTE"})

    def test_missing_or_wrong_status_cannot_satisfy_ruleset_contract(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        ruleset = schema["properties"]["ruleset"]
        required = set(ruleset["required"])
        status_contract = ruleset["properties"]["status"]

        missing = {
            "version": "v3.4",
            "effective_date": "17/08/2026",
            "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
        }
        wrong = {**missing, "status": "PENDENTE"}

        self.assertFalse(required.issubset(missing))
        self.assertNotEqual(wrong["status"], status_contract["const"])


if __name__ == "__main__":
    unittest.main()
