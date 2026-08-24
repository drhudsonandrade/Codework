#!/usr/bin/env python3
"""Fail-closed attestation for the actually deployed Project Instructions snapshot.

This control is deliberately separate from ``bootstrap_attestation.py``. The normative
bootstrap attestation proves that the sealed ruleset contains the BOOTSTRAP CURTO
requirement. This module proves that an owner-exported snapshot of the persistent Project
Instructions contains the required v3.4 bootstrap clauses. Only this attestation may feed
``post_deployment.bootstrap_installed``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.sealed_ruleset import EXPECTED_DATE, EXPECTED_NAME, EXPECTED_SHA, EXPECTED_VERSION

ATTESTATION_TYPE = "GENOMA_PROJECT_INSTRUCTIONS"
SOURCE_KIND = "OWNER_EXPORTED_PROJECT_INSTRUCTIONS"
VERIFIED_STATUS = "VERIFICADO"
EXPECTED_RULESET_IDENTITY = f"{EXPECTED_VERSION}/VIGENTE/{EXPECTED_DATE}"
RFC3339_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

# These are literal, high-signal fragments from the canonical v3.4 BOOTSTRAP CURTO.
# Requiring the exact fragments prevents a generic or superseded instruction from being
# promoted to PROJECT_BOOTSTRAP_INSTALLED.
REQUIRED_CLAUSES: dict[str, str] = {
    "canonical_ruleset_filename": EXPECTED_NAME,
    "status_vigente": "STATUS NORMATIVO: VIGENTE",
    "version_v3_4": "VERSÃO NORMATIVA: v3.4",
    "effective_date": "DATA FORMAL DE EMISSÃO E VIGÊNCIA: 17/08/2026",
    "fail_closed_conflict": "RULESET NÃO DISPONÍVEL/CONFLITANTE",
    "operational_status_contract": "EXECUTADO, VERIFICADO, INFERIDO, PROPOSTO ou NÃO DISPONÍVEL",
    "runtime_resource_gate": "reexecutar o Runtime/Resource Gate antes de calling real",
}
EXPECTED_CHECKS = frozenset(REQUIRED_CLAUSES)


class ProjectInstructionsAttestationError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_verified_at(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectInstructionsAttestationError("project instructions verified_at is missing")
    candidate = value.strip()
    if RFC3339_DATETIME_RE.fullmatch(candidate) is None:
        raise ProjectInstructionsAttestationError(
            "project instructions verified_at must use strict RFC 3339 with T and Z or ±HH:MM"
        )
    normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProjectInstructionsAttestationError(
            "project instructions verified_at is not a valid RFC 3339 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProjectInstructionsAttestationError("project instructions verified_at requires a timezone")
    return candidate


def _require_locator(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectInstructionsAttestationError(
            "project instructions source locator is required and must identify the deployed Project Instructions"
        )
    return value.strip()


def _read_source(path: str | Path) -> tuple[bytes, str]:
    source = Path(path)
    if not source.is_file():
        raise ProjectInstructionsAttestationError("project instructions source snapshot is missing")
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProjectInstructionsAttestationError(
            f"project instructions source snapshot is unreadable: {type(exc).__name__}: {exc}"
        ) from exc
    if not text.strip():
        raise ProjectInstructionsAttestationError("project instructions source snapshot is empty")
    return raw, text


def _evaluate(text: str) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for name, clause in REQUIRED_CLAUSES.items():
        offset = text.find(clause)
        checks[name] = {
            "satisfied": offset >= 0,
            "clause_sha256": _sha256(clause.encode("utf-8")),
            "line": text.count("\n", 0, offset) + 1 if offset >= 0 else None,
        }
    return checks


def build_attestation(
    source_path: str | Path,
    *,
    source_locator: str,
    verified_at: str,
) -> dict[str, Any]:
    verified_at = _require_verified_at(verified_at)
    source_locator = _require_locator(source_locator)
    raw, text = _read_source(source_path)
    checks = _evaluate(text)
    missing = sorted(name for name, result in checks.items() if not result["satisfied"])
    if missing:
        raise ProjectInstructionsAttestationError(
            "PROJECT_BOOTSTRAP_INSTALLED cannot be attested; missing canonical Project Instructions clauses: "
            + ", ".join(missing)
        )
    return {
        "attestation_type": ATTESTATION_TYPE,
        "status": VERIFIED_STATUS,
        "project_bootstrap_installed": True,
        "ruleset_identity": EXPECTED_RULESET_IDENTITY,
        "canonical_filename": EXPECTED_NAME,
        "canonical_sha256": EXPECTED_SHA,
        "verified_at": verified_at,
        "actor_type": "OWNER_EXPORT",
        "source": {
            "kind": SOURCE_KIND,
            "locator": source_locator,
            "sha256": _sha256(raw),
            "size_bytes": len(raw),
        },
        "checks_evidence": checks,
        "limitations": (
            "This attestation is re-derived from an owner-exported snapshot of the persistent Project Instructions. "
            "It proves the snapshot content and its recorded locator; it is not evidence that can be generated from "
            "the sealed ruleset itself and must be refreshed whenever Project Instructions change."
        ),
    }


def serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def verify_project_instructions_attestation(
    path: str | Path,
    *,
    source_path: str | Path,
) -> dict[str, Any]:
    attestation_path = Path(path)
    if not attestation_path.is_file():
        raise ProjectInstructionsAttestationError("project instructions attestation is missing")
    try:
        raw_attestation = attestation_path.read_bytes()
        payload = json.loads(raw_attestation.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectInstructionsAttestationError(
            f"project instructions attestation is invalid: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProjectInstructionsAttestationError("project instructions attestation must be a JSON object")

    expected_identity = {
        "attestation_type": ATTESTATION_TYPE,
        "status": VERIFIED_STATUS,
        "project_bootstrap_installed": True,
        "ruleset_identity": EXPECTED_RULESET_IDENTITY,
        "canonical_filename": EXPECTED_NAME,
        "canonical_sha256": EXPECTED_SHA,
        "actor_type": "OWNER_EXPORT",
    }
    mismatches = {
        key: (payload.get(key), expected)
        for key, expected in expected_identity.items()
        if payload.get(key) != expected
    }
    if mismatches:
        raise ProjectInstructionsAttestationError(
            f"project instructions attestation identity mismatch: {mismatches}"
        )
    _require_verified_at(payload.get("verified_at"))

    source_meta = payload.get("source")
    if not isinstance(source_meta, dict) or source_meta.get("kind") != SOURCE_KIND:
        raise ProjectInstructionsAttestationError("project instructions source metadata is invalid")
    locator = _require_locator(source_meta.get("locator"))
    raw_source, source_text = _read_source(source_path)
    source_sha = _sha256(raw_source)
    if source_meta.get("sha256") != source_sha or source_meta.get("size_bytes") != len(raw_source):
        raise ProjectInstructionsAttestationError(
            "project instructions source snapshot does not match the attested digest/size"
        )

    checks = _evaluate(source_text)
    missing = sorted(name for name, result in checks.items() if not result["satisfied"])
    if missing:
        raise ProjectInstructionsAttestationError(
            "PROJECT_BOOTSTRAP_INSTALLED verification failed; canonical clauses are missing: "
            + ", ".join(missing)
        )
    recorded_checks = payload.get("checks_evidence")
    if recorded_checks != checks or set(checks) != EXPECTED_CHECKS:
        raise ProjectInstructionsAttestationError(
            "project instructions check evidence is not reproducible from the supplied source snapshot"
        )

    return {
        "status": VERIFIED_STATUS,
        "project_bootstrap_installed": True,
        "file_sha256": _sha256(raw_attestation),
        "source_sha256": source_sha,
        "source_locator": locator,
        "ruleset_identity": EXPECTED_RULESET_IDENTITY,
        "canonical_sha256": EXPECTED_SHA,
        "checks_verified": sorted(EXPECTED_CHECKS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="owner-exported Project Instructions UTF-8 snapshot")
    parser.add_argument("--output", required=True, help="attestation JSON path")
    parser.add_argument("--source-locator")
    parser.add_argument("--verified-at")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.write:
            if not args.source_locator:
                parser.error("--source-locator is required with --write")
            if not args.verified_at:
                parser.error("--verified-at is required with --write")
            payload = build_attestation(
                args.source,
                source_locator=args.source_locator,
                verified_at=args.verified_at,
            )
            target = Path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(serialize(payload), encoding="utf-8")
            print(json.dumps({"written": str(target), "sha256": _sha256(target.read_bytes())}, indent=2))
            return 0

        evidence = verify_project_instructions_attestation(args.output, source_path=args.source)
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0
    except ProjectInstructionsAttestationError as exc:
        print(f"ERROR: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
