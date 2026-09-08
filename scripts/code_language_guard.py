from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import subprocess  # nosec B404 -- fixed-argv Git provenance checks; shell is never enabled.
import sys
import tarfile
import tokenize
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

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
    if path == Path(".") or not path.parts or path.is_absolute() or ".." in path.parts:
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
    if (
        not isinstance(raw_terms, list)
        or not raw_terms
        or not all(isinstance(term, str) and term for term in raw_terms)
    ):
        raise LanguagePolicyError("language policy technical_terms must be non-empty strings")

    raw_literals = payload.get("contract_literals")
    if not isinstance(raw_literals, list) or not all(
        isinstance(item, str) and item for item in raw_literals
    ):
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
        technical_terms=frozenset(_normalize_word(term) for term in raw_terms),
        contract_literals=tuple(raw_literals),
        excluded_roots=tuple(excluded),
    )


def load_baseline(root: Path) -> tuple[BaselineEntry, ...]:
    payload = _read_json(
        root / "config" / "code_language_legacy_baseline.json", "language baseline")
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


PORTUGUESE_VERB_SUFFIXES = {
    "ar": frozenset({
        "ar", "ando", "ado", "ada", "ados", "adas", "amos", "am", "ou", "ei",
        "ava", "avam", "aria", "ariam",
    }),
    "er": frozenset({"er", "endo", "ido", "ida", "idos", "idas"}),
    "ir": frozenset({"ir", "indo", "ido", "ida", "idos", "idas", "iu", "iram"}),
}


def _identifier_words(identifier: str) -> tuple[str, ...]:
    expanded: list[str] = []
    for index, current in enumerate(identifier):
        previous = identifier[index - 1] if index else ""
        following = identifier[index + 1] if index + 1 < len(identifier) else ""
        boundary = (
            (current.isupper() and (previous.islower() or previous.isdigit()))
            or (current.isupper() and previous.isupper() and following.islower())
            or (current.isdigit() and previous.isalpha())
            or (current.isalpha() and previous.isdigit())
        )
        if boundary:
            expanded.append("_")
        expanded.append(current)
    return tuple(
        word
        for part in re.split(r"[_\W]+", "".join(expanded), flags=re.UNICODE)
        if (word := _normalize_word(part))
    )


def _canonical_technical_term(word: str, policy: LanguagePolicy) -> str | None:
    normalized = _normalize_word(word)
    terms = policy.technical_terms
    if normalized in terms:
        return normalized
    if normalized.endswith("oes"):
        singular = normalized[:-3] + "ao"
        if singular in terms:
            return singular
    if normalized.endswith("s") and normalized[:-1] in terms:
        return normalized[:-1]
    for term in sorted(terms, key=len, reverse=True):
        ending = term[-2:]
        if ending not in PORTUGUESE_VERB_SUFFIXES or len(term) < 5:
            continue
        stem = term[:-2]
        suffix = normalized[len(stem):]
        if normalized.startswith(stem) and suffix in PORTUGUESE_VERB_SUFFIXES[ending]:
            return term
    return None


def _contract_identifier_forms(policy: LanguagePolicy) -> frozenset[str]:
    return frozenset(
        "_".join(_identifier_words(literal))
        for literal in policy.contract_literals
    )


def _matched_identifier_terms(identifier: str, policy: LanguagePolicy) -> tuple[str, ...]:
    words = _identifier_words(identifier)
    if "_".join(words) in _contract_identifier_forms(policy):
        return ()
    matched = {
        canonical
        for word in words
        if (canonical := _canonical_technical_term(word, policy)) is not None
    }
    return tuple(sorted(matched))


def _strip_contract_literals(text: str, policy: LanguagePolicy) -> str:
    for literal in policy.contract_literals:
        text = text.replace(literal, " ")
    return text


def _matched_text_terms(text: str, policy: LanguagePolicy) -> tuple[str, ...]:
    cleaned = _strip_contract_literals(text, policy)
    matches: list[str] = []
    for part in re.findall(r"[^\W_]+", cleaned, flags=re.UNICODE):
        canonical = _canonical_technical_term(part, policy)
        if canonical is not None:
            matches.append(canonical)
    return tuple(matches)


def _relative_source_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise LanguagePolicyError(f"scanned source is outside repository root: {path}") from exc



