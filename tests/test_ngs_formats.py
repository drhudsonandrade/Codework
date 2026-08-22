"""A gate that checks the file extension has not read the file.

`wgs_input_gate` accepted BAM and CRAM on `is_file()` and `size > 0`, then recorded a
SHA-256. A 32-byte text file named `fake.bam` came back `status: VERIFICADO`, zero errors,
digest attached — the gate certified as a verified alignment input a file holding one line of
prose. `count_vcf_records` had the same shape from the other side: it counted every line not
starting with `#`, so three lines of prose in a file named `.vcf` were reported as three
variant records. Both were reproduced before being closed.

Three places also chose their decompressor with `path.suffix == ".gz"`. A bgzipped VCF named
`.vcf` was therefore read as its own compressed bytes: no line parsed, nothing raised, zero
variants scored — and zero variants against a truth set reads as "the caller found nothing",
which demands the opposite response from "this file was never opened correctly".

`scripts/ngs_formats` reads the containers instead: BGZF framing and the BAM header, the CRAM
file definition, the VCF `##fileformat` line and its eight mandatory columns, and the FASTQ
record structure — deciding format by content, because the extension is not evidence.
"""
from __future__ import annotations

import gzip
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ngs_formats import (
    FormatError,
    detect_container,
    probe_alignment,
    probe_bam,
    probe_cram,
    probe_fastq,
    probe_vcf,
)

SAM_HEADER = (
    b"@HD\tVN:1.6\tSO:coordinate\n"
    b"@SQ\tSN:chr1\tLN:248956422\n"
    b"@RG\tID:rg1\tSM:AMOSTRA-1\tPL:ILLUMINA\n"
)

VCF_TEXT = (
    "##fileformat=VCFv4.2\n"
    "##contig=<ID=chr1,length=248956422>\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tAMOSTRA-1\n"
    "chr1\t100\t.\tA\tG\t50\tPASS\t.\tGT\t0/1\n"
    "chr1\t200\trs1\tC\tT\t60\tPASS\t.\tGT\t1/1\n"
)

FASTQ_TEXT = "@leitura1\nACGTACGT\n+\nIIIIIIII\n@leitura2\nTTTTGGGG\n+\nJJJJJJJJ\n"


def bgzf(payload: bytes) -> bytes:
    """One BGZF block — gzip carrying the `BC` extra subfield that BAM requires."""
    compressor = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = compressor.compress(payload) + compressor.flush()
    extra = struct.pack("<BBHH", 66, 67, 2, len(body) + 25)
    header = struct.pack("<4BI2BH", 0x1F, 0x8B, 8, 4, 0, 0, 255, len(extra)) + extra
    trailer = struct.pack("<II", zlib.crc32(payload) & 0xFFFFFFFF, len(payload) & 0xFFFFFFFF)
    return header + body + trailer


def bam_bytes(header_text: bytes = SAM_HEADER, references: int = 1) -> bytes:
    name = b"chr1\x00"
    payload = b"BAM\x01" + struct.pack("<i", len(header_text)) + header_text
    payload += struct.pack("<i", references)
    for _ in range(references):
        payload += struct.pack("<i", len(name)) + name + struct.pack("<i", 248956422)
    return payload


def cram_bytes(major: int = 3, minor: int = 0, file_id: bytes = b"AMOSTRA-1") -> bytes:
    return b"CRAM" + bytes([major, minor]) + file_id.ljust(20, b"\x00")


class Files:
    """Written into one temporary directory so every probe sees a real path."""

    def __init__(self, directory: Path) -> None:
        def write(name: str, payload: bytes) -> Path:
            path = directory / name
            path.write_bytes(payload)
            return path

        self.dir = directory
        vcf_bytes = VCF_TEXT.encode("utf-8")
        fastq_bytes = FASTQ_TEXT.encode("utf-8")
        self.bam = write("real.bam", bgzf(bam_bytes()))
        self.cram = write("real.cram", cram_bytes())
        self.vcf = write("real.vcf", vcf_bytes)
        self.vcf_gz = write("real.vcf.gz", gzip.compress(vcf_bytes))
        self.fastq = write("real.fastq", fastq_bytes)
        self.fastq_gz = write("real.fastq.gz", gzip.compress(fastq_bytes))
        # The exact file that used to pass.
        self.fake_bam = write("fake.bam", b"isto nao e um BAM, e texto puro\n")
        self.fake_vcf = write("fake.vcf", b"linha um\nlinha dois\nlinha tres\n")
        # Valid BAM content, plain gzip rather than BGZF: decompresses, cannot be indexed.
        self.plain_gzip_bam = write("plain.bam", gzip.compress(bam_bytes()))
        # A bgzipped VCF wearing the plain extension — the silent-zero case.
        self.gz_named_plain = write("misnamed.vcf", gzip.compress(vcf_bytes))
        self.sam = write("reads.sam", SAM_HEADER)
        self.empty = write("empty.bam", b"")


