#!/usr/bin/env python3
"""Regenerate the sealed inactive transport for a canonical GENOMA ruleset.

The repository never stores the active plaintext `VIGENTE` TXT. It stores a
deterministic `base64(gzip(raw, mtime=0, level=9))` transport split into fixed-size
chunks, plus a manifest of content hashes. `scripts/sealed_ruleset.py` is the only
reader; this is the only writer.

Sealing is a normative migration, not a routine edit: it is the step that makes a new
ruleset version the single VIGENTE source. It refuses to run unless the supplied file
matches the identity declared in `normative/__init__.py` byte for byte, so a wrong or
tampered artifact can never be sealed.

    python3 scripts/seal_ruleset.py --input /secure/REGRAS_..._v3.4_2026-08-17.txt
"""
from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative
from scripts.sealed_ruleset import sequential_sections, sha256_bytes

CHUNK_BYTES = 8000
SEALED_DIR = ROOT / "normative" / "sealed"


class SealError(RuntimeError):
    pass


def deterministic_gzip(raw: bytes) -> bytes:
    """gzip with mtime pinned to 0 so the transport is byte-reproducible."""

    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as handle:
        handle.write(raw)
    return buffer.getvalue()


def verify_source_identity(raw: bytes) -> None:
    digest = sha256_bytes(raw)
    if digest != normative.RAW_SHA256:
        raise SealError(
            "RULESET NÃO DISPONÍVEL/CONFLITANTE: source SHA-256 does not match the "
            f"declared canonical identity\n  expected {normative.RAW_SHA256}\n  observed {digest}"
        )
    if len(raw) != normative.RAW_SIZE_BYTES:
        raise SealError(f"source size mismatch: expected {normative.RAW_SIZE_BYTES}, observed {len(raw)}")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise SealError("canonical normative payload is not UTF-8") from exc
    header = set(text.splitlines()[:20])
    missing = sorted(set(normative.REQUIRED_HEADER_LINES) - header)
    if missing:
        raise SealError(f"canonical normative identity missing from header: {missing}")
    sections = sequential_sections(text)
    if sections != list(range(normative.SECTION_COUNT)):
        raise SealError(
            f"top-level section sequence mismatch: count={len(sections)} "
            f"last={sections[-1] if sections else None}"
        )


def build_manifest(raw: bytes) -> tuple[dict, list[bytes]]:
    compressed = deterministic_gzip(raw)
    encoded = base64.b64encode(compressed)
    chunks = [encoded[i : i + CHUNK_BYTES] for i in range(0, len(encoded), CHUNK_BYTES)]
    parts = [
        {
            "file": f"parts/part-{index:03d}.b64",
            "size_bytes": len(chunk),
            "sha256": sha256_bytes(chunk),
        }
        for index, chunk in enumerate(chunks)
    ]
    manifest = {
        "format": "genoma-sealed-normative-v1",
        "canonical_filename": normative.CANONICAL_FILENAME,
        "status": normative.STATUS,
        "version": normative.VERSION,
        "effective_date": normative.EFFECTIVE_DATE,
        "normative_identifier": normative.NORMATIVE_IDENTIFIER,
        "raw_sha256": sha256_bytes(raw),
        "raw_size_bytes": len(raw),
        "transport_encoding": "base64(gzip(raw,mtime=0,level=9))",
        "gzip_sha256": sha256_bytes(compressed),
        "gzip_size_bytes": len(compressed),
        "transport_sha256": sha256_bytes(encoded),
        "transport_size_bytes": len(encoded),
        "transport_sha256_scope": "ordered concatenation of compact base64 chunk payloads",
        "transport_parts": parts,
        "section_count": normative.SECTION_COUNT,
        "supersedes": dict(normative.SUPERSEDED),
        "active_at_rest": False,
        "activation_contract": (
            "materialize byte-exact canonical TXT at runtime, verify identity+hash+0-262, "
            "chmod 0444, mount read-only; never commit active plaintext ruleset"
        ),
    }
    return manifest, chunks


def write_sealed(manifest: dict, chunks: list[bytes], sealed_dir: Path) -> None:
    parts_dir = sealed_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    for stale in parts_dir.glob("part-*.b64"):
        stale.unlink()
    for index, chunk in enumerate(chunks):
        (parts_dir / f"part-{index:03d}.b64").write_bytes(chunk)
    (sealed_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="path to the canonical VIGENTE ruleset TXT")
    parser.add_argument("--sealed-dir", default=str(SEALED_DIR))
    parser.add_argument("--sha-manifest", default=str(ROOT / normative.SHA_MANIFEST_RELATIVE))
    args = parser.parse_args()

    raw = Path(args.input).read_bytes()
    verify_source_identity(raw)
    manifest, chunks = build_manifest(raw)
    write_sealed(manifest, chunks, Path(args.sealed_dir))

    sha_manifest = Path(args.sha_manifest)
    sha_manifest.parent.mkdir(parents=True, exist_ok=True)
    sha_manifest.write_text(
        f"{normative.RAW_SHA256}  {normative.CANONICAL_FILENAME}\n", encoding="ascii"
    )

    print(f"sealed {normative.CANONICAL_FILENAME}")
    print(f"  raw_sha256       {manifest['raw_sha256']}")
    print(f"  gzip_sha256      {manifest['gzip_sha256']}")
    print(f"  transport_sha256 {manifest['transport_sha256']}")
    print(f"  parts            {len(chunks)}")
    print(f"  sha manifest     {sha_manifest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
