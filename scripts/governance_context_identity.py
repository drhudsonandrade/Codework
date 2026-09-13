from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def context_digest(value: str) -> str:
    """Return the SHA-256 digest of an exact UTF-8 check context."""
    if not isinstance(value, str) or not value:
        raise ValueError("check context must be a non-empty string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint_is_valid(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        value.get("algorithm") == "sha256"
        and value.get("case_sensitive") is True
        and isinstance(value.get("provider_family"), str)
        and bool(value.get("provider_family"))
        and isinstance(value.get("digest"), str)
        and _SHA256_RE.fullmatch(value["digest"]) is not None
    )


def expected_check_is_well_formed(expected: object) -> bool:
    """Validate either a literal or fingerprinted tracked check identity."""
    if not isinstance(expected, dict):
        return False
    has_context = "context" in expected
    has_fingerprint = "context_fingerprint" in expected
    if has_context == has_fingerprint:
        return False
    if has_context and (
        not isinstance(expected.get("context"), str) or not expected.get("context")
    ):
        return False
    if has_fingerprint and not _fingerprint_is_valid(expected.get("context_fingerprint")):
        return False
    integration_id = expected.get("integration_id")
    return integration_id is None or (isinstance(integration_id, int) and not isinstance(integration_id, bool))


def match_expected_check(live: dict, expected: dict) -> bool:
    """Match live provider state against a tracked neutral check identity."""
    if not expected_check_is_well_formed(expected) or not isinstance(live, dict):
        return False
    live_context = live.get("context")
    if not isinstance(live_context, str):
        return False
    if "context" in expected:
        context_match = live_context == expected["context"]
    else:
        fingerprint = expected["context_fingerprint"]
        context_match = context_digest(live_context) == fingerprint["digest"]
    if not context_match:
        return False
    if "integration_id" in expected:
        return live.get("integration_id") == expected["integration_id"]
    return True


def _required_status_rule(payload: dict) -> dict:
    """Return the unique required-status-checks rule from one ruleset payload."""
    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise ValueError("ruleset rules must be a list")
    matches = [
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks"
    ]
    if len(matches) != 1:
        raise ValueError("ruleset must contain exactly one required_status_checks rule")
    return matches[0]


def materialize_ruleset_spec(spec: dict, live: dict) -> dict:
    """Materialize a neutral tracked spec into a provider-valid payload using live state."""
    if spec.get("provider_payload") is True:
        raise ValueError("provider payload cannot be rematerialized as a neutral spec")

    materialized = copy.deepcopy(spec)
    materialized.pop("schema", None)
    materialized.pop("provider_payload", None)
    expected_rule = _required_status_rule(materialized)
    live_rule = _required_status_rule(live)
    expected_checks = expected_rule.get("parameters", {}).get("required_status_checks")
    live_checks = live_rule.get("parameters", {}).get("required_status_checks")
    if not isinstance(expected_checks, list) or not isinstance(live_checks, list):
        raise ValueError("required_status_checks must be lists")

    resolved: list[dict] = []
    for expected in expected_checks:
        if not expected_check_is_well_formed(expected):
            raise ValueError("neutral required-check identity is malformed")
        if "context" in expected:
            resolved.append(copy.deepcopy(expected))
            continue
        matches = [
            item
            for item in live_checks
            if isinstance(item, dict) and match_expected_check(item, expected)
        ]
        if len(matches) != 1:
            raise ValueError("fingerprinted required check did not resolve uniquely")
        resolved_item = {"context": matches[0]["context"]}
        if "integration_id" in expected:
            resolved_item["integration_id"] = expected["integration_id"]
        resolved.append(resolved_item)
    expected_rule["parameters"]["required_status_checks"] = resolved
    return materialized


def main(argv: list[str] | None = None) -> int:
    """Materialize a tracked neutral ruleset spec from authenticated live-state JSON."""
    parser = argparse.ArgumentParser(description="Materialize neutral ruleset fingerprints.")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    live = json.loads(args.live.read_text(encoding="utf-8"))
    payload = materialize_ruleset_spec(spec, live)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
