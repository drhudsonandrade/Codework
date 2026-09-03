#!/usr/bin/env python3
"""Deterministic path classification for targeted GitHub Actions jobs."""

from __future__ import annotations

import argparse
import subprocess
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
POLICY_PREFIXES = (
    "normative/",
    "policy_engine/",
    "locks/",
    "template_store/",
    "adapters/",
    ".github/governance/",
)


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


def _decode_nul_paths(payload: bytes) -> list[str]:
    if not payload:
        return []
    if not payload.endswith(b"\0"):
        raise ValueError("NUL-delimited git path output is truncated")
    return [item.decode("utf-8") for item in payload[:-1].split(b"\0") if item]


def _is_null_sha(value: str) -> bool:
    return bool(value) and set(value) == {"0"}


def _git_paths(repo: Path, base: str, head: str, *, deleted_only: bool = False) -> list[str]:
    if _is_null_sha(base):
        if deleted_only:
            return []
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "-z", head, "--"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
        )
        return _decode_nul_paths(result.stdout)

    command = ["git", "diff", "--no-renames"]
    if deleted_only:
        command.append("--diff-filter=D")
    command.extend(["--name-only", "-z", base, head, "--"])
    result = subprocess.run(command, cwd=repo, check=True, stdout=subprocess.PIPE)
    return _decode_nul_paths(result.stdout)


def classify_git_diff(mode: str, base: str, head: str, repo: Path = Path(".")) -> bool:
    changed = _git_paths(repo, base, head)
    if mode == "policy":
        return policy_relevant(changed)
    if mode == "markdown":
        return validation_required(changed, _git_paths(repo, base, head, deleted_only=True))
    raise ValueError(f"unsupported classifier mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("policy", "markdown"))
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()

    result = classify_git_diff(args.mode, args.base, args.head, args.repo)
    print("true" if result else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
