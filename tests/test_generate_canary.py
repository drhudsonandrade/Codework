import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_canary.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_canary", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load canary generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CanaryGeneratorTest(unittest.TestCase):
    def test_generation_is_byte_reproducible(self):
        generator = load_generator()
        names = [
            "reference.fa",
            "reads_R1.fastq.gz",
            "reads_R2.fastq.gz",
            "truth.vcf",
            "fixture.json",
        ]
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            generator.generate(Path(first))
            generator.generate(Path(second))
            self.assertEqual(
                {name: digest(Path(first) / name) for name in names},
                {name: digest(Path(second) / name) for name in names},
            )

    def test_fixture_has_expected_shape_and_truth_variants(self):
        generator = load_generator()
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            generator.generate(out)
            fixture = json.loads((out / "fixture.json").read_text(encoding="utf-8"))
            self.assertEqual(fixture["reference_length"], 30_000)
            self.assertEqual(fixture["read_pairs"], 2_966)
            self.assertEqual(fixture["read_length"], 151)
            records = [
                line.split("\t")
                for line in (out / "truth.vcf").read_text(encoding="utf-8").splitlines()
                if line and not line.startswith("#")
            ]
            self.assertEqual([int(row[1]) for row in records], [5_000, 15_000, 25_000])
            self.assertTrue(all(row[9] == "0/1" for row in records))


if __name__ == "__main__":
    unittest.main()
