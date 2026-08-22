#!/usr/bin/env python3
"""Fail-closed verifier for the GENOMA v3.4 project-bootstrap attestation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_FILE_SHA256 = "dbe574cff326d3a0b429de8a2450359024be97d7bb1c64468bf6a96b8d77d5b9"
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


class BootstrapAttestationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_bootstrap_attestation(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise BootstrapAttestationError("bootstrap attestation is missing")
    observed_sha = sha256_file(source)
    if observed_sha != EXPECTED_FILE_SHA256:
        raise BootstrapAttestationError(
            f"bootstrap attestation digest mismatch: expected {EXPECTED_FILE_SHA256}, observed {observed_sha}"
        )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
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
    return {
        "status": "VERIFICADO",
        "file_sha256": observed_sha,
        "ruleset_identity": EXPECTED_RULESET_IDENTITY,
        "canonical_sha256": EXPECTED_CANONICAL_SHA256,
        "checks_verified": sorted(EXPECTED_CHECKS),
    }
