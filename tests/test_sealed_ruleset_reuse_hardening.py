from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from scripts.sealed_ruleset import EXPECTED_NAME, SealedRulesetError, materialize

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


if __name__ == "__main__":
    unittest.main()
