from __future__ import annotations

import ast
import inspect
import tempfile
import textwrap
import unittest
from pathlib import Path

import scripts.validate_repo as validate_repo_module
from scripts.validate_repo import (
    SUPERSEDED_IDENTITY_TEST_FIXTURES,
    _missing_path_error,
    validate,
    validate_superseded_identity_locations,
)

ROOT = Path(__file__).resolve().parents[1]


def _call_terminal_names(tree: ast.AST) -> set[str]:
    return {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
    }


_ALLOWED_REGISTERED_FIXTURE_CALLS = {
    "assertTrue",
    "validate_superseded_identity_locations",
    "any",
    "assertEqual",
}


def _assert_registered_fixture_call_allowlist(tree: ast.AST) -> set[str]:
    scanner_name = "validate_superseded_identity_locations"
    calls = _call_terminal_names(tree)
    unexpected = calls - _ALLOWED_REGISTERED_FIXTURE_CALLS
    missing = {scanner_name} - calls

    if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)):
        raise AssertionError("local imports are forbidden in the optimized fixture test")

    stored_names = [
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    ]
    if scanner_name in stored_names or "ROOT" in stored_names:
        raise AssertionError("scanner or ROOT must not be rebound")
    if stored_names.count("errors") != 1:
        raise AssertionError("errors must be initialized exactly once")

    shadowing_defs = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name in {scanner_name, "ROOT"}
    ]
    if shadowing_defs:
        raise AssertionError(f"shadowing definitions are forbidden: {shadowing_defs}")

    errors_initializers = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "errors":
            errors_initializers.append(node.value)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "errors" for target in node.targets
        ):
            errors_initializers.append(node.value)
    if len(errors_initializers) != 1 or not isinstance(errors_initializers[0], ast.List) or errors_initializers[0].elts:
        raise AssertionError("errors must be initialized once as an empty list")

    scanner_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == scanner_name
    ]
    if len(scanner_calls) != 1:
        raise AssertionError("exactly one direct scanner call is required")
    scanner_call = scanner_calls[0]
    exact_args = (
        len(scanner_call.args) == 2
        and isinstance(scanner_call.args[0], ast.Name)
        and scanner_call.args[0].id == "ROOT"
        and isinstance(scanner_call.args[1], ast.Name)
        and scanner_call.args[1].id == "errors"
        and not scanner_call.keywords
    )
    if not exact_args:
        raise AssertionError("scanner must be called exactly as validate_superseded_identity_locations(ROOT, errors)")

    if unexpected or missing:
        raise AssertionError(f"unexpected={sorted(unexpected)} missing={sorted(missing)}")
    return calls



class ValidateRepoStaticFstringTests(unittest.TestCase):
    def test_call_terminal_names_catches_direct_and_attribute_calls(self) -> None:
        tree = ast.parse("validate(ROOT)\nvalidator.validate(ROOT)\nself.validate(ROOT)\n")
        self.assertEqual(_call_terminal_names(tree), {"validate"})

    def test_target_call_allowlist_rejects_local_validator_aliases(self) -> None:
        tree = ast.parse(
            "full_validate = validate\nfull_validate(ROOT)\n"
            "runner = validator.validate\nrunner(ROOT)\n"
        )
        with self.assertRaises(AssertionError):
            _assert_registered_fixture_call_allowlist(tree)

    def test_target_call_guard_rejects_scanner_rebinding(self) -> None:
        tree = ast.parse(
            "validate_superseded_identity_locations = validate\n"
            "errors = []\n"
            "validate_superseded_identity_locations(ROOT, errors)\n"
        )
        with self.assertRaises(AssertionError):
            _assert_registered_fixture_call_allowlist(tree)

    def test_target_call_guard_rejects_wrong_scanner_arguments(self) -> None:
        tree = ast.parse(
            "errors = []\n"
            "validate_superseded_identity_locations(errors, ROOT)\n"
        )
        with self.assertRaises(AssertionError):
            _assert_registered_fixture_call_allowlist(tree)

    def test_static_fstring_format_spec_cannot_hide_superseded_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stray = root / "reporting" / "formatted_identity.py"
            stray.parent.mkdir(parents=True, exist_ok=True)
            stray.write_text('RULESET = f"GENOMA-V3.{3:01d}"\n', encoding="utf-8")
            errors = validate(root)
            self.assertTrue(
                any(
                    "reporting/formatted_identity.py" in error
                    and "superseded identity outside explicit history" in error
                    and "GENOMA-V3.3" in error
                    for error in errors
                ),
                errors,
            )

    def test_registered_fixture_check_uses_only_targeted_identity_scanner(self) -> None:
        self.assertIs(
            validate_superseded_identity_locations,
            validate_repo_module.validate_superseded_identity_locations,
        )
        self.assertEqual(ROOT, Path(__file__).resolve().parents[1])
        source = inspect.getsource(self.test_registered_test_fixtures_do_not_block_the_current_checkout)
        tree = ast.parse(textwrap.dedent(source))
        calls = _assert_registered_fixture_call_allowlist(tree)
        self.assertEqual(calls, _ALLOWED_REGISTERED_FIXTURE_CALLS)

    def test_registered_test_fixtures_do_not_block_the_current_checkout(self) -> None:
        # Derived from the registry itself so a newly registered fixture — for example
        # tests/test_superseded_identity_scanner.py — is covered without editing a second
        # copy of the list here.
        allowed = SUPERSEDED_IDENTITY_TEST_FIXTURES
        self.assertTrue(allowed, "the fixture registry must not be empty")
        errors: list[str] = []
        validate_superseded_identity_locations(ROOT, errors)
        blocked_fixture_errors = [
            error
            for error in errors
            if "superseded identity outside explicit history" in error
            and any(relative in error for relative in allowed)
        ]
        self.assertEqual(blocked_fixture_errors, [])

    def test_unregistered_test_file_with_superseded_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stray = root / "tests" / "test_unregistered_history_fixture.py"
            stray.parent.mkdir(parents=True, exist_ok=True)
            stray.write_text('RULESET = "GENOMA-V3.3"\n', encoding="utf-8")
            errors = validate(root)
            self.assertTrue(
                any(
                    "tests/test_unregistered_history_fixture.py" in error
                    and "superseded identity outside explicit history" in error
                    and "GENOMA-V3.3" in error
                    for error in errors
                ),
                errors,
            )

    def test_missing_ruleset_manifest_message_is_actionable(self) -> None:
        message = _missing_path_error("manifests/RULESET_V3.4.sha256")
        self.assertIn("restore the tracked canonical SHA manifest", message)
        self.assertIn("do not add an active plaintext ruleset", message)


if __name__ == "__main__":
    unittest.main()
