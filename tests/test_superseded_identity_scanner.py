"""A historical mention of a superseded ruleset is not an active normative source.

These tests pin the boundary the scanner has to hold from both sides: it must keep
blocking anything that could activate an obsolete ruleset, and it must stop flagging
prose, dated filenames, unrelated timestamps and negative regression fixtures.
"""
from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_repo import (
    SUPERSEDED_STRONG_TOKENS,
    SUPERSEDED_WEAK_TOKENS,
    validate_superseded_identity_locations,
)


def _scan(files: dict[str, str]) -> list[str]:
    with TemporaryDirectory() as td:
        root = Path(td)
        shutil.copytree(ROOT / "docs" / "history", root / "docs" / "history")
        for relative, content in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        errors: list[str] = []
        validate_superseded_identity_locations(root, errors)
        return errors


class SupersededIdentityContractTest(unittest.TestCase):
    def test_registry_splits_strong_and_weak_tokens(self):
        self.assertIn("REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt", SUPERSEDED_STRONG_TOKENS)
        self.assertIn("RULESET_V3.3.sha256", SUPERSEDED_STRONG_TOKENS)
        self.assertIn("187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a", SUPERSEDED_STRONG_TOKENS)
        self.assertIn("v3.3", SUPERSEDED_WEAK_TOKENS)
        self.assertIn("14/08/2026", SUPERSEDED_WEAK_TOKENS)
        self.assertIn("2026-08-14", SUPERSEDED_WEAK_TOKENS)
        self.assertFalse(set(SUPERSEDED_STRONG_TOKENS) & set(SUPERSEDED_WEAK_TOKENS))


class SupersededIdentityStillBlockedTest(unittest.TestCase):
    """Protection against reactivating an obsolete ruleset must not weaken."""

    def test_canonical_filename_is_rejected_in_any_text_surface(self):
        errors = _scan({"notes.md": "restore REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt\n"})
        self.assertTrue(any("REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt" in e for e in errors), errors)

    def test_superseded_raw_sha_is_rejected(self):
        errors = _scan({"pin.json": '{"sha256": "187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a"}\n'})
        self.assertTrue(errors)

    def test_superseded_manifest_filename_is_rejected_in_a_path(self):
        errors = _scan({"manifests/RULESET_V3.3.sha256": "deadbeef  x.txt\n"})
        self.assertTrue(any("path outside explicit history" in e for e in errors), errors)

    def test_superseded_rule_id_prefix_is_rejected(self):
        errors = _scan({"policy.rego": 'rule_id := "GENOMA-V3.3-260"\n'})
        self.assertTrue(errors)

    def test_python_constant_declaring_the_old_version_is_rejected(self):
        errors = _scan({"config.py": 'CANONICAL_RULESET_VERSION = "v3.3"\n'})
        self.assertTrue(any("declared as active" in e for e in errors), errors)

    def test_python_dict_entry_declaring_the_old_identity_is_rejected(self):
        errors = _scan({"config.py": 'RULESET = {"version": "v3.3", "effective_date": "14/08/2026"}\n'})
        self.assertTrue(any("declared as active" in e for e in errors), errors)

    def test_fstring_constant_declaring_the_old_version_is_rejected(self):
        errors = _scan({"stamp.py": 'code = "01"\nCURRENT_RULESET_LABEL = f"GENOMA,{code},v3.3,report"\n'})
        self.assertTrue(any("declared as active" in e for e in errors), errors)

    def test_declaration_line_in_markdown_is_rejected(self):
        errors = _scan({"doc.md": "STATUS NORMATIVO: VIGENTE — v3.3\n"})
        self.assertTrue(any("declared as active" in e for e in errors), errors)


class HistoricalOccurrenceIsAllowedTest(unittest.TestCase):
    """A permitted historical occurrence is not an active normative source."""

    def test_prose_describing_the_migration_is_allowed(self):
        self.assertEqual(_scan({"CHANGELOG.md": "Migrated from v3.3 to v3.4 on 2026-08-17.\n"}), [])

    def test_dated_plan_filename_is_allowed(self):
        self.assertEqual(_scan({"docs/plans/2026-08-14-private-mcp.md": "Plan notes.\n"}), [])

    def test_unrelated_timestamp_in_a_test_fixture_is_allowed(self):
        self.assertEqual(_scan({"tests/test_freshness.py": 'PAYLOAD = {"checked_at": "2026-08-14T12:00:00Z"}\n'}), [])

    def test_negative_regression_fixture_is_allowed(self):
        source = 'def test_rejects_old_marker():\n    assert not accepts("GENOMA-HUDSON-RULESET-v3.3")\n'
        self.assertEqual(_scan({"tests/test_markers.py": source}), [])

    def test_python_comment_and_docstring_mentions_are_allowed(self):
        source = '"""Superseded v3.3 behaviour is documented here."""\n# previously v3.3, effective 14/08/2026\n'
        self.assertEqual(_scan({"legacy_notes.py": source}), [])

    def test_typescript_timestamp_fixture_is_allowed(self):
        self.assertEqual(_scan({"mcp/test/core.test.ts": 'const startedAt = "2026-08-14T00:00:00.000Z";\n'}), [])


class RepositoryIsCleanUnderTheScannerTest(unittest.TestCase):
    def test_repository_has_no_superseded_identity_findings(self):
        errors: list[str] = []
        validate_superseded_identity_locations(ROOT, errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