def _identifier_occurrences(tree: ast.AST) -> tuple[tuple[str, int], ...]:
    occurrences: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 1)
        if isinstance(node, ast.Name):
            occurrences.append((node.id, line))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            occurrences.append((node.name, line))
        elif isinstance(node, ast.arg):
            occurrences.append((node.arg, line))
        elif isinstance(node, ast.Attribute):
            occurrences.append((node.attr, line))
        elif isinstance(node, ast.ImportFrom) and isinstance(node.module, str):
            occurrences.append((node.module, line))
        elif isinstance(node, ast.alias):
            occurrences.append((node.name, line))
            if node.asname:
                occurrences.append((node.asname, line))
        elif isinstance(node, ast.keyword) and isinstance(node.arg, str):
            occurrences.append((node.arg, line))
        elif isinstance(node, ast.ExceptHandler) and isinstance(node.name, str):
            occurrences.append((node.name, line))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            occurrences.extend((name, line) for name in node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and isinstance(node.name, str):
            occurrences.append((node.name, line))
        elif isinstance(node, ast.MatchMapping) and isinstance(node.rest, str):
            occurrences.append((node.rest, line))
        elif type(node).__name__ in {"TypeVar", "ParamSpec", "TypeVarTuple"}:
            name = getattr(node, "name", None)
            if isinstance(name, str):
                occurrences.append((name, line))
    return tuple(occurrences)


def _docstrings(tree: ast.AST) -> tuple[tuple[str, int], ...]:
    values: list[tuple[str, int]] = []
    doc_nodes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, doc_nodes) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
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
    except (tokenize.TokenError, SyntaxError) as exc:
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
            findings.append(LanguageFinding(
                relative, token_info.start[0], "comment", term, (term,)))

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

@dataclass(frozen=True)
class BaselineDelta:
    unexpected: tuple[BaselineEntry, ...]
    stale: tuple[BaselineEntry, ...]

    @property
    def clean(self) -> bool:
        return not self.unexpected and not self.stale


def compare_to_baseline(
    current: tuple[BaselineEntry, ...],
    baseline: tuple[BaselineEntry, ...],
) -> BaselineDelta:
    current_set = set(current)
    baseline_set = set(baseline)
    return BaselineDelta(
        unexpected=tuple(sorted(current_set - baseline_set)),
        stale=tuple(sorted(baseline_set - current_set)),
    )


def validate_code_language(root: Path, errors: list[str]) -> None:
    policy = load_policy(root)
    baseline = load_baseline(root)
    _validate_baseline_provenance(root, policy, baseline)
    current = group_findings(scan_repository(root, policy))
    delta = compare_to_baseline(current, baseline)
    errors.extend(
        f"new Portuguese technical language debt: {entry.path}: {entry.kind}: "
        f"{entry.token}: {entry.count}"
        for entry in delta.unexpected
    )
    errors.extend(
        f"resolved language baseline entry must be removed: {entry.path}: {entry.kind}: "
        f"{entry.token}: {entry.count}"
        for entry in delta.stale
    )


def _run_git(
    root: Path, *args: str, allow_nonzero: bool = False
) -> subprocess.CompletedProcess[bytes]:
    try:
        if sys.platform == "win32":
            result = subprocess.run(  # nosec B603 -- approved absolute Git path, argv list, no shell.
                [r"C:\Program Files\Git\cmd\git.exe", "-C", str(root), *args],
                check=False,
                capture_output=True,
            )
        else:
            result = subprocess.run(  # nosec B603 -- approved absolute Git path, argv list, no shell.
                ["/usr/bin/git", "-C", str(root), *args],
                check=False,
                capture_output=True,
            )
    except OSError as exc:
        raise LanguagePolicyError(
            "unable to execute trusted git for language baseline provenance") from exc
    if result.returncode != 0 and not allow_nonzero:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise LanguagePolicyError(f"git baseline provenance check failed: {detail or args[0]}")
    return result


def _trusted_pull_request_base() -> str | None:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return None
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise LanguagePolicyError("trusted pull request event path is unavailable")
    payload = _read_json(Path(event_path), "GitHub pull request event")
    if not isinstance(payload, dict):
        raise LanguagePolicyError("invalid GitHub pull request event")
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict):
        raise LanguagePolicyError("invalid GitHub pull request event")
    base = pull_request.get("base")
    if not isinstance(base, dict):
        raise LanguagePolicyError("invalid GitHub pull request base")
    sha = base.get("sha")
    if not isinstance(sha, str) or not SHA40.fullmatch(sha):
        raise LanguagePolicyError("invalid trusted pull request base SHA")
    return sha


