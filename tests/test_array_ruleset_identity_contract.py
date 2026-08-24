from __future__ import annotations

import unittest

from scripts import build_array_case_manifest

EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_VERSION = "v3.4"
EXPECTED_DATE = "17/08/2026"
EXPECTED_SHA = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"


class ArrayRulesetIdentityContractTests(unittest.TestCase):
    def test_curation_manifest_emits_full_canonical_identity_for_policy_gate(self) -> None:
        self.assertEqual(
            build_array_case_manifest.RULESET,
            {
                "status": "VIGENTE",
                "version": EXPECTED_VERSION,
                "effective_date": EXPECTED_DATE,
                "sha256": EXPECTED_SHA,
                "canonical_filename": EXPECTED_NAME,
            },
        )


if __name__ == "__main__":
    unittest.main()
