from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate_repo import _missing_path_error, validate

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

    def test_the_current_checkout_satisfies_the_whole_repository_contract(self) -> None:
        """validate() must return nothing at all, not merely nothing from three files.

        scripts/validate_repo.py is the repository's own contract guardian. A test
        that filters its output down to a chosen subset before asserting emptiness
        passes while any number of unrelated violations stand, which is precisely
        the state the guardian exists to prevent.
        """
        self.assertEqual(validate(ROOT), [])

    def test_registered_test_fixtures_do_not_block_the_current_checkout(self) -> None:
        """The narrower fixture-specific guarantee, kept for a precise failure message."""
        errors = validate(ROOT)
        allowed = {
            "tests/test_v34_activation_contract.py",
            "tests/test_validate_repo_static_fstrings.py",
            "policy_engine/tests/test_policy_engine.py",
        }
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
