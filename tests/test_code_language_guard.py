from __future__ import annotations

import json
import sys
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.code_language_guard import (
    BaselineEntry,
    LanguagePolicyError,
    compare_to_baseline,
    group_findings,
    load_baseline,
    load_policy,
    scan_repository,
)

import scripts.validate_repo as validate_repo


def _write_json(root: Path, relative: str, payload: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


class LanguagePolicyLoadingTest(unittest.TestCase):
    def test_policy_requires_exact_schema(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_json(root, "config/code_language_policy.json", {"schema": "wrong"})
            with self.assertRaisesRegex(LanguagePolicyError, "invalid language policy schema"):
                load_policy(root)

    def test_baseline_requires_exact_schema(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_json(root, "config/code_language_legacy_baseline.json", {"schema": "wrong"})
            with self.assertRaisesRegex(LanguagePolicyError, "invalid language baseline schema"):
                load_baseline(root)


class PythonLanguageScannerTest(unittest.TestCase):
    def _repo(self, files: dict[str, str]) -> tuple[TemporaryDirectory, Path]:
        td = TemporaryDirectory()
        root = Path(td.name)
        policy = {
            "schema": "genoma-code-language-policy-v1",
            "scan_suffixes": [".py"],
            "technical_terms": ["arquivo", "amostra", "relatorio", "validar", "verificacao"],
            "contract_literals": ["VERIFICADO", "NÃO DISPONÍVEL"],
            "excluded_roots": [
                {"path": "docs/history", "reason": "historical evidence"},
                {"path": "normative/sealed", "reason": "sealed transport"},
            ],
        }
        _write_json(root, "config/code_language_policy.json", policy)
        for relative, source in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        return td, root

    def test_snake_case_portuguese_identifier_is_reported(self):
        td, root = self._repo({"pkg/mod.py": "def validar_arquivo():\n    return True\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "identifier" and f.token == "validar_arquivo" for f in findings), findings)

    def test_camel_case_portuguese_identifier_is_reported(self):
        td, root = self._repo({"pkg/mod.py": "class RelatorioBuilder:\n    pass\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "identifier" and f.token == "RelatorioBuilder" for f in findings), findings)

    def test_accented_comment_is_normalized_and_reported(self):
        td, root = self._repo({"pkg/mod.py": "# verificação do arquivo\nvalue = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "comment" for f in findings), findings)

    def test_docstring_is_scanned(self):
        td, root = self._repo({"pkg/mod.py": 'def build():\n    """Validar a amostra antes da chamada."""\n    return 1\n'})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "docstring" for f in findings), findings)

    def test_contract_literal_is_removed_before_comment_word_scan(self):
        td, root = self._repo({"pkg/mod.py": "# external status remains NÃO DISPONÍVEL\nvalue = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertEqual(findings, ())

    def test_historical_root_is_not_scanned(self):
        td, root = self._repo({"docs/history/v3.3/example.py": "def validar_arquivo():\n    return True\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertEqual(findings, ())


class LanguageBaselineTest(unittest.TestCase):
    def test_new_finding_is_unexpected(self):
        current = (BaselineEntry("pkg/a.py", "identifier", "validar_arquivo", 1),)
        delta = compare_to_baseline(current, ())
        self.assertEqual(delta.unexpected, current)
        self.assertEqual(delta.stale, ())

    def test_resolved_finding_makes_baseline_stale(self):
        baseline = (BaselineEntry("pkg/a.py", "identifier", "validar_arquivo", 1),)
        delta = compare_to_baseline((), baseline)
        self.assertEqual(delta.unexpected, ())
        self.assertEqual(delta.stale, baseline)

    def test_partial_cleanup_changes_count_and_requires_baseline_update(self):
        baseline = (BaselineEntry("pkg/a.py", "comment", "validar", 2),)
        current = (BaselineEntry("pkg/a.py", "comment", "validar", 1),)
        delta = compare_to_baseline(current, baseline)
        self.assertEqual(delta.unexpected, current)
        self.assertEqual(delta.stale, baseline)


class RepositoryLanguageBaselineTest(unittest.TestCase):
    def test_repository_matches_tracked_language_baseline(self):
        policy = load_policy(ROOT)
        baseline = load_baseline(ROOT)
        current = group_findings(scan_repository(ROOT, policy))
        delta = compare_to_baseline(current, baseline)
        self.assertTrue(delta.clean, delta)


class ValidateRepoLanguageIntegrationTest(unittest.TestCase):
    def test_validate_repo_invokes_language_guard(self):
        errors: list[str] = []
        with mock.patch.object(
            validate_repo,
            "validate_code_language",
            side_effect=lambda root, out: out.append("language guard sentinel"),
        ) as guard:
            validate_repo.validate_language_policy(ROOT, errors)
        guard.assert_called_once_with(ROOT, errors)
        self.assertEqual(errors, ["language guard sentinel"])


class LanguagePolicyDocumentationTest(unittest.TestCase):
    def test_agent_and_policy_docs_name_the_enforced_contract(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        policy_doc = (ROOT / "docs" / "CODE_LANGUAGE_POLICY.md").read_text(encoding="utf-8")
        self.assertIn("English-first technical code", agents)
        self.assertIn("code_language_legacy_baseline.json", agents)
        self.assertIn("Category A — Private implementation identifier", policy_doc)
        self.assertIn("Category E — Immutable or historical evidence", policy_doc)
        self.assertIn("python3 scripts/code_language_guard.py --check", policy_doc)


if __name__ == "__main__":
    unittest.main()
