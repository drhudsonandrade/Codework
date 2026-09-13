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
_REQUIRED_CLASS_IDS = frozenset({"P1", "P2", "P3", "P4"})
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


def _parse_policy_bytes(data: bytes) -> tuple[FingerprintClass, ...]:
    """Parse and validate fingerprint policy bytes from one authoritative tree."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PolicyError(f"unable to parse zero-identity policy: {exc}") from exc
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
    if seen_ids != _REQUIRED_CLASS_IDS:
        raise PolicyError("zero-identity policy must define exactly P1, P2, P3, and P4")
    return tuple(classes)


def load_policy(path: Path = DEFAULT_POLICY) -> tuple[FingerprintClass, ...]:
    """Load and validate a fingerprint policy from an explicit filesystem path."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PolicyError(f"unable to load zero-identity policy: {exc}") from exc
    return _parse_policy_bytes(data)


_ASCII_LOWER_TABLE = bytes.maketrans(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    b"abcdefghijklmnopqrstuvwxyz",
)


def _ascii_lower(data: bytes) -> bytes:
    """Lower only ASCII uppercase bytes without Unicode decoding."""
    return data.translate(_ASCII_LOWER_TABLE)


def _candidate_runs(data: bytes) -> Iterable[tuple[int, int]]:
    """Yield maximal lowercase-ASCII letter runs as half-open offsets."""
    run_start: int | None = None
    for index, byte in enumerate(data):
        is_letter = 97 <= byte <= 122
        if is_letter and run_start is None:
            run_start = index
        elif not is_letter and run_start is not None:
            yield run_start, index
            run_start = None
    if run_start is not None:
        yield run_start, len(data)


def _candidate_offsets(data: bytes, length: int) -> Iterable[int]:
    """Yield candidate windows for one length from the shared run iterator."""
    if length > len(data):
        return
    for run_start, run_end in _candidate_runs(data):
        run_length = run_end - run_start
        if run_length < length:
            continue
        yield from range(run_start, run_end - length + 1)


def _find_matches(data: bytes, classes: tuple[FingerprintClass, ...]) -> list[tuple[str, int]]:
    """Return class/offset matches without retaining matched bytes."""
    lowered = _ascii_lower(data)
    by_length: dict[int, dict[str, str]] = {}
    for item in classes:
        by_length.setdefault(item.length, {})[item.sha256] = item.class_id
    matches: list[tuple[str, int]] = []
    for run_start, run_end in _candidate_runs(lowered):
        run_length = run_end - run_start
        for length, digests in by_length.items():
            if run_length < length:
                continue
            for offset in range(run_start, run_end - length + 1):
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


def _read_index_blob(
    root: Path, path_bytes: bytes, classes: tuple[FingerprintClass, ...]
) -> bytes:
    """Read the exact stage-0 blob and mode recorded in the Git index."""
    path = path_bytes.decode("utf-8", "surrogateescape")
    safe_path = _safe_diagnostic_path(path, classes)
    try:
        indexed = subprocess.run(
            ["git", "ls-files", "-s", "-z", "--", path],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        raise RepositoryScanError(
            f"tracked index lookup failed for {safe_path}: git_exit={exc.returncode}"
        ) from exc
    except OSError as exc:
        raise RepositoryScanError(
            f"tracked index lookup failed for {safe_path}: {type(exc).__name__}"
        ) from exc
    entries = [part for part in indexed.stdout.split(b"\0") if part]
    if len(entries) != 1 or b"\t" not in entries[0]:
        raise RepositoryScanError(f"tracked index entry is ambiguous for {safe_path}")
    metadata, indexed_path = entries[0].split(b"\t", 1)
    fields = metadata.split()
    if len(fields) != 3 or indexed_path != path_bytes or fields[2] != b"0":
        raise RepositoryScanError(f"tracked index entry is invalid for {safe_path}")
    mode, object_id, _stage = fields
    if mode == b"120000":
        raise RepositoryScanError(f"tracked symlink is not allowed: {safe_path}")
    try:
        blob = subprocess.run(
            ["git", "cat-file", "blob", object_id.decode("ascii")],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        raise RepositoryScanError(
            f"tracked blob read failed for {safe_path}: git_exit={exc.returncode}"
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise RepositoryScanError(
            f"tracked blob read failed for {safe_path}: {type(exc).__name__}"
        ) from exc
    return blob.stdout


def _load_index_policy(root: Path) -> tuple[FingerprintClass, ...]:
    """Load the policy from the same stage-0 index that supplies scanned blobs."""
    data = _read_index_blob(
        root,
        b"config/zero_identity_policy.json",
        (),
    )
    return _parse_policy_bytes(data)


def _safe_diagnostic_path(path: str, classes: tuple[FingerprintClass, ...]) -> str:
    """Redact only path components that themselves contain prohibited fingerprints."""
    raw = path.encode("utf-8", "surrogateescape")
    safe: list[bytes] = []
    for component in raw.split(b"/"):
        if _find_matches(component, classes):
            digest = hashlib.sha256(component).hexdigest()[:12]
            safe.append(f"[redacted-{digest}]".encode("ascii"))
        else:
            safe.append(component)
    return b"/".join(safe).decode("utf-8", "surrogateescape")


def scan_repository(root: Path, policy_path: Path | None = None) -> list[Finding]:
    """Scan every tracked path and blob for fingerprint matches."""
    root = root.resolve()
    classes = load_policy(policy_path) if policy_path is not None else _load_index_policy(root)
    findings: list[Finding] = []
    for path_bytes in _tracked_paths(root):
        path = path_bytes.decode("utf-8", "surrogateescape")
        for class_id, offset in _find_matches(path_bytes, classes):
            findings.append(Finding(class_id, path, offset))
        blob = _read_index_blob(root, path_bytes, classes)
        for class_id, offset in _find_matches(blob, classes):
            findings.append(Finding(class_id, path, offset))
    return sorted(findings, key=lambda item: (item.path, item.offset, item.class_id))


def validate_zero_identity(root: Path) -> list[str]:
    """Return stable diagnostics using the same indexed policy as the scan."""
    root = root.resolve()
    classes = _load_index_policy(root)
    return [
        f"{item.class_id}\t{_safe_diagnostic_path(item.path, classes)}\tbyte_offset={item.offset}"
        for item in scan_repository(root)
    ]


def _inventory(
    findings: list[Finding],
    classes: tuple[FingerprintClass, ...],
) -> dict[str, object]:
    """Build a machine-readable inventory without prohibited path components."""
    records: dict[str, dict[str, object]] = {
        item.class_id: {"count": 0, "paths": []} for item in classes
    }
    for finding in findings:
        record = records[finding.class_id]
        record["count"] = int(record["count"]) + 1
        paths = record["paths"]
        assert isinstance(paths, list)
        safe_path = _safe_diagnostic_path(finding.path, classes)
        if safe_path not in paths:
            paths.append(safe_path)
    for record in records.values():
        paths = record["paths"]
        assert isinstance(paths, list)
        paths.sort()
    return {"schema": "omnigenis-zero-identity-inventory-v1", "classes": records}


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
        print(json.dumps(_inventory(findings, _load_index_policy(ROOT)), indent=2, sort_keys=True))
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
