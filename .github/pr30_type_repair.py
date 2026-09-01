from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected snippet not found for {label}: {path}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def repair() -> None:
    replace_once(
        "tests/attestations.py",
        "def consent_file(root: Path, *, case_id: str, **kwargs: Any) -> Path:",
        "def consent_file(root: Path, *, case_id: str, **kwargs: object) -> Path:",
        "consent_file kwargs annotation",
    )
    replace_once(
        "tests/attestations.py",
        "def wgs_qc_file(root: Path, *, case_id: str, **kwargs: Any) -> Path:",
        "def wgs_qc_file(root: Path, *, case_id: str, **kwargs: object) -> Path:",
        "wgs_qc_file kwargs annotation",
    )

    replace_once(
        "tests/test_allele_discrimination.py",
        "from pathlib import Path\n",
        "from pathlib import Path\nfrom typing import Any\n",
        "Any import",
    )
    replace_once(
        "tests/test_allele_discrimination.py",
        "def _analyse(classifications, findings, heterozygous, spec=_DEFAULT_SPEC):",
        "def _analyse(classifications, findings, heterozygous, spec=_DEFAULT_SPEC) -> dict[str, Any]:",
        "_analyse return type",
    )

    replace_once(
        "tests/test_core_imports_without_optional_adapters.py",
        "from pathlib import Path\n",
        "from pathlib import Path\nfrom types import ModuleType\n",
        "ModuleType import",
    )
    replace_once(
        "tests/test_core_imports_without_optional_adapters.py",
        "    def _import_named_core_module(module_name: str):",
        "    def _import_named_core_module(module_name: str) -> ModuleType:",
        "core import helper return type",
    )

    replace_once(
        "tests/test_pharmacogenomics.py",
        "from pathlib import Path\n",
        "from pathlib import Path\nfrom typing import Any\n",
        "Any import",
    )
    replace_once(
        "tests/test_pharmacogenomics.py",
        "        prepare_release: bool = True,\n    ):",
        "        prepare_release: bool = True,\n    ) -> tuple[dict[str, Any], dict[str, Any]]:",
        "_payload return type",
    )


def function_lines(path: str) -> dict[str, int]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    result: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.setdefault(node.name, node.lineno)
    return result


def verify_requested_ruff_findings_are_absent() -> None:
    files = [
        "tests/attestations.py",
        "tests/test_allele_discrimination.py",
        "tests/test_core_imports_without_optional_adapters.py",
        "tests/test_pharmacogenomics.py",
    ]
    run = subprocess.run(
        [
            "python3", "-m", "ruff", "check",
            "--select", "ANN401,ANN202,ANN205",
            "--output-format", "json",
            *files,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    try:
        diagnostics = json.loads(run.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"unable to parse Ruff JSON output: {run.stdout}") from exc

    target_functions = {
        ("tests/attestations.py", "consent_file"): "ANN401",
        ("tests/attestations.py", "wgs_qc_file"): "ANN401",
        ("tests/test_allele_discrimination.py", "_analyse"): "ANN202",
        ("tests/test_core_imports_without_optional_adapters.py", "_import_named_core_module"): "ANN205",
        ("tests/test_pharmacogenomics.py", "_payload"): "ANN202",
    }
    targets: set[tuple[str, int, str]] = set()
    for (path, function), code in target_functions.items():
        lines = function_lines(path)
        if function not in lines:
            raise SystemExit(f"target function missing: {path}:{function}")
        targets.add((str(Path(path).resolve()), lines[function], code))

    remaining = []
    for item in diagnostics:
        filename = str(Path(item["filename"]).resolve())
        row = int(item["location"]["row"])
        code = str(item["code"])
        if (filename, row, code) in targets:
            remaining.append(item)

    print(f"Ruff returned {len(diagnostics)} selected-rule diagnostics in the broader files; "
          f"requested PR30 findings remaining: {len(remaining)}")
    if remaining:
        print(json.dumps(remaining, indent=2, ensure_ascii=False))
        raise SystemExit("requested Ruff/CodeRabbit type findings remain")


def verify() -> None:
    files = [
        "tests/attestations.py",
        "tests/test_allele_discrimination.py",
        "tests/test_core_imports_without_optional_adapters.py",
        "tests/test_pharmacogenomics.py",
    ]
    subprocess.run(["git", "diff", "--check"], check=True)
    subprocess.run(["python3", "-m", "compileall", "-q", *files], check=True)
    subprocess.run(
        ["python3", "-m", "pip", "install", "--disable-pip-version-check", "ruff==0.16.3"],
        check=True,
    )
    verify_requested_ruff_findings_are_absent()
    subprocess.run([
        "python3", "-m", "unittest",
        "tests.test_allele_discrimination",
        "tests.test_core_imports_without_optional_adapters",
        "tests.test_pharmacogenomics",
        "-v",
    ], check=True)
    subprocess.run(["python3", "scripts/validate_repo.py"], check=True)


if __name__ == "__main__":
    repair()
    verify()
