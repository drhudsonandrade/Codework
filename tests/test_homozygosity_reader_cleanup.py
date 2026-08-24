from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from array_pipeline.homozygosity import read_autosomal_genotypes


class HomozygosityReaderCleanupTest(unittest.TestCase):
    def test_autosomal_reader_closes_row_generator(self):
        closed = []

        def rows():
            try:
                yield "raw_snp_array_v1", {
                    "RSID": "rs1", "CHROMOSOME": "1", "POSITION": "1", "RESULT": "AA"
                }
            finally:
                closed.append(True)

        with patch("array_pipeline.completeness._row_reader", return_value=rows()):
            markers, total = read_autosomal_genotypes(Path("unused.csv"))
        self.assertEqual(markers, [("1", 1, "AA")])
        self.assertEqual(total, 1)
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
