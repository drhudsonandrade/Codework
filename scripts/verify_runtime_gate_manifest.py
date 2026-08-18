#!/usr/bin/env python3
"""Verify a Runtime/Resource Gate attestation before it is allowed to authorize work.

Ruleset v3.4 section 259 (REGRA DE RUNTIME/RESOURCE LOCK) ends with "Não herdar o PASS de
outra sessão." Reading the producer's own `inherited_from_previous_session: false` back out
of the file does not enforce that: the flag is written unconditionally, so a gate artifact
copied from another machine, or produced before a reboot, satisfies it unchanged.

This verifier therefore re-derives the environment identity at verification time and
requires the attestation to have been produced by the kernel boot it is being consumed in,
within a bounded age. A gate that cannot prove its origin is NÃO DISPONÍVEL, not PASS.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runtime_resource_gate import read_boot_id

ENVIRONMENT_REQUIRED = (
    "executables_and_versions",
    "reference_build_and_contigs",
    "fasta_fai_dictionary",
    "aligner_indexes",
    "required_resources_checksums",
    "caller_model_reference_compatibility",
)
SAMPLE_REQUIRED = (
    "sample_read_group_integrity",
    "fastq_bam_cram_integrity",
)
DEFAULT_MAX_AGE_SECONDS = 86_400


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def verify_session_binding(
    payload: dict,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    expect_session_id: str | None = None,
    allow_unbound: bool = False,
    current_boot_id: str | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Prove the attestation belongs to the session consuming it."""

    errors: list[str] = []
    binding = payload.get("session_binding")
    if not isinstance(binding, dict):
        if not allow_unbound:
            errors.append("session_binding missing; runtime gate cannot be proven current")
        return errors

    observed_boot = current_boot_id if current_boot_id is not None else read_boot_id()
    recorded_boot = binding.get("boot_id")
    if not recorded_boot or not observed_boot:
        if not allow_unbound:
            errors.append("boot identity unavailable; runtime gate cannot be proven current")
    elif recorded_boot != observed_boot:
        errors.append("runtime gate was produced in a different boot/host and may not be inherited")

    created = _parse_timestamp(binding.get("created_at"))
    if created is None:
        errors.append("session_binding.created_at is missing or unparseable")
    else:
        reference = now or datetime.now(timezone.utc)
        age = (reference - created).total_seconds()
        if age > max_age_seconds:
            errors.append(f"runtime gate is stale: {int(age)}s old exceeds {max_age_seconds}s")
        elif age < -300:
            errors.append("session_binding.created_at is in the future")

    if expect_session_id is not None and binding.get("session_id") != expect_session_id:
        errors.append("runtime gate session_id does not match the consuming session")

    return errors


def verify(
    payload: dict,
    *,
    scope: str,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    expect_session_id: str | None = None,
    allow_unbound: bool = False,
    current_boot_id: str | None = None,
    now: datetime | None = None,
) -> list[str]:
    errors: list[str] = []
    if payload.get("gate") != "RUNTIME_RESOURCE_GATE":
        errors.append("gate identity is not RUNTIME_RESOURCE_GATE")
    if payload.get("inherited_from_previous_session") is not False:
        errors.append("runtime gate may be inherited from another session")
    if not payload.get("session_id"):
        errors.append("session_id missing")

    errors.extend(
        verify_session_binding(
            payload,
            max_age_seconds=max_age_seconds,
            expect_session_id=expect_session_id,
            allow_unbound=allow_unbound,
            current_boot_id=current_boot_id,
            now=now,
        )
    )

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    required = list(ENVIRONMENT_REQUIRED + (SAMPLE_REQUIRED if scope == "full" else ()))

    # An aligner index is only meaningful when this session will actually align. A staged
    # BAM/CRAM run never reads it, so demanding it would force an ~80 GiB index build for a
    # resource nothing opens. The exemption is narrow and self-checking: it applies only when
    # the attestation declares stage mode AND carries no FASTQ integrity evidence, so a
    # manifest cannot claim stage and then hand the pipeline FASTQ.
    alignment_mode = payload.get("alignment_mode", "align")
    integrity = checks.get("fastq_bam_cram_integrity") if isinstance(checks.get("fastq_bam_cram_integrity"), dict) else {}
    details = integrity.get("details") if isinstance(integrity.get("details"), dict) else {}
    declared_fastq = any(key.startswith("fastq") for key in details)
    if alignment_mode == "stage":
        if declared_fastq:
            errors.append("alignment_mode=stage contradicts FASTQ input evidence; aligner index is required")
        elif payload.get("aligner_index_required") is not False:
            errors.append("alignment_mode=stage but the attestation still declares the aligner index required")
        else:
            required.remove("aligner_indexes")
            aligner = checks.get("aligner_indexes") if isinstance(checks.get("aligner_indexes"), dict) else {}
            if aligner.get("status") not in {"NÃO APLICÁVEL", "EXECUTADO"}:
                errors.append("aligner_indexes must be NÃO APLICÁVEL or EXECUTADO under stage mode")
    elif alignment_mode != "align":
        errors.append(f"unknown alignment_mode: {alignment_mode!r}")

    for key in required:
        check = checks.get(key) if isinstance(checks.get(key), dict) else {}
        if check.get("status") != "EXECUTADO":
            errors.append(f"{key} not EXECUTADO")
    if scope == "full":
        if payload.get("status") != "EXECUTADO":
            errors.append("runtime gate status is not EXECUTADO")
        if payload.get("ready_for_real_calling") is not True:
            errors.append("ready_for_real_calling is not true")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scope", choices=["environment", "full"], default="full")
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=DEFAULT_MAX_AGE_SECONDS,
        help="reject an attestation older than this (section 259 forbids inheriting a stale PASS)",
    )
    parser.add_argument(
        "--expect-session-id",
        help="require the attestation to carry this session id",
    )
    parser.add_argument(
        "--allow-unbound-session",
        action="store_true",
        help="accept an attestation with no boot identity (non-Linux hosts); records the weaker basis",
    )
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    errors = verify(
        payload,
        scope=args.scope,
        max_age_seconds=args.max_age_seconds,
        expect_session_id=args.expect_session_id,
        allow_unbound=args.allow_unbound_session,
    )
    binding = payload.get("session_binding") if isinstance(payload.get("session_binding"), dict) else {}
    result = {
        "schema": "genoma-runtime-gate-entry-verification-v2",
        "scope": args.scope,
        "status": "VERIFICADO" if not errors else "NÃO DISPONÍVEL",
        "runtime_session_id": payload.get("session_id"),
        "session_binding_basis": "boot-id" if binding.get("boot_id") else ("unbound" if args.allow_unbound_session else "none"),
        "verified_boot_id": read_boot_id(),
        "attestation_boot_id": binding.get("boot_id"),
        "max_age_seconds": args.max_age_seconds,
        "ready_for_operation": not errors,
        "errors": errors,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
