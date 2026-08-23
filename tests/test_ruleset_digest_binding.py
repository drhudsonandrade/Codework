from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from policy_engine.genoma_policy import ruleset as policy_ruleset
from scripts import sealed_ruleset

ROOT = Path(__file__).resolve().parents[1]


class RulesetDigestBindingTests(unittest.TestCase):
    def test_load_ruleset_accepts_canonical_materialized_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target, _ = sealed_ruleset.materialize(ROOT / "normative" / "sealed", Path(td))
            loaded = policy_ruleset.load_ruleset(target)
            self.assertEqual(loaded.sha256, policy_ruleset.EXPECTED_SHA256)

    def test_load_ruleset_rejects_tampered_bytes_with_canonical_headers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target, _ = sealed_ruleset.materialize(ROOT / "normative" / "sealed", Path(td))
            original = target.read_text(encoding="utf-8")
            tampered = original.replace("Genoma Pessoal", "Genoma pessoal", 1)
            self.assertNotEqual(tampered, original)
            target.chmod(0o644)
            target.write_text(tampered, encoding="utf-8")

            with self.assertRaisesRegex(policy_ruleset.RulesetError, "sha256"):
                policy_ruleset.load_ruleset(target)


if __name__ == "__main__":
    unittest.main()
