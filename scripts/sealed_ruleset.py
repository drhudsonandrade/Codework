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

import normative

EXPECTED_SHA = normative.RAW_SHA256
EXPECTED_NAME = normative.CANONICAL_FILENAME
EXPECTED_STATUS = normative.STATUS
EXPECTED_VERSION = normative.VERSION
EXPECTED_DATE = normative.EFFECTIVE_DATE
EXPECTED_SECTIONS = normative.SECTION_COUNT
EXPECTED_IDENTIFIER = normative.NORMATIVE_IDENTIFIER
EXPECTED_TRANSPORT_PARTS = tuple(f"parts/part-{index:03d}.b64" for index in range(13))
MANIFEST_NAME = "MANIFEST.json"


class SealedRulesetError(RuntimeError):
    """The sealed transport does not decode to the canonical ruleset, byte for byte.

    Every failure in this module is this one error: a missing part, a bad Base64 body, a
    digest mismatch and a truncated section list all mean the same thing operationally — the
    ruleset this run would use is not the one that was sealed, so nothing may proceed on it.
    """


def sha256_bytes(value: bytes) -> str:
    """SHA-256 of a byte string, as lowercase hex."""
    return hashlib.sha256(value).hexdigest()


def sequential_sections(text: str) -> list[int]:
    """Section numbers read from the ruleset, stopping at the first gap.

    The ruleset is numbered from zero without gaps, so the first number that is not the one
    expected ends the run. A caller compares the length against the declared section count:
    a body that decodes cleanly but stops numbering at 200 is truncated, and a digest check
    alone would not say where.
    """
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
    """Read the sealed manifest, refusing anything unreadable rather than defaulting.

    The manifest declares the part list, the sizes and the digests every other check in this
    module compares against, so a missing or malformed one leaves nothing to verify against
    and must stop the run rather than let it proceed unverified.
    """
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
    """Resolve one declared transport part, refusing any path that leaves `parts/`.

    The manifest is data, and a `file` entry of `../../etc/passwd` would otherwise be read
    and hashed as though it were transport. The name shape is checked and the resolved
    parent compared against the real `parts` directory, so a symlink cannot redirect it.
    """
    if not relative.startswith("parts/part-") or not relative.endswith(".b64"):
        raise SealedRulesetError(f"invalid sealed transport part path: {relative!r}")
    root = sealed_dir.resolve()
    candidate = (sealed_dir / relative).resolve()
    if candidate.parent != (root / "parts"):
        raise SealedRulesetError(f"sealed transport part escapes parts directory: {relative!r}")
    return candidate


def read_transport(sealed_dir: str | Path, manifest: dict[str, Any] | None = None) -> tuple[bytes, list[dict[str, Any]]]:
    """Concatenate the Base64 parts in canonical order, with per-part evidence.

    The declared part list must equal `EXPECTED_TRANSPORT_PARTS` exactly — same names, same
    order. Accepting a reordering or a subset would let a manifest choose which bytes are
    assembled, and the concatenation is what every later digest is taken over.
    """
    root = Path(sealed_dir)
    manifest = manifest or load_manifest(root)
    parts = manifest.get("transport_parts")
    if not isinstance(parts, list):
        raise SealedRulesetError("sealed transport must declare transport_parts as a list")
    declared_parts = [item.get("file") if isinstance(item, dict) else None for item in parts]
    if declared_parts != list(EXPECTED_TRANSPORT_PARTS):
        raise SealedRulesetError(
            "sealed transport must declare exactly parts/part-000.b64 through parts/part-012.b64 in canonical order"
        )

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
    """Check the decoded ruleset against every identity the project pins.

    Digest, size, decodability, header lines and section count are all checked, against the
    module's own constants *and* the manifest: a manifest that agrees with itself proves
    nothing, so the pinned `EXPECTED_SHA` is compared too.
    """
    digest = sha256_bytes(raw)
    if digest != EXPECTED_SHA or digest != manifest.get("raw_sha256"):
        raise SealedRulesetError(f"canonical raw SHA-256 mismatch: {digest}")
    if len(raw) != manifest.get("raw_size_bytes"):
        raise SealedRulesetError("canonical raw size mismatch")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise SealedRulesetError("canonical normative payload is not UTF-8") from exc
    # One contract, not a copy of it. This set used to be rebuilt here with four of the five
    # header lines — IDENTIFICADOR NORMATIVO was missing — yet the evidence below returns
    # `normative_identifier` from a module constant. A payload whose identifier line was
    # absent, wrong, or belonged to another ruleset therefore verified clean and was still
    # reported as carrying the expected identifier, which is the field a consumer reads to
    # learn *which* normative text it got. Reading the tuple `normative` already publishes
    # keeps the requirement and the emitted evidence from drifting apart again.
    required_lines = set(normative.REQUIRED_HEADER_LINES)
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
        "normative_identifier": EXPECTED_IDENTIFIER,
        "canonical_filename": EXPECTED_NAME,
        "raw_sha256": digest,
        "raw_size_bytes": len(raw),
        "section_count": len(sections),
        "section_range": [0, EXPECTED_SECTIONS - 1],
    }


