from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from array_pipeline.homozygosity import analyse_array, read_autosomal_genotypes


class HomozygosityReaderCleanupTest(unittest.TestCase):
    """The homozygosity readers release what they open, and bound what they accept."""
    def test_autosomal_reader_closes_row_generator(self):
        """The autosomal reader closes its row generator explicitly."""
        closed = []

        class Rows:
            """A row iterator that records whether it was closed."""
            def __init__(self):
                """Start undrained."""
                self.done = False

            def __iter__(self):
                """The iterator is its own iterable."""
                return self

            def __next__(self):
                """Yield one row, then stop."""
                if self.done:
                    raise StopIteration
                self.done = True
                return "raw_snp_array_v1", {
                    "RSID": "rs1", "CHROMOSOME": "1", "POSITION": "1", "RESULT": "AA"
                }

            def close(self):
                """Record that the consumer closed this iterator."""
                closed.append(True)

        with patch("array_pipeline.completeness._row_reader", return_value=Rows()):
            markers, total = read_autosomal_genotypes(Path("unused.csv"))
        self.assertEqual(markers, [("1", 1, "AA")])
        self.assertEqual(total, 1)
        self.assertEqual(closed, [True])


    def test_exact_autosomal_bounds_reject_zero_and_length_plus_one(self):
        """The autosomal bounds are exact: position 0 and length+1 are both rejected."""
        from array_pipeline import assembly
        from array_pipeline.homozygosity import analyse

        for position in (0, assembly.CHROMOSOME_LENGTHS["GRCh37"]["1"] + 1):
            with (
                self.subTest(position=position),
                patch("array_pipeline.homozygosity.MIN_CALLED_MARKERS", 1),
                patch("array_pipeline.homozygosity.MIN_CALL_RATE", 0.0),
            ):
                result = analyse([("1", position, "AA")], build="GRCh37")
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertTrue(any("fim do próprio cromossomo" in x for x in result["refusals"]))

    def test_f_roh_bounds_follow_the_declared_build(self):
        """The F-roh denominator follows the declared build, not a hard-coded chromosome length."""
        from array_pipeline.homozygosity import analyse

        marker = [("1", 249_100_000, "AA")]
        with (
            patch("array_pipeline.homozygosity.MIN_CALLED_MARKERS", 1),
            patch("array_pipeline.homozygosity.MIN_CALL_RATE", 0.0),
        ):
            grch37 = analyse(marker, build="GRCh37")
            grch38 = analyse(marker, build="GRCh38")
        self.assertEqual(grch37["status"], "INFERIDO")
        self.assertEqual(grch37["reference_build"], "GRCh37")
        self.assertEqual(grch38["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("fim do próprio cromossomo" in x for x in grch38["refusals"]))

if __name__ == "__main__":
    unittest.main()


class AnalyseArrayBuildContractTest(unittest.TestCase):
    """The build is a property of the file, so it cannot be assumed.

    `analyse_array` defaulted to GRCh37 and has no caller in this repository, so nothing was
    relying on the default — but a GRCh38 file handed over without the argument would have
    been analysed against GRCh37 coordinates and returned a wrong answer silently.
    """

    def test_build_has_no_default(self):
        """`build` has no default: a caller that omits it gets a TypeError, not an assumed assembly."""
        import inspect

        parameter = inspect.signature(analyse_array).parameters["build"]
        self.assertIs(parameter.default, inspect.Parameter.empty)
        with self.assertRaises(TypeError):
            inspect.signature(analyse_array).bind(Path("unused.txt"))

    @staticmethod
    def _homozygous_run(count: int = 100_001, step: int = 2_000):
        """A run dense enough to clear the density guard, so the success path is reached.

        The analyser refuses below 100,000 called autosomal markers, so a smaller fixture
        never reaches the code that records `reference_build` and the build would go
        unexercised.
        """

        def generator():
            """Yield a homozygous run of this many markers."""
            for i in range(count):
                yield "raw_snp_array_v1", {
                    "RSID": f"rs{i}",
                    "CHROMOSOME": "1",
                    "POSITION": str(1_000_000 + i * step),
                    "RESULT": "AA",
                }

        return generator()

    def test_the_grch38_path_is_exercised(self):
        """The GRCh38 path is exercised, not only GRCh37."""
        with patch(
            "array_pipeline.completeness._row_reader",
            return_value=self._homozygous_run(),
        ):
            result = analyse_array(Path("unused.txt"), build="GRCh38")
        self.assertEqual(result["reference_build"], "GRCh38")
        self.assertEqual(result["autosomal_rows"], 100_001)

    def test_an_unsupported_build_is_refused_rather_than_assumed(self):
        """An unsupported build is refused rather than assumed to be the nearest known one."""
        with patch(
            "array_pipeline.completeness._row_reader",
            return_value=self._homozygous_run(),
        ):
            result = analyse_array(Path("unused.txt"), build="GRCh36")
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("GRCh36" in r for r in result["refusals"]), result["refusals"])


