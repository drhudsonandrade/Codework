"""Audit unexplained Portuguese after the English migration.

Fail closed when retained residual text is unclassified or changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess  # nosec B404
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_SCHEMA = "genoma-residual-language-classification-v1"
ALLOWED_CATEGORIES = (
    "normative",
    "localized",
    "historical",
    "canonical",
    "compatibility-preserved",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PORTUGUESE_ACCENT = re.compile(r"[áéíóúâêôãõçà]", re.IGNORECASE)
EMAIL_ADDRESS = re.compile(
    r"\b[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b"
)
DOMAIN_COM_SUFFIX = re.compile(r"(?<=\.)com\b", re.IGNORECASE)


class ResidualLanguageError(RuntimeError):
    """The residual-language contract cannot be evaluated safely."""


@dataclass(frozen=True)
class ResidualFinding:
    """One detected residual-language line in a tracked text file."""

    path: str
    line: int
    text: str
    tokens: tuple[str, ...]


PORTUGUESE_ASCII_COMMON_WORDS = frozenset(
    {
        "agora",
        "ainda",
        "aqui",
        "assim",
        "cada",
        "como",
        "depois",
        "desde",
        "esse",
        "essa",
        "este",
        "esta",
        "isso",
        "isto",
        "mais",
        "menos",
        "mesmo",
        "muito",
        "muitos",
        "nao",
        "onde",
        "ontem",
        "outro",
        "outros",
        "outra",
        "outras",
        "para",
        "pela",
        "pelas",
        "pelo",
        "pelos",
        "pois",
        "porque",
        "quando",
        "sem",
        "somente",
        "tambem",
        "talvez",
        "toda",
        "todas",
        "todo",
        "todos",
        "uma",
        "umas",
        "uns",
    }
)
PORTUGUESE_ASCII_VERB_ENDINGS = (
    "ando",
    "endo",
    "indo",
    "amos",
    "emos",
    "imos",
    "aram",
    "eram",
    "iram",
    "avam",
    "aria",
    "ariam",
    "eria",
    "eriam",
    "iria",
    "iriam",
    "asse",
    "assem",
    "esse",
    "essem",
    "isse",
    "issem",
    "ou",
    "eu",
    "iu",
)
PORTUGUESE_ASCII_NOMINAL_ENDINGS = (
    "cao",
    "coes",
    "dade",
    "dades",
    "mente",
    "amento",
    "amentos",
    "imento",
    "imentos",
    "avel",
    "aveis",
    "ivel",
    "iveis",
)
LOCAL_PORTUGUESE_PROSE_TERMS = frozenset(
    {
        "apenas",
        "ainda",
        "alem",
        "antes",
        "apos",
        "arquivo",
        "arquivos",
        "cada",
        "como",
        "com",
        "dados",
        "deve",
        "devem",
        "durante",
        "entre",
        "essa",
        "esse",
        "esta",
        "este",
        "execucao",
        "fica",
        "ficam",
        "foi",
        "foram",
        "marcador",
        "marcadores",
        "mesmo",
        "nao",
        "onde",
        "painel",
        "para",
        "pode",
        "podem",
        "por",
        "quando",
        "que",
        "registro",
        "resultado",
        "resultados",
        "revisao",
        "sem",
        "sobre",
        "somente",
        "tambem",
        "todos",
        "todas",
        "uma",
        "versao",
    }
)


def _normalize(value: str) -> str:
    """Normalize Portuguese matching text without changing source bytes."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    ).casefold()


@lru_cache(maxsize=8)
def _policy_terms(root: Path = ROOT) -> tuple[frozenset[str], tuple[str, ...]]:
    """Load the existing language policy terms and exact contract literals."""
    path = root / "config" / "code_language_policy.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResidualLanguageError(
            f"unable to load language policy: {path}"
        ) from exc
    terms = payload.get("technical_terms")
    literals = payload.get("contract_literals")
    if not isinstance(terms, list) or not isinstance(literals, list):
        raise ResidualLanguageError(
            "language policy is missing terms or contract literals"
        )
    if not all(isinstance(item, str) and item for item in terms + literals):
        raise ResidualLanguageError(
            "language policy terms and literals must be non-empty strings"
        )
    return frozenset(_normalize(item) for item in terms), tuple(literals)


