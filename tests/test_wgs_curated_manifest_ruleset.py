from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.build_wgs_curated_manifest import _verified_ruleset_identity

EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_SHA = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"


class WgsCuratedManifestRulesetTests(unittest.TestCase):
    def test_verified_ruleset_identity_comes_from_sealed_transport(self) -> None:
        identity = _verified_ruleset_identity()
        self.assertEqual(identity["status"], "VIGENTE")
        self.assertEqual(identity["version"], "v3.4")
        self.assertEqual(identity["effective_date"], "17/08/2026")
        self.assertEqual(identity["sha256"], EXPECTED_SHA)
        self.assertEqual(identity["canonical_filename"], EXPECTED_NAME)

    def test_verified_ruleset_identity_rejects_wrong_canonical_filename_with_valid_sha(self) -> None:
        bad = {
            "canonical_filename": "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_WRONG.txt",
            "raw_sha256": EXPECTED_SHA,
            "version": "v3.4",
            "effective_date": "17/08/2026",
        }
        with patch("scripts.build_wgs_curated_manifest.verify_transport", return_value=bad):
            with self.assertRaisesRegex(SystemExit, "RULESET NÃO DISPONÍVEL/CONFLITANTE"):
                _verified_ruleset_identity()

    def test_verified_ruleset_identity_rejects_transport_digest_mismatch(self) -> None:
        bad = {
            "canonical_filename": EXPECTED_NAME,
            "raw_sha256": "0" * 64,
            "version": "v3.4",
            "effective_date": "17/08/2026",
        }
        with patch("scripts.build_wgs_curated_manifest.verify_transport", return_value=bad):
            with self.assertRaisesRegex(SystemExit, "RULESET NÃO DISPONÍVEL/CONFLITANTE"):
                _verified_ruleset_identity()

    def test_verified_ruleset_identity_rejects_wrong_version_alone(self) -> None:
        """Version is checked, but only ever alongside a second wrong field until now.

        Isolating it proves the version comparison is load-bearing rather than
        incidentally covered by the filename or digest assertion.
        """
        bad = {
            "canonical_filename": EXPECTED_NAME,
            "raw_sha256": EXPECTED_SHA,
            "version": "v3.5",
            "effective_date": "17/08/2026",
        }
        with patch("scripts.build_wgs_curated_manifest.verify_transport", return_value=bad):
            with self.assertRaisesRegex(SystemExit, "RULESET NÃO DISPONÍVEL/CONFLITANTE"):
                _verified_ruleset_identity()

    def test_verified_ruleset_identity_rejects_wrong_effective_date_alone(self) -> None:
        bad = {
            "canonical_filename": EXPECTED_NAME,
            "raw_sha256": EXPECTED_SHA,
            "version": "v3.4",
            "effective_date": "18/08/2026",
        }
        with patch("scripts.build_wgs_curated_manifest.verify_transport", return_value=bad):
            with self.assertRaisesRegex(SystemExit, "RULESET NÃO DISPONÍVEL/CONFLITANTE"):
                _verified_ruleset_identity()


if __name__ == "__main__":
    unittest.main()
