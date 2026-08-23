from __future__ import annotations

import gc
import gzip
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from array_pipeline.qc import _text_stream, inspect_array


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


class ZipSourceHandleTest(unittest.TestCase):
    """A rejected ZIP must not leave its archive handle open."""

    @staticmethod
    def _open_zip_handles() -> int:
        return sum(1 for obj in gc.get_objects() if isinstance(obj, zipfile.ZipFile) and obj.fp is not None)

    def _assert_no_leak(self, build: "callable[[Path], None]", expected: type[Exception]):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "input.zip"
            build(archive)
            gc.collect()
            before = self._open_zip_handles()
            with self.assertRaises(expected):
                _text_stream(archive)
            gc.collect()
            self.assertEqual(self._open_zip_handles(), before, "ZipFile handle leaked on the failure path")

    def test_multi_member_zip_closes_its_archive(self):
        def build(archive: Path) -> None:
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("a.csv", "RSID\nrs1\n")
                zf.writestr("b.csv", "RSID\nrs2\n")

        self._assert_no_leak(build, ValueError)

    def test_empty_zip_closes_its_archive(self):
        def build(archive: Path) -> None:
            with zipfile.ZipFile(archive, "w"):
                pass

        self._assert_no_leak(build, ValueError)

    def test_unreadable_member_closes_its_archive(self):
        def build(archive: Path) -> None:
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("a.csv", "RSID\nrs1\n")
            # Corrupt the stored member so opening it fails after inspection succeeded.
            raw = bytearray(archive.read_bytes())
            raw[:4] = b"\x00\x00\x00\x00"
            archive.write_bytes(bytes(raw))

        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "input.zip"
            build(archive)
            gc.collect()
            before = self._open_zip_handles()
            try:
                stream, _ = _text_stream(archive)
            except Exception:
                gc.collect()
                self.assertEqual(self._open_zip_handles(), before, "ZipFile handle leaked on the failure path")
            else:
                stream.close()

    def test_single_member_zip_is_read_successfully(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "input.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("data.csv", "RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\n")
            stream, source = _text_stream(archive)
            try:
                self.assertEqual(source.kind, "zip")
                self.assertIn("RSID", stream.readline())
            finally:
                stream.close()


if __name__ == "__main__":
    unittest.main()
