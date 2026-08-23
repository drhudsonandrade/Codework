from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.sealed_ruleset import (
    EXPECTED_NAME,
    SealedRulesetError,
    _active_vigente_files,
    materialize,
)

ROOT = Path(__file__).resolve().parents[1]
SEALED = ROOT / "normative" / "sealed"


class SealedRulesetReuseHardeningTest(unittest.TestCase):
    def test_mode_0400_is_not_accepted_as_idempotent_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            target, _ = materialize(SEALED, td)
            os.chmod(target, 0o400)
            with self.assertRaises(SealedRulesetError):
                materialize(SEALED, td)

    def test_canonical_symlink_is_not_accepted_as_idempotent_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            target, _ = materialize(SEALED, out)
            payload = target.read_bytes()
            target.unlink()
            backing = out / "backing.txt"
            backing.write_bytes(payload)
            os.chmod(backing, 0o444)
            target.symlink_to(backing.name)
            self.assertEqual(target.name, EXPECTED_NAME)
            with self.assertRaises(SealedRulesetError):
                materialize(SEALED, out)

    def test_unreadable_candidate_active_ruleset_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            candidate = out / EXPECTED_NAME
            candidate.write_text("STATUS NORMATIVO: VIGENTE\n", encoding="utf-8")
            original_read_text = Path.read_text

            def read_text(path: Path, *args, **kwargs):
                if path == candidate:
                    raise OSError("permission denied")
                return original_read_text(path, *args, **kwargs)

            with (
                mock.patch.object(Path, "read_text", autospec=True, side_effect=read_text),
                self.assertRaisesRegex(SealedRulesetError, "could not read candidate active ruleset"),
            ):
                _active_vigente_files(out)


if __name__ == "__main__":
    unittest.main()
