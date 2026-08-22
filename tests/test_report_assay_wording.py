"""A report must not describe a method it did not use.

Every builder had the assay written into its prose as a constant — "Genotipagem em array não
produz DP, GQ nem balanço alélico", "Call rate do array", "A matriz descreve cobertura do
array", "locus não presente no arquivo do array". True of a SNP-array export, and false the
moment the same stack reads a table projected from a WGS VCF.

One of those sentences was worse than imprecise. The projected table carries DP and GQ on
every row, and the technical report told the reader there was no depth behind any call. A
report that understates the evidence it holds is as wrong as one that overstates it, and this
one did it in the section explaining its own methods.

The wording now comes from `reporting.assay`, keyed by the schema `array_pipeline.qc` measured
off the input's header. An unknown schema raises rather than borrowing a sentence.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.qc import HARMONIZED_COLUMNS, RAW_COLUMNS, VCF_PROJECTION_COLUMNS, detect_schema
from reporting.assay import ASSAYS, UnknownAssayError, assay_for, assay_for_schema

#: Prose that asserts the method was an array. Matched against a whole payload, so a report
#: built from a projection may not contain any of it.
ARRAY_CLAIMS = re.compile(r"em array|do array|este array|por array|no array")


class EveryReadableSchemaHasAnAssayTest(unittest.TestCase):
    def test_the_three_headers_the_stack_accepts_are_all_described(self):
        for header in (HARMONIZED_COLUMNS, RAW_COLUMNS, VCF_PROJECTION_COLUMNS):
            schema = detect_schema(header)
            with self.subTest(schema=schema):
                self.assertIn(schema, ASSAYS)
                self.assertEqual(schema, assay_for_schema(schema).schema)

    def test_an_unknown_schema_raises_rather_than_borrowing_a_sentence(self):
        with self.assertRaises(UnknownAssayError) as caught:
            assay_for_schema("algum_formato_novo_v1")
        self.assertIn("emprestaria a frase", str(caught.exception))

    def test_the_assay_is_read_from_the_qc_artifact(self):
        self.assertEqual(
            "wgs_vcf_projection_v1",
            assay_for({"input": {"schema": "wgs_vcf_projection_v1"}}).schema,
        )

    def test_only_the_array_assays_deny_read_depth(self):
        self.assertFalse(assay_for_schema("raw_snp_array_v1").produces_read_depth)
        self.assertFalse(assay_for_schema("harmonized_genera_myheritage_v1").produces_read_depth)
        self.assertTrue(assay_for_schema("wgs_vcf_projection_v1").produces_read_depth)

    def test_the_projection_never_claims_the_absence_of_depth(self):
        note = assay_for_schema("wgs_vcf_projection_v1").depth_note
        self.assertIn("DP", note)
        self.assertNotIn("não há profundidade", note)

    def test_each_schema_has_its_own_name(self):
        names = [assay.name for assay in ASSAYS.values()]
        self.assertEqual(len(names), len(set(names)))

    def test_the_projection_is_described_differently_from_an_array(self):
        """The two array schemas may share wording; the projection may not share theirs."""
        projection = assay_for_schema("wgs_vcf_projection_v1")
        for schema in ("raw_snp_array_v1", "harmonized_genera_myheritage_v1"):
            array = assay_for_schema(schema)
            with self.subTest(schema=schema):
                self.assertNotEqual(array.depth_note, projection.depth_note)
                self.assertNotEqual(array.absence_note, projection.absence_note)
                self.assertNotEqual(array.coverage_subject, projection.coverage_subject)
                self.assertNotEqual(array.genome_wide_note, projection.genome_wide_note)


class AProjectionReportNamesNoArrayTest(unittest.TestCase):
    """Built end to end, because the wording has to survive the whole chain."""

    TARGETS = [
        {
            "rsid": f"rs{index:04d}", "gene": f"G{index}", "label": "l", "scope": "CLINICO",
            "grch38": {"chromosome": "1", "position": 10_000 + index * 100},
            "reference_allele": "A",
        }
        for index in range(80)
    ]

    def _artifacts(self, root: Path):
        from scripts.run_snp_array import inspect_array, write_outputs
        from scripts.vcf_projection import project, provenance_attestations, write_table
        from array_pipeline.completeness import build_completeness_matrix, write_matrix

        registry = root / "targets.json"
        registry.write_text(
            json.dumps({
                "schema": "genoma-partial-genome-targets-v1", "id": "T", "version": "1",
                "description": "d", "generated_at": "2026-08-22T00:00:00Z",
                "targets": self.TARGETS,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        body = "\n".join(
            f"chr1\t{10_000 + index * 100}\t.\tA\t{'G' if index % 3 else '<NON_REF>'}\t900\t"
            f"{'PASS' if index % 3 else '.'}\t"
            f"{'.' if index % 3 else f'END={10_000 + index * 100}'}\tGT:DP:GQ\t"
            f"{'0/1' if index % 3 else '0/0'}:40:99"
            for index in range(80)
        )
        source = root / "case.vcf"
        source.write_text(
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tCASO-1\n" + body + "\n",
            encoding="utf-8",
        )
        rows, evidence = project(source, registry)
        table = write_table(rows, root / "table.csv")
        from scripts.ngs_formats import sha256_of

        attestations = provenance_attestations(evidence, sha256_of(table))
        self.assertEqual("VERIFICADO", attestations["status"], evidence)
        result = inspect_array(
            table,
            case_id="CASO-PROJ",
            build="GRCh38",
            strand="forward",
            build_evidence=json.dumps(attestations["build"], ensure_ascii=False),
            strand_evidence=json.dumps(attestations["strand"], ensure_ascii=False),
        )
        paths = write_outputs(result, root / "qc")
        qc_path = paths["qc"] if isinstance(paths, dict) else root / "qc" / "array-qc.json"
        matrix = build_completeness_matrix(table, Path(qc_path), registry)
        return Path(qc_path), write_matrix(matrix, root / "completeness.json")

    def test_reports_05_and_09_describe_a_projection_and_never_an_array(self):
        from scripts.build_completeness_report import build_payload as report_09
        from scripts.build_technical_report import build_payload as report_05

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            qc_path, matrix_path = self._artifacts(root)
            payloads = {
                "09": report_09(matrix_path, qc_path),
                "05": report_05(qc_path, matrix_path, None),
            }
        for name, payload in payloads.items():
            text = json.dumps(payload, ensure_ascii=False)
            with self.subTest(report=name):
                self.assertEqual(
                    [], ARRAY_CLAIMS.findall(text),
                    f"relatório {name} afirma ter usado um array",
                )
                self.assertIn("projeção", text)

    def test_the_technical_report_states_the_depth_it_actually_has(self):
        from scripts.build_technical_report import build_payload as report_05

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            qc_path, matrix_path = self._artifacts(root)
            payload = report_05(qc_path, matrix_path, None)
        limitations = str(payload["sections"]["Limitações e fontes"])
        self.assertIn("profundidade (DP)", limitations)
        self.assertNotIn("não há profundidade de leitura", limitations)


class AnArrayReportStillNamesTheArrayTest(unittest.TestCase):
    """The repair must not have made the array lane describe itself wrongly instead."""

    def test_the_array_assays_keep_their_wording(self):
        for schema in ("raw_snp_array_v1", "harmonized_genera_myheritage_v1"):
            assay = assay_for_schema(schema)
            with self.subTest(schema=schema):
                self.assertIn("array", assay.name)
                self.assertIn("não produz DP", assay.depth_note)
                self.assertIn("arquivo do array", assay.absence_note)


if __name__ == "__main__":
    unittest.main()
