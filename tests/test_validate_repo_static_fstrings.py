from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.validate_repo as validate_repo_module
from scripts.validate_repo import (
    SUPERSEDED_IDENTITY_TEST_FIXTURES,
    _missing_path_error,
    validate,
    validate_superseded_identity_locations,
)

ROOT = Path(__file__).resolve().parents[1]


class ValidateRepoStaticFstringTests(unittest.TestCase):
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
        module = sys.modules[__name__]
        original_scanner = validate_repo_module.validate_superseded_identity_locations
        forbidden = AssertionError("full repository validator must not run in the targeted fixture test")
        with (
            mock.patch.object(module, "validate", side_effect=forbidden) as local_validate,
            mock.patch.object(validate_repo_module, "validate", side_effect=forbidden) as module_validate,
            mock.patch.object(
                module, "validate_superseded_identity_locations", wraps=original_scanner
            ) as targeted_scanner,
            mock.patch.object(
                validate_repo_module,
                "validate_superseded_identity_locations",
                wraps=original_scanner,
            ) as module_scanner,
            mock.patch.object(self, "validate", side_effect=forbidden, create=True) as self_validate,
        ):
            self.test_registered_test_fixtures_do_not_block_the_current_checkout()

        local_validate.assert_not_called()
        module_validate.assert_not_called()
        self_validate.assert_not_called()
        module_scanner.assert_not_called()
        targeted_scanner.assert_called_once()
        args, kwargs = targeted_scanner.call_args
        self.assertEqual(len(args), 2)
        self.assertEqual(args[0], ROOT)
        self.assertIsInstance(args[1], list)
        self.assertEqual(kwargs, {})

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
