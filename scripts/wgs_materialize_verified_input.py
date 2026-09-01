#!/usr/bin/env python3
"""Materialize one gate-verified WGS input through the secure containment opener."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from wgs_input_gate import InputMissing, InputRefused, InputUnreadable, open_contained

INVALID_ARGUMENT = 2
STAGING_UNAVAILABLE = 3
DIGEST_MISMATCH = 4
INPUT_REFUSED = 5
INPUT_MISSING = 6
INPUT_UNREADABLE = 7

_EXIT_CODES = {
    "INVALID_ARGUMENT": INVALID_ARGUMENT,
    "STAGING_UNAVAILABLE": STAGING_UNAVAILABLE,
    "DIGEST_MISMATCH": DIGEST_MISMATCH,
    "INPUT_REFUSED": INPUT_REFUSED,
    "INPUT_MISSING": INPUT_MISSING,
    "INPUT_UNREADABLE": INPUT_UNREADABLE,
}


def exit_code_contract() -> dict[str, int]:
    """Return the single machine-readable authority for shell-visible exit codes."""
    return dict(_EXIT_CODES)


def _unlink_if_present(path: Path) -> OSError | None:
    """Best-effort cleanup whose failure remains explicit to the caller."""
    try:
        path.unlink()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return exc
    return None


def _close_source(source) -> None:
    try:
        source.close()
    except OSError:
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
        return STAGING_UNAVAILABLE

    try:
        source = open_contained(root, source_path)
    except InputRefused as exc:
        print(f"NÃO DISPONÍVEL: verified input refused by secure containment: {exc}", file=sys.stderr)
        return INPUT_REFUSED
    except InputMissing as exc:
        print(f"NÃO DISPONÍVEL: verified input is missing: {exc}", file=sys.stderr)
        return INPUT_MISSING
    except InputUnreadable as exc:
        print(f"NÃO DISPONÍVEL: verified input is unreadable: {exc}", file=sys.stderr)
        return INPUT_UNREADABLE
    except OSError as exc:
        print(
            f"NÃO DISPONÍVEL: verified input open failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return INPUT_UNREADABLE

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _close_source(source)
        print(
            f"NÃO DISPONÍVEL: verified staging directory unavailable: {type(exc).__name__}",
            file=sys.stderr,
        )
        return STAGING_UNAVAILABLE

    digest = hashlib.sha256()
    try:
        descriptor = os.open(
            output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
        )
    except OSError as exc:
        _close_source(source)
        print(
            f"NÃO DISPONÍVEL: verified staging file cannot be created: {type(exc).__name__}",
            file=sys.stderr,
        )
        return STAGING_UNAVAILABLE

    try:
        with source, os.fdopen(descriptor, "wb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    except (OSError, ValueError) as exc:
        cleanup_error = _unlink_if_present(output)
        if cleanup_error is not None:
            print(
                "NÃO DISPONÍVEL: verified staging cleanup unavailable after copy failure: "
                f"{type(cleanup_error).__name__}",
                file=sys.stderr,
            )
            return STAGING_UNAVAILABLE
        print(
            f"NÃO DISPONÍVEL: verified input staging failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return STAGING_UNAVAILABLE

    if digest.hexdigest() != expected:
        cleanup_error = _unlink_if_present(output)
        if cleanup_error is not None:
            print(
                "NÃO DISPONÍVEL: verified staging cleanup unavailable after digest mismatch: "
                f"{type(cleanup_error).__name__}",
                file=sys.stderr,
            )
            return STAGING_UNAVAILABLE
        return DIGEST_MISMATCH
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-exit-codes", action="store_true")
    parser.add_argument("--root")
    parser.add_argument("--source")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--output")
    args = parser.parse_args()

    if args.print_exit_codes:
        print(json.dumps(exit_code_contract(), sort_keys=True, separators=(",", ":")))
        return 0

    required = {
        "--root": args.root,
        "--source": args.source,
        "--expected-sha256": args.expected_sha256,
        "--output": args.output,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        parser.error(f"the following arguments are required: {', '.join(missing)}")

    return materialize(
        Path(args.root),
        Path(args.source),
        args.expected_sha256,
        Path(args.output),
    )


if __name__ == "__main__":
    raise SystemExit(main())
