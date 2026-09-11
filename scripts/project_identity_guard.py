#!/usr/bin/env python3
"""Validate the canonical OmniGenis identity contract and migration ledger."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_PATH = Path("config/project_identity.json")
LEDGER_PATH = Path("config/legacy_identity_ledger.json")
LEGACY_PATTERN = re.compile("code" + "work", re.IGNORECASE)
CONTROL_METADATA_PATHS = {LEDGER_PATH}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _flatten_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _flatten_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten_strings(child)


def _repository_paths(root: Path) -> tuple[Path, ...]:
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tuple(
        Path(item)
        for item in proc.stdout.decode("utf-8").split("\0")
        if item
    )


def _compile_matcher(entry: dict[str, Any]) -> re.Pattern[str]:
    matcher = entry["matcher"]
    kind = matcher["kind"]
    value = matcher["value"]
    if kind == "literal":
        return re.compile(re.escape(value))
    if kind == "regex":
        return re.compile(value)
    raise ValueError(f"unsupported matcher kind: {kind}")


def scan_legacy_identities(root: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    suffixes = tuple(ledger["scan_suffixes"])
    historical = tuple(ledger["historical_prefixes"])
    entries = ledger["entries"]
    report: dict[str, Any] = {
        "counts": {},
        "unclassified": [],
        "over_budget": [],
    }
    for relative in _repository_paths(root):
        posix = relative.as_posix()
        if relative in CONTROL_METADATA_PATHS:
            continue
        if posix.startswith(historical) or relative.suffix not in suffixes:
            continue
        path = root / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        covered: list[tuple[int, int]] = []
        for entry in entries:
            allowed = entry["locations"].get(posix)
            pattern = _compile_matcher(entry)
            matches = list(pattern.finditer(text))
            count = len(matches)
            if count:
                report["counts"].setdefault(entry["id"], {})[posix] = count
            if count and allowed is None:
                continue
            if allowed is not None and count > allowed:
                report["over_budget"].append(
                    {"id": entry["id"], "path": posix, "count": count, "max": allowed}
                )
            if allowed is not None:
                covered.extend((match.start(), match.end()) for match in matches)
        for match in LEGACY_PATTERN.finditer(text):
            if not any(start <= match.start() and match.end() <= end for start, end in covered):
                line = text.count("\n", 0, match.start()) + 1
                report["unclassified"].append({"path": posix, "line": line})
    return report


def validate_project_identity(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        identity = _load_json(root / IDENTITY_PATH)
        ledger = _load_json(root / LEDGER_PATH)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"project identity contract unreadable: {exc}"]

    if identity.get("schema") != "omnigenis-project-identity-v1":
        errors.append("project identity schema mismatch")
    if ledger.get("schema") != "omnigenis-legacy-identity-ledger-v1":
        errors.append("legacy identity ledger schema mismatch")
    if ledger.get("phase") != "2A":
        errors.append("legacy identity ledger must remain in Phase 2A during this subphase")

    canonical = set(_flatten_strings(identity))
    for entry in ledger.get("entries", []):
        replacement = entry.get("replacement")
        disposition = entry.get("disposition", "migrate")
        if disposition == "migrate" and replacement not in canonical:
            errors.append(f"legacy identity replacement is not canonical: {entry.get('id')}")
        if not entry.get("reason") or not entry.get("retire_by"):
            errors.append(f"legacy identity entry lacks reason/retire_by: {entry.get('id')}")

    try:
        report = scan_legacy_identities(root, ledger)
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, ValueError) as exc:
        return errors + [f"legacy identity scan failed closed: {exc}"]
    for item in report["unclassified"]:
        errors.append(
            f"unclassified legacy identity: {item['path']}:{item['line']}"
        )
    for item in report["over_budget"]:
        errors.append(
            "legacy occurrence count increased: "
            f"{item['id']} {item['path']} {item['count']}>{item['max']}"
        )
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--inventory", action="store_true")
    args = parser.parse_args()

    if args.inventory:
        try:
            ledger = _load_json(ROOT / LEDGER_PATH)
            report = scan_legacy_identities(ROOT, ledger)
        except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise SystemExit(f"legacy identity inventory failed closed: {exc}") from exc
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    errors = validate_project_identity(ROOT)
    if errors:
        for error in errors:
            print(f"FAIL\t{error}")
        raise SystemExit(1)
    print("PASS\tproject_identity_contract")


if __name__ == "__main__":
    main()