def _validate_source_commit(root: Path, source_commit: str) -> None:
    if not SHA40.fullmatch(source_commit):
        raise LanguagePolicyError("invalid language baseline source_commit")
    trusted_base = _trusted_pull_request_base()
    kind_result = _run_git(root, "cat-file", "-t", source_commit, allow_nonzero=True)
    if kind_result.returncode != 0:
        raise LanguagePolicyError("language baseline source_commit does not exist")
    kind = kind_result.stdout.decode("utf-8", errors="replace").strip()
    if kind != "commit":
        raise LanguagePolicyError("language baseline source_commit is not a commit")
    if trusted_base is not None:
        trusted_kind = _run_git(root, "cat-file", "-t", trusted_base, allow_nonzero=True)
        if (
            trusted_kind.returncode != 0
            or trusted_kind.stdout.decode("utf-8", errors="replace").strip() != "commit"
        ):
            raise LanguagePolicyError("trusted pull request base commit is unavailable")
        trusted_ancestor = _run_git(
            root, "merge-base", "--is-ancestor", source_commit, trusted_base, allow_nonzero=True
        )
        if trusted_ancestor.returncode != 0:
            raise LanguagePolicyError(
                "language baseline source_commit is not an ancestor of trusted pull request base")
    ancestor = _run_git(root, "merge-base", "--is-ancestor",
                        source_commit, "HEAD", allow_nonzero=True)
    if ancestor.returncode != 0:
        raise LanguagePolicyError("language baseline source_commit is not an ancestor of HEAD")


def _scan_source_commit(
    root: Path, source_commit: str, policy: LanguagePolicy
) -> tuple[BaselineEntry, ...]:
    _validate_source_commit(root, source_commit)
    archive = _run_git(root, "archive", "--format=tar", source_commit).stdout
    with TemporaryDirectory() as td:
        snapshot = Path(td)
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
                for member in bundle.getmembers():
                    if not member.isfile() or not member.name.endswith(policy.scan_suffixes):
                        continue
                    relative = _relative_path(member.name, "archived source")
                    extracted = bundle.extractfile(member)
                    if extracted is None:
                        raise LanguagePolicyError(
                            f"unable to read archived Python source: {relative}")
                    try:
                        source = extracted.read().decode("utf-8")
                    except UnicodeError as exc:
                        raise LanguagePolicyError(
                            f"unable to read archived Python source: {relative}") from exc
                    target = snapshot / relative
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(source, encoding="utf-8")
                    except OSError as exc:
                        raise LanguagePolicyError(
                            f"unable to materialize archived Python source: {relative}: {exc}"
                        ) from exc
        except tarfile.TarError as exc:
            raise LanguagePolicyError(
                "unable to inspect language baseline source_commit archive") from exc
        return group_findings(scan_repository(snapshot, policy))


def _write_baseline_payload(
    root: Path, source_commit: str, entries: tuple[BaselineEntry, ...]
) -> None:
    payload = {
        "schema": BASELINE_SCHEMA,
        "source_commit": source_commit,
        "entries": [
            {"path": entry.path, "kind": entry.kind, "token": entry.token, "count": entry.count}
            for entry in entries
        ],
    }
    path = root / "config" / "code_language_legacy_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _entry_counts(entries: tuple[BaselineEntry, ...]) -> dict[tuple[str, str, str], int]:
    return {(entry.path, entry.kind, entry.token): entry.count for entry in entries}


def _baseline_source_commit(root: Path) -> str:
    payload = _read_json(
        root / "config" / "code_language_legacy_baseline.json", "language baseline")
    if not isinstance(payload, dict) or payload.get("schema") != BASELINE_SCHEMA:
        raise LanguagePolicyError("invalid language baseline schema")
    source_commit = payload.get("source_commit")
    if not isinstance(source_commit, str) or not SHA40.fullmatch(source_commit):
        raise LanguagePolicyError("invalid language baseline source_commit")
    return source_commit


def _policy_at_commit(root: Path, commit: str) -> LanguagePolicy | None:
    ref = f"{commit}:config/code_language_policy.json"
    exists = _run_git(root, "cat-file", "-e", ref, allow_nonzero=True)
    if exists.returncode != 0:
        return None
    payload_result = _run_git(root, "show", ref)
    with TemporaryDirectory() as td:
        snapshot = Path(td)
        policy_path = snapshot / "config" / "code_language_policy.json"
        try:
            policy_path.parent.mkdir(parents=True, exist_ok=True)
            policy_path.write_bytes(payload_result.stdout)
            return load_policy(snapshot)
        except (OSError, LanguagePolicyError) as exc:
            raise LanguagePolicyError(
                f"trusted pull request base language policy is invalid: {exc}"
            ) from exc


def _validate_policy_monotonicity(root: Path, policy: LanguagePolicy) -> None:
    trusted_base = _trusted_pull_request_base()
    if trusted_base is None:
        return
    base_policy = _policy_at_commit(root, trusted_base)
    if base_policy is None:
        return
    removed = sorted(base_policy.technical_terms - policy.technical_terms)
    if removed:
        raise LanguagePolicyError(
            "language policy technical_terms may not remove trusted pull request base terms: "
            + ", ".join(removed)
        )
    base_excluded = {entry.path for entry in base_policy.excluded_roots}
    added_excluded = sorted({entry.path for entry in policy.excluded_roots} - base_excluded)
    if added_excluded:
        raise LanguagePolicyError(
            "language policy excluded_roots may not add trusted pull request base exclusions: "
            + ", ".join(added_excluded)
        )


