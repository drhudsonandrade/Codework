from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from array_pipeline.homozygosity import read_autosomal_genotypes


class HomozygosityReaderCleanupTest(unittest.TestCase):
    def test_autosomal_reader_closes_row_generator(self):
        closed = []

        class Rows:
            def __init__(self):
                self.done = False

            def __iter__(self):
                return self

            def __next__(self):
                if self.done:
                    raise StopIteration
                self.done = True
                return "raw_snp_array_v1", {
                    "RSID": "rs1", "CHROMOSOME": "1", "POSITION": "1", "RESULT": "AA"
                }

            def close(self):
                closed.append(True)

        with patch("array_pipeline.completeness._row_reader", return_value=Rows()):
            markers, total = read_autosomal_genotypes(Path("unused.csv"))
        self.assertEqual(markers, [("1", 1, "AA")])
        self.assertEqual(total, 1)
        self.assertEqual(closed, [True])


    def test_f_roh_bounds_follow_the_declared_build(self):
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
