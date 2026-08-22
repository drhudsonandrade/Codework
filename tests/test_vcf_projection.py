"""A VCF can feed the interpretation stack, and absence in a VCF is not reference.

The eleven reports are built from one artifact: the genotype table `array_pipeline` reads.
Only a SNP-array export could produce one, so a WGS run reached QC and provenance and stopped
— `build_wgs_curated_manifest` emitted `claims: []` and said so. `scripts/vcf_projection.py`
writes the same table from a VCF, and the whole downstream stack works unchanged.

What this suite guards is the part that could quietly produce a false negative. An array
interrogates every locus on the chip; a VCF lists variants. Reading "no record here" as
"homozygous reference" would manufacture a negative result at every uncalled locus — the
failure sections 46, 117 and 146 exist to prevent. Homozygous reference is emitted only where
a gVCF non-variant block or a callable-regions BED positively establishes coverage, and
everything else is absent from the projection, which the coverage matrix classifies
NÃO TESTADO.

It also guards the join. The registry carries GRCh38 coordinates, so the match is by position
and the VCF's REF is checked against the reference allele the registry declares: an isolated
disagreement means that coordinate is not the variant the registry names, and a systematic one
means the file is not on the build it claims.
"""
from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.vcf_projection import (
    MIN_REFERENCE_CHECKS,
    PROJECTION_COLUMNS,
    ProjectionError,
    normalise_contig,
    project,
    provenance_attestations,
    write_table,
)

HEADER = (
    "##fileformat=VCFv4.2\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tCASO-1\n"
)

#: Four targets with real-looking GRCh38 coordinates and declared reference alleles.
TARGETS = [
    {"rsid": "rs001", "gene": "GENE1", "label": "l1", "scope": "CLINICO",
     "grch38": {"chromosome": "1", "position": 1000}, "reference_allele": "A"},
    {"rsid": "rs002", "gene": "GENE2", "label": "l2", "scope": "CLINICO",
     "grch38": {"chromosome": "1", "position": 2000}, "reference_allele": "C"},
    {"rsid": "rs003", "gene": "GENE3", "label": "l3", "scope": "CLINICO",
     "grch38": {"chromosome": "2", "position": 3000}, "reference_allele": "G"},
    {"rsid": "rs004", "gene": "GENE4", "label": "l4", "scope": "CLINICO",
     "grch38": {"chromosome": "X", "position": 4000}, "reference_allele": "T"},
]


