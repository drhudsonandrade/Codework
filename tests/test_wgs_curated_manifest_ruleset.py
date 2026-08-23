from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.build_wgs_curated_manifest import _verified_ruleset_identity


class WgsCuratedManifestRulesetTests(unittest.TestCase):
    def test_verified_ruleset_identity_comes_from_sealed_transport(self) -> None:
        identity = _verified_ruleset_identity()
        self.assertEqual(identity["status"], "VIGENTE")
        self.assertEqual(identity["version"], "v3.4")
        self.assertEqual(identity["effective_date"], "17/08/2026")
        self.assertEqual(
            identity["sha256"],
            "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
        )

    def test_verified_ruleset_identity_rejects_transport_mismatch(self) -> None:
        bad = {
            "canonical_filename": "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt",
            "raw_sha256": "0" * 64,
            "version": "v3.4",
            "effective_date": "17/08/2026",
        }
        with patch("scripts.build_wgs_curated_manifest.verify_transport", return_value=bad):
            with self.assertRaisesRegex(SystemExit, "RULESET NÃO DISPONÍVEL/CONFLITANTE"):
                _verified_ruleset_identity()


if __name__ == "__main__":
    unittest.main()
