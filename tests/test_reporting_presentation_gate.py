"""Keep the repository presentation gate meaningful after locale extraction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import validate_repo

LOCALE = 'GENOMIC_RESULT = "RESULTADO GENÔMICO"\nLANGUAGE_TAG = "pt-BR"\n'
RENDERER = (
    "from reporting import locale_pt_br as pt_br\n"
    "def _pdf():\n    return pt_br.GENOMIC_RESULT\n"
    "def _docx():\n    return pt_br.GENOMIC_RESULT\n"
)


class ReportingPresentationGateTest(unittest.TestCase):
    """Exercise the real static gate with positive and corrupted file fixtures."""

    def _validate(self, locale=LOCALE, renderer=RENDERER, *, full_gate=False):
        """Write only temporary source fixtures and invoke the real locale gate."""
        self.assertTrue(hasattr(validate_repo, "validate_report_presentation"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "reporting"
            folder.mkdir()
            if locale is not None:
                (folder / "locale_pt_br.py").write_text(locale, encoding="utf-8")
            (folder / "editorial_v3_hifi.py").write_text(renderer, encoding="utf-8")
            errors = []
            if full_gate:
                errors = validate_repo.validate(root)
            else:
                validate_repo.validate_report_presentation(root, errors)
        return errors

    def test_owned_marker_used_by_both_renderers_is_accepted(self):
        """Moving a required display value does not remove the contract check."""
        self.assertEqual(self._validate(), [])

    def test_missing_or_changed_locale_contract_is_rejected(self):
        """Missing, translated, duplicate, computed or malformed constants fail closed."""
        for source in (
            None,
            LOCALE.replace("RESULTADO GENÔMICO", "GENOMIC RESULT"),
            LOCALE.replace("pt-BR", "en-US"),
            LOCALE + 'GENOMIC_RESULT = "changed"\n',
            LOCALE.replace('"RESULTADO GENÔMICO"', 'str("RESULTADO GENÔMICO")'),
            LOCALE + "BROKEN = [\n",
            LOCALE.replace('"pt-BR"', "123"),
        ):
            with self.subTest(source=source):
                self.assertTrue(self._validate(locale=source))

    def test_comments_wrong_imports_and_missing_renderer_use_are_rejected(self):
        """A comment or unused locale constant cannot satisfy the renderer contract."""
        for source in (
            RENDERER.replace("from reporting import locale_pt_br as pt_br", "# pt_br"),
            RENDERER.replace("from reporting import", "from unrelated import"),
            RENDERER.replace("from reporting import", "from .reporting import"),
            RENDERER.replace("return pt_br.GENOMIC_RESULT", "return 'unused'", 1),
            RENDERER + "\npt_br = object()\n",
            "# RESULTADO GENÔMICO\n",
        ):
            with self.subTest(source=source):
                self.assertTrue(self._validate(renderer=source))

    def test_repository_validation_never_executes_the_locale_source(self):
        """Nonliteral module statements are rejected, not imported or evaluated."""
        self.assertTrue(self._validate(locale=LOCALE + "raise RuntimeError('must not run')\n"))

    def test_full_repository_validator_dispatches_the_presentation_check(self):
        """The official gate must report a corrupt display value, not only a helper test."""
        errors = self._validate(
            locale=LOCALE.replace("RESULTADO GENÔMICO", "GENOMIC RESULT"), full_gate=True
        )
        self.assertIn("reporting presentation contract mismatch: GENOMIC_RESULT", errors)

    def test_repository_gate_requires_the_locale_file(self):
        """The dependency is part of the official required-path contract."""
        self.assertIn("reporting/locale_pt_br.py", validate_repo.REQUIRED_PATHS)


if __name__ == "__main__":
    unittest.main()