class FormatIsDecidedByContentTest(unittest.TestCase):
    def test_each_container_is_recognised_from_its_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            f = Files(Path(td))
            self.assertEqual("BAM", detect_container(f.bam))
            self.assertEqual("CRAM", detect_container(f.cram))
            self.assertEqual("VCF", detect_container(f.vcf))
            self.assertEqual("VCF", detect_container(f.vcf_gz))
            self.assertEqual("SAM", detect_container(f.sam))
            self.assertEqual("EMPTY", detect_container(f.empty))
            self.assertEqual("UNKNOWN", detect_container(f.fake_bam))

    def test_the_extension_is_not_evidence(self):
        """`misnamed.vcf` is gzip; `fake.bam` is prose. Both are named for what they are not."""
        with tempfile.TemporaryDirectory() as td:
            f = Files(Path(td))
            self.assertEqual("VCF", detect_container(f.gz_named_plain))
            self.assertEqual("UNKNOWN", detect_container(f.fake_bam))


class TheAlignmentProbeReadsTheHeaderTest(unittest.TestCase):
    def test_a_real_bam_yields_its_header(self):
        with tempfile.TemporaryDirectory() as td:
            detail = probe_bam(Files(Path(td)).bam)
        self.assertEqual("BAM", detail["format"])
        self.assertIs(True, detail["bgzf"])
        self.assertEqual(1, detail["reference_count"])
        self.assertEqual("coordinate", detail["sort_order"])
        self.assertEqual(
            [{"id": "rg1", "sample": "AMOSTRA-1", "platform": "ILLUMINA"}], detail["read_groups"]
        )
        self.assertEqual([{"name": "chr1", "length": 248956422}], detail["references_sampled"])

    def test_the_text_file_that_used_to_pass_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FormatError) as caught:
                probe_alignment(Files(Path(td)).fake_bam)
        self.assertIn("extensão do arquivo não é evidência", str(caught.exception))

    def test_a_bam_that_is_plain_gzip_rather_than_bgzf_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FormatError) as caught:
                probe_alignment(Files(Path(td)).plain_gzip_bam)
        self.assertIn("BGZF", str(caught.exception))

    def test_a_sam_is_named_as_a_sam_rather_than_merely_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FormatError) as caught:
                probe_alignment(Files(Path(td)).sam)
        self.assertIn("SAM", str(caught.exception))

    def test_a_vcf_offered_as_an_alignment_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FormatError) as caught:
                probe_alignment(Files(Path(td)).vcf)
        self.assertIn("VCF", str(caught.exception))

    def test_a_real_cram_yields_its_version(self):
        with tempfile.TemporaryDirectory() as td:
            detail = probe_cram(Files(Path(td)).cram)
        self.assertEqual({"format": "CRAM", "version": "3.0", "file_id": "AMOSTRA-1"}, detail)

    def test_an_implausible_cram_version_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "odd.cram"
            path.write_bytes(cram_bytes(major=9))
            with self.assertRaises(FormatError):
                probe_cram(path)

    def test_a_truncated_bam_header_is_refused_not_half_read(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "short.bam"
            # Declares 4096 bytes of header text and supplies none.
            path.write_bytes(bgzf(b"BAM\x01" + struct.pack("<i", 4096)))
            with self.assertRaises(FormatError) as caught:
                probe_bam(path)
        self.assertIn("l_text", str(caught.exception))

    def test_an_absurd_reference_count_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "many.bam"
            payload = b"BAM\x01" + struct.pack("<i", 0) + struct.pack("<i", 2_000_000)
            path.write_bytes(bgzf(payload))
            with self.assertRaises(FormatError) as caught:
                probe_bam(path)
        self.assertIn("n_ref", str(caught.exception))


class TheVcfProbeCountsRecordsNotLinesTest(unittest.TestCase):
    def test_a_real_vcf_is_read_with_its_samples_and_records(self):
        with tempfile.TemporaryDirectory() as td:
            detail = probe_vcf(Files(Path(td)).vcf)
        self.assertEqual("VCFv4.2", detail["version"])
        self.assertEqual(1, detail["sample_count"])
        self.assertEqual(["AMOSTRA-1"], detail["samples"])
        self.assertEqual(2, detail["record_count"])
        self.assertEqual(1, detail["distinct_contigs"])

    def test_three_lines_of_prose_are_not_three_variant_records(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FormatError) as caught:
                probe_vcf(Files(Path(td)).fake_vcf)
        self.assertIn("##fileformat=VCF", str(caught.exception))

    def test_a_bgzipped_vcf_named_plain_is_read_as_a_vcf(self):
        """The silent-zero case: it used to parse as its own compressed bytes."""
        with tempfile.TemporaryDirectory() as td:
            detail = probe_vcf(Files(Path(td)).gz_named_plain)
        self.assertEqual(2, detail["record_count"])
        self.assertEqual("bgzf/gzip", detail["compression"])

    def test_a_missing_chrom_line_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "noheader.vcf"
            path.write_text("##fileformat=VCFv4.2\n##contig=<ID=chr1>\n", encoding="utf-8")
            with self.assertRaises(FormatError) as caught:
                probe_vcf(path)
        self.assertIn("#CHROM", str(caught.exception))

    def test_wrong_mandatory_columns_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cols.vcf"
            path.write_text(
                "##fileformat=VCFv4.2\n#CHROM\tPOSICAO\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n",
                encoding="utf-8",
            )
            with self.assertRaises(FormatError) as caught:
                probe_vcf(path)
        self.assertIn("#CHROM", str(caught.exception))

    def test_a_record_with_a_non_integer_position_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pos.vcf"
            path.write_text(
                VCF_TEXT.replace("chr1\t100\t", "chr1\tinicio\t"), encoding="utf-8"
            )
            with self.assertRaises(FormatError) as caught:
                probe_vcf(path)
        self.assertIn("POS", str(caught.exception))

    def test_records_before_the_header_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "early.vcf"
            path.write_text("##fileformat=VCFv4.2\nchr1\t1\t.\tA\tG\t.\t.\t.\n", encoding="utf-8")
            with self.assertRaises(FormatError):
                probe_vcf(path)


class TheFastqProbeStillProbesTest(unittest.TestCase):
    def test_plain_and_gzipped_fastq_both_read(self):
        with tempfile.TemporaryDirectory() as td:
            f = Files(Path(td))
            self.assertEqual(2, probe_fastq(f.fastq)["probe_records"])
            self.assertEqual(2, probe_fastq(f.fastq_gz)["probe_records"])
            self.assertEqual("gzip", probe_fastq(f.fastq_gz)["compression"])

    def test_mismatched_sequence_and_quality_lengths_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.fastq"
            path.write_text("@r1\nACGT\n+\nII\n", encoding="utf-8")
            with self.assertRaises(FormatError) as caught:
                probe_fastq(path)
        self.assertIn("comprimentos diferentes", str(caught.exception))

    def test_an_empty_file_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.fastq"
            path.write_bytes(b"")
            with self.assertRaises(FormatError):
                probe_fastq(path)


class TheInputGateUsesTheProbesTest(unittest.TestCase):
    def _gate(self, directory: Path, manifest: dict) -> dict:
        import json

        from scripts.wgs_input_gate import validate_manifest

        path = directory / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return validate_manifest(path)

    def _read_group(self, sample: str = "AMOSTRA-1", identifier: str = "rg1") -> dict:
        return {"id": identifier, "sample": sample, "library": "lib1", "platform": "ILLUMINA"}

    def test_the_fake_bam_no_longer_passes(self):
        with tempfile.TemporaryDirectory() as td:
            Files(Path(td))
            result = self._gate(
                Path(td),
                {
                    "sample_id": "AMOSTRA-1",
                    "input_type": "BAM",
                    "alignment": "fake.bam",
                    "read_group": self._read_group(),
                },
            )
        self.assertEqual("NÃO DISPONÍVEL", result["status"])
        self.assertTrue(any("integrity probe failed" in e for e in result["errors"]))

    def test_a_real_bam_passes_and_the_header_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            Files(Path(td))
            result = self._gate(
                Path(td),
                {
                    "sample_id": "AMOSTRA-1",
                    "input_type": "BAM",
                    "alignment": "real.bam",
                    "read_group": self._read_group(),
                },
            )
        self.assertEqual("VERIFICADO", result["status"], result["errors"])
        self.assertEqual("BAM", result["inputs"]["alignment"]["format"])
        self.assertEqual(1, result["inputs"]["alignment"]["reference_count"])
        self.assertTrue(result["inputs"]["alignment"]["sha256"])

    def test_a_manifest_that_names_the_wrong_container_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            Files(Path(td))
            result = self._gate(
                Path(td),
                {
                    "sample_id": "AMOSTRA-1",
                    "input_type": "CRAM",
                    "alignment": "real.bam",
                    "read_group": self._read_group(),
                },
            )
        self.assertEqual("NÃO DISPONÍVEL", result["status"])
        self.assertTrue(any("declares CRAM and the file is BAM" in e for e in result["errors"]))

    def test_a_bam_describing_another_sample_is_refused(self):
        """The header names the sample; the manifest claims one. Disagreement is the finding."""
        with tempfile.TemporaryDirectory() as td:
            Files(Path(td))
            result = self._gate(
                Path(td),
                {
                    "sample_id": "OUTRA-AMOSTRA",
                    "input_type": "BAM",
                    "alignment": "real.bam",
                    "read_group": self._read_group(sample="OUTRA-AMOSTRA", identifier="rgX"),
                },
            )
        self.assertEqual("NÃO DISPONÍVEL", result["status"])
        self.assertTrue(any("read groups in the BAM header" in e for e in result["errors"]))

    def test_fastq_still_passes_through_the_gate(self):
        with tempfile.TemporaryDirectory() as td:
            Files(Path(td))
            result = self._gate(
                Path(td),
                {
                    "sample_id": "AMOSTRA-1",
                    "input_type": "FASTQ",
                    "r1": "real.fastq",
                    "r2": "real.fastq.gz",
                    "read_group": self._read_group(),
                },
            )
        self.assertEqual("VERIFICADO", result["status"], result["errors"])
        self.assertEqual(2, result["inputs"]["r1"]["probe_records"])


class TheVcfConsumersRefuseNonVcfTest(unittest.TestCase):
    def test_the_curated_manifest_no_longer_counts_prose_as_variants(self):
        from scripts.build_wgs_curated_manifest import count_vcf_records

        with tempfile.TemporaryDirectory() as td:
            f = Files(Path(td))
            with self.assertRaises(SystemExit) as caught:
                count_vcf_records(f.fake_vcf)
            self.assertIn("não é um VCF legível", str(caught.exception))
            self.assertEqual(2, count_vcf_records(f.vcf))

    def test_the_scorer_refuses_a_file_that_is_not_a_vcf(self):
        from scripts.score_variants import read_variants

        with tempfile.TemporaryDirectory() as td:
            f = Files(Path(td))
            with self.assertRaises(SystemExit) as caught:
                read_variants(f.fake_vcf)
        self.assertIn("##fileformat=VCF", str(caught.exception))

    def test_the_scorer_reads_a_misnamed_gzipped_vcf_instead_of_scoring_zero(self):
        from scripts.score_variants import read_variants, score

        with tempfile.TemporaryDirectory() as td:
            f = Files(Path(td))
            self.assertEqual(2, len(read_variants(f.gz_named_plain)))
            result = score(f.vcf, f.gz_named_plain)
        self.assertEqual(1.0, result["f1"])
        self.assertEqual(2, result["tp"])

    def test_two_empty_call_sets_are_not_a_perfect_score(self):
        """`tp > 0` is what keeps the canary from passing on nothing."""
        from scripts.score_variants import score

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.vcf"
            path.write_text(
                "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n",
                encoding="utf-8",
            )
            result = score(path, path)
        self.assertEqual(0, result["tp"])
        self.assertEqual(0.0, result["f1"])


if __name__ == "__main__":
    unittest.main()
