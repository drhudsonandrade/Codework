import tempfile
import unittest
from pathlib import Path


class LatestCandidateTest(unittest.TestCase):
    def test_candidate_unpins_managed_runtime_packages_without_mutating_source(self):
        from scripts.prepare_latest_candidate import prepare_candidate

        source = """name: test\nchannels:\n  - conda-forge\ndependencies:\n  - python=3.11\n  - samtools=1.24\n  - bcftools=1.24\n  - curl\n"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "environment.yml"
            dst = root / "candidate.yml"
            src.write_text(source, encoding="utf-8")
            result = prepare_candidate(src, dst, managed={"python", "samtools", "bcftools"})
            self.assertEqual(src.read_text(encoding="utf-8"), source)
            candidate = dst.read_text(encoding="utf-8")
            self.assertIn("  - python\n", candidate)
            self.assertIn("  - samtools\n", candidate)
            self.assertIn("  - bcftools\n", candidate)
            self.assertIn("  - curl\n", candidate)
            self.assertEqual(result["unpinned"], ["python", "samtools", "bcftools"])


if __name__ == "__main__":
    unittest.main()
