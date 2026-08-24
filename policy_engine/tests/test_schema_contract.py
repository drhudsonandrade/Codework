from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "policy" / "schema" / "execution-manifest.schema.json"
CANONICAL_FILENAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"


def _minimal_object_contract_errors(contract: dict[str, Any], instance: object) -> list[str]:
    errors: list[str] = []
    if contract.get("type") == "object" and not isinstance(instance, dict):
        return ["type"]
    assert isinstance(instance, dict)
    for key in contract.get("required", []):
        if key not in instance:
            errors.append(f"required:{key}")
    properties = contract.get("properties", {})
    for key, value in instance.items():
        spec = properties.get(key, {}) if isinstance(properties, dict) else {}
        if isinstance(spec, dict) and "const" in spec and value != spec["const"]:
            errors.append(f"const:{key}")
    return errors


class ExecutionSchemaContractTests(unittest.TestCase):
    def test_ruleset_requires_vigente_status(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        ruleset = schema["properties"]["ruleset"]
        self.assertIn("status", ruleset["required"])
        self.assertEqual(ruleset["properties"]["status"], {"const": "VIGENTE"})

    def test_missing_or_wrong_status_cannot_satisfy_ruleset_contract(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        ruleset = schema["properties"]["ruleset"]
        base = {
            "version": "v3.4",
            "effective_date": "17/08/2026",
            "canonical_filename": CANONICAL_FILENAME,
            "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
        }
        missing = dict(base)
        wrong = {**base, "status": "PENDENTE"}
        valid = {**base, "status": "VIGENTE"}

        self.assertIn("required:status", _minimal_object_contract_errors(ruleset, missing))
        self.assertIn("const:status", _minimal_object_contract_errors(ruleset, wrong))
        self.assertEqual(_minimal_object_contract_errors(ruleset, valid), [])


if __name__ == "__main__":
    unittest.main()
