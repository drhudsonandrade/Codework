from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.verify_prebuilt_bwa_mem2_bundle import FASTA, INDEX_SUFFIXES, LOCK, verify


class GRCh38ComputeStrategyTest(unittest.TestCase):
    def test_prebuilt_bundle_requires_fasta_and_all_five_indexes_in_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names = [FASTA] + [FASTA + s for s in INDEX_SUFFIXES]
            lines = []
            for i, name in enumerate(names):
                data = f"fixture-{i}".encode()
                (root / name).write_bytes(data)
                lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
            (root / LOCK).write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = verify(root)
            self.assertEqual(result["status"], "VERIFICADO")
            self.assertEqual(len(result["files"]), 6)
            self.assertEqual(result["functional_validation"]["status"], "PROPOSTO")

    def test_prebuilt_bundle_rejects_checksum_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names = [FASTA] + [FASTA + s for s in INDEX_SUFFIXES]
            lines = []
            for i, name in enumerate(names):
                data = f"fixture-{i}".encode()
                (root / name).write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                if name.endswith(".pac"):
                    digest = "0" * 64
                lines.append(f"{digest}  {name}")
            (root / LOCK).write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify(root)


if __name__ == "__main__":
    unittest.main()