def decode_verified_payload(sealed_dir: str | Path) -> tuple[bytes, dict[str, Any]]:
    """The canonical ruleset bytes, with the evidence gathered while verifying them.

    Nothing is returned until identity has been established, so a caller cannot hold the
    bytes before the checks that authorise using them have run.
    """
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
    """Verify the sealed transport and return only the evidence, discarding the bytes.

    For callers that need to know the transport is intact without holding the ruleset.
    """
    _, evidence = decode_verified_payload(sealed_dir)
    return evidence


def _active_vigente_files(output_dir: Path) -> list[Path]:
    """Ruleset files already present in the output directory that declare themselves VIGENTE.

    Materialising over one without checking would leave two files claiming to be the active
    ruleset, and which of them a reader picked up would depend on the glob order.
    """
    active: list[Path] = []
    for candidate in output_dir.glob("REGRAS_PROJETO_GENOMA*.txt"):
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError as exc:
            raise SealedRulesetError(f"could not read candidate active ruleset: {candidate}") from exc
        except UnicodeError:
            continue
        if re.search(r"^STATUS NORMATIVO:\s*VIGENTE\s*$", text, re.MULTILINE):
            active.append(candidate)
    return active


def _already_materialized(destination: Path, active: list[Path], raw: bytes) -> Path | None:
    """The one case where re-materializing is a safe no-op.

    Every condition must hold: exactly one active VIGENTE file, it is the canonical
    filename, it is a regular non-symlink file, its bytes are byte-identical to the
    verified sealed payload, and its permission bits are exactly 0444. Anything else —
    a second VIGENTE, a different filename, drifted bytes, a symlink or a different
    mode — is a conflict and must keep blocking.
    """
    if len(active) != 1:
        return None
    existing = active[0]
    if existing.name != EXPECTED_NAME or existing != destination / EXPECTED_NAME:
        return None
    if existing.is_symlink() or not existing.is_file():
        return None
    try:
        current = existing.read_bytes()
        mode = os.lstat(existing).st_mode & 0o777
    except OSError:
        return None
    if current != raw or sha256_bytes(current) != EXPECTED_SHA:
        return None
    if mode != 0o444:
        return None
    return existing


def materialize(sealed_dir: str | Path, output_dir: str | Path) -> tuple[Path, dict[str, Any]]:
    """Write the verified ruleset to disk, reusing an identical file already there.

    Provenance is established before anything on disk is read as trustworthy or written, and
    an existing VIGENTE file is only reused when its bytes match — otherwise it is a
    different ruleset wearing the canonical name and the run must not continue on it.
    """
    # Provenance is verified before anything on disk is trusted or written.
    raw, evidence = decode_verified_payload(sealed_dir)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    active = _active_vigente_files(destination)
    if active:
        reusable = _already_materialized(destination, active, raw)
        if reusable is None:
            raise SealedRulesetError(
                f"refusing to activate beside an existing VIGENTE ruleset: {[p.name for p in active]}"
            )
        mode = os.lstat(reusable).st_mode & 0o777
        evidence = dict(evidence)
        evidence.update(
            {
                "materialized_path": str(reusable),
                "mode_octal": oct(mode),
                "host": socket.gethostname(),
                "materialized_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "idempotent_reuse": True,
                "idempotent_reason": "canonical VIGENTE already materialized byte-identical to the verified sealed payload",
            }
        )
        return reusable, evidence

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

    if target.is_symlink() or not target.is_file():
        raise SealedRulesetError("materialized ruleset is not a regular file")
    mode = os.lstat(target).st_mode & 0o777
    if mode != 0o444:
        raise SealedRulesetError(f"materialized ruleset mode mismatch: {oct(mode)}")
    if sha256_bytes(target.read_bytes()) != EXPECTED_SHA:
        raise SealedRulesetError("post-write canonical ruleset SHA-256 mismatch")
    evidence = dict(evidence)
    evidence.update(
        {
            "materialized_path": str(target),
            "mode_octal": oct(mode),
            "host": socket.gethostname(),
            "materialized_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "idempotent_reuse": False,
        }
    )
    return target, evidence
