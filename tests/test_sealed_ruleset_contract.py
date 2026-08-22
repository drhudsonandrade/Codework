import os
import stat
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SealedRulesetContractTest(unittest.TestCase):
    def test_chunked_transport_is_single_source_of_truth(self):
        from scripts.sealed_ruleset import (
            EXPECTED_DATE,
            EXPECTED_NAME,
            EXPECTED_SHA,
            EXPECTED_STATUS,
            EXPECTED_VERSION,
            load_manifest,
            verify_transport,
        )

        manifest = load_manifest(ROOT / "normative" / "sealed")
        self.assertEqual(manifest["canonical_filename"], EXPECTED_NAME)
        self.assertEqual(manifest["status"], EXPECTED_STATUS)
        self.assertEqual(manifest["version"], EXPECTED_VERSION)
        self.assertEqual(manifest["effective_date"], EXPECTED_DATE)
        self.assertEqual(manifest["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(len(manifest["transport_parts"]), 13)
        self.assertFalse((ROOT / "normative" / "sealed" / "GENOMA_RULESET_v3.4.txt.gz.b64").exists())
        evidence = verify_transport(ROOT / "normative" / "sealed")
        self.assertEqual(evidence["canonical_filename"], EXPECTED_NAME)
        self.assertEqual(evidence["version"], EXPECTED_VERSION)
        self.assertEqual(evidence["effective_date"], EXPECTED_DATE)
        self.assertEqual(evidence["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(evidence["section_count"], 263)
        self.assertEqual(evidence["section_range"], [0, 262])

    def test_materialization_is_byte_exact_and_read_only(self):
        from scripts.sealed_ruleset import EXPECTED_SHA, materialize

        with tempfile.TemporaryDirectory() as td:
            target, evidence = materialize(ROOT / "normative" / "sealed", Path(td))
            self.assertEqual(evidence["raw_sha256"], EXPECTED_SHA)
            self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o444)
            self.assertFalse(os.access(target, os.W_OK) and (stat.S_IMODE(os.stat(target).st_mode) & 0o222))


if __name__ == "__main__":
    unittest.main()
