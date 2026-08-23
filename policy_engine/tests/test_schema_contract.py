from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from genoma_policy import ruleset as ruleset_module

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "policy" / "schema" / "execution-manifest.schema.json"
REGO = ROOT / "policy" / "rego" / "genoma.rego"
CANONICAL_FILENAME = ruleset_module.EXPECTED_CANONICAL
CANONICAL_SHA256 = ruleset_module.EXPECTED_SHA256


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

    def test_ruleset_binds_the_canonical_filename(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        ruleset = schema["properties"]["ruleset"]
        self.assertIn("canonical_filename", ruleset["required"])
        self.assertEqual(ruleset["properties"]["canonical_filename"], {"const": CANONICAL_FILENAME})

    def test_missing_or_wrong_status_cannot_satisfy_ruleset_contract(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        ruleset = schema["properties"]["ruleset"]
        base = {
            "version": "v3.4",
            "effective_date": "17/08/2026",
            "sha256": CANONICAL_SHA256,
            "canonical_filename": CANONICAL_FILENAME,
        }
        missing = dict(base)
        wrong = {**base, "status": "PENDENTE"}
        valid = {**base, "status": "VIGENTE"}

        self.assertIn("required:status", _minimal_object_contract_errors(ruleset, missing))
        self.assertIn("const:status", _minimal_object_contract_errors(ruleset, wrong))
        self.assertEqual(_minimal_object_contract_errors(ruleset, valid), [])

    def test_missing_or_wrong_canonical_filename_cannot_satisfy_ruleset_contract(self) -> None:
        """A manifest must not pass on the strength of the other identity fields alone."""
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        ruleset = schema["properties"]["ruleset"]
        base = {
            "status": "VIGENTE",
            "version": "v3.4",
            "effective_date": "17/08/2026",
            "sha256": CANONICAL_SHA256,
        }
        missing = dict(base)
        wrong = {**base, "canonical_filename": "REGRAS_PROJETO_GENOMA_VIGENTE_v9.9_2030-01-01.txt"}
        valid = {**base, "canonical_filename": CANONICAL_FILENAME}

        self.assertIn("required:canonical_filename", _minimal_object_contract_errors(ruleset, missing))
        self.assertIn("const:canonical_filename", _minimal_object_contract_errors(ruleset, wrong))
        self.assertEqual(_minimal_object_contract_errors(ruleset, valid), [])


class CanonicalIdentityIsCentralisedTests(unittest.TestCase):
    """Every plane must bind the same canonical identity, not its own copy of it.

    The schema and the Rego policy cannot import the Python loader, so their
    literals are duplicates by construction. These tests are what keeps the
    duplicates honest: a future migration that changes ``ruleset.py`` without
    changing the policy surfaces fails here instead of silently letting a
    divergent manifest through one layer.
    """

    def test_schema_literals_match_the_canonical_loader(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        properties = schema["properties"]["ruleset"]["properties"]
        self.assertEqual(properties["status"]["const"], ruleset_module.EXPECTED_STATUS)
        self.assertEqual(properties["version"]["const"], ruleset_module.EXPECTED_VERSION)
        self.assertEqual(properties["effective_date"]["const"], ruleset_module.EXPECTED_DATE)
        self.assertEqual(properties["sha256"]["const"], ruleset_module.EXPECTED_SHA256)
        self.assertEqual(properties["canonical_filename"]["const"], ruleset_module.EXPECTED_CANONICAL)

    def test_rego_literals_match_the_canonical_loader(self) -> None:
        rego = REGO.read_text(encoding="utf-8")
        for expected in (
            ruleset_module.EXPECTED_STATUS,
            ruleset_module.EXPECTED_VERSION,
            ruleset_module.EXPECTED_DATE,
            ruleset_module.EXPECTED_SHA256,
            ruleset_module.EXPECTED_CANONICAL,
        ):
            self.assertIn(f'"{expected}"', rego, f"rego policy does not bind {expected!r}")

    def test_rego_denies_an_absent_canonical_filename(self) -> None:
        """A bare ``input.ruleset.canonical_filename !=`` would be undefined, not a deny."""
        rego = REGO.read_text(encoding="utf-8")
        canonical_rule = next(
            line for line in rego.splitlines() if "canonical filename mismatch" in line
        )
        self.assertIn('object.get(input.ruleset, "canonical_filename", "")', canonical_rule)


if __name__ == "__main__":
    unittest.main()
