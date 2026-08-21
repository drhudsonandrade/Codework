from __future__ import annotations

import gzip
import hashlib
import json
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

    def _verified_evidence(self, p: Path) -> str:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        return json.dumps({
            "status": "VERIFICADO",
            "decision": "SATISFIED",
            "justification": "Synthetic fixture provenance is explicitly controlled by this test.",
            "evidence_refs": ["synthetic-test-fixture"],
            "trace": {
                "attestation_id": "test-array-provenance",
                "created_at": "2026-08-17T00:00:00Z",
                "actor_type": "SOFTWARE",
                "actor_id": "tests.test_snp_array_qc",
                "method": "deterministic fixture",
                "run_id": "unit-test",
                "input_sha256": [sha],
                "output_sha256": [],
                "tool_versions": {"test": "1"},
            },
        })

    def test_harmonized_pass_and_conflict_retained(self):
        p = self._write(
            "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"
            "rs1,1,100,AG,consensus,GA,AG,GM\n"
            "rs2,1,200,CC,consensus,CC,CC,GM\n"
            "rs3,2,300,CT,genotype_conflict,CT,CC,GM\n"
        )
        evidence = self._verified_evidence(p)
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence=evidence, strand_evidence=evidence,
            min_call_rate=.9, max_overlap_conflict_rate=.5,
        )
        self.assertEqual(r["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "PASS")
        self.assertEqual(r["metrics"]["direct_overlap_genotype_conflicts"], 1)

    def test_plain_text_provenance_cannot_unlock_direct_library_gate(self):
        p = self._write("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\n")
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence="fixture", strand_evidence="fixture",
        )
        self.assertEqual(r["gates"]["BUILD_STRAND_GATE"]["state"], "BLOCKED")
        self.assertEqual(r["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "BLOCKED")

    def test_unknown_build_blocks(self):
        p = self._write("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\n")
        r = inspect_array(p, case_id="T")
        self.assertEqual(r["gates"]["BUILD_STRAND_GATE"]["state"], "BLOCKED")
        self.assertEqual(r["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "BLOCKED")

    def test_raw_duplicate_rsid_is_retained_not_silently_collapsed(self):
        p = self._write("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\nrs1,1,101,AG\n")
        evidence = self._verified_evidence(p)
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence=evidence, strand_evidence=evidence,
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
        evidence = self._verified_evidence(p)
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence=evidence, strand_evidence=evidence,
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


class AssemblyBoundsTest(unittest.TestCase):
    """A coordinate past the end of its chromosome must stop at the gate, not later.

    This was found by running a fixture whose coordinate column was fabricated: 332,291 of
    700,000 markers sat beyond the end of their own chromosome, `homozygosity` refused to
    estimate F_ROH on it, and all five QC gates returned PASS. The clinical join and the
    completeness matrix consumed the same coordinates in between. The check existed in the
    codebase; it just was not at the gate that everything downstream trusts.
    """

    def _write(self, rows: str) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = Path(td.name) / "x.csv.gz"
        with gzip.open(p, "wt", encoding="utf-8", newline="") as f:
            f.write("RSID,CHROMOSOME,POSITION,RESULT\n" + rows)
        return p

    def test_a_position_past_the_end_of_its_chromosome_fails_the_structure_gate(self):
        # chr21 ends near 48.1 Mb on GRCh37; 90 Mb is not a rare value, it is no base at all.
        p = self._write("rs1,1,100,AA\nrs2,21,90000000,CC\n")
        r = inspect_array(p, case_id="T", build="GRCh37")
        self.assertEqual(r["gates"]["STRUCTURE_GATE"]["state"], "FAIL")
        self.assertEqual(r["metrics"]["positions_beyond_chromosome_end"], 1)

    def test_the_reason_names_the_worst_row_and_the_limit_it_broke(self):
        p = self._write("rs1,21,90000000,AA\nrs2,21,200000000,CC\n")
        r = inspect_array(p, case_id="T", build="GRCh37")
        reason = " ".join(r["gates"]["STRUCTURE_GATE"]["reasons"])
        self.assertIn("chr21:200,000,000", reason)
        self.assertIn("48,129,895", reason)

    def test_a_single_offending_row_is_enough(self):
        # No tolerance: a fraction of impossible coordinates is not a smaller measurement,
        # it is the same corrupt column affecting the loci nobody happened to check.
        rows = "".join(f"rs{i},1,{1000 + i},AA\n" for i in range(500))
        p = self._write(rows + "rs_bad,22,60000000,CC\n")
        r = inspect_array(p, case_id="T", build="GRCh37")
        self.assertEqual(r["gates"]["STRUCTURE_GATE"]["state"], "FAIL")

    def test_coordinates_inside_their_chromosomes_pass_and_state_the_zero(self):
        p = self._write("rs1,1,100000,AA\nrs2,21,48000000,CC\nrs3,X,155000000,GG\nrs4,MT,16000,TT\n")
        r = inspect_array(p, case_id="T", build="GRCh37")
        self.assertEqual(r["gates"]["STRUCTURE_GATE"]["state"], "PASS")
        self.assertEqual(r["metrics"]["positions_beyond_chromosome_end"], 0)
        self.assertEqual(r["metrics"]["assembly_bounds_basis"], "GRCh37")

    def test_a_grch38_only_coordinate_is_not_flagged_when_grch38_is_declared(self):
        # chr20 is longer on GRCh38 (64.44 Mb) than on GRCh37 (63.03 Mb). Checking against
        # the wrong table would manufacture a violation out of a correct file.
        rows = "rs1,20,64000000,AA\n"
        self.assertEqual(
            inspect_array(self._write(rows), case_id="T", build="GRCh38")["gates"][
                "STRUCTURE_GATE"
            ]["state"],
            "PASS",
        )
        self.assertEqual(
            inspect_array(self._write(rows), case_id="T", build="GRCh37")["gates"][
                "STRUCTURE_GATE"
            ]["state"],
            "FAIL",
        )

    def test_an_unverified_build_is_checked_against_the_longer_of_the_two(self):
        # Without a build there is no table to prefer, so only violations that hold under
        # both assemblies are asserted. Anything else would be an accusation with nothing
        # behind it.
        r = inspect_array(self._write("rs1,20,64000000,AA\n"), case_id="T")
        self.assertEqual(r["gates"]["STRUCTURE_GATE"]["state"], "PASS")
        self.assertIn("build não verificado", r["metrics"]["assembly_bounds_basis"])

        beyond_both = inspect_array(self._write("rs1,20,70000000,AA\n"), case_id="T")
        self.assertEqual(beyond_both["gates"]["STRUCTURE_GATE"]["state"], "FAIL")

    def test_an_unknown_contig_is_left_to_the_chromosome_allowlist(self):
        # "beyond the end" needs a declared end. Answering it for an unknown contig would be
        # an assertion with nothing behind it; the allowlist already refuses the name.
        r = inspect_array(self._write("rs1,GL000191,100000,AA\n"), case_id="T", build="GRCh37")
        self.assertEqual(r["metrics"]["positions_beyond_chromosome_end"], 0)
        self.assertIn(
            "invalid chromosomes=1", " ".join(r["gates"]["STRUCTURE_GATE"]["reasons"])
        )

    def test_qc_and_homozygosity_bound_coordinates_identically(self):
        # The two used to hold separate copies of the table and were free to disagree about
        # which files are physically possible. They now read the same one.
        from array_pipeline.assembly import GRCH37
        from array_pipeline.homozygosity import CHROMOSOME_KB

        for chromosome, kb in CHROMOSOME_KB.items():
            with self.subTest(chromosome=chromosome):
                self.assertEqual(kb, -(-GRCH37[chromosome] // 1000))


class InputHardeningTest(unittest.TestCase):
    """Reading the input must be bounded and exact, because everything downstream trusts it.

    An external audit found two ways a malformed input passed as data: a ZIP member's
    declared sizes were never checked, so one member could ask the decompressor for any
    amount, and all three openers decoded with errors="replace", so an undecodable byte
    became U+FFFD and was parsed as content.
    """

    def _zip(self, root: Path, payload: str, name: str = "array.csv") -> Path:
        import zipfile

        path = root / "in.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(name, payload)
        return path

    def _rows(self, n: int) -> str:
        return "RSID,CHROMOSOME,POSITION,RESULT\n" + "rs1,1,100,AA\n" * n

    def test_a_decompression_bomb_is_refused_before_it_is_read(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._zip(Path(td), self._rows(4_000_000))
            with self.assertRaises(ValueError) as caught:
                inspect_array(path, case_id="T")
        self.assertIn("compression ratio", str(caught.exception))

    def test_an_ordinary_zip_export_still_opens(self):
        # Measured genotype exports run about 5:1; the ceiling must not argue with them.
        with tempfile.TemporaryDirectory() as td:
            path = self._zip(Path(td), "RSID,CHROMOSOME,POSITION,RESULT\n" + "".join(
                f"rs{i},1,{1000 + i},AA\n" for i in range(500)
            ))
            self.assertEqual(inspect_array(path, case_id="T")["metrics"]["rows"], 500)

    def test_the_ceilings_leave_room_above_a_real_export(self):
        from array_pipeline.qc import MAX_COMPRESSION_RATIO, MAX_UNCOMPRESSED_BYTES

        self.assertGreater(MAX_COMPRESSION_RATIO, 20)
        self.assertGreater(MAX_UNCOMPRESSED_BYTES, 100 * 1024 * 1024)

    def test_invalid_utf8_is_refused_and_the_refusal_names_the_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.csv.gz"
            with gzip.open(path, "wb") as fh:
                fh.write(b"RSID,CHROMOSOME,POSITION,RESULT\nrs17\xff\xfe99,3,165548529,CT\n")
            with self.assertRaises(ValueError) as caught:
                inspect_array(path, case_id="T")
        message = str(caught.exception)
        self.assertIn("x.csv.gz", message)
        self.assertIn("not valid UTF-8", message)

    def test_a_replaced_byte_can_no_longer_reach_the_join(self):
        # The failure this closes: U+FFFD in an rsid still joins, against the wrong key, and
        # the run reports a clean call rate over a file it did not read as written.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "y.csv"
            path.write_bytes(b"RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\nrs\xff2,1,200,CC\n")
            with self.assertRaises(ValueError):
                inspect_array(path, case_id="T")


if __name__ == "__main__":
    unittest.main()