def _known_inflection_hints(
    words: set[str], terms: frozenset[str]
) -> set[str]:
    """Return known Portuguese inflections derived from policy vocabulary."""
    matches: set[str] = set()
    for word in words:
        candidates: set[str] = set()
        if len(word) > 3 and word.endswith("s"):
            candidates.add(word[:-1])
        if len(word) > 4 and word.endswith("oes"):
            candidates.add(word[:-3] + "ao")
        if len(word) > 4 and word.endswith("ais"):
            candidates.add(word[:-3] + "al")
        if len(word) > 4 and word.endswith("eis"):
            candidates.add(word[:-3] + "el")
        if candidates & terms:
            matches.add(word)
    return matches


def _ascii_hints(words: set[str]) -> set[str]:
    """Return multi-signal hints for otherwise ambiguous ASCII Portuguese."""
    hints = words & PORTUGUESE_ASCII_COMMON_WORDS
    for word in words:
        if len(word) >= 5 and word.endswith(PORTUGUESE_ASCII_VERB_ENDINGS):
            hints.add(word)
        if len(word) >= 6 and word.endswith(PORTUGUESE_ASCII_NOMINAL_ENDINGS):
            hints.add(word)
    return hints if len(hints) >= 2 else set()


def detect_text(text: str, *, root: Path = ROOT) -> tuple[str, ...]:
    """Return Portuguese signals, including exact contract literals."""
    technical_terms, contract_literals = _policy_terms(root)
    matches: set[str] = set()
    cleaned = re.sub(r"https?://\S+", " ", text)
    cleaned = EMAIL_ADDRESS.sub(" ", cleaned)
    cleaned = DOMAIN_COM_SUFFIX.sub(" ", cleaned)
    for literal in contract_literals:
        if literal in cleaned:
            matches.add(f"literal:{literal}")
            cleaned = cleaned.replace(literal, " ")
    parts = re.findall(r"[^\W_]+", cleaned, flags=re.UNICODE)
    normalized = {_normalize(part) for part in parts}
    prose_terms = technical_terms | LOCAL_PORTUGUESE_PROSE_TERMS
    matches.update(f"term:{word}" for word in normalized & prose_terms)
    matches.update(
        f"term:{word}"
        for word in _known_inflection_hints(normalized, prose_terms)
    )
    matches.update(
        f"accent:{_normalize(part)}"
        for part in parts
        if PORTUGUESE_ACCENT.search(part)
    )
    if not matches:
        matches.update(f"ascii:{word}" for word in _ascii_hints(normalized))
    return tuple(sorted(matches))


