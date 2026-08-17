from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.source_integrity_audit import audit
from scripts.wgs_input_gate import resolve


ROOT = Path(__file__).resolve().parents[1]


class PreAnalysisHardeningTest(unittest.TestCase):
    def test_wgs_manifest_relative_path_cannot_escape_sample_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            with self.assertRaises(ValueError):
                resolve(root, "../outside.fastq.gz")
            with self.assertRaises(ValueError):
                resolve(root, "nested/../../outside.bam")

    def test_wgs_manifest_absolute_path_is_not_ambient_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            with self.assertRaises(ValueError):
                resolve(root, "/etc/passwd")

    def test_wgs_curated_manifest_does_not_hardcode_post_deployment_pass(self):
        source = (ROOT / "scripts/build_wgs_curated_manifest.py").read_text(encoding="utf-8")
        self.assertNotIn('"post_deployment_status": "PASS"', source)
        self.assertIn('"post_deployment_status": "PENDENTE"', source)

    def test_current_source_tree_has_no_removed_provider_names(self):
        forbidden = (("chat" + "gpt").lower(), ("open" + "ai").lower())
        hits: list[str] = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            low = text.lower()
            if any(term in low for term in forbidden):
                hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [])

    def test_whole_tree_source_integrity_audit_is_blocking_and_clean(self):
        result = audit(ROOT)
        self.assertEqual(result["blocking_failures"], [])
        self.assertEqual(result["operational_status"], "VERIFICADO")
        self.assertEqual(result["provider_hits"], [])
        self.assertEqual(result["risky_code_hits"], [])
        self.assertEqual(result["python_parse_errors"], [])
        self.assertEqual(result["unpinned_actions"], [])


if __name__ == "__main__":
    unittest.main()
