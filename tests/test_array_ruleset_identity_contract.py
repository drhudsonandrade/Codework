from __future__ import annotations

import unittest

from array_pipeline import annotation, qc
from scripts import build_array_case_manifest

EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_VERSION = "v3.4"
EXPECTED_DATE = "17/08/2026"
EXPECTED_SHA = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"


class ArrayRulesetIdentityContractTests(unittest.TestCase):
    def test_every_array_ruleset_producer_emits_full_canonical_identity(self) -> None:
        expected = {
            "status": "VIGENTE",
            "version": EXPECTED_VERSION,
            "effective_date": EXPECTED_DATE,
            "sha256": EXPECTED_SHA,
            "canonical_filename": EXPECTED_NAME,
        }
        for name, ruleset in (
            ("qc", qc.RULESET),
            ("annotation", annotation.RULESET),
            ("curation_manifest", build_array_case_manifest.RULESET),
        ):
            with self.subTest(producer=name):
                self.assertEqual(ruleset, expected)


if __name__ == "__main__":
    unittest.main()