def findings_for_path(
    path: Path, *, root: Path = ROOT
) -> tuple[ResidualFinding, ...]:
    """Detect Portuguese signals in one UTF-8 file, one record per line."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ()
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        tokens = detect_text(line, root=root)
        if tokens:
            findings.append(
                ResidualFinding(relative, line_number, line, tokens)
            )
    return tuple(findings)


def _tracked_paths(root: Path) -> tuple[Path, ...]:
    """List tracked regular files through fixed-argv trusted Git."""
    try:
        result = subprocess.run(  # nosec B603 -- fixed Git argv; no shell.
            ["/usr/bin/git", "-C", str(root), "ls-files", "-z"],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise ResidualLanguageError(
            "unable to execute trusted git for residual audit"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ResidualLanguageError(
            f"git tracked-file discovery failed: {detail}"
        )
    names = result.stdout.decode("utf-8").split("\0")
    paths: list[Path] = []
    for name in names:
        if not name:
            continue
        path = root / name
        if path.is_symlink():
            raise ResidualLanguageError(
                f"tracked symlink is not supported by residual audit: {name}"
            )
        if path.is_file():
            paths.append(path)
    return tuple(paths)


def scan_repository(root: Path) -> dict[str, tuple[ResidualFinding, ...]]:
    """Return every tracked UTF-8 file containing a Portuguese signal."""
    found: dict[str, tuple[ResidualFinding, ...]] = {}
    for path in _tracked_paths(root):
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8192]:
            continue
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        findings = findings_for_path(path, root=root)
        if findings:
            found[path.relative_to(root).as_posix()] = findings
    return found


def fingerprint_findings(findings: tuple[ResidualFinding, ...]) -> str:
    """Hash finding content independent of source line numbers."""
    records = sorted(
        (finding.text, list(finding.tokens)) for finding in findings
    )
    raw = json.dumps(
        records, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fingerprint_group(
    grouped: dict[str, tuple[ResidualFinding, ...]],
) -> str:
    """Hash a classified root including exact relative paths and content."""
    records = sorted(
        (path, finding.text, list(finding.tokens))
        for path, findings in grouped.items()
        for finding in findings
    )
    raw = json.dumps(
        records, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_classification(
    identity: str,
    entry: dict[str, Any],
) -> None:
    """Validate one closed-category residual classification record."""
    category = entry.get("category")
    reason = entry.get("reason")
    count = entry.get("count")
    fingerprint = entry.get("fingerprint")
    if category not in ALLOWED_CATEGORIES:
        raise ResidualLanguageError(
            f"invalid residual category for {identity}: {category!r}"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise ResidualLanguageError(f"missing residual reason for {identity}")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ResidualLanguageError(f"invalid residual count for {identity}")
    if not isinstance(fingerprint, str) or not SHA256_RE.fullmatch(
        fingerprint
    ):
        raise ResidualLanguageError(
            f"invalid residual fingerprint for {identity}"
        )


def _relative_identity(value: object, label: str) -> str:
    """Normalize a repository-relative classification identity."""
    if not isinstance(value, str) or not value:
        raise ResidualLanguageError(f"invalid {label}: {value!r}")
    path = Path(value)
    if path == Path(".") or path.is_absolute() or ".." in path.parts:
        raise ResidualLanguageError(f"invalid {label}: {value!r}")
    return path.as_posix().rstrip("/")


def _read_ledger_lists(root: Path) -> tuple[list[object], list[object]]:
    """Read and validate the residual ledger container and list fields."""
    path = root / "config" / "residual_language_classification.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResidualLanguageError(
            f"unable to load residual-language ledger: {path}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != LEDGER_SCHEMA:
        raise ResidualLanguageError("invalid residual-language ledger schema")
    raw_entries = payload.get("entries")
    raw_roots = payload.get("root_entries")
    if not isinstance(raw_entries, list) or not isinstance(raw_roots, list):
        raise ResidualLanguageError(
            "residual-language ledger entries and root_entries must be lists"
        )
    return raw_entries, raw_roots


def _index_direct_entries(raw_entries: list[object]) -> dict[str, dict[str, Any]]:
    """Index validated direct-file classifications by repository path."""
    entries: dict[str, dict[str, Any]] = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ResidualLanguageError("invalid residual-language ledger entry")
        path_value = _relative_identity(raw.get("path"), "residual path")
        if path_value in entries:
            raise ResidualLanguageError(f"duplicate residual path: {path_value!r}")
        _validate_classification(path_value, raw)
        entries[path_value] = raw
    return entries


def _index_root_entries(raw_roots: list[object]) -> dict[str, dict[str, Any]]:
    """Index validated aggregate-root classifications by repository path."""
    roots: dict[str, dict[str, Any]] = {}
    for raw in raw_roots:
        if not isinstance(raw, dict):
            raise ResidualLanguageError("invalid residual-language root entry")
        root_value = _relative_identity(raw.get("root"), "residual root")
        if root_value in roots:
            raise ResidualLanguageError(f"duplicate residual root: {root_value!r}")
        _validate_classification(root_value, raw)
        files = raw.get("files")
        if not isinstance(files, int) or isinstance(files, bool) or files < 1:
            raise ResidualLanguageError(
                f"invalid residual root file count for {root_value}"
            )
        roots[root_value] = raw
    return roots


def _root_for(path: str, roots: dict[str, dict[str, Any]]) -> str | None:
    """Return the single classified root that owns a residual path, if any."""
    for root_value in roots:
        if path == root_value or path.startswith(root_value + "/"):
            return root_value
    return None


def _validate_root_ownership(
    entries: dict[str, dict[str, Any]],
    roots: dict[str, dict[str, Any]],
) -> None:
    """Reject overlapping roots and direct entries hidden below a root."""
    sorted_roots = sorted(roots)
    for index, first in enumerate(sorted_roots):
        overlap = next(
            (
                second
                for second in sorted_roots[index + 1:]
                if second.startswith(first + "/")
            ),
            None,
        )
        if overlap is not None:
            raise ResidualLanguageError(
                f"overlapping residual roots: {first!r}, {overlap!r}"
            )
    covered = next((path for path in entries if _root_for(path, roots)), None)
    if covered is not None:
        raise ResidualLanguageError(
            f"direct residual entry is covered by root: {covered}"
        )


def _load_ledger(
    root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load the closed direct-file and aggregate-root classification maps."""
    raw_entries, raw_roots = _read_ledger_lists(root)
    entries = _index_direct_entries(raw_entries)
    roots = _index_root_entries(raw_roots)
    _validate_root_ownership(entries, roots)
    return entries, roots


