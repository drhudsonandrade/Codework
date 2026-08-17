#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve(root: Path, value: str | None) -> Path | None:
    """Resolve a manifest-owned path without granting ambient filesystem authority."""
    if not value:
        return None
    raw = Path(value)
    if raw.is_absolute():
        raise ValueError("absolute input paths are not allowed in sample-manifest.json")
    absolute_root = root.resolve()
    candidate = (absolute_root / raw).resolve()
    try:
        candidate.relative_to(absolute_root)
    except ValueError as exc:
        raise ValueError("input path escapes the sample directory") from exc
    return candidate


def fastq_probe(path: Path) -> tuple[bool, dict]:
    if not path.is_file() or path.stat().st_size == 0:
        return False, {"path": str(path), "reason": "missing_or_empty"}
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="strict") as handle:
            records = []
            for _ in range(128):
                row = [handle.readline() for __ in range(4)]
                if row[0] == "":
                    break
                if any(part == "" for part in row) or not row[0].startswith("@") or not row[2].startswith("+") or len(row[1].strip()) != len(row[3].strip()):
                    return False, {"path": str(path), "reason": "malformed_fastq_probe"}
                records.append(row[0].strip().split()[0])
        if not records:
            return False, {"path": str(path), "reason": "no_records"}
        return True, {"path": str(path), "probe_records": len(records), "sha256": sha256_file(path)}
    except (OSError, UnicodeError) as exc:
        return False, {"path": str(path), "reason": type(exc).__name__}


def validate_manifest(manifest_path: Path) -> dict:
    root = manifest_path.parent.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    sample_id = str(manifest.get("sample_id") or "").strip()
    input_type = str(manifest.get("input_type") or "").upper()
    rg = manifest.get("read_group") if isinstance(manifest.get("read_group"), dict) else {}
    if not sample_id:
        errors.append("sample_id missing")
    if input_type not in {"FASTQ", "BAM", "CRAM"}:
        errors.append("input_type must be FASTQ, BAM, or CRAM")
    required_rg = ("id", "sample", "library", "platform")
    for key in required_rg:
        if not str(rg.get(key) or "").strip():
            errors.append(f"read_group.{key} missing")
    if sample_id and str(rg.get("sample") or "") != sample_id:
        errors.append("read_group.sample must equal sample_id")

    inputs: dict[str, dict] = {}
    if input_type == "FASTQ":
        try:
            r1 = resolve(root, manifest.get("r1")); r2 = resolve(root, manifest.get("r2"))
        except ValueError as exc:
            r1 = r2 = None
            errors.append(str(exc))
        if r1 is None or r2 is None:
            if not any("path" in error for error in errors):
                errors.append("FASTQ requires r1 and r2")
        else:
            ok1, d1 = fastq_probe(r1); ok2, d2 = fastq_probe(r2)
            inputs["r1"] = d1; inputs["r2"] = d2
            if not ok1: errors.append("R1 integrity probe failed")
            if not ok2: errors.append("R2 integrity probe failed")
    elif input_type in {"BAM", "CRAM"}:
        try:
            alignment = resolve(root, manifest.get("alignment"))
        except ValueError as exc:
            alignment = None
            errors.append(str(exc))
        if alignment is None or not alignment.is_file() or alignment.stat().st_size == 0:
            if not any("path" in error for error in errors):
                errors.append(f"{input_type} alignment missing_or_empty")
        else:
            inputs["alignment"] = {"path": str(alignment), "size_bytes": alignment.stat().st_size, "sha256": sha256_file(alignment)}

    return {
        "schema": "genoma-wgs-input-gate-v1",
        "status": "VERIFICADO" if not errors else "NÃO DISPONÍVEL",
        "sample_id": sample_id or None,
        "input_type": input_type or None,
        "read_group": rg,
        "inputs": inputs,
        "errors": errors,
        "note": "FASTQ is probed here; complete BAM/CRAM/read-group integrity is re-executed after alignment before variant calling.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = validate_manifest(Path(args.manifest))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "VERIFICADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
