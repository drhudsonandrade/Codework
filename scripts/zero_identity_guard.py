from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config/zero_identity_policy.json"
_SCHEMA = "omnigenis-zero-identity-policy-v1"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class PolicyError(ValueError):
    """Raised when the fingerprint policy is malformed or ambiguous."""


class RepositoryScanError(RuntimeError):
    """Raised when the tracked-tree scan cannot complete safely."""


@dataclass(frozen=True)
class FingerprintClass:
    class_id: str
    length: int
    sha256: str


@dataclass(frozen=True)
class Finding:
    class_id: str
    path: str
    offset: int


def load_policy(path: Path = DEFAULT_POLICY) -> tuple[FingerprintClass, ...]:
    """Load and validate the fingerprint-only repository policy."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"unable to load zero-identity policy: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != _SCHEMA:
        raise PolicyError("zero-identity policy schema mismatch")
    raw_classes = payload.get("classes")
    if not isinstance(raw_classes, list) or not raw_classes:
        raise PolicyError("zero-identity policy classes missing")

    classes: list[FingerprintClass] = []
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[int, str]] = set()
    for raw in raw_classes:
        if not isinstance(raw, dict):
            raise PolicyError("zero-identity policy class must be an object")
        class_id = raw.get("id")
        length = raw.get("length")
        digest = raw.get("sha256")
        if not isinstance(class_id, str) or not re.fullmatch(r"P[1-9][0-9]*", class_id):
            raise PolicyError("zero-identity class id invalid")
        if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            raise PolicyError(f"zero-identity class length invalid for {class_id}")
        if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
            raise PolicyError(f"zero-identity class digest invalid for {class_id}")
        pair = (length, digest)
        if class_id in seen_ids:
            raise PolicyError(f"duplicate zero-identity class id: {class_id}")
        if pair in seen_pairs:
            raise PolicyError("duplicate zero-identity fingerprint pair")
        seen_ids.add(class_id)
        seen_pairs.add(pair)
        classes.append(FingerprintClass(class_id, length, digest))
    return tuple(classes)


def _ascii_lower(data: bytes) -> bytes:
    """Lower only ASCII uppercase bytes without Unicode decoding."""
    return bytes(byte + 32 if 65 <= byte <= 90 else byte for byte in data)


def _candidate_offsets(data: bytes, length: int) -> Iterable[int]:
    """Yield windows that can match the alphabetic policy fingerprints."""
    if length > len(data):
        return
    run_start: int | None = None
    for index, byte in enumerate(data):
        is_letter = 97 <= byte <= 122
        if is_letter and run_start is None:
            run_start = index
        if not is_letter and run_start is not None:
            run_length = index - run_start
            for offset in range(run_start, run_start + max(0, run_length - length + 1)):
                yield offset
            run_start = None
    if run_start is not None:
        run_length = len(data) - run_start
        for offset in range(run_start, run_start + max(0, run_length - length + 1)):
            yield offset


def _find_matches(data: bytes, classes: tuple[FingerprintClass, ...]) -> list[tuple[str, int]]:
    """Return class/offset matches without retaining matched bytes."""
    lowered = _ascii_lower(data)
    by_length: dict[int, dict[str, str]] = {}
    for item in classes:
        by_length.setdefault(item.length, {})[item.sha256] = item.class_id
    matches: list[tuple[str, int]] = []
    for length, digests in by_length.items():
        for offset in _candidate_offsets(lowered, length):
            digest = hashlib.sha256(lowered[offset : offset + length]).hexdigest()
            class_id = digests.get(digest)
            if class_id is not None:
                matches.append((class_id, offset))
    return matches


def _tracked_paths(root: Path) -> list[bytes]:
    """Enumerate Git-tracked paths as raw bytes and fail closed on errors."""
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--cached"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RepositoryScanError(f"tracked-file enumeration failed: {exc}") from exc
    paths = [part for part in completed.stdout.split(b"\0") if part]
    if not paths:
        try:
            subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RepositoryScanError(f"repository verification failed: {exc}") from exc
    return paths


def scan_repository(root: Path, policy_path: Path | None = None) -> list[Finding]:
    """Scan every tracked path and blob for fingerprint matches."""
    root = root.resolve()
    classes = load_policy(policy_path or root / "config/zero_identity_policy.json")
    findings: list[Finding] = []
    for path_bytes in _tracked_paths(root):
        path = path_bytes.decode("utf-8", "surrogateescape")
        for class_id, offset in _find_matches(path_bytes, classes):
            findings.append(Finding(class_id, path, offset))
        target = root / path
        if target.is_symlink():
            raise RepositoryScanError(f"tracked symlink is not allowed: {path}")
        try:
            blob = target.read_bytes()
        except OSError as exc:
            raise RepositoryScanError(f"tracked blob read failed for {path}: {exc}") from exc
        for class_id, offset in _find_matches(blob, classes):
            findings.append(Finding(class_id, path, offset))
    return sorted(findings, key=lambda item: (item.path, item.offset, item.class_id))


def validate_zero_identity(root: Path) -> list[str]:
    """Return stable, non-sensitive diagnostics for all findings."""
    return [f"{item.class_id}\t{item.path}\tbyte_offset={item.offset}" for item in scan_repository(root)]


def _inventory(findings: list[Finding]) -> dict[str, object]:
    """Build a non-sensitive machine-readable inventory."""
    classes: dict[str, dict[str, object]] = {}
    for finding in findings:
        record = classes.setdefault(finding.class_id, {"count": 0, "paths": []})
        record["count"] = int(record["count"]) + 1
        paths = record["paths"]
        assert isinstance(paths, list)
        if finding.path not in paths:
            paths.append(finding.path)
    for record in classes.values():
        paths = record["paths"]
        assert isinstance(paths, list)
        paths.sort()
    return {"schema": "omnigenis-zero-identity-inventory-v1", "classes": classes}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for fail-closed repository validation and inventory."""
    parser = argparse.ArgumentParser(description="Validate the tracked-tree identity policy.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--inventory-json", action="store_true")
    args = parser.parse_args(argv)
    try:
        findings = scan_repository(ROOT)
    except (PolicyError, RepositoryScanError) as exc:
        print(f"FAIL\tzero_identity_guard\t{exc}", file=sys.stderr)
        return 2
    if args.inventory_json:
        print(json.dumps(_inventory(findings), indent=2, sort_keys=True))
        return 0
    if findings:
        print(f"FAIL\tzero_identity_guard\tfindings={len(findings)}", file=sys.stderr)
        for diagnostic in validate_zero_identity(ROOT):
            print(diagnostic, file=sys.stderr)
        return 1
    print("PASS\tzero_identity_guard\tfindings=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
