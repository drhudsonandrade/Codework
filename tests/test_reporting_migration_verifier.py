"""Exercise the independent reference and tracked-path migration proof."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import hashlib
import json
import io
import sys
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ReportingMigrationVerifierTest(unittest.TestCase):
    """Fail on substituted references or unreviewed added paths."""

    def _verifier(self):
        """Locate the proof implementation without hiding missing implementation."""
        self.assertIsNotNone(
            importlib.util.find_spec("scripts.verify_reporting_language_migration")
        )
        return importlib.import_module("scripts.verify_reporting_language_migration")

    def test_unexpected_added_or_deleted_tracked_paths_are_rejected(self):
        """Baseline-only iteration must not overlook additions to the candidate."""
        verifier = self._verifier()
        for candidate in ({"kept.py", "unexpected.py"}, set()):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                verifier.validate_path_scope({"kept.py"}, candidate, set())
        verifier.validate_path_scope({"kept.py"}, {"kept.py", "allowed.py"}, {"allowed.py"})

    def test_modified_reference_bytes_cannot_certify_themselves(self):
        """A candidate-controlled harness and golden cannot supply their own digest."""
        verifier = self._verifier()
        for relative, digest in verifier.REFERENCE_DIGESTS.items():
            original = (ROOT / relative).read_bytes()
            with patch.object(verifier, "git", return_value=original) as reader:
                self.assertEqual(verifier.read_reference(ROOT, relative), original)
                reader.assert_called_once_with(
                    ROOT, "show", f"{verifier.REFERENCE_COMMIT}:{relative}"
                )
            verifier.require_digest(original, digest, relative)
            with self.subTest(reference=relative), self.assertRaises(ValueError):
                verifier.require_digest(original + b"\n", digest, relative)
        self.assertEqual(verifier.REFERENCE_COMMIT, "c87b336a292f6c9f2fb490a51d2853b74ab72749")

    def test_locale_normalization_does_not_hide_unrelated_code_changes(self):
        """The exact extraction is reversible without masking different executable values."""
        verifier = self._verifier()
        texts = {"GENOMIC_RESULT": "RESULTADO GENÔMICO"}
        before = ast.parse('caption = "RESULTADO GENÔMICO"')
        moved = verifier.RestorePresentation(texts).visit(
            ast.parse("caption = pt_br.GENOMIC_RESULT")
        )
        self.assertEqual(ast.dump(before), ast.dump(moved))
        changed = verifier.RestorePresentation(texts).visit(ast.parse("caption = 'different'"))
        self.assertNotEqual(ast.dump(before), ast.dump(changed))

    def test_type_normalization_refuses_unapproved_fields_or_executable_statements(self):
        """A typing-only exception cannot remove an arbitrary new class or field."""
        verifier = self._verifier()
        for source in (
            "class _DesignTokens(TypedDict):\n    injected: str\n",
            "class _DesignTokens(TypedDict):\n    pass\n",
            "DESIGN: dict = {}\n",
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                verifier.RestorePresentation({}).visit(ast.parse(source))

    def test_comparison_digest_is_enforced_not_only_printed(self):
        """An incorrect expected digest must reject an otherwise valid replay."""
        verifier = self._verifier()
        self.assertTrue(hasattr(verifier, "comparison_digest"))
        proof = {"base": "synthetic-reference", "protected_files": []}
        encoded = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
        expected = hashlib.sha256(encoded).hexdigest()
        with patch.object(verifier, "EXPECTED_COMPARISON_SHA256", expected):
            self.assertEqual(verifier.comparison_digest(proof), expected)
            with self.assertRaisesRegex(ValueError, "comparison digest mismatch"):
                verifier.comparison_digest({**proof, "unexpected": True})
        with (
            patch.object(verifier, "EXPECTED_COMPARISON_SHA256", "0" * 64),
            self.assertRaisesRegex(ValueError, "comparison digest mismatch"),
        ):
            verifier.comparison_digest(proof)

    def test_inventory_has_a_fixed_source_and_reproducible_vocabulary(self):
        """Inventory claims name the base, paths, finite tokens and individual matches."""
        verifier = self._verifier()
        self.assertTrue(hasattr(verifier, "lexical_inventory"))
        fixture = '# ação\ndef retorna():\n    """Fixture."""\n    return 1\n'
        with patch.object(verifier, "git", return_value=fixture.encode()) as reader:
            result = verifier.lexical_inventory(ROOT)
        self.assertEqual(result["base"], "0a643128f3ac3e99a51428644c3012a2d638ab8b")
        self.assertEqual(len(result["paths"]), 33)
        self.assertEqual(reader.call_count, 33)
        self.assertEqual(len(result["identifier_candidates"]), 33)
        self.assertEqual(len(result["prose_candidates"]), 33)
        for call, relative in zip(reader.call_args_list, result["paths"], strict=True):
            self.assertEqual(call.args, (ROOT, "show", f"{result['base']}:{relative}"))
        self.assertTrue(result["identifier_tokens"])
        self.assertTrue(result["accent_pattern"])

    def test_inventory_cli_executes_the_documented_command(self):
        """The documented --inventory command must not fail as an unknown argument."""
        verifier = self._verifier()
        expected = {"base": "0a643128f3ac3e99a51428644c3012a2d638ab8b"}
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["verify-reporting", "--root", str(ROOT), "--inventory"]),
            patch.object(verifier, "lexical_inventory", return_value=expected) as inventory,
            redirect_stdout(output),
        ):
            self.assertEqual(verifier.main(), 0)
        inventory.assert_called_once_with(ROOT.resolve())
        self.assertEqual(json.loads(output.getvalue()), expected)


if __name__ == "__main__":
    unittest.main()
