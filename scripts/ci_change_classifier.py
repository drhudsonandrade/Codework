#!/usr/bin/env python3
"""Deterministic path classification for targeted GitHub Actions jobs."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

POLICY_EXACT = {
    "manifests/RULESET_V3.4.sha256",
    "scripts/validate_repo.py",
    "scripts/verify_supply_chain_lock.py",
    "scripts/materialize_ruleset.py",
    "scripts/sealed_ruleset.py",
    "scripts/ci_change_classifier.py",
    "scripts/run_live_post_deployment_smoke.py",
    ".github/workflows/genoma-policy-engine.yml",
}
POLICY_PREFIXES = ("normative/", "policy_engine/", "locks/", "template_store/", "adapters/")


def _normalize(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def policy_relevant(paths: Iterable[str]) -> bool:
    for raw_path in paths:
        path = _normalize(raw_path)
        if path in POLICY_EXACT or path.startswith(POLICY_PREFIXES):
            return True
    return False


def validation_required(changed_paths: Iterable[str], deleted_paths: Iterable[str]) -> bool:
    if any(True for _ in deleted_paths):
        return True
    return any(not _normalize(path).endswith(".md") for path in changed_paths)


def _read_nul_paths(path: Path) -> list[str]:
    payload = path.read_bytes()
    if not payload:
        return []
    if not payload.endswith(b"\0"):
        raise ValueError(f"NUL-delimited path list is truncated: {path}")
    return [item.decode("utf-8") for item in payload[:-1].split(b"\0") if item]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("policy", "markdown"))
    parser.add_argument("--changed", type=Path, required=True)
    parser.add_argument("--deleted", type=Path)
    args = parser.parse_args()

    changed = _read_nul_paths(args.changed)
    if args.mode == "policy":
        result = policy_relevant(changed)
    else:
        if args.deleted is None:
            parser.error("--deleted is required for markdown mode")
        result = validation_required(changed, _read_nul_paths(args.deleted))
    print("true" if result else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
