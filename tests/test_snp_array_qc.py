from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from array_pipeline.qc import inspect_array


class ArrayQCTest(unittest.TestCase):
    def _write(self, text: str) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = Path(td.name) / "x.csv.gz"
        with gzip.open(p, "wt", encoding="utf-8", newline="") as f:
            f.write(text)
        return p

    def test_harmonized_pass_and_conflict_retained(self):
        p = self._write(
            "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"
            "rs1,1,100,AG,consensus,GA,AG,GM\n"
            "rs2,1,200,CC,consensus,CC,CC,GM\n"
            "rs3,2,300,CT,genotype_conflict,CT,CC,GM\n"
        )
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence="fixture", strand_evidence="fixture",
            min_call_rate=.9, max_overlap_conflict_rate=.5,
        )
        self.assertEqual(r["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "PASS")
        self.assertEqual(r["metrics"]["direct_overlap_genotype_conflicts"], 1)

    def test_unknown_build_blocks(self):
        p = self._write("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\n")
        r = inspect_array(p, case_id="T")
        self.assertEqual(r["gates"]["BUILD_STRAND_GATE"]["state"], "BLOCKED")
        self.assertEqual(r["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "BLOCKED")

    def test_raw_duplicate_rsid_is_retained_not_silently_collapsed(self):
        p = self._write("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\nrs1,1,101,AG\n")
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence="fixture", strand_evidence="fixture",
        )
        self.assertEqual(r["gates"]["STRUCTURE_GATE"]["state"], "PASS")
        self.assertEqual(r["metrics"]["duplicate_rsid_rows"], 1)
        self.assertTrue(r["gates"]["STRUCTURE_GATE"]["notes"])

    def test_duplicate_rsid_fails_after_harmonization(self):
        p = self._write(
            "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"
            "rs1,1,100,AA,consensus,AA,AA,GM\n"
            "rs1,1,100,AA,consensus,AA,AA,GM\n"
        )
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence="fixture", strand_evidence="fixture",
        )
        self.assertEqual(r["gates"]["STRUCTURE_GATE"]["state"], "FAIL")

    def test_myheritage_metadata_verifies_build_and_strand(self):
        p = self._write(
            "##fileformat=MyHeritage\n##chip=GSA\n##reference=build37\n"
            "# The genotype is reported on the forward (+) strand with respect to human reference build 37.\n"
            "RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\n"
        )
        r = inspect_array(p, case_id="T")
        self.assertEqual(r["gates"]["BUILD_STRAND_GATE"]["state"], "PASS")
        self.assertEqual(r["input"]["build"], "GRCh37")
        self.assertEqual(r["input"]["strand"], "forward")


if __name__ == "__main__":
    unittest.main()
