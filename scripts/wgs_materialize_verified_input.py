#!/usr/bin/env python3
"""Materialize one gate-verified WGS input through the secure containment opener."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from wgs_input_gate import InputMissing, InputRefused, InputUnreadable, open_contained

DIGEST_MISMATCH = 4
INPUT_UNAVAILABLE = 3
INVALID_ARGUMENT = 2


def _unlink_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def materialize(root: Path, source_path: Path, expected_sha256: str, output: Path) -> int:
    """Copy a securely opened regular input to a private stage file and verify its digest."""
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        print("NÃO DISPONÍVEL: invalid expected SHA-256", file=sys.stderr)
        return INVALID_ARGUMENT

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        print("NÃO DISPONÍVEL: O_NOFOLLOW unavailable for verified staging", file=sys.stderr)
        return INPUT_UNAVAILABLE

    try:
        source = open_contained(root, source_path)
    except (InputMissing, InputRefused, InputUnreadable, OSError, ValueError) as exc:
        print(f"NÃO DISPONÍVEL: verified input cannot be opened safely: {type(exc).__name__}", file=sys.stderr)
        return INPUT_UNAVAILABLE

    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    try:
        descriptor = os.open(
            output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
        )
    except OSError as exc:
        source.close()
        print(f"NÃO DISPONÍVEL: verified staging file cannot be created: {type(exc).__name__}", file=sys.stderr)
        return INPUT_UNAVAILABLE

    try:
        with source, os.fdopen(descriptor, "wb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    except (OSError, ValueError) as exc:
        _unlink_if_present(output)
        print(f"NÃO DISPONÍVEL: verified input staging failed: {type(exc).__name__}", file=sys.stderr)
        return INPUT_UNAVAILABLE

    if digest.hexdigest() != expected:
        _unlink_if_present(output)
        return DIGEST_MISMATCH
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    return materialize(
        Path(args.root),
        Path(args.source),
        args.expected_sha256,
        Path(args.output),
    )


if __name__ == "__main__":
    raise SystemExit(main())
