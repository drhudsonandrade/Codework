#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ngs_formats import FormatError, detect_container, probe_alignment, probe_fastq


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def fastq_probe(path: Path) -> tuple[bool, dict]:
    """Structurally read the first records, then hash. Delegates to `scripts.ngs_formats`.

    The probe itself is unchanged in what it verifies; the decompressor is now chosen by
    magic bytes rather than by `path.suffix == ".gz"`, so a bgzipped FASTQ named `.fastq`
    is read as the reads it holds instead of failing every record silently.
    """
    try:
        detail = probe_fastq(path)
    except FormatError as exc:
        return False, {"path": str(path), "reason": str(exc)}
    return True, {"path": str(path), **detail, "sha256": sha256_file(path)}


def alignment_probe(path: Path) -> tuple[bool, dict]:
    """Read the BAM/CRAM header, refusing a file that only carries the extension.

    This checked `is_file()` and `size > 0` and then recorded a SHA-256. A 32-byte text file
    named `fake.bam` passed with `status: VERIFICADO` and no errors — the gate certified as a
    verified alignment input a file containing one line of prose. Verified by doing it before
    closing it.
    """
    if not path.is_file() or path.stat().st_size == 0:
        return False, {"path": str(path), "reason": "missing_or_empty"}
    try:
        detail = probe_alignment(path)
    except FormatError as exc:
        return False, {
            "path": str(path),
            "detected": detect_container(path),
            "reason": str(exc),
        }
    return True, {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        **detail,
        "sha256": sha256_file(path),
    }


def validate_manifest(manifest_path: Path) -> dict:
    root = manifest_path.parent
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
        r1 = resolve(root, manifest.get("r1")); r2 = resolve(root, manifest.get("r2"))
        if r1 is None or r2 is None:
            errors.append("FASTQ requires r1 and r2")
        else:
            ok1, d1 = fastq_probe(r1); ok2, d2 = fastq_probe(r2)
            inputs["r1"] = d1; inputs["r2"] = d2
            if not ok1: errors.append("R1 integrity probe failed")
            if not ok2: errors.append("R2 integrity probe failed")
    elif input_type in {"BAM", "CRAM"}:
        alignment = resolve(root, manifest.get("alignment"))
        if alignment is None:
            errors.append(f"{input_type} requires an alignment path")
        else:
            ok, detail = alignment_probe(alignment)
            inputs["alignment"] = detail
            if not ok:
                errors.append(f"{input_type} integrity probe failed: {detail.get('reason')}")
            elif detail.get("format") != input_type:
                # The manifest says BAM and the bytes say CRAM, or the reverse. Neither is
                # trustworthy on its own; the disagreement is the finding.
                errors.append(
                    f"manifest declares {input_type} and the file is {detail.get('format')}"
                )
            else:
                # A BAM header that names read groups is checkable evidence about the same
                # sample the manifest claims. Where the two disagree the manifest is
                # describing a different file, which is exactly what this gate is for.
                declared = {str(rg.get("id")), str(rg.get("sample"))}
                observed = {
                    str(value)
                    for group in detail.get("read_groups") or []
                    for value in (group.get("id"), group.get("sample"))
                    if value
                }
                if observed and not (observed & declared):
                    errors.append(
                        f"read groups in the {input_type} header {sorted(observed)} do not "
                        f"include the manifest's id/sample {sorted(declared)}"
                    )

    return {
        "schema": "genoma-wgs-input-gate-v1",
        "status": "VERIFICADO" if not errors else "NÃO DISPONÍVEL",
        "sample_id": sample_id or None,
        "input_type": input_type or None,
        "read_group": rg,
        "inputs": inputs,
        "errors": errors,
        "note": "FASTQ, BAM and CRAM are read structurally here — magic bytes, BGZF framing, header text and read groups. Full-file integrity (samtools quickcheck, index consistency) is re-executed after alignment, before variant calling.",
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
