from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate_repo import SUPERSEDED, _missing_path_error, validate


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
                    and SUPERSEDED["rule_id_prefix"] in error
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
