from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.verify_template_store import verify

ROOT = Path(__file__).resolve().parents[1]


class TemplateStoreTest(unittest.TestCase):
    def test_manifest_matches_all_11_reference_identities(self):
        store = json.loads((ROOT / "template_store/v3.0/MANIFEST.json").read_text())
        ref = json.loads((ROOT / "reporting/reference_v3_manifest.json").read_text())
        self.assertEqual(set(store["reports"]), {f"{i:02d}" for i in range(1, 12)})
        for rid, meta in store["reports"].items():
            for field in ("filename", "sha256", "size_bytes", "page_count"):
                self.assertEqual(meta[field], ref["reports"][rid][field])

    def test_verifier_never_promotes_missing_binary_parts(self):
        result = verify(allow_sealed_only=True)
        if result["binary_materialization"] == "NÃO DISPONÍVEL":
            self.assertEqual(result["operational_status"], "NÃO DISPONÍVEL")
            self.assertTrue(result["missing_parts"])
        else:
            self.assertEqual(result["operational_status"], "VERIFICADO")
            self.assertEqual(result["reports"], 11)


if __name__ == "__main__":
    unittest.main()
