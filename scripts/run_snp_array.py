#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.qc import inspect_array, write_outputs

ALLOWED_ACTOR_TYPES = {"HUMAN", "SOFTWARE", "SERVICE"}


def _normalise(assertion: str, value: str) -> str:
    """Canonical spelling, so `plus` and `forward` are not read as two different claims."""
    from array_pipeline.qc import _normalised_assertion

    return _normalised_assertion("strand" if assertion == "strand" else "reference_build", value) or ""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json_value(value: str) -> dict[str, Any]:
    """Accept either a path to an attestation or the attestation itself.

    Which one it is, is decided by the shape of the string rather than by asking the
    filesystem. `Path(value).is_file()` raises `OSError: File name too long` on any inline
    attestation whose JSON has no `/` in it — every path component over 255 bytes does — so
    the documented inline form crashed for most real payloads, and `main` reported it as
    `NÃO DISPONÍVEL: [Errno 36] File name too long`, which names neither the problem nor the
    fix. It survived unnoticed because CI passes attestations as files and the one inline
    fixture happened to contain a slash.
    """
    text = value.strip()
    if text.startswith("{"):
        raw = text
    else:
        try:
            candidate = Path(value)
            raw = candidate.read_text(encoding="utf-8") if candidate.is_file() else value
        except OSError as exc:
            raise ValueError(f"provenance evidence path is unreadable: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("provenance evidence must be a JSON object or a path to a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("provenance evidence must decode to a JSON object")
    return payload


def load_verified_attestation(
    value: str, *, assertion: str, input_path: Path, declared_value: str | None = None
) -> dict[str, Any]:
    """Validate build/strand provenance before it can unlock an array gate.

    Plain prose is intentionally insufficient.  The attestation must explicitly be
    VERIFICADO/SATISFIED, justify the assertion, name evidence references, retain a
    trace object, bind to the exact array input SHA-256, and name the value it
    establishes.  INFERIDO remains useful evidence, but cannot be silently promoted to
    verification by this gate.

    `asserted_value` is required and must equal `declared_value`.  Without it the checks
    above verify only that *an* attestation exists: `array_pipeline.provenance_probe` will
    correctly determine that a file is on the reverse strand and emit a properly formed,
    correctly bound attestation saying so, and paired with `--strand forward` that
    attestation used to pass every test here and unlock BUILD_STRAND_GATE.
    """
    payload = _load_json_value(value)
    prefix = f"{assertion} provenance"

    asserted = payload.get("asserted_value")
    if not isinstance(asserted, str) or not asserted.strip():
        raise ValueError(
            f"{prefix} must carry asserted_value naming the {assertion} it establishes; "
            "an attestation that does not say what it asserts cannot verify a declared value"
        )
    if declared_value is not None and _normalise(assertion, asserted) != _normalise(assertion, declared_value):
        raise ValueError(
            f"{prefix} attests {assertion}={asserted!r} but {declared_value!r} was declared; "
            "the evidence contradicts the claim it was supplied to support"
        )

    if payload.get("status") != "VERIFICADO":
        raise ValueError(f"{prefix} status must be VERIFICADO")
    if payload.get("decision") != "SATISFIED":
        raise ValueError(f"{prefix} decision must be SATISFIED")
    justification = payload.get("justification")
    if not isinstance(justification, str) or not justification.strip():
        raise ValueError(f"{prefix} justification is required")
    refs = payload.get("evidence_refs")
    if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or not x.strip() for x in refs):
        raise ValueError(f"{prefix} evidence_refs must contain one or more non-empty IDs")

    trace = payload.get("trace")
    if not isinstance(trace, dict):
        raise ValueError(f"{prefix} trace object is required")
    for field in ("attestation_id", "created_at", "actor_type", "actor_id", "method", "run_id"):
        if not isinstance(trace.get(field), str) or not trace[field].strip():
            raise ValueError(f"{prefix} trace.{field} is required")
    if trace.get("actor_type") not in ALLOWED_ACTOR_TYPES:
        raise ValueError(f"{prefix} trace.actor_type is invalid")
    try:
        datetime.fromisoformat(trace["created_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{prefix} trace.created_at must be ISO-8601") from exc
    tool_versions = trace.get("tool_versions")
    if not isinstance(tool_versions, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in tool_versions.items()):
        raise ValueError(f"{prefix} trace.tool_versions must be a string map")

    hashes = trace.get("input_sha256")
    if not isinstance(hashes, list) or any(not isinstance(x, str) or len(x) != 64 for x in hashes):
        raise ValueError(f"{prefix} trace.input_sha256 must contain SHA-256 hashes")
    actual_sha = _sha256_file(input_path.resolve())
    if actual_sha not in {x.lower() for x in hashes}:
        raise ValueError(f"{prefix} does not bind to the exact array input SHA-256")

    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="GENOMA v3.4 fail-closed SNP-array QC and baseline observation extractor")
    p.add_argument("--input", required=True)
    p.add_argument("--case-id", required=True)
    p.add_argument("--build", choices=["GRCh37", "GRCh38"])
    p.add_argument("--strand", choices=["forward", "plus", "+"])
    p.add_argument("--platform")
    p.add_argument("--build-evidence", help="verified structured JSON attestation or path; plain text is rejected")
    p.add_argument("--strand-evidence", help="verified structured JSON attestation or path; plain text is rejected")
    p.add_argument("--min-call-rate", type=float, default=0.95)
    p.add_argument("--max-overlap-conflict-rate", type=float, default=0.005)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()

    input_path = Path(args.input)
    try:
        build_attestation = (
            load_verified_attestation(
                args.build_evidence, assertion="build", input_path=input_path,
                declared_value=args.build,
            )
            if args.build_evidence else None
        )
        strand_attestation = (
            load_verified_attestation(
                args.strand_evidence, assertion="strand", input_path=input_path,
                declared_value=args.strand,
            )
            if args.strand_evidence else None
        )
    except (ValueError, OSError) as exc:
        raise SystemExit(f"NÃO DISPONÍVEL: {exc}")

    result = inspect_array(
        input_path,
        case_id=args.case_id,
        build=args.build,
        strand=args.strand,
        platform=args.platform,
        build_evidence=json.dumps(build_attestation, ensure_ascii=False, sort_keys=True) if build_attestation else None,
        strand_evidence=json.dumps(strand_attestation, ensure_ascii=False, sort_keys=True) if strand_attestation else None,
        min_call_rate=args.min_call_rate,
        max_overlap_conflict_rate=args.max_overlap_conflict_rate,
    )
    paths = write_outputs(result, Path(args.output_dir))
    ready = result["gates"]["LIMITED_INTERPRETATION_GATE"]["state"] == "PASS"
    print(json.dumps({"status": result["operational_status"], "ready": ready, "outputs": paths}, ensure_ascii=False))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
