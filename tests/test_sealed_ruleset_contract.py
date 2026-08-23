import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_STATUS = "VIGENTE"
EXPECTED_VERSION = "v3.4"
EXPECTED_DATE = "17/08/2026"
EXPECTED_SHA = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
SUPERSEDED_FIXTURE = next((ROOT / "docs" / "history").glob("*/superseded-identities.json"))
SUPERSEDED = json.loads(SUPERSEDED_FIXTURE.read_text(encoding="utf-8"))


class SealedRulesetContractTest(unittest.TestCase):
    def test_chunked_transport_is_single_source_of_truth(self):
        from scripts.sealed_ruleset import load_manifest, verify_transport

        manifest = load_manifest(ROOT / "normative" / "sealed")
        self.assertEqual(manifest["canonical_filename"], EXPECTED_NAME)
        self.assertEqual(manifest["status"], EXPECTED_STATUS)
        self.assertEqual(manifest["version"], EXPECTED_VERSION)
        self.assertEqual(manifest["effective_date"], EXPECTED_DATE)
        self.assertEqual(manifest["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(len(manifest["transport_parts"]), 13)

        sealed_root = ROOT / "normative" / "sealed"
        legacy_monolith = sealed_root / f"GENOMA_RULESET_{SUPERSEDED['version']}.txt.gz.b64"
        current_monolith = sealed_root / f"GENOMA_RULESET_{EXPECTED_VERSION}.txt.gz.b64"
        self.assertFalse(legacy_monolith.exists())
        self.assertFalse(current_monolith.exists())

        evidence = verify_transport(sealed_root)
        self.assertEqual(evidence["canonical_filename"], EXPECTED_NAME)
        self.assertEqual(evidence["status"], EXPECTED_STATUS)
        self.assertEqual(evidence["version"], EXPECTED_VERSION)
        self.assertEqual(evidence["effective_date"], EXPECTED_DATE)
        self.assertEqual(evidence["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(evidence["section_count"], 263)
        self.assertEqual(evidence["section_range"], [0, 262])

    def test_materialization_is_byte_exact_and_read_only(self):
        from scripts.sealed_ruleset import materialize

        with tempfile.TemporaryDirectory() as td:
            target, evidence = materialize(ROOT / "normative" / "sealed", Path(td))
            self.assertEqual(evidence["raw_sha256"], EXPECTED_SHA)
            self.assertEqual(hashlib.sha256(Path(target).read_bytes()).hexdigest(), EXPECTED_SHA)
            self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o444)
            self.assertFalse(
                os.access(target, os.W_OK)
                and (stat.S_IMODE(os.stat(target).st_mode) & 0o222)
            )


if __name__ == "__main__":
    unittest.main()
