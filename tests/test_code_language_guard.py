from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORTUGUESE_FIXTURE_IDENTIFIER = "validar_arquivo"
PORTUGUESE_FIXTURE_CLASS = "RelatorioBuilder"
TERM_ARCHIVE = "arquivo"
TERM_VALIDATE = "validar"
TERM_CALCULATE = "calcular"
IDENTIFIER_CALCULATE_TOTAL = "calcular_total"
IDENTIFIER_PROCESSED_FILES = "arquivos_processados"
IDENTIFIER_XML_FILE = "XMLArquivo"
IDENTIFIER_SAMPLE_ONE = "amostra1"
IDENTIFIER_UNICODE_CAMEL = "relatórioArquivo"
IDENTIFIER_UNICODE_UPPER = "arquivoÁrvore"
IDENTIFIER_AVAILABLE = "disponivel"
TERM_VERIFICATION = "verificacao"
TERM_PROCESS = "processar"


from scripts.code_language_guard import (
    BaselineEntry,
    LanguagePolicyError,
    compare_to_baseline,
    group_findings,
    load_baseline,
    load_policy,
    scan_repository,
    _run_git,
)

from scripts import validate_repo


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

    def test_policy_rejects_parent_traversal_exclusion(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_json(root, "config/code_language_policy.json", {
                "schema": "genoma-code-language-policy-v1",
                "scan_suffixes": [".py"],
                "technical_terms": ["arquivo"],
                "contract_literals": [],
                "excluded_roots": [{"path": "../escape", "reason": "invalid"}],
            })
            with self.assertRaisesRegex(LanguagePolicyError, "invalid excluded root path"):
                load_policy(root)

    def test_baseline_rejects_parent_traversal_entry(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_json(root, "config/code_language_legacy_baseline.json", {
                "schema": "genoma-code-language-legacy-baseline-v1",
                "source_commit": "0" * 40,
                "entries": [{"path": "../escape.py", "kind": "comment", "token": TERM_ARCHIVE, "count": 1}],
            })
            with self.assertRaisesRegex(LanguagePolicyError, "invalid baseline entry path"):
                load_baseline(root)

    def test_repository_policy_covers_common_technical_lemmas(self):
        policy = load_policy(ROOT)
        self.assertTrue({"calcular", "processar", "arquivo"} <= policy.technical_terms)



class PythonLanguageScannerTest(unittest.TestCase):
    def _repo(self, files: dict[str, str]) -> tuple[TemporaryDirectory, Path]:
        td = TemporaryDirectory()
        root = Path(td.name)
        policy = {
            "schema": "genoma-code-language-policy-v1",
            "scan_suffixes": [".py"],
            "technical_terms": ["arquivo", "amostra", "calcular", "disponivel", "processar", "relatorio", "validar", "verificacao"],
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
        self.assertTrue(any(f.kind == "identifier" and f.token == PORTUGUESE_FIXTURE_IDENTIFIER for f in findings), findings)

    def test_camel_case_portuguese_identifier_is_reported(self):
        td, root = self._repo({"pkg/mod.py": "class RelatorioBuilder:\n    pass\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "identifier" and f.token == PORTUGUESE_FIXTURE_CLASS for f in findings), findings)

    def test_accented_comment_is_normalized_and_reported(self):
        td, root = self._repo({"pkg/mod.py": "# verificação\nvalue = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(
            any(f.kind == "comment" and f.token == TERM_VERIFICATION for f in findings),
            findings,
        )

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

    def test_repeated_comment_term_preserves_occurrence_count(self):
        td, root = self._repo({"pkg/mod.py": "# validar validar\nvalue = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        matches = [f for f in findings if f.kind == "comment" and f.token == TERM_VALIDATE]
        self.assertEqual(len(matches), 2, findings)

    def test_unlisted_portuguese_lemma_is_reported_across_scanned_surfaces(self):
        source = 'def calcular_total():\n    """calcular resultado"""\n    # calcular agora\n    return 1\n'
        td, root = self._repo({"pkg/mod.py": source})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "identifier" and f.token == IDENTIFIER_CALCULATE_TOTAL for f in findings), findings)
        self.assertTrue(any(f.kind == "comment" and f.token == TERM_CALCULATE for f in findings), findings)
        self.assertTrue(any(f.kind == "docstring" and f.token == TERM_CALCULATE for f in findings), findings)

    def test_portuguese_plural_and_participle_are_normalized(self):
        td, root = self._repo({"pkg/mod.py": "def arquivos_processados():\n    return True\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        finding = next(
            f for f in findings
            if f.kind == "identifier" and f.token == IDENTIFIER_PROCESSED_FILES
        )
        self.assertIn(TERM_PROCESS, finding.matched_terms)

    def test_acronym_pascal_case_identifier_is_split(self):
        td, root = self._repo({"pkg/mod.py": "class XMLArquivo:\n    pass\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "identifier" and f.token == IDENTIFIER_XML_FILE for f in findings), findings)

    def test_unicode_camel_case_identifier_is_split(self):
        td, root = self._repo({"pkg/mod.py": "relatórioArquivo = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        finding = next(
            f for f in findings
            if f.kind == "identifier" and f.token == IDENTIFIER_UNICODE_CAMEL
        )
        self.assertIn(TERM_ARCHIVE, finding.matched_terms)

    def test_unicode_uppercase_boundary_is_split(self):
        td, root = self._repo({"pkg/mod.py": "arquivoÁrvore = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        finding = next(
            f for f in findings
            if f.kind == "identifier" and f.token == IDENTIFIER_UNICODE_UPPER
        )
        self.assertIn(TERM_ARCHIVE, finding.matched_terms)

    def test_contract_literal_word_does_not_exempt_identifier(self):
        td, root = self._repo({"pkg/mod.py": "def disponivel():\n    return True\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(
            any(f.kind == "identifier" and f.token == IDENTIFIER_AVAILABLE for f in findings),
            findings,
        )

    def test_full_contract_literal_identifier_form_is_preserved(self):
        td, root = self._repo({"pkg/mod.py": "NAO_DISPONIVEL = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertEqual(findings, ())

    def test_letter_digit_boundary_does_not_hide_term(self):
        td, root = self._repo({"pkg/mod.py": "amostra1 = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "identifier" and f.token == IDENTIFIER_SAMPLE_ONE for f in findings), findings)

    def test_unaliased_import_and_keyword_argument_are_scanned(self):
        source = "from pacote import validar_arquivo\nfunc(arquivo=True)\n"
        td, root = self._repo({"pkg/mod.py": source})
        with td:
            findings = scan_repository(root, load_policy(root))
        tokens = {f.token for f in findings if f.kind == "identifier"}
        self.assertIn("validar_arquivo", tokens)
        self.assertIn("arquivo", tokens)

    def test_pattern_binding_names_are_scanned(self):
        source = 'match payload:\n    case {"item": arquivo}:\n        pass\n'
        td, root = self._repo({"pkg/mod.py": source})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "identifier" and f.token == TERM_ARCHIVE for f in findings), findings)

    def test_unparseable_python_fails_closed(self):
        td, root = self._repo({"pkg/mod.py": "def broken(:\n    pass\n"})
        with td, self.assertRaisesRegex(LanguagePolicyError, "unable to parse scanned Python source"):
            scan_repository(root, load_policy(root))

    def test_historical_root_is_not_scanned(self):
        td, root = self._repo({"docs/history/v3.3/example.py": "def validar_arquivo():\n    return True\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertEqual(findings, ())


def _git(root: Path, *args: str) -> str:
    result = _run_git(root, *args)
    return result.stdout.decode("utf-8", errors="strict").strip()


def _init_git_repo(root: Path) -> str:
    _git(root, "init")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Language Guard Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "baseline")
    return _git(root, "rev-parse", "HEAD")


class GitProvenanceExecutionTest(unittest.TestCase):
    def test_git_provenance_uses_absolute_trusted_executable(self):
        from scripts import code_language_guard as guard
        completed = guard.subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(guard.subprocess, "run", return_value=completed) as runner:
            guard._run_git(ROOT, "status")
        command = runner.call_args.args[0]
        executable = Path(command[0])
        self.assertTrue(executable.is_absolute(), command)
        if sys.platform == "win32":
            self.assertEqual(executable, Path(r"C:\Program Files\Git\cmd\git.exe"))
        else:
            self.assertEqual(executable, Path("/usr/bin/git"))


class BaselineWriteSafetyTest(unittest.TestCase):
    def _repo(self) -> tuple[TemporaryDirectory, Path, str]:
        td = TemporaryDirectory()
        root = Path(td.name)
        policy = {
            "schema": "genoma-code-language-policy-v1",
            "scan_suffixes": [".py"],
            "technical_terms": ["arquivo", "validar"],
            "contract_literals": ["VERIFICADO", "NÃO DISPONÍVEL"],
            "excluded_roots": [],
        }
        _write_json(root, "config/code_language_policy.json", policy)
        source = root / "pkg" / "base.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# validar\nvalue = 1\n", encoding="utf-8")
        base = _init_git_repo(root)
        _write_json(root, "config/code_language_legacy_baseline.json", {
            "schema": "genoma-code-language-legacy-baseline-v1",
            "source_commit": base,
            "entries": [{"path": "pkg/base.py", "kind": "comment", "token": TERM_VALIDATE, "count": 1}],
        })
        return td, root, base

    def test_write_baseline_rejects_new_debt(self):
        from scripts import code_language_guard as guard
        td, root, base = self._repo()
        with td:
            (root / "pkg" / "new.py").write_text("# validar\nvalue = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(LanguagePolicyError, "new language debt"):
                guard._write_baseline(root, base)

    def test_write_baseline_rejects_nonexistent_commit(self):
        from scripts import code_language_guard as guard
        td, root, _ = self._repo()
        with td, self.assertRaisesRegex(LanguagePolicyError, "source_commit"):
            guard._write_baseline(root, "0" * 40)

    def test_bootstrap_baseline_uses_source_tree_not_worktree(self):
        from scripts import code_language_guard as guard
        td, root, base = self._repo()
        with td:
            (root / "pkg" / "new.py").write_text("# validar\nvalue = 2\n", encoding="utf-8")
            guard._bootstrap_baseline(root, base)
            entries = load_baseline(root)
        self.assertEqual(entries, (BaselineEntry("pkg/base.py", "comment", "validar", 1),))

    def test_check_rejects_nonexistent_source_commit(self):
        from scripts import code_language_guard as guard
        td, root, _ = self._repo()
        with td:
            payload = json.loads((root / "config/code_language_legacy_baseline.json").read_text(encoding="utf-8"))
            payload["source_commit"] = "0" * 40
            _write_json(root, "config/code_language_legacy_baseline.json", payload)
            with self.assertRaisesRegex(LanguagePolicyError, "source_commit"):
                guard._check(root)

    def test_check_rejects_entry_absent_from_source_commit(self):
        from scripts import code_language_guard as guard
        td, root, base = self._repo()
        with td:
            new_file = root / "pkg" / "new.py"
            new_file.write_text("# validar\nvalue = 2\n", encoding="utf-8")
            _write_json(root, "config/code_language_legacy_baseline.json", {
                "schema": "genoma-code-language-legacy-baseline-v1",
                "source_commit": base,
                "entries": [
                    {"path": "pkg/base.py", "kind": "comment", "token": TERM_VALIDATE, "count": 1},
                    {"path": "pkg/new.py", "kind": "comment", "token": TERM_VALIDATE, "count": 1},
                ],
            })
            with self.assertRaisesRegex(LanguagePolicyError, "supported by source_commit"):
                guard._check(root)

    def test_library_validation_rejects_invalid_baseline_provenance(self):
        from scripts import code_language_guard as guard
        td, root, _ = self._repo()
        with td:
            payload = json.loads((root / "config/code_language_legacy_baseline.json").read_text(encoding="utf-8"))
            payload["source_commit"] = "0" * 40
            _write_json(root, "config/code_language_legacy_baseline.json", payload)
            with self.assertRaisesRegex(LanguagePolicyError, "source_commit"):
                guard.validate_code_language(root, [])

    def test_check_accepts_exact_trusted_pull_request_base(self):
        from scripts import code_language_guard as guard
        td, root, base = self._repo()
        with td:
            _write_json(root, "event.json", {"pull_request": {"base": {"sha": base}}})
            event_path = root / "event.json"
            with mock.patch.dict(
                os.environ,
                {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event_path)},
                clear=False,
            ):
                self.assertEqual(guard._check(root), 0)

    def test_check_rejects_source_commit_after_trusted_pull_request_base(self):
        from scripts import code_language_guard as guard
        td, root, base = self._repo()
        with td:
            new_file = root / "pkg" / "new.py"
            new_file.write_text("# validar\nvalue = 2\n", encoding="utf-8")
            _git(root, "add", ".")
            _git(root, "commit", "-m", "introduce later debt")
            later = _git(root, "rev-parse", "HEAD")
            _write_json(root, "config/code_language_legacy_baseline.json", {
                "schema": "genoma-code-language-legacy-baseline-v1",
                "source_commit": later,
                "entries": [
                    {"path": "pkg/base.py", "kind": "comment", "token": TERM_VALIDATE, "count": 1},
                    {"path": "pkg/new.py", "kind": "comment", "token": TERM_VALIDATE, "count": 1},
                ],
            })
            _write_json(root, "event.json", {"pull_request": {"base": {"sha": base}}})
            event_path = root / "event.json"
            with mock.patch.dict(
                os.environ,
                {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event_path)},
                clear=False,
            ):
                with self.assertRaisesRegex(LanguagePolicyError, "trusted pull request base"):
                    guard._check(root)


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
        with mock.patch.object(
            validate_repo,
            "validate_code_language",
            side_effect=lambda _root, out: out.append("language guard sentinel"),
        ) as guard:
            errors = validate_repo.validate(ROOT)
        guard.assert_called_once()
        called_root, called_errors = guard.call_args.args
        self.assertEqual(called_root, ROOT)
        self.assertIs(called_errors, errors)
        self.assertIn("language guard sentinel", errors)


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
