import gzip
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "score_variants.py"


def load_scorer():
    spec = importlib.util.spec_from_file_location("score_variants", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load variant scorer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_vcf(path: Path, rows: list[str]) -> None:
    text = (
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tCANARY\n"
        + "\n".join(rows)
        + "\n"
    )
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="ascii") as handle:
            handle.write(text)
    else:
        path.write_text(text, encoding="ascii")


class VariantScorerTest(unittest.TestCase):
    def test_scores_tp_fp_fn_and_genotype_concordance(self):
        scorer = load_scorer()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            truth = root / "truth.vcf"
            called = root / "called.vcf.gz"
            write_vcf(
                truth,
                [
                    "chr1\t10\t.\tA\tC\t100\tPASS\t.\tGT\t0/1",
                    "chr1\t20\t.\tG\tT\t100\tPASS\t.\tGT\t0/1",
                ],
            )
            write_vcf(
                called,
                [
                    "chr1\t10\t.\tA\tC\t90\tPASS\t.\tGT:DP\t1/0:30",
                    "chr1\t30\t.\tT\tG\t80\tPASS\t.\tGT:DP\t0/1:25",
                ],
            )
            score = scorer.score(truth, called)
            self.assertEqual(score["tp"], 1)
            self.assertEqual(score["fp"], 1)
            self.assertEqual(score["fn"], 1)
            self.assertEqual(score["genotype_concordant"], 1)
            self.assertEqual(score["genotype_compared"], 1)
            self.assertEqual(score["precision"], 0.5)
            self.assertEqual(score["recall"], 0.5)
            self.assertEqual(score["f1"], 0.5)


if __name__ == "__main__":
    unittest.main()
