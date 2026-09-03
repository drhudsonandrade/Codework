from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

POLICY_SCHEMA = "genoma-code-language-policy-v1"
BASELINE_SCHEMA = "genoma-code-language-legacy-baseline-v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class LanguagePolicyError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class BaselineEntry:
    path: str
    kind: str
    token: str
    count: int


@dataclass(frozen=True)
class ExcludedRoot:
    path: str
    reason: str


@dataclass(frozen=True)
class LanguagePolicy:
    schema: str
    scan_suffixes: tuple[str, ...]
    technical_terms: frozenset[str]
    contract_literals: tuple[str, ...]
    excluded_roots: tuple[ExcludedRoot, ...]


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LanguagePolicyError(f"unable to load {label}: {path}") from exc


def _relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LanguagePolicyError(f"invalid {label} path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise LanguagePolicyError(f"invalid {label} path: {value}")
    return path.as_posix()


def load_policy(root: Path) -> LanguagePolicy:
    payload = _read_json(root / "config" / "code_language_policy.json", "language policy")
    if not isinstance(payload, dict) or payload.get("schema") != POLICY_SCHEMA:
        raise LanguagePolicyError("invalid language policy schema")

    suffixes = payload.get("scan_suffixes")
    if suffixes != [".py"]:
        raise LanguagePolicyError("language policy scan_suffixes must contain only .py")

    raw_terms = payload.get("technical_terms")
    if not isinstance(raw_terms, list) or not raw_terms or not all(isinstance(term, str) and term for term in raw_terms):
        raise LanguagePolicyError("language policy technical_terms must be non-empty strings")

    raw_literals = payload.get("contract_literals")
    if not isinstance(raw_literals, list) or not all(isinstance(item, str) and item for item in raw_literals):
        raise LanguagePolicyError("invalid language policy contract_literals")

    raw_excluded = payload.get("excluded_roots")
    if not isinstance(raw_excluded, list):
        raise LanguagePolicyError("invalid language policy excluded_roots")
    excluded: list[ExcludedRoot] = []
    for item in raw_excluded:
        if not isinstance(item, dict):
            raise LanguagePolicyError("invalid language policy excluded root")
        path = _relative_path(item.get("path"), "excluded root")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise LanguagePolicyError(f"excluded root requires reason: {path}")
        excluded.append(ExcludedRoot(path=path, reason=reason.strip()))

    return LanguagePolicy(
        schema=POLICY_SCHEMA,
        scan_suffixes=(".py",),
        technical_terms=frozenset(raw_terms),
        contract_literals=tuple(raw_literals),
        excluded_roots=tuple(excluded),
    )


def load_baseline(root: Path) -> tuple[BaselineEntry, ...]:
    payload = _read_json(root / "config" / "code_language_legacy_baseline.json", "language baseline")
    if not isinstance(payload, dict) or payload.get("schema") != BASELINE_SCHEMA:
        raise LanguagePolicyError("invalid language baseline schema")
    source_commit = payload.get("source_commit")
    if not isinstance(source_commit, str) or not SHA40.fullmatch(source_commit):
        raise LanguagePolicyError("invalid language baseline source_commit")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise LanguagePolicyError("invalid language baseline entries")

    entries: list[BaselineEntry] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw_entries:
        if not isinstance(item, dict):
            raise LanguagePolicyError("invalid language baseline entry")
        path = _relative_path(item.get("path"), "baseline entry")
        kind = item.get("kind")
        token = item.get("token")
        count = item.get("count")
        if not isinstance(kind, str) or not kind or not isinstance(token, str) or not token:
            raise LanguagePolicyError("invalid language baseline entry identity")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise LanguagePolicyError("invalid language baseline entry count")
        key = (path, kind, token)
        if key in seen:
            raise LanguagePolicyError(f"duplicate language baseline entry: {key}")
        seen.add(key)
        entries.append(BaselineEntry(path=path, kind=kind, token=token, count=count))
    return tuple(sorted(entries))
