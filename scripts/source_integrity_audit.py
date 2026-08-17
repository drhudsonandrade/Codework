#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", "node_modules", "dist", "__pycache__", ".pytest_cache", ".mypy_cache"}
CODE_SUFFIXES = {".py", ".ts", ".js", ".mjs", ".cjs", ".sh", ".bash", ".nf"}
PROVIDER_TERMS = (("chat" + "gpt").lower(), ("open" + "ai").lower())
RISK_PATTERNS = {
    "python_eval": re.compile(r"\beval\s*\("),
    "python_exec": re.compile(r"\bexec\s*\("),
    "os_system": re.compile(r"\bos\.system\s*\("),
    "subprocess_shell_true": re.compile(r"\bshell\s*=\s*True\b"),
    "pickle_loads": re.compile(r"\bpickle\.loads?\s*\("),
    "unsafe_yaml_load": re.compile(r"\byaml\.load\s*\("),
}
ACTION_REF = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit(root: Path = ROOT) -> dict:
    files = 0
    text_files = 0
    binary_files = 0
    text_lines = 0
    provider_hits: list[dict] = []
    risky_hits: list[dict] = []
    python_parse_errors: list[dict] = []
    unpinned_actions: list[dict] = []
    file_hashes: list[dict] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        relative = str(path.relative_to(root))
        data = path.read_bytes()
        files += 1
        digest = sha256_bytes(data)
        file_hashes.append({"path": relative, "sha256": digest, "size_bytes": len(data)})
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            binary_files += 1
            continue
        text_files += 1
        lines = text.splitlines()
        text_lines += len(lines)
        low = text.lower()
        for term in PROVIDER_TERMS:
            if term in low:
                for number, line in enumerate(lines, 1):
                    if term in line.lower():
                        provider_hits.append({"path": relative, "line": number})

        if path.suffix in CODE_SUFFIXES:
            for name, pattern in RISK_PATTERNS.items():
                for number, line in enumerate(lines, 1):
                    if pattern.search(line):
                        risky_hits.append({"path": relative, "line": number, "pattern": name})

        if path.suffix == ".py":
            try:
                ast.parse(text, filename=relative)
            except SyntaxError as exc:
                python_parse_errors.append({"path": relative, "line": exc.lineno, "error": exc.msg})

        if relative.startswith(".github/workflows/") and path.suffix in {".yml", ".yaml"}:
            for number, line in enumerate(lines, 1):
                match = ACTION_REF.match(line)
                if not match:
                    continue
                ref = match.group(1)
                if ref.startswith("./"):
                    continue
                if not PINNED_ACTION.fullmatch(ref):
                    unpinned_actions.append({"path": relative, "line": number, "ref": ref})

    blocking = []
    if provider_hits:
        blocking.append("PROVIDER_NEUTRALITY")
    if risky_hits:
        blocking.append("DANGEROUS_CODE_PATTERN")
    if python_parse_errors:
        blocking.append("PYTHON_PARSE")
    if unpinned_actions:
        blocking.append("ACTION_IMMUTABILITY")

    return {
        "schema": "genoma-source-integrity-audit-v1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "operational_status": "VERIFICADO" if not blocking else "NÃO DISPONÍVEL",
        "root": str(root),
        "counts": {"files": files, "text_files": text_files, "binary_files": binary_files, "text_lines": text_lines},
        "provider_hits": provider_hits,
        "risky_code_hits": risky_hits,
        "python_parse_errors": python_parse_errors,
        "unpinned_actions": unpinned_actions,
        "blocking_failures": blocking,
        "file_hashes": file_hashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit()
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["operational_status"] == "VERIFICADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
