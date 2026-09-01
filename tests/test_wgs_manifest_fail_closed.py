import tempfile
import unittest
from pathlib import Path


class WgsManifestFailClosedTest(unittest.TestCase):
    """Sample-supplied manifest failures must produce a gate verdict, not a traceback."""

    def test_malformed_json_is_a_non_available_verdict(self):
        from scripts.wgs_input_gate import validate_manifest

        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "sample-manifest.json"
            manifest.write_text('{"sample_id": "S1", "input_type": ', encoding="utf-8")

            result = validate_manifest(manifest)

            self.assertEqual(result["schema"], "genoma-wgs-input-gate-v1")
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertEqual(result["inputs"], {})
            self.assertTrue(any("JSON" in error or "json" in error for error in result["errors"]), result["errors"])


if __name__ == "__main__":
    unittest.main()
