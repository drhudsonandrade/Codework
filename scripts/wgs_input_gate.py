#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import gzip
import hashlib
import io
import json
import os
from pathlib import Path


def _sha256_stream(handle) -> str:
    """Hash an already-open handle from its start, leaving it rewound."""
    handle.seek(0)
    h = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        h.update(chunk)
    handle.seek(0)
    return h.hexdigest()


def open_contained(root: Path, path: Path):
    """Open a validated input by walking down from the root, one component at a time.

    Containment is checked against a *path*, and every later step used to reopen that path by
    name — probe it, hash it, size it. Between the check and each of those opens the name can
    be repointed, so the bytes recorded as this sample's input were not provably the bytes
    that passed containment.

    Opening the final component with `O_NOFOLLOW` is not enough on its own: given
    `nested/r1.fastq`, `nested` itself can be swapped for a link to somewhere else after
    `resolve` accepted the path, and the final open then lands on an outside file that is a
    perfectly ordinary regular file. So the walk starts at the trusted root and opens each
    component relative to the previous one with `dir_fd`, refusing a symlink at every step,
    directories included. The descriptor that comes back is the one every consumer uses;
    nothing re-looks-up a name afterwards.
    """
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("input path escapes the sample directory") from exc
    parts = relative.parts
    if not parts:
        raise ValueError("input path names no file")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    open_fds: list[int] = []
    try:
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        open_fds.append(parent)
        for component in parts[:-1]:
            parent = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=parent,
            )
            open_fds.append(parent)
        descriptor = os.open(parts[-1], os.O_RDONLY | nofollow, dir_fd=parent)
    except OSError as exc:
        raise ValueError(f"input could not be opened: {exc}") from exc
    finally:
        for fd in open_fds:
            os.close(fd)
    return os.fdopen(descriptor, "rb")


def resolve(root: Path, value: str | None) -> Path | None:
    """Resolve a manifest-declared input without granting ambient filesystem authority.

    The manifest is sample-supplied, so an absolute path or a `../` chain must not let it
    name a file outside the sample directory that the gate would then hash and record as a
    verified input. Symlinks are followed before the containment check, so a link planted
    inside the sample directory cannot reach out either.

    Every refusal is a ValueError, so `validate_manifest` has one exception type to catch and
    the gate always answers with a status rather than a traceback.
    """
    # Type before emptiness, in that order. The manifest is JSON, so a path field can arrive
    # as a number, a bool, a list or an object, and `Path()` raises TypeError on all of them.
    # Testing `not value` first also swallowed every *falsy* non-string — False, 0, 0.0, [],
    # {} — as though the field had been left out, which reports "FASTQ requires r1 and r2"
    # for a manifest that did supply r1, just not as text. A missing field and a wrong type
    # are different facts and the gate now says which one it found.
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"input path must be a string, got {type(value).__name__}")
    raw = Path(value)
    if raw.is_absolute():
        raise ValueError("absolute input paths are not allowed in sample-manifest.json")
    try:
        absolute_root = root.resolve()
        candidate = (absolute_root / raw).resolve()
    except (OSError, RuntimeError) as exc:
        # `Path.resolve()` raises RuntimeError on a symlink loop and OSError on other
        # filesystem failures. Left uncaught, the call added here to *enforce* containment
        # was itself a way to kill the gate before it could report NÃO DISPONÍVEL.
        raise ValueError(f"input path could not be resolved: {exc}") from exc
    try:
        candidate.relative_to(absolute_root)
    except ValueError as exc:
        raise ValueError("input path escapes the sample directory") from exc
    # Version-independent loop detection. `Path.resolve()` raises RuntimeError on a symlink
    # loop up to Python 3.12; from 3.13 the non-strict form raises nothing and returns a
    # partially resolved path instead, so the handler above would never fire and the loop
    # would only surface later, as an ELOOP at open time. `stat` reports ELOOP on every
    # supported version, and a path that simply does not exist yet is not this check's
    # business — the probe reports that separately.
    try:
        candidate.stat()
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"input path could not be resolved: {exc}") from exc
    return candidate


def fastq_probe(root: Path, path: Path) -> tuple[bool, dict]:
    """Probe and hash one FASTQ through a single open handle.

    The probe and the hash used to open the path separately, so the bytes recorded as this
    sample's input were not provably the bytes the probe accepted.
    """
    try:
        raw = open_contained(root, path)
    except ValueError:
        return False, {"path": str(path), "reason": "missing_or_empty"}
    try:
        with raw:
            if os.fstat(raw.fileno()).st_size == 0:
                return False, {"path": str(path), "reason": "missing_or_empty"}
            stream = gzip.GzipFile(fileobj=raw) if path.suffix == ".gz" else raw
            handle = io.TextIOWrapper(stream, encoding="utf-8", errors="strict")
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
            handle.detach()
            return True, {
                "path": str(path),
                "probe_records": len(records),
                "sha256": _sha256_stream(raw),
            }
    except (OSError, EOFError, UnicodeError, gzip.BadGzipFile) as exc:
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
    # A refused path is already a reported error; re-reporting it as "missing" would
    # describe a containment breach as an absent file.
    refused = False
    if input_type == "FASTQ":
        try:
            r1 = resolve(root, manifest.get("r1"))
            r2 = resolve(root, manifest.get("r2"))
        except ValueError as exc:
            r1 = r2 = None
            refused = True
            errors.append(str(exc))
        if r1 is None or r2 is None:
            if not refused:
                errors.append("FASTQ requires r1 and r2")
        else:
            ok1, d1 = fastq_probe(root, r1)
            ok2, d2 = fastq_probe(root, r2)
            inputs["r1"] = d1
            inputs["r2"] = d2
            if not ok1:
                errors.append("R1 integrity probe failed")
            if not ok2:
                errors.append("R2 integrity probe failed")
    elif input_type in {"BAM", "CRAM"}:
        try:
            alignment = resolve(root, manifest.get("alignment"))
        except ValueError as exc:
            alignment = None
            refused = True
            errors.append(str(exc))
        # Size and hash from one handle, for the same reason as the FASTQ path: `stat` then
        # `open` is two lookups of a name that was validated once.
        alignment_size = None
        if alignment is not None:
            try:
                with open_contained(root, alignment) as handle:
                    alignment_size = os.fstat(handle.fileno()).st_size
                    alignment_sha = _sha256_stream(handle) if alignment_size else None
            except (ValueError, OSError):
                alignment_size = None
        if alignment is None or not alignment_size:
            if not refused:
                errors.append(f"{input_type} alignment missing_or_empty")
        else:
            inputs["alignment"] = {
                "path": str(alignment),
                "size_bytes": alignment_size,
                "sha256": alignment_sha,
            }

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
