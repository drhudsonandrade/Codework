from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import sealed_ruleset

ROOT = Path(__file__).resolve().parents[1]


class SealedTransportPartsRegressionTests(unittest.TestCase):
    def test_resegmented_twelve_part_transport_is_rejected(self) -> None:
        source = ROOT / "normative" / "sealed"
        with tempfile.TemporaryDirectory() as td:
            sealed = Path(td) / "sealed"
            shutil.copytree(source, sealed)
            manifest_path = sealed / "MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            parts = manifest["transport_parts"]
            combined = (
                (sealed / parts[-2]["file"]).read_bytes().strip()
                + (sealed / parts[-1]["file"]).read_bytes().strip()
            )
            combined_path = sealed / parts[-2]["file"]
            combined_path.write_bytes(combined)
            (sealed / parts[-1]["file"]).unlink()
            manifest["transport_parts"] = parts[:-2] + [
                {
                    "file": parts[-2]["file"],
                    "size_bytes": len(combined),
                    "sha256": hashlib.sha256(combined).hexdigest(),
                }
            ]
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(sealed_ruleset.SealedRulesetError):
                sealed_ruleset.verify_transport(sealed)

    def test_canonical_transport_has_exact_part_names_and_order(self) -> None:
        manifest = sealed_ruleset.load_manifest(ROOT / "normative" / "sealed")
        self.assertEqual(
            [item["file"] for item in manifest["transport_parts"]],
            [f"parts/part-{index:03d}.b64" for index in range(13)],
        )


if __name__ == "__main__":
    unittest.main()
