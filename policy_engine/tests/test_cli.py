from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from genoma_policy.version import __version__

RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _schema_contract_errors(
    schema: dict[str, Any],
    instance: Any,
    root_schema: dict[str, Any],
    path: str = "$",
) -> list[str]:
    errors: list[str] = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return [f"{path}:unsupported-ref:{ref}"]
        resolved: Any = root_schema
        for part in ref[2:].split("/"):
            resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
        return _schema_contract_errors(resolved, instance, root_schema, path)

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]

        def matches(kind: str) -> bool:
            if kind == "object":
                return isinstance(instance, dict)
            if kind == "array":
                return isinstance(instance, list)
            if kind == "string":
                return isinstance(instance, str)
            if kind == "boolean":
                return isinstance(instance, bool)
            if kind == "integer":
                return isinstance(instance, int) and not isinstance(instance, bool)
            if kind == "number":
                return isinstance(instance, (int, float)) and not isinstance(instance, bool)
            if kind == "null":
                return instance is None
            return False

        if not any(matches(kind) for kind in expected_types):
            return [f"{path}:type:{expected_type}"]

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}:const")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}:enum")

    if isinstance(instance, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                errors.append(f"{path}:required:{key}")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, value in instance.items():
                if key in properties:
                    errors.extend(
                        _schema_contract_errors(
                            properties[key], value, root_schema, f"{path}.{key}"
                        )
                    )
                else:
                    additional = schema.get("additionalProperties", True)
                    if additional is False:
                        errors.append(f"{path}:additionalProperties:{key}")
                    elif isinstance(additional, dict):
                        errors.extend(
                            _schema_contract_errors(
                                additional, value, root_schema, f"{path}.{key}"
                            )
                        )

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < int(schema["minItems"]):
            errors.append(f"{path}:minItems")
        if "maxItems" in schema and len(instance) > int(schema["maxItems"]):
            errors.append(f"{path}:maxItems")
        if schema.get("uniqueItems") is True:
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in instance]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{path}:uniqueItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(
                    _schema_contract_errors(
                        item_schema, item, root_schema, f"{path}[{index}]"
                    )
                )

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < int(schema["minLength"]):
            errors.append(f"{path}:minLength")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, instance) is None:
            errors.append(f"{path}:pattern")
        if schema.get("format") == "date-time":
            valid_datetime = RFC3339_DATE_TIME.fullmatch(instance) is not None
            normalized = instance[:-1] + "+00:00" if instance.endswith("Z") else instance
            if valid_datetime:
                try:
                    parsed = datetime.fromisoformat(normalized)
                except ValueError:
                    valid_datetime = False
                else:
                    valid_datetime = parsed.tzinfo is not None and parsed.utcoffset() is not None
            if not valid_datetime:
                errors.append(f"{path}:format:date-time")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}:minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}:maximum")

    return errors


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "genoma_policy", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_schema_date_time_requires_rfc3339_time_and_offset(self):
        schema = {"type": "string", "format": "date-time"}
        for invalid in (
            "2026-08-17",
            "2026-08-17T12:00:00",
            "2026-08-17T12:00:00+0000",
            "2026-08-17T12:00:00+00",
            "2026-08-17T12:00:00+00:00:30",
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(
                    _schema_contract_errors(schema, invalid, schema),
                    ["$:format:date-time"],
                )
        for valid in (
            "2026-08-17T12:00:00Z",
            "2026-08-17T12:00:00+00:00",
            "2026-08-17T12:00:00-03:00",
        ):
            with self.subTest(valid=valid):
                self.assertEqual(_schema_contract_errors(schema, valid, schema), [])

    def test_ruleset_check(self):
        result = self.run_cli("ruleset-check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["ruleset"]["section_count"], 263)

    def test_catalog_contains_all_rules(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "catalog.json"
            result = self.run_cli("catalog", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["rules"]), 263)
            self.assertEqual(payload["rules"][0]["rule_id"], "GENOMA-V3.4-S000")
            self.assertEqual(payload["rules"][-1]["rule_id"], "GENOMA-V3.4-S262")

    def test_scaffold_writes_a_manifest_matching_the_execution_schema(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "manifest.json"
            result = self.run_cli("scaffold", "--case-id", "CASE-SCAFFOLD-1", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(payload["case_id"], "CASE-SCAFFOLD-1")
            self.assertEqual(payload["session_id"], "SESSION-ID")
            self.assertEqual(
                payload["ruleset"],
                {
                    "status": "VIGENTE",
                    "version": "v3.4",
                    "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
                    "effective_date": "17/08/2026",
                    "canonical_filename": "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt",
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
            expected_rule_ids = [f"GENOMA-V3.4-S{section:03d}" for section in range(263)]
            self.assertEqual(
                [item["rule_id"] for item in payload["section_attestations"]],
                expected_rule_ids,
            )
            first = payload["section_attestations"][0]
            self.assertEqual(first["status"], "PROPOSTO")
            self.assertEqual(first["decision"], "UNRESOLVED")
            self.assertEqual(first["trace"]["actor_id"], "genoma-policy-engine-scaffold")
            self.assertEqual(first["trace"]["tool_versions"]["genoma-policy-engine"], __version__)

            schema = json.loads(
                (ROOT / "policy" / "schema" / "execution-manifest.schema.json").read_text(encoding="utf-8")
            )
            self.assertEqual(_schema_contract_errors(schema, payload, schema), [])

    def test_scaffold_default_case_id_is_used_when_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "manifest.json"
            result = self.run_cli("scaffold", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["case_id"], "CASE-ID")

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