def registry(directory: Path, targets=None) -> Path:
    path = directory / "targets.json"
    path.write_text(
        json.dumps(
            {
                "schema": "genoma-partial-genome-targets-v1",
                "id": "TESTE",
                "version": "1",
                "description": "registro de teste",
                "generated_at": "2026-08-22T00:00:00Z",
                "targets": targets if targets is not None else TARGETS,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def vcf(directory: Path, body: str, name: str = "case.vcf") -> Path:
    path = directory / name
    path.write_text(HEADER + body, encoding="utf-8")
    return path


class TheJoinIsByCoordinateTest(unittest.TestCase):
    def test_a_called_variant_becomes_a_genotype(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, evidence = project(
                vcf(root, "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"),
                registry(root),
            )
        self.assertEqual(1, len(rows))
        self.assertEqual("rs001", rows[0]["RSID"])
        self.assertEqual("AG", rows[0]["RESULT"])
        self.assertEqual(40, rows[0]["DEPTH"])
        self.assertEqual(99, rows[0]["GENOTYPE_QUALITY"])
        self.assertEqual(1, evidence["outcomes"]["called_from_variant"])

    def test_a_homozygous_alternate_call_is_two_alternate_bases(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(
                vcf(root, "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t1/1:40:99\n"),
                registry(root),
            )
        self.assertEqual("GG", rows[0]["RESULT"])

    def test_the_id_column_is_ignored_in_favour_of_the_coordinate(self):
        """A stale or merged rsID in the VCF must not decide which target this is."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(
                vcf(root, "chr1\t1000\trs999999\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"),
                registry(root),
            )
        self.assertEqual("rs001", rows[0]["RSID"])

    def test_contig_naming_does_not_change_the_match(self):
        for contig in ("chr1", "1", "CHR1"):
            with self.subTest(contig=contig), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                rows, _ = project(
                    vcf(root, f"{contig}\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"),
                    registry(root),
                )
                self.assertEqual(1, len(rows))

    def test_the_mitochondrion_has_one_name(self):
        self.assertEqual("MT", normalise_contig("chrM"))
        self.assertEqual("MT", normalise_contig("MT"))

    def test_a_position_no_target_names_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, evidence = project(
                vcf(root, "chr1\t999999\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"),
                registry(root),
            )
        self.assertEqual([], rows)
        self.assertEqual(4, evidence["targets_absent_from_vcf"])


class AbsenceIsNotReferenceTest(unittest.TestCase):
    """The failure this adapter most needed to avoid."""

    def test_a_target_with_no_record_is_absent_from_the_projection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, evidence = project(
                vcf(root, "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"),
                registry(root),
            )
        self.assertEqual({"rs001"}, {row["RSID"] for row in rows})
        self.assertEqual(3, evidence["targets_absent_from_vcf"])
        self.assertIn("Ausência num VCF não é referência", evidence["absence_contract"])

    def test_a_plain_vcf_declares_no_homozygous_reference_at_all(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _rows, evidence = project(
                vcf(root, "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"),
                registry(root),
            )
        self.assertIn("NÃO DISPONÍVEL", evidence["homozygous_reference"])
        self.assertEqual(0, evidence["outcomes"].get("homref_from_gvcf", 0))

    def test_a_gvcf_block_establishes_reference_where_it_covers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, evidence = project(
                vcf(root, "chr1\t900\t.\tA\t<NON_REF>\t.\t.\tEND=2100\tGT:DP:GQ\t0/0:30:60\n"),
                registry(root),
            )
        by_rsid = {row["RSID"]: row for row in rows}
        self.assertEqual("AA", by_rsid["rs001"]["RESULT"])
        self.assertEqual("CC", by_rsid["rs002"]["RESULT"])
        self.assertIn("bloco não-variante", by_rsid["rs001"]["CALL_BASIS"])
        self.assertEqual(2, evidence["outcomes"]["homref_from_gvcf"])
        # The targets the block does not reach stay uninterrogated.
        self.assertEqual(2, evidence["targets_absent_from_vcf"])

    def test_a_shallow_gvcf_block_does_not_establish_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, evidence = project(
                vcf(root, "chr1\t900\t.\tA\t<NON_REF>\t.\t.\tEND=1100\tGT:DP:GQ\t0/0:4:12\n"),
                registry(root),
            )
        self.assertEqual("--", rows[0]["RESULT"])
        self.assertIn("não sustenta declarar referência", rows[0]["CALL_BASIS"])
        self.assertEqual(1, evidence["outcomes"]["homref_below_quality"])

    def test_a_callable_bed_establishes_reference_more_weakly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bed = root / "callable.bed"
            bed.write_text("chr1\t900\t2100\n", encoding="utf-8")
            rows, evidence = project(vcf(root, ""), registry(root), callable_bed=bed)
        by_rsid = {row["RSID"]: row for row in rows}
        self.assertEqual("AA", by_rsid["rs001"]["RESULT"])
        self.assertEqual(2, evidence["homozygous_reference_from_callable_bed"])
        self.assertIn("mais fraca que um bloco de gVCF", by_rsid["rs001"]["CALL_BASIS"])

    def test_the_coverage_matrix_reads_absence_as_uninterrogated(self):
        """End to end: the contract has to survive into the artifact reports are built on."""
        from array_pipeline.completeness import _classify
        from reporting.assay import assay_for_schema

        classification, basis = _classify(None, None, TARGETS[0], "wgs_vcf_projection_v1")
        self.assertEqual("NÃO TESTADO", classification)
        self.assertEqual(assay_for_schema("wgs_vcf_projection_v1").absence_note, basis)
        self.assertIn("ausência num VCF não é referência", basis)


class TheReferenceBaseIsCheckedTest(unittest.TestCase):
    def test_an_isolated_mismatch_yields_no_genotype(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, evidence = project(
                vcf(root, "chr1\t1000\t.\tT\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"),
                registry(root),
            )
        self.assertEqual("--", rows[0]["RESULT"])
        self.assertIn("diverge do alelo de referência", rows[0]["CALL_BASIS"])
        self.assertEqual(1, evidence["reference_allele_mismatches"])

    def test_a_systematic_mismatch_refuses_the_whole_projection(self):
        """What a wrong build looks like: disagreement almost everywhere."""
        targets, body = [], []
        for index in range(MIN_REFERENCE_CHECKS + 10):
            position = 1000 + index
            targets.append({
                "rsid": f"rs{index:04d}", "gene": "G", "label": "l", "scope": "CLINICO",
                "grch38": {"chromosome": "1", "position": position}, "reference_allele": "A",
            })
            body.append(f"chr1\t{position}\t.\tT\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ProjectionError) as caught:
                project(vcf(root, "\n".join(body) + "\n"), registry(root, targets))
        self.assertIn("não está em GRCh38", str(caught.exception))

    def test_a_grch37_projection_is_refused_rather_than_lifted_over(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ProjectionError) as caught:
                project(vcf(root, ""), registry(root), declared_build="GRCh37")
        self.assertIn("chain file", str(caught.exception))


class QualityTravelsWithTheCallTest(unittest.TestCase):
    def test_a_filtered_record_is_not_a_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(
                vcf(root, "chr1\t1000\t.\tA\tG\t900\tLowQual\t.\tGT:DP:GQ\t0/1:40:99\n"),
                registry(root),
            )
        self.assertEqual("--", rows[0]["RESULT"])
        self.assertIn("filtrada não é uma chamada", rows[0]["CALL_BASIS"])

    def test_a_shallow_call_is_recorded_as_a_no_call_with_its_depth(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(
                vcf(root, "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:4:99\n"),
                registry(root),
            )
        self.assertEqual("--", rows[0]["RESULT"])
        self.assertEqual(4, rows[0]["DEPTH"])
        self.assertIn("DP=4 abaixo do mínimo 10", rows[0]["CALL_BASIS"])

    def test_a_low_genotype_quality_call_is_a_no_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(
                vcf(root, "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:5\n"),
                registry(root),
            )
        self.assertEqual("--", rows[0]["RESULT"])
        self.assertIn("GQ=5", rows[0]["CALL_BASIS"])

    def test_an_indel_is_recorded_rather_than_expressed_as_two_bases(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, evidence = project(
                vcf(root, "chr1\t1000\t.\tA\tAGGG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"),
                registry(root),
            )
        self.assertEqual("--", rows[0]["RESULT"])
        self.assertIn("não-SNV", rows[0]["CALL_BASIS"])
        self.assertEqual(1, evidence["outcomes"]["not_expressible"])

    def test_an_uncalled_genotype_is_a_no_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(
                vcf(root, "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t./.:40:99\n"),
                registry(root),
            )
        self.assertEqual("--", rows[0]["RESULT"])
        self.assertIn("não chamado", rows[0]["CALL_BASIS"])

    def test_a_haploid_call_keeps_its_single_base(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(
                vcf(root, "chrX\t4000\t.\tT\tC\t900\tPASS\t.\tGT:DP:GQ\t1:40:99\n"),
                registry(root),
            )
        self.assertEqual("C", rows[0]["RESULT"])


class ConflictsAreNotArbitratedTest(unittest.TestCase):
    def test_two_records_at_one_coordinate_disagreeing_are_unreportable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, evidence = project(
                vcf(root,
                    "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"
                    "chr1\t1000\t.\tA\tC\t900\tPASS\t.\tGT:DP:GQ\t1/1:40:99\n"),
                registry(root),
            )
        self.assertEqual("--", rows[0]["RESULT"])
        self.assertIn("escolher um seria arbitrar", rows[0]["CALL_BASIS"])
        self.assertEqual(1, evidence["outcomes"]["duplicate_conflict"])

    def test_two_registry_targets_at_one_coordinate_refuse_the_projection(self):
        duplicated = TARGETS + [{
            "rsid": "rs999", "gene": "G", "label": "l", "scope": "CLINICO",
            "grch38": {"chromosome": "1", "position": 1000}, "reference_allele": "A",
        }]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ProjectionError) as caught:
                project(vcf(root, ""), registry(root, duplicated))
        self.assertIn("arbitrar", str(caught.exception))


class TheSampleIsChosenNotGuessedTest(unittest.TestCase):
    def _multi(self, root: Path) -> Path:
        path = root / "multi.vcf"
        path.write_text(
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tA\tB\n"
            "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\t1/1:40:99\n",
            encoding="utf-8",
        )
        return path

    def test_a_multi_sample_vcf_refuses_until_told_which_sample(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ProjectionError) as caught:
                project(self._multi(root), registry(root))
        self.assertIn("--sample", str(caught.exception))

    def test_the_named_sample_is_the_one_projected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(self._multi(root), registry(root), sample="B")
        self.assertEqual("GG", rows[0]["RESULT"])

    def test_an_absent_sample_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ProjectionError):
                project(self._multi(root), registry(root), sample="C")


class TheProjectionIsReadableByTheStackTest(unittest.TestCase):
    def test_the_table_header_is_the_schema_the_qc_recognises(self):
        from array_pipeline.qc import VCF_PROJECTION_COLUMNS, detect_schema

        self.assertEqual(PROJECTION_COLUMNS, VCF_PROJECTION_COLUMNS)
        self.assertEqual("wgs_vcf_projection_v1", detect_schema(PROJECTION_COLUMNS))

    def test_a_written_table_round_trips_through_the_row_reader(self):
        from array_pipeline.completeness import _row_reader

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(
                vcf(root, "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"),
                registry(root),
            )
            table = write_table(rows, root / "table.csv")
            read = list(_row_reader(table))
        self.assertEqual(1, len(read))
        schema, row = read[0]
        self.assertEqual("wgs_vcf_projection_v1", schema)
        self.assertEqual("rs001", row["RSID"])
        self.assertEqual("AG", row["RESULT"])

    def test_a_bgzipped_vcf_projects_the_same_as_a_plain_one(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            body = "chr1\t1000\t.\tA\tG\t900\tPASS\t.\tGT:DP:GQ\t0/1:40:99\n"
            plain = vcf(root, body)
            packed = root / "case.vcf.gz"
            packed.write_bytes(gzip.compress((HEADER + body).encode("utf-8")))
            a, _ = project(plain, registry(root))
            b, _ = project(packed, registry(root))
        self.assertEqual(a, b)

    def test_a_file_that_is_not_a_vcf_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "prosa.vcf"
            path.write_text("linha um\nlinha dois\n", encoding="utf-8")
            with self.assertRaises(ProjectionError) as caught:
                project(path, registry(root))
        self.assertIn("não é um VCF legível", str(caught.exception))


class BuildAndStrandAreMeasuredNotAssertedTest(unittest.TestCase):
    def test_too_few_checks_yield_no_attestation(self):
        evidence = {"reference_allele_checks": 3, "reference_allele_mismatches": 0}
        result = provenance_attestations(evidence, "a" * 64)
        self.assertEqual("NÃO DISPONÍVEL", result["status"])
        self.assertIn("nada estabelece build nem orientação", result["reason"])

    def test_enough_concordance_attests_build_and_forward_strand(self):
        evidence = {
            "reference_allele_checks": 500,
            "reference_allele_mismatches": 2,
            "registry_targets": 500,
        }
        result = provenance_attestations(evidence, "b" * 64)
        self.assertEqual("VERIFICADO", result["status"])
        self.assertEqual("GRCh38", result["build"]["asserted_value"])
        self.assertEqual("forward", result["strand"]["asserted_value"])
        # Bound to the table the QC will hash, or the gate refuses it — correctly.
        self.assertEqual(["b" * 64], result["build"]["trace"]["input_sha256"])
        self.assertIn("498 de 500", result["build"]["justification"])


if __name__ == "__main__":
    unittest.main()
