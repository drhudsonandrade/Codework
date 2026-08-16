#!/usr/bin/env python3
"""Materialize the byte-exact canonical GENOMA v3.3 TXT from an inactive sealed transport.

The sealed transport is safe to keep in source control because it is not an active
plaintext normative source. Activation is explicit, fail-closed, content-addressed,
and produces a mode-0444 canonical TXT for read-only mounting.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEALED_DIR = ROOT / "normative" / "sealed"
MANIFEST_PATH = SEALED_DIR / "MANIFEST.json"
EXPECTED_SHA = "187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a"
EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt"
EXPECTED_STATUS = "VIGENTE"
EXPECTED_VERSION = "v3.3"
EXPECTED_DATE = "14/08/2026"
EXPECTED_SECTIONS = 263


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sequential_sections(text: str) -> list[int]:
    expected = 0
    found: list[int] = []
    for raw in text.splitlines():
        match = re.match(r"^(\d+)\.\s+(.+?)\s*$", raw.strip())
        if not match:
            continue
        number = int(match.group(1))
        if number != expected:
            continue
        found.append(number)
        expected += 1
        if expected == EXPECTED_SECTIONS:
            break
    return found


def verify_identity(raw: bytes, manifest: dict[str, object]) -> dict[str, object]:
    digest = sha256_bytes(raw)
    if digest != EXPECTED_SHA or digest != manifest.get("raw_sha256"):
        raise RuntimeError(f"canonical raw SHA-256 mismatch: {digest}")
    text = raw.decode("utf-8")
    required_lines = {
        f"STATUS NORMATIVO: {EXPECTED_STATUS}",
        f"VERSÃO NORMATIVA: {EXPECTED_VERSION}",
        f"DATA FORMAL DE EMISSÃO E VIGÊNCIA: {EXPECTED_DATE}",
        f"ARQUIVO CANÔNICO: {EXPECTED_NAME}",
    }
    missing = sorted(line for line in required_lines if line not in text.splitlines()[:20])
    if missing:
        raise RuntimeError(f"canonical normative identity missing: {missing}")
    sections = sequential_sections(text)
    if sections != list(range(EXPECTED_SECTIONS)):
        raise RuntimeError(
            f"top-level section sequence mismatch: count={len(sections)} last={sections[-1] if sections else None}"
        )
    return {
        "status": EXPECTED_STATUS,
        "version": EXPECTED_VERSION,
        "effective_date": EXPECTED_DATE,
        "canonical_filename": EXPECTED_NAME,
        "raw_sha256": digest,
        "raw_size_bytes": len(raw),
        "section_count": len(sections),
        "section_range": [0, 262],
    }


def materialize(output_dir: Path) -> tuple[Path, dict[str, object]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("canonical_filename") != EXPECTED_NAME:
        raise RuntimeError("sealed manifest canonical filename mismatch")
    transport = SEALED_DIR / str(manifest.get("transport_file"))
    encoded = transport.read_bytes()
    if sha256_bytes(encoded) != manifest.get("transport_sha256"):
        raise RuntimeError("sealed transport SHA-256 mismatch")
    compressed = base64.b64decode(b"".join(encoded.split()), validate=True)
    if sha256_bytes(compressed) != manifest.get("gzip_sha256"):
        raise RuntimeError("sealed gzip SHA-256 mismatch")
    raw = gzip.decompress(compressed)
    metadata = verify_identity(raw, manifest)

    output_dir.mkdir(parents=True, exist_ok=True)
    active = []
    for candidate in output_dir.glob("REGRAS_PROJETO_GENOMA*.txt"):
        try:
            if re.search(r"^STATUS NORMATIVO:\s*VIGENTE\s*$", candidate.read_text(encoding="utf-8"), re.MULTILINE):
                active.append(candidate)
        except UnicodeDecodeError:
            pass
    if active:
        raise RuntimeError(f"refusing to activate beside an existing VIGENTE ruleset: {[p.name for p in active]}")

    target = output_dir / EXPECTED_NAME
    fd, tmp_name = tempfile.mkstemp(prefix=f".{EXPECTED_NAME}.", dir=output_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o444)
        os.replace(tmp_name, target)
    finally:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass
    if (target.stat().st_mode & 0o222) != 0:
        raise RuntimeError("materialized ruleset is writable")
    if sha256_bytes(target.read_bytes()) != EXPECTED_SHA:
        raise RuntimeError("post-write canonical ruleset SHA-256 mismatch")
    metadata.update(
        {
            "materialized_path": str(target),
            "mode_octal": oct(target.stat().st_mode & 0o777),
            "host": socket.gethostname(),
            "materialized_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "transport_sha256": manifest["transport_sha256"],
            "gzip_sha256": manifest["gzip_sha256"],
        }
    )
    return target, metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--evidence")
    args = parser.parse_args()
    target, evidence = materialize(Path(args.output_dir))
    payload = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if args.evidence:
        evidence_path = Path(args.evidence)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(payload, encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
