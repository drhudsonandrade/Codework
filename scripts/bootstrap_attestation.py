#!/usr/bin/env python3
"""Fail-closed verifier for the GENOMA v3.4 project-bootstrap attestation."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

EXPECTED_FILE_SHA256 = "e2af0ef46e5bc26f45cc2c0b38047481bab1cd64d5a5d97f5d3cde2b2d947575"
EXPECTED_RULESET_IDENTITY = "v3.4/VIGENTE/17/08/2026"
EXPECTED_CANONICAL_FILENAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_CANONICAL_SHA256 = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
EXPECTED_CHECKS = {
    "consult_ruleset_before_relevant_genetic_analysis",
    "require_status_vigente",
    "require_version_v3_4",
    "require_effective_date_2026_08_17",
    "fail_closed_on_missing_or_conflicting_ruleset",
    "runtime_resource_gate_before_real_calling",
    "operational_status_contract_present",
    "post_deployment_requires_live_15_of_15_zero_critical",
}


# Provenance a consumer needs in order to reproduce the verification rather than
# take it on trust: who verified, at which version, by which command, from which
# inputs, and where the result is recorded.
REQUIRED_VERIFIER_FIELDS = ("name", "version", "command", "inputs", "result_locator")
# The inputs the checks are derived from. A commit SHA cannot be one of them: the
# attestation is part of the commit that would name it. Digests bind the same
# provenance without that cycle.
REQUIRED_VERIFIER_INPUTS = (
    "normative/sealed/MANIFEST.json",
    "policy_engine/policy/schema/execution-manifest.schema.json",
    "canonical_ruleset_raw_sha256",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class BootstrapAttestationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_reproducible_provenance(payload: dict[str, Any]) -> None:
    """A status of VERIFICADO must rest on something a third party can re-derive.

    Without this, ``method`` was free to be prose about a session: a reader could
    confirm the file's digest and its declared identity, yet had no command to run,
    no inputs to hash and no result to compare. That is a textual claim, which this
    project does not accept as technical evidence.
    """
    verifier = payload.get("verifier")
    if not isinstance(verifier, dict):
        raise BootstrapAttestationError("bootstrap attestation carries no verifier provenance")
    missing = [field for field in REQUIRED_VERIFIER_FIELDS if not verifier.get(field)]
    if missing:
        raise BootstrapAttestationError(f"bootstrap attestation verifier provenance is incomplete: {missing}")
    inputs = verifier["inputs"]
    if not isinstance(inputs, dict):
        raise BootstrapAttestationError("bootstrap attestation verifier inputs must be an object")
    missing_inputs = [name for name in REQUIRED_VERIFIER_INPUTS if name not in inputs]
    if missing_inputs:
        raise BootstrapAttestationError(f"bootstrap attestation verifier inputs are incomplete: {missing_inputs}")
    unhashed = sorted(
        name for name, digest in inputs.items() if not isinstance(digest, str) or not SHA256_PATTERN.match(digest)
    )
    if unhashed:
        raise BootstrapAttestationError(f"bootstrap attestation verifier inputs are not content-addressed: {unhashed}")
    if inputs["canonical_ruleset_raw_sha256"] != EXPECTED_CANONICAL_SHA256:
        raise BootstrapAttestationError("bootstrap attestation was derived from a different canonical ruleset")


def verify_bootstrap_attestation(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise BootstrapAttestationError("bootstrap attestation is missing")
    raw = source.read_bytes()
    observed_sha = hashlib.sha256(raw).hexdigest()
    if observed_sha != EXPECTED_FILE_SHA256:
        raise BootstrapAttestationError(
            f"bootstrap attestation digest mismatch: expected {EXPECTED_FILE_SHA256}, observed {observed_sha}"
        )
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapAttestationError(f"bootstrap attestation is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BootstrapAttestationError("bootstrap attestation must be a JSON object")
    expected_identity = {
        "attestation_type": "GENOMA_PROJECT_BOOTSTRAP",
        "status": "VERIFICADO",
        "ruleset_identity": EXPECTED_RULESET_IDENTITY,
        "canonical_filename": EXPECTED_CANONICAL_FILENAME,
        "canonical_sha256": EXPECTED_CANONICAL_SHA256,
        "actor_type": "SERVICE",
        "actor_id": "genoma-project-bootstrap-verifier",
    }
    mismatches = {
        key: (payload.get(key), expected)
        for key, expected in expected_identity.items()
        if payload.get(key) != expected
    }
    if mismatches:
        raise BootstrapAttestationError(f"bootstrap attestation identity mismatch: {mismatches}")
    if not isinstance(payload.get("verified_at"), str) or not payload["verified_at"].strip():
        raise BootstrapAttestationError("bootstrap attestation verified_at is missing")
    if not isinstance(payload.get("method"), str) or not payload["method"].strip():
        raise BootstrapAttestationError("bootstrap attestation method is missing")
    _require_reproducible_provenance(payload)
    checks = payload.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise BootstrapAttestationError("bootstrap attestation checks are missing or empty")
    if set(checks) != EXPECTED_CHECKS:
        raise BootstrapAttestationError(
            f"bootstrap attestation check set mismatch: expected {sorted(EXPECTED_CHECKS)}, observed {sorted(checks)}"
        )
    failed = sorted(key for key in EXPECTED_CHECKS if checks.get(key) is not True)
    if failed:
        raise BootstrapAttestationError(f"bootstrap attestation has failed checks: {failed}")
    verifier = payload["verifier"]
    return {
        "status": "VERIFICADO",
        "file_sha256": observed_sha,
        "ruleset_identity": EXPECTED_RULESET_IDENTITY,
        "canonical_sha256": EXPECTED_CANONICAL_SHA256,
        "checks_verified": sorted(EXPECTED_CHECKS),
        # Carried through so a downstream witness records how to reproduce this,
        # not merely that it was accepted.
        "verifier_command": verifier["command"],
        "verifier_version": verifier["version"],
        "verifier_inputs": dict(verifier["inputs"]),
        "result_locator": verifier["result_locator"],
    }
