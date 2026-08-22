from __future__ import annotations

import json
import unittest
from pathlib import Path

from policy_engine.genoma_policy import paths as policy_paths
from policy_engine.genoma_policy import ruleset as policy_ruleset
from scripts import sealed_ruleset

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_SHA = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
EXPECTED_VERSION = "v3.4"
EXPECTED_DATE = "17/08/2026"


class V34ActivationContractTests(unittest.TestCase):
    def test_shared_ruleset_contract_targets_v34(self) -> None:
        self.assertEqual(sealed_ruleset.EXPECTED_NAME, EXPECTED_NAME)
        self.assertEqual(sealed_ruleset.EXPECTED_SHA, EXPECTED_SHA)
        self.assertEqual(sealed_ruleset.EXPECTED_VERSION, EXPECTED_VERSION)
        self.assertEqual(sealed_ruleset.EXPECTED_DATE, EXPECTED_DATE)

        self.assertEqual(policy_ruleset.EXPECTED_CANONICAL, EXPECTED_NAME)
        self.assertEqual(policy_ruleset.EXPECTED_VERSION, EXPECTED_VERSION)
        self.assertEqual(policy_ruleset.EXPECTED_DATE, EXPECTED_DATE)
        self.assertEqual(policy_paths.CANONICAL_RULESET_NAME, EXPECTED_NAME)
        self.assertEqual(policy_paths.CANONICAL_MANIFEST_RELATIVE, Path("manifests") / "RULESET_V3.4.sha256")

    def test_sealed_transport_is_v34_and_keeps_13_chunks(self) -> None:
        manifest = json.loads((ROOT / "normative" / "sealed" / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["canonical_filename"], EXPECTED_NAME)
        self.assertEqual(manifest["version"], EXPECTED_VERSION)
        self.assertEqual(manifest["effective_date"], EXPECTED_DATE)
        self.assertEqual(manifest["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(len(manifest["transport_parts"]), 13)
        self.assertFalse(manifest["active_at_rest"])

    def test_external_v34_manifest_is_the_active_contract(self) -> None:
        current = ROOT / "manifests" / "RULESET_V3.4.sha256"
        self.assertTrue(current.is_file())
        self.assertEqual(current.read_text(encoding="ascii").strip(), f"{EXPECTED_SHA}  {EXPECTED_NAME}")

    def test_live_smoke_targets_v34_identity(self) -> None:
        text = (ROOT / "scripts" / "run_live_post_deployment_smoke.py").read_text(encoding="utf-8")
        self.assertIn(EXPECTED_SHA, text)
        self.assertIn("v3.4/VIGENTE/17/08/2026", text)
        self.assertIn(EXPECTED_NAME, text)
        self.assertNotIn("v3.3/VIGENTE/14/08/2026", text)


if __name__ == "__main__":
    unittest.main()
