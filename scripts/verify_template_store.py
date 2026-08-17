#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import lzma
import shutil
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "template_store" / "v3.0"
MANIFEST = STORE / "MANIFEST.json"
REFERENCE = ROOT / "reporting" / "reference_v3_manifest.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(*, materialize: Path | None = None, allow_sealed_only: bool = False) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    reports = manifest.get("reports", {})
    if set(reports) != {f"{i:02d}" for i in range(1, 12)}:
        raise ValueError("template store must define exactly reports 01..11")
    if set(reference.get("reports", {})) != set(reports):
        raise ValueError("reference manifest report IDs differ from template store")
    for rid, meta in reports.items():
        ref = reference["reports"][rid]
        for field in ("filename", "sha256", "size_bytes", "page_count"):
            if meta.get(field) != ref.get(field):
                raise ValueError(f"report {rid} {field} differs from verified reference identity")

    storage = manifest.get("storage", {})
    parts_dir = ROOT / storage.get("parts_dir", "")
    parts = manifest.get("parts", [])
    expected_count = int(storage.get("part_count", 0))
    if len(parts) != expected_count:
        raise ValueError("manifest part_count differs from parts list")

    missing: list[str] = []
    bad: list[str] = []
    payload_parts: list[bytes] = []
    for part in parts:
        p = parts_dir / part["name"]
        if not p.is_file():
            missing.append(part["name"])
            continue
        data = p.read_bytes()
        if len(data) != part["size_bytes"] or sha256_bytes(data) != part["sha256"]:
            bad.append(part["name"])
        payload_parts.append(data)

    if bad:
        raise ValueError(f"sealed template part integrity failure: {bad}")
    if missing:
        if allow_sealed_only:
            return {
                "schema": "genoma-template-store-verification-v1",
                "operational_status": "NÃO DISPONÍVEL",
                "manifest_identity": "VERIFICADO",
                "binary_materialization": "NÃO DISPONÍVEL",
                "reports": 11,
                "missing_parts": missing,
                "reason": "GitHub source identities are sealed, but binary source parts are not materialized in this checkout.",
            }
        raise ValueError(f"sealed template source parts missing: {missing[:5]}{'...' if len(missing)>5 else ''}")

    b64 = b"".join(payload_parts)
    if len(b64) != storage["base64_size_bytes"]:
        raise ValueError("sealed base64 payload size mismatch")
    archive = base64.b64decode(b64, validate=True)
    if len(archive) != storage["decoded_archive_size_bytes"] or sha256_bytes(archive) != storage["decoded_archive_sha256"]:
        raise ValueError("decoded template archive identity mismatch")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        archive_path = tmp / storage["decoded_archive"]
        archive_path.write_bytes(archive)
        with lzma.open(archive_path, "rb") as xz, tarfile.open(fileobj=xz, mode="r|") as tf:
            extracted: dict[str, bytes] = {}
            for member in tf:
                if not member.isfile():
                    continue
                handle = tf.extractfile(member)
                if handle is None:
                    continue
                extracted[Path(member.name).name] = handle.read()
        if set(extracted) != {m["filename"] for m in reports.values()}:
            raise ValueError("archive member set is not exactly the 11 approved templates")
        for rid, meta in reports.items():
            data = extracted[meta["filename"]]
            if len(data) != meta["size_bytes"] or sha256_bytes(data) != meta["sha256"]:
                raise ValueError(f"materialized template {rid} differs from immutable identity")
        if materialize is not None:
            materialize.mkdir(parents=True, exist_ok=True)
            for meta in reports.values():
                (materialize / meta["filename"]).write_bytes(extracted[meta["filename"]])

    return {
        "schema": "genoma-template-store-verification-v1",
        "operational_status": "VERIFICADO",
        "manifest_identity": "VERIFICADO",
        "binary_materialization": "VERIFICADO",
        "reports": 11,
        "archive_sha256": storage["decoded_archive_sha256"],
        "parts": len(parts),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--materialize")
    p.add_argument("--allow-sealed-only", action="store_true")
    args = p.parse_args()
    try:
        result = verify(materialize=Path(args.materialize) if args.materialize else None, allow_sealed_only=args.allow_sealed_only)
    except Exception as exc:
        print(f"NÃO DISPONÍVEL: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
