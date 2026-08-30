from __future__ import annotations

import gc
import gzip
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from array_pipeline.qc import _text_stream, inspect_array


class ArrayQCTest(unittest.TestCase):
    def _write(self, text: str) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = Path(td.name) / "x.csv.gz"
        with gzip.open(p, "wt", encoding="utf-8", newline="") as f:
            f.write(text)
        return p

    def _verified_evidence(self, p: Path, *, asserted_value: str) -> str:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        return json.dumps({
            "status": "VERIFICADO",
            "decision": "SATISFIED",
            "asserted_value": asserted_value,
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
        build_evidence = self._verified_evidence(p, asserted_value="GRCh37")
        strand_evidence = self._verified_evidence(p, asserted_value="forward")
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence=build_evidence, strand_evidence=strand_evidence,
            min_call_rate=.9, max_overlap_conflict_rate=.5,
        )
        self.assertEqual(r["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "PASS")
        self.assertEqual(r["metrics"]["direct_overlap_genotype_conflicts"], 1)

    def test_reverse_strand_is_blocked_even_with_bound_attestation(self):
        p = self._write("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\n")
        build_evidence = self._verified_evidence(p, asserted_value="GRCh37")
        strand_evidence = self._verified_evidence(p, asserted_value="reverse")
        r = inspect_array(
            p,
            case_id="T",
            build="GRCh37",
            strand="reverse",
            build_evidence=build_evidence,
            strand_evidence=strand_evidence,
        )
        self.assertEqual(r["gates"]["BUILD_STRAND_GATE"]["state"], "BLOCKED")
        self.assertEqual(r["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "BLOCKED")

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
        build_evidence = self._verified_evidence(p, asserted_value="GRCh37")
        strand_evidence = self._verified_evidence(p, asserted_value="forward")
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence=build_evidence, strand_evidence=strand_evidence,
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
        build_evidence = self._verified_evidence(p, asserted_value="GRCh37")
        strand_evidence = self._verified_evidence(p, asserted_value="forward")
        r = inspect_array(
            p, case_id="T", build="GRCh37", strand="forward",
            build_evidence=build_evidence, strand_evidence=strand_evidence,
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

    def test_metadata_cannot_attest_a_build_that_contradicts_the_file(self):
        p = self._write(
            "##reference=build37\n"
            "RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\n"
        )
        strand_evidence = self._verified_evidence(p, asserted_value="forward")
        result = inspect_array(
            p,
            case_id="T",
            build="GRCh38",
            strand="forward",
            strand_evidence=strand_evidence,
        )
        self.assertFalse(result["input"]["build_evidence_verified"])
        self.assertEqual(result["gates"]["BUILD_STRAND_GATE"]["state"], "BLOCKED")

    def test_duplicate_rsid_contributes_at_most_one_strand_vote(self):
        p = self._write(
            "RSID,CHROMOSOME,POSITION,RESULT\n"
            "rs1,1,100,TC\n"
            "rs1,1,101,TC\n"
            "rs1,1,102,TC\n"
        )
        build_evidence = self._verified_evidence(p, asserted_value="GRCh37")
        strand_evidence = self._verified_evidence(p, asserted_value="forward")
        with patch("array_pipeline.qc._strand_marker_alleles", return_value={"rs1": {"A", "G"}}):
            result = inspect_array(
                p,
                case_id="T",
                build="GRCh37",
                strand="forward",
                build_evidence=build_evidence,
                strand_evidence=strand_evidence,
            )
        self.assertEqual(result["metrics"]["strand_markers_minus_only"], 1)
        self.assertEqual(result["gates"]["BUILD_STRAND_GATE"]["state"], "PASS")
        self.assertEqual(result["metrics"]["strand_contradiction_check"], "EXECUTADO")

    def test_a_marker_table_with_nothing_usable_also_blocks(self):
        """An empty or all-invalid table is the same fail-open through a different door.

        The first version of this refusal only checked that the payload was a dict with a
        `markers` list, then skipped entries it could not parse. `{"markers": []}` produced
        an empty mapping and no refusal: zero votes on both sides, the check recorded as
        EXECUTADO, and BUILD_STRAND_GATE free to pass — exactly the state the refusal was
        written to prevent. Validation now delegates to `provenance_probe.load_markers`, so
        the rules live in one place, plus a check that something usable survives the
        palindromic exclusion.
        """
        p = self._write("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,TC\n")
        build_evidence = self._verified_evidence(p, asserted_value="GRCh37")
        strand_evidence = self._verified_evidence(p, asserted_value="forward")
        good = json.loads(
            (Path(__file__).resolve().parents[1] / "config/array_provenance_markers.json")
            .read_text(encoding="utf-8")
        )
        only_palindromic = dict(good)
        only_palindromic["markers"] = [m for m in good["markers"] if m.get("palindromic")]
        unverified = dict(good)
        unverified["verification_status"] = "PROPOSTO"
        for label, payload in (
            ("empty markers", {**good, "markers": []}),
            ("entries not objects", {**good, "markers": ["rs1"]}),
            ("every marker palindromic", only_palindromic),
            ("table not itself verified", unverified),
        ):
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as td:
                    table = Path(td) / "array_provenance_markers.json"
                    table.write_text(json.dumps(payload), encoding="utf-8")
                    with patch("array_pipeline.qc.STRAND_MARKERS_PATH", table):
                        result = inspect_array(
                            p,
                            case_id="T",
                            build="GRCh37",
                            strand="forward",
                            build_evidence=build_evidence,
                            strand_evidence=strand_evidence,
                        )
                self.assertEqual(result["gates"]["BUILD_STRAND_GATE"]["state"], "BLOCKED")
                self.assertEqual(
                    result["metrics"]["strand_contradiction_check"], "NÃO DISPONÍVEL"
                )
                self.assertEqual(result["operational_status"], "NÃO DISPONÍVEL")

    def test_an_unreadable_marker_table_blocks_instead_of_disappearing(self):
        """The one check against a lying attestation must not vanish with its data file.

        `_strand_marker_alleles` swallowed OSError/JSONDecodeError and returned `{}`. The
        gate then found zero votes on both sides, which is the same reading as a file with
        too few informative markers, and reported PASS. Deleting or corrupting
        `config/array_provenance_markers.json` therefore silently removed the only automated
        control against a well-formed, correctly bound attestation that asserts `forward`
        about a reverse-strand file — the exact case the check exists for.

        Both failure modes are covered because they arrive by different exceptions.
        """
        p = self._write("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,TC\n")
        build_evidence = self._verified_evidence(p, asserted_value="GRCh37")
        strand_evidence = self._verified_evidence(p, asserted_value="forward")
        for label, failure in (
            ("table missing", OSError(2, "No such file or directory")),
            ("table corrupt", json.JSONDecodeError("Expecting value", "", 0)),
        ):
            with self.subTest(case=label):
                with patch(
                    "array_pipeline.qc.STRAND_MARKERS_PATH"
                ) as marker_path:
                    marker_path.read_text.side_effect = failure
                    marker_path.name = "array_provenance_markers.json"
                    result = inspect_array(
                        p,
                        case_id="T",
                        build="GRCh37",
                        strand="forward",
                        build_evidence=build_evidence,
                        strand_evidence=strand_evidence,
                    )
                self.assertEqual(result["gates"]["BUILD_STRAND_GATE"]["state"], "BLOCKED")
                self.assertTrue(
                    any(
                        "não pôde ser executada" in reason
                        for reason in result["gates"]["BUILD_STRAND_GATE"]["reasons"]
                    ),
                    result["gates"]["BUILD_STRAND_GATE"]["reasons"],
                )
                # The record has to distinguish "no contradiction found" from "no
                # contradiction could be found"; the vote counts alone cannot.
                self.assertEqual(
                    result["metrics"]["strand_contradiction_check"], "NÃO DISPONÍVEL"
                )
                self.assertIn(
                    "array_provenance_markers.json",
                    result["metrics"]["strand_contradiction_check_reason"],
                )
                # And nothing downstream may read this file as interpretable.
                self.assertEqual(
                    result["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "BLOCKED"
                )
                self.assertEqual(result["operational_status"], "NÃO DISPONÍVEL")

    def test_a_marker_table_that_is_not_valid_utf8_blocks_rather_than_aborting(self):
        """A third way for the file to be unreadable, arriving by a third exception.

        `load_markers` reads the table with `encoding="utf-8"`, so a file carrying invalid
        bytes raises `UnicodeDecodeError` — a `ValueError`, not an `OSError`, and not a
        `JSONDecodeError` either, so it matched none of the handled types and propagated out
        of `inspect_array`, which only converts `StrandMarkerTableError`. A corrupt byte in
        the marker table aborted the whole QC inspection instead of blocking the one gate
        that depends on it: not fail-open like the original defect, but not fail-closed
        either — an inspection that raises produces no record at all.

        Written against a real file rather than a patched `side_effect`, because the point is
        that the bytes on disk produce this, not that the exception type is handled.
        """
        p = self._write("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,TC\n")
        build_evidence = self._verified_evidence(p, asserted_value="GRCh37")
        strand_evidence = self._verified_evidence(p, asserted_value="forward")
        with tempfile.TemporaryDirectory() as td:
            table = Path(td) / "array_provenance_markers.json"
            table.write_bytes(b'{"schema": "genoma-array-provenance-markers-v1", \xff\xfe}')
            with patch("array_pipeline.qc.STRAND_MARKERS_PATH", table):
                result = inspect_array(
                    p,
                    case_id="T",
                    build="GRCh37",
                    strand="forward",
                    build_evidence=build_evidence,
                    strand_evidence=strand_evidence,
                )
        self.assertEqual(result["gates"]["BUILD_STRAND_GATE"]["state"], "BLOCKED")
        self.assertEqual(result["metrics"]["strand_contradiction_check"], "NÃO DISPONÍVEL")
        self.assertIn(
            "array_provenance_markers.json",
            result["metrics"]["strand_contradiction_check_reason"],
        )
        self.assertEqual(
            result["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "BLOCKED"
        )
        self.assertEqual(result["operational_status"], "NÃO DISPONÍVEL")


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
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "input.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("a.csv", "RSID\nrs1\n")
            with zipfile.ZipFile(archive) as zf:
                member = zf.getinfo("a.csv")
                header_offset = member.header_offset

            # Corrupt only the member's local-file-header signature. The central directory
            # remains readable, so ZIP inspection succeeds and opening the sole member is
            # guaranteed to exercise the exact post-inspection failure path in _text_stream.
            raw = bytearray(archive.read_bytes())
            raw[header_offset:header_offset + 4] = b"\x00\x00\x00\x00"
            archive.write_bytes(bytes(raw))

            with zipfile.ZipFile(archive) as probe:
                members = [item for item in probe.infolist() if not item.is_dir()]
                self.assertEqual(len(members), 1)
                with self.assertRaises(zipfile.BadZipFile):
                    probe.open(members[0], "r")

            gc.collect()
            before = self._open_zip_handles()
            with self.assertRaises(zipfile.BadZipFile):
                _text_stream(archive)
            gc.collect()
            self.assertEqual(self._open_zip_handles(), before, "ZipFile handle leaked on the failure path")

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

    def test_successful_read_releases_its_archive_on_close(self):
        """The success path leaks too if only the member stream is closed.

        Every caller in the pipeline closes the returned stream and nothing else, so
        closing it has to release the enclosing ZipFile as well.
        """
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "input.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("data.csv", "RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\n")
            gc.collect()
            before = self._open_zip_handles()
            stream, _ = _text_stream(archive)
            self.assertEqual(self._open_zip_handles(), before + 1, "the archive should be open while reading")
            self.assertIsInstance(getattr(stream, "_genoma_zipfile", None), zipfile.ZipFile)
            stream.close()
            gc.collect()
            self.assertEqual(
                self._open_zip_handles(),
                before,
                "ZipFile handle leaked on the success path",
            )
            self.assertTrue(stream._genoma_zipfile.fp is None)


class RuntimeExpansionLimitTest(unittest.TestCase):
    def test_gzip_limit_is_enforced_on_bytes_actually_read(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "input.csv.gz"
            with gzip.open(path, "wb") as fh:
                fh.write(b"123456")
            with patch("array_pipeline.qc.MAX_UNCOMPRESSED_BYTES", 4):
                stream, _ = _text_stream(path)
                try:
                    with self.assertRaisesRegex(ValueError, "decompressed bytes"):
                        stream.read()
                finally:
                    stream.close()

    def test_zip_limit_is_enforced_even_if_header_validation_is_bypassed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "input.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("input.csv", b"123456")
            with (
                patch("array_pipeline.qc.MAX_UNCOMPRESSED_BYTES", 4),
                patch("array_pipeline.qc._check_zip_member", return_value=None),
            ):
                stream, _ = _text_stream(path)
                try:
                    with self.assertRaisesRegex(ValueError, "decompressed bytes"):
                        stream.read()
                finally:
                    stream.close()


if __name__ == "__main__":
    unittest.main()
