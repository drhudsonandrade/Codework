#!/usr/bin/env python3
"""Single implementation of the GENOMA v3.4 sealed normative transport contract.

The repository keeps the normative TXT inactive at rest as content-addressed Base64
chunks. This module is the ONLY implementation allowed to decode, verify, and
materialize that transport. Repository validation and production activation both call
this code so their contracts cannot drift independently.
"""
from __future__ import annotations

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
from typing import Any

EXPECTED_SHA = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_STATUS = "VIGENTE"
EXPECTED_VERSION = "v3.4"
EXPECTED_DATE = "17/08/2026"
EXPECTED_SECTIONS = 263
MANIFEST_NAME = "MANIFEST.json"


class SealedRulesetError(RuntimeError):
    pass


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


def load_manifest(sealed_dir: str | Path) -> dict[str, Any]:
    root = Path(sealed_dir)
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise SealedRulesetError(f"sealed manifest not found: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SealedRulesetError(f"sealed manifest invalid: {type(exc).__name__}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SealedRulesetError("sealed manifest must be a JSON object")
    if manifest.get("active_at_rest") is not False:
        raise SealedRulesetError("sealed normative transport must declare active_at_rest=false")
    if manifest.get("canonical_filename") != EXPECTED_NAME:
        raise SealedRulesetError("sealed manifest canonical filename mismatch")
    if manifest.get("status") != EXPECTED_STATUS:
        raise SealedRulesetError("sealed manifest status mismatch")
    if manifest.get("version") != EXPECTED_VERSION:
        raise SealedRulesetError("sealed manifest version mismatch")
    if manifest.get("effective_date") != EXPECTED_DATE:
        raise SealedRulesetError("sealed manifest effective date mismatch")
    if manifest.get("raw_sha256") != EXPECTED_SHA:
        raise SealedRulesetError("sealed manifest raw SHA-256 mismatch")
    return manifest


def _safe_part_path(sealed_dir: Path, relative: str) -> Path:
    if not relative.startswith("parts/part-") or not relative.endswith(".b64"):
        raise SealedRulesetError(f"invalid sealed transport part path: {relative!r}")
    root = sealed_dir.resolve()
    candidate = (sealed_dir / relative).resolve()
    if candidate.parent != (root / "parts"):
        raise SealedRulesetError(f"sealed transport part escapes parts directory: {relative!r}")
    return candidate


def read_transport(sealed_dir: str | Path, manifest: dict[str, Any] | None = None) -> tuple[bytes, list[dict[str, Any]]]:
    root = Path(sealed_dir)
    manifest = manifest or load_manifest(root)
    parts = manifest.get("transport_parts")
    if not isinstance(parts, list) or not parts:
        raise SealedRulesetError("sealed transport must declare one or more chunks")

    assembled: list[bytes] = []
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(parts):
        if not isinstance(item, dict):
            raise SealedRulesetError(f"sealed transport part[{index}] manifest is malformed")
        relative = item.get("file")
        if not isinstance(relative, str):
            raise SealedRulesetError(f"sealed transport part[{index}] path is missing")
        if relative in seen:
            raise SealedRulesetError(f"sealed transport part duplicated: {relative}")
        seen.add(relative)
        path = _safe_part_path(root, relative)
        if not path.is_file():
            raise SealedRulesetError(f"sealed transport part missing: {relative}")
        compact = b"".join(path.read_bytes().split())
        expected_size = item.get("size_bytes")
        expected_sha = item.get("sha256")
        if len(compact) != expected_size:
            raise SealedRulesetError(f"sealed transport part[{index}] size mismatch")
        observed_sha = sha256_bytes(compact)
        if observed_sha != expected_sha:
            raise SealedRulesetError(f"sealed transport part[{index}] SHA-256 mismatch")
        assembled.append(compact)
        evidence.append({"index": index, "file": relative, "size_bytes": len(compact), "sha256": observed_sha})

    encoded = b"".join(assembled)
    if len(encoded) != manifest.get("transport_size_bytes"):
        raise SealedRulesetError("sealed transport aggregate size mismatch")
    if sha256_bytes(encoded) != manifest.get("transport_sha256"):
        raise SealedRulesetError("sealed transport aggregate SHA-256 mismatch")
    return encoded, evidence


def _verify_identity(raw: bytes, manifest: dict[str, Any]) -> dict[str, Any]:
    digest = sha256_bytes(raw)
    if digest != EXPECTED_SHA or digest != manifest.get("raw_sha256"):
        raise SealedRulesetError(f"canonical raw SHA-256 mismatch: {digest}")
    if len(raw) != manifest.get("raw_size_bytes"):
        raise SealedRulesetError("canonical raw size mismatch")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise SealedRulesetError("canonical normative payload is not UTF-8") from exc
    required_lines = {
        f"STATUS NORMATIVO: {EXPECTED_STATUS}",
        f"VERSÃO NORMATIVA: {EXPECTED_VERSION}",
        f"DATA FORMAL DE EMISSÃO E VIGÊNCIA: {EXPECTED_DATE}",
        f"ARQUIVO CANÔNICO: {EXPECTED_NAME}",
    }
    header = set(text.splitlines()[:20])
    missing = sorted(required_lines - header)
    if missing:
        raise SealedRulesetError(f"canonical normative identity missing: {missing}")
    sections = sequential_sections(text)
    if sections != list(range(EXPECTED_SECTIONS)):
        raise SealedRulesetError(
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


def decode_verified_payload(sealed_dir: str | Path) -> tuple[bytes, dict[str, Any]]:
    root = Path(sealed_dir)
    manifest = load_manifest(root)
    encoded, part_evidence = read_transport(root, manifest)
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise SealedRulesetError("sealed transport is not valid Base64") from exc
    if len(compressed) != manifest.get("gzip_size_bytes"):
        raise SealedRulesetError("sealed gzip size mismatch")
    gzip_sha = sha256_bytes(compressed)
    if gzip_sha != manifest.get("gzip_sha256"):
        raise SealedRulesetError("sealed gzip SHA-256 mismatch")
    try:
        raw = gzip.decompress(compressed)
    except (OSError, gzip.BadGzipFile) as exc:
        raise SealedRulesetError("sealed gzip payload is invalid") from exc
    evidence = _verify_identity(raw, manifest)
    evidence.update(
        {
            "transport_sha256": manifest["transport_sha256"],
            "transport_size_bytes": len(encoded),
            "gzip_sha256": gzip_sha,
            "gzip_size_bytes": len(compressed),
            "transport_parts": part_evidence,
        }
    )
    return raw, evidence


def verify_transport(sealed_dir: str | Path) -> dict[str, Any]:
    _, evidence = decode_verified_payload(sealed_dir)
    return evidence


def _active_vigente_files(output_dir: Path) -> list[Path]:
    active: list[Path] = []
    for candidate in output_dir.glob("REGRAS_PROJETO_GENOMA*.txt"):
        try:
            text = candidate.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        if re.search(r"^STATUS NORMATIVO:\s*VIGENTE\s*$", text, re.MULTILINE):
            active.append(candidate)
    return active


def materialize(sealed_dir: str | Path, output_dir: str | Path) -> tuple[Path, dict[str, Any]]:
    raw, evidence = decode_verified_payload(sealed_dir)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    active = _active_vigente_files(destination)
    if active:
        raise SealedRulesetError(
            f"refusing to activate beside an existing VIGENTE ruleset: {[p.name for p in active]}"
        )

    target = destination / EXPECTED_NAME
    fd, tmp_name = tempfile.mkstemp(prefix=f".{EXPECTED_NAME}.", dir=destination)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o444)
        os.replace(tmp_name, target)
    finally:
        Path(tmp_name).unlink(missing_ok=True)

    mode = target.stat().st_mode & 0o777
    if mode & 0o222:
        raise SealedRulesetError("materialized ruleset is writable")
    if sha256_bytes(target.read_bytes()) != EXPECTED_SHA:
        raise SealedRulesetError("post-write canonical ruleset SHA-256 mismatch")
    evidence = dict(evidence)
    evidence.update(
        {
            "materialized_path": str(target),
            "mode_octal": oct(mode),
            "host": socket.gethostname(),
            "materialized_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    )
    return target, evidence