def _require_entries_supported(
    entries: tuple[BaselineEntry, ...],
    supported: tuple[BaselineEntry, ...],
    label: str,
) -> None:
    supported_counts = _entry_counts(supported)
    for entry in entries:
        key = (entry.path, entry.kind, entry.token)
        if key not in supported_counts or entry.count > supported_counts[key]:
            raise LanguagePolicyError(
                f"language baseline entry is not supported by {label}: {entry.path}: "
                f"{entry.kind}: {entry.token}"
            )


def _validate_baseline_provenance(
    root: Path, policy: LanguagePolicy, baseline: tuple[BaselineEntry, ...]
) -> None:
    _validate_policy_monotonicity(root, policy)
    source_commit = _baseline_source_commit(root)
    source_entries = _scan_source_commit(root, source_commit, policy)
    _require_entries_supported(baseline, source_entries, "source_commit")
    trusted_base = _trusted_pull_request_base()
    if trusted_base is not None:
        trusted_entries = source_entries if trusted_base == source_commit else _scan_source_commit(
            root, trusted_base, policy)
        _require_entries_supported(baseline, trusted_entries, "trusted pull request base")


def _bootstrap_baseline(root: Path, source_commit: str) -> None:
    policy = load_policy(root)
    _validate_policy_monotonicity(root, policy)
    path = root / "config" / "code_language_legacy_baseline.json"
    if path.exists():
        load_baseline(root)
        payload = _read_json(path, "language baseline")
        if not isinstance(payload, dict):
            raise LanguagePolicyError("invalid language baseline structure")
        if payload.get("source_commit") != source_commit:
            raise LanguagePolicyError("bootstrap baseline may not change an existing source_commit")
    entries = _scan_source_commit(root, source_commit, policy)
    trusted_base = _trusted_pull_request_base()
    if trusted_base is not None and trusted_base != source_commit:
        _require_entries_supported(entries, _scan_source_commit(
            root, trusted_base, policy), "trusted pull request base")
    _write_baseline_payload(root, source_commit, entries)


def _write_baseline(root: Path, source_commit: str) -> None:
    policy = load_policy(root)
    existing = load_baseline(root)
    _validate_baseline_provenance(root, policy, existing)
    source_entries = _scan_source_commit(root, source_commit, policy)
    current = group_findings(scan_repository(root, policy))
    existing_counts = _entry_counts(existing)
    source_counts = _entry_counts(source_entries)
    for entry in current:
        key = (entry.path, entry.kind, entry.token)
        if key not in existing_counts or entry.count > existing_counts[key]:
            raise LanguagePolicyError(
                f"new language debt cannot be added to baseline: {entry.path}: "
                f"{entry.kind}: {entry.token}"
            )
        if key not in source_counts or entry.count > source_counts[key]:
            raise LanguagePolicyError(
                f"language baseline entry is not supported by source_commit: {entry.path}: "
                f"{entry.kind}: {entry.token}"
            )
    trusted_base = _trusted_pull_request_base()
    if trusted_base is not None and trusted_base != source_commit:
        _require_entries_supported(current, _scan_source_commit(
            root, trusted_base, policy), "trusted pull request base")
    _write_baseline_payload(root, source_commit, current)


def _check(root: Path) -> int:
    policy = load_policy(root)
    baseline = load_baseline(root)
    _validate_baseline_provenance(root, policy, baseline)
    current = group_findings(scan_repository(root, policy))
    delta = compare_to_baseline(current, baseline)
    for entry in delta.unexpected:
        print(f"NEW_LANGUAGE_DEBT\t{entry.path}\t{entry.kind}\t{entry.token}\t{entry.count}")
    for entry in delta.stale:
        print(f"RESOLVED_BASELINE_ENTRY\t{entry.path}\t{entry.kind}\t{entry.token}\t{entry.count}")
    return 0 if delta.clean else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check English-first technical code language policy.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--write-baseline", action="store_true")
    modes.add_argument("--bootstrap-baseline", action="store_true")
    parser.add_argument("--source-commit")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if args.write_baseline or args.bootstrap_baseline:
            if not args.source_commit:
                mode = "--write-baseline" if args.write_baseline else "--bootstrap-baseline"
                raise LanguagePolicyError(f"--source-commit is required with {mode}")
            if args.bootstrap_baseline:
                _bootstrap_baseline(root, args.source_commit)
            else:
                _write_baseline(root, args.source_commit)
            return 0
        if args.source_commit:
            raise LanguagePolicyError("--source-commit is only valid with a baseline-writing mode")
        return _check(root)
    except LanguagePolicyError as exc:
        print(f"LANGUAGE_POLICY_ERROR\t{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
