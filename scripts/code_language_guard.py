from __future__ import annotations

import ast
import io
import json
import re
import tokenize
import unicodedata
from collections import Counter
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


SKIP_PARTS = frozenset({".git", "node_modules", "dist", "__pycache__", ".pytest_cache", ".venv"})


@dataclass(frozen=True, order=True)
class LanguageFinding:
    path: str
    line: int
    kind: str
    token: str
    matched_terms: tuple[str, ...]


def _normalize_word(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _identifier_words(identifier: str) -> tuple[str, ...]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    return tuple(
        word
        for part in re.split(r"[_\W]+", expanded, flags=re.UNICODE)
        if (word := _normalize_word(part))
    )



def _technical_terms(policy: LanguagePolicy) -> frozenset[str]:
    return frozenset(_normalize_word(term) for term in policy.technical_terms)


def _matched_identifier_terms(identifier: str, policy: LanguagePolicy) -> tuple[str, ...]:
    terms = _technical_terms(policy)
    return tuple(sorted(set(_identifier_words(identifier)) & terms))


def _strip_contract_literals(text: str, policy: LanguagePolicy) -> str:
    for literal in policy.contract_literals:
        text = text.replace(literal, " ")
    return text


def _matched_text_terms(text: str, policy: LanguagePolicy) -> tuple[str, ...]:
    terms = _technical_terms(policy)
    cleaned = _strip_contract_literals(text, policy)
    words = {
        _normalize_word(part)
        for part in re.findall(r"[^\W_]+", cleaned, flags=re.UNICODE)
    }
    return tuple(sorted(words & terms))


def _relative_source_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise LanguagePolicyError(f"scanned source is outside repository root: {path}") from exc



def _identifier_occurrences(tree: ast.AST) -> tuple[tuple[str, int], ...]:
    occurrences: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            occurrences.append((node.id, node.lineno))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            occurrences.append((node.name, node.lineno))
        elif isinstance(node, ast.arg):
            occurrences.append((node.arg, node.lineno))
        elif isinstance(node, ast.Attribute):
            occurrences.append((node.attr, node.lineno))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname:
                    occurrences.append((alias.asname, node.lineno))
        elif isinstance(node, ast.ExceptHandler) and isinstance(node.name, str):
            occurrences.append((node.name, node.lineno))
    return tuple(occurrences)


def _docstrings(tree: ast.AST) -> tuple[tuple[str, int], ...]:
    values: list[tuple[str, int]] = []
    doc_nodes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, doc_nodes) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            values.append((first.value.value, first.lineno))
    return tuple(values)



def scan_python_file(path: Path, root: Path, policy: LanguagePolicy) -> tuple[LanguageFinding, ...]:
    relative = _relative_source_path(path, root)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise LanguagePolicyError(f"unable to read scanned Python source: {relative}") from exc

    try:
        tree = ast.parse(source, filename=relative)
    except (SyntaxError, ValueError) as exc:
        raise LanguagePolicyError(f"unable to parse scanned Python source: {relative}") from exc

    try:
        token_stream = tuple(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise LanguagePolicyError(f"unable to tokenize scanned Python source: {relative}") from exc

    findings: list[LanguageFinding] = []
    for identifier, line in _identifier_occurrences(tree):
        matched = _matched_identifier_terms(identifier, policy)
        if matched:
            findings.append(LanguageFinding(relative, line, "identifier", identifier, matched))


    for token_info in token_stream:
        if token_info.type != tokenize.COMMENT:
            continue
        for term in _matched_text_terms(token_info.string, policy):
            findings.append(LanguageFinding(relative, token_info.start[0], "comment", term, (term,)))

    for docstring, line in _docstrings(tree):
        for term in _matched_text_terms(docstring, policy):
            findings.append(LanguageFinding(relative, line, "docstring", term, (term,)))

    return tuple(sorted(findings))


def _is_excluded(relative: Path, policy: LanguagePolicy) -> bool:
    parts = relative.parts
    for excluded in policy.excluded_roots:
        excluded_parts = Path(excluded.path).parts
        if parts[: len(excluded_parts)] == excluded_parts:
            return True
    return False


def scan_repository(root: Path, policy: LanguagePolicy) -> tuple[LanguageFinding, ...]:
    findings: list[LanguageFinding] = []
    candidates: set[Path] = set()
    for suffix in policy.scan_suffixes:
        candidates.update(root.rglob(f"*{suffix}"))
    for path in sorted(candidates, key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_PARTS for part in relative.parts) or _is_excluded(relative, policy):
            continue
        findings.extend(scan_python_file(path, root, policy))
    return tuple(sorted(findings))



def group_findings(findings: tuple[LanguageFinding, ...]) -> tuple[BaselineEntry, ...]:
    counts = Counter((finding.path, finding.kind, finding.token) for finding in findings)
    return tuple(
        BaselineEntry(path=path, kind=kind, token=token, count=count)
        for (path, kind, token), count in sorted(counts.items())
    )
