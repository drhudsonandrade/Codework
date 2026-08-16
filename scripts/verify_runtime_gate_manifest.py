#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = (
    "executables_and_versions",
    "reference_build_and_contigs",
    "fasta_fai_dictionary",
    "aligner_indexes",
    "required_resources_checksums",
    "sample_read_group_integrity",
    "fastq_bam_cram_integrity",
    "caller_model_reference_compatibility",
)


def verify(payload: dict) -> list[str]:
    errors: list[str] = []
    if payload.get("gate") != "RUNTIME_RESOURCE_GATE":
        errors.append("gate identity is not RUNTIME_RESOURCE_GATE")
    if payload.get("status") != "EXECUTADO":
        errors.append("runtime gate status is not EXECUTADO")
    if payload.get("ready_for_real_calling") is not True:
        errors.append("ready_for_real_calling is not true")
    if payload.get("inherited_from_previous_session") is not False:
        errors.append("runtime gate may be inherited from another session")
    if not payload.get("session_id"):
        errors.append("session_id missing")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    for key in REQUIRED:
        check = checks.get(key) if isinstance(checks.get(key), dict) else {}
        if check.get("status") != "EXECUTADO":
            errors.append(f"{key} not EXECUTADO")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    errors = verify(payload)
    result = {
        "schema": "genoma-runtime-gate-entry-verification-v1",
        "status": "VERIFICADO" if not errors else "NÃO DISPONÍVEL",
        "runtime_session_id": payload.get("session_id"),
        "ready_for_wgs": not errors,
        "errors": errors,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