def _partition_current(
    current: dict[str, tuple[ResidualFinding, ...]],
    roots: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, tuple[ResidualFinding, ...]],
    dict[str, dict[str, tuple[ResidualFinding, ...]]],
]:
    """Separate direct-file findings from aggregate-root findings."""
    root_current: dict[str, dict[str, tuple[ResidualFinding, ...]]] = {
        root_value: {} for root_value in roots
    }
    direct_current: dict[str, tuple[ResidualFinding, ...]] = {}
    for path, findings in current.items():
        root_value = _root_for(path, roots)
        if root_value is None:
            direct_current[path] = findings
        else:
            root_current[root_value][path] = findings
    return direct_current, root_current


def _direct_drift(
    current: dict[str, tuple[ResidualFinding, ...]],
    ledger: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return count or fingerprint drift for direct-file classifications."""
    drift: list[dict[str, Any]] = []
    for path in sorted(set(current) & set(ledger)):
        findings = current[path]
        entry = ledger[path]
        observed = {
            "count": len(findings),
            "fingerprint": fingerprint_findings(findings),
        }
        expected = {
            "count": entry["count"],
            "fingerprint": entry["fingerprint"],
        }
        if observed != expected:
            drift.append({"path": path, "expected": expected, "observed": observed})
    return drift


def _root_drift(
    current: dict[str, dict[str, tuple[ResidualFinding, ...]]],
    roots: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return aggregate file-count, line-count, or fingerprint root drift."""
    drift: list[dict[str, Any]] = []
    for root_value, entry in roots.items():
        grouped = current[root_value]
        observed = {
            "files": len(grouped),
            "count": sum(len(findings) for findings in grouped.values()),
            "fingerprint": fingerprint_group(grouped),
        }
        expected = {
            "files": entry["files"],
            "count": entry["count"],
            "fingerprint": entry["fingerprint"],
        }
        if observed != expected:
            drift.append(
                {"root": root_value, "expected": expected, "observed": observed}
            )
    return drift


def _category_totals(
    ledger: dict[str, dict[str, Any]],
    roots: dict[str, dict[str, Any]],
    root_current: dict[str, dict[str, tuple[ResidualFinding, ...]]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Count classified files and detected lines by closed category."""
    category_files = {category: 0 for category in ALLOWED_CATEGORIES}
    category_lines = {category: 0 for category in ALLOWED_CATEGORIES}
    for entry in ledger.values():
        category_files[entry["category"]] += 1
        category_lines[entry["category"]] += int(entry["count"])
    for root_value, entry in roots.items():
        grouped = root_current[root_value]
        category_files[entry["category"]] += len(grouped)
        category_lines[entry["category"]] += sum(
            len(findings) for findings in grouped.values()
        )
    return category_files, category_lines


def audit_repository(root: Path = ROOT) -> dict[str, Any]:
    """Compare tracked residuals with reviewed classifications."""
    current = scan_repository(root)
    ledger, roots = _load_ledger(root)
    direct_current, root_current = _partition_current(current, roots)
    current_paths = set(direct_current)
    ledger_paths = set(ledger)
    unclassified = sorted(current_paths - ledger_paths)
    missing = sorted(ledger_paths - current_paths)
    drift = _direct_drift(direct_current, ledger) + _root_drift(root_current, roots)
    category_files, category_lines = _category_totals(ledger, roots, root_current)
    return {
        "schema": "genoma-residual-language-audit-v1",
        "tracked_files_with_residuals": len(current),
        "detected_lines": sum(len(items) for items in current.values()),
        "category_files": category_files,
        "category_lines": category_lines,
        "unclassified": unclassified,
        "missing": missing,
        "drift": drift,
        "clean": not unclassified and not missing and not drift,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the fail-closed residual-language audit CLI."""
    parser = argparse.ArgumentParser(
        description="Audit classified residual Portuguese text."
    )
    parser.add_argument(
        "--check", action="store_true", help="verify the reviewed ledger"
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required")
    try:
        report = audit_repository(ROOT)
    except ResidualLanguageError as exc:
        print(f"RESIDUAL_LANGUAGE_ERROR\t{exc}")
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
