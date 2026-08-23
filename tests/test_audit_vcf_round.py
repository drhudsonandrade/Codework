"""Defects found auditing the system after the VCF projection landed.

Five, each reproduced before being closed. Two of them were the same failure the projection
itself was written to avoid, arriving through a different door.

1. A **gVCF non-variant block with a failing FILTER** produced a homozygous-reference
   genotype. The variant branch refused a filtered record and this one did not, so a span the
   caller had itself marked low-quality was read as "reference confirmed here" at every target
   inside it — a false negative at the exact place the adapter exists to prevent one.

2. **Overlapping BED intervals lost coverage.** `_covered_by_bed` bisects to the last interval
   starting at or before the position; with `chr1 0-5000` followed by `chr1 900-950`, position
   1000 is inside the first and only the second was ever examined. Fail-closed — it
   understated coverage — and still wrong.

3. The **array lane's 263 section attestations were attached to a WGS run.** Section 3 declared
   the input the harmonised bank with "nenhum WGS foi enviado", 7 and 55 dismissed WGS rules as
   inapplicable because none existed, 8 dismissed variant normalisation as an array concern.
   Six judgements were false about the very run they certified, and RULE_COVERAGE_GATE passed
   on them. The manifest also declared `operation: "SNP-array curated interpretation"` for a
   VCF. Judgements made about one operation certifying another is the inheritance this whole
   gate exists to prevent.

4. The **witness accepted type-confused values**, because `1 == True` and `False == 0` in
   Python: `all_pass: 1`, `bootstrap_verified: 1` and — worst — `critical_failures: false`,
   which is not a count of anything and was read as zero critical failures.

5. `load_targets` returned its "how many lack coordinates" count **inside the coordinate-keyed
   index**, under a string key, in a dict every caller iterates as `for contig, position in
   index`.
"""
from __future__ import annotations

import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative
from reporting.provenance import witness_verdict
from scripts.vcf_projection import _covered_by_bed, _load_callable_bed, load_targets, project

TARGET = {
    "rsid": "rs001", "gene": "G", "label": "l", "scope": "CLINICO",
    "grch38": {"chromosome": "1", "position": 1000}, "reference_allele": "A",
}
HEADER = (
    "##fileformat=VCFv4.2\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n"
)


def registry(directory: Path, targets=None) -> Path:
    path = directory / "targets.json"
    path.write_text(
        json.dumps({
            "schema": "genoma-partial-genome-targets-v1", "id": "T", "version": "1",
            "description": "d", "generated_at": "2026-08-22T00:00:00Z",
            "targets": targets if targets is not None else [TARGET],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def vcf(directory: Path, body: str) -> Path:
    path = directory / "case.vcf"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


class AFilteredBlockIsNotReferenceTest(unittest.TestCase):
    def test_a_filtered_gvcf_block_declares_no_homozygous_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, evidence = project(
                vcf(root, "chr1\t900\t.\tA\t<NON_REF>\t.\tLowQual\tEND=1100\tGT:DP:GQ\t0/0:30:60\n"),
                registry(root),
            )
        self.assertEqual([], rows)
        self.assertEqual(1, evidence["outcomes"]["filtered_gvcf_block"])
        # Uninterrogated, which is what the coverage matrix must see.
        self.assertEqual(1, evidence["targets_absent_from_vcf"])

    def test_a_passing_block_still_establishes_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows, _ = project(
                vcf(root, "chr1\t900\t.\tA\t<NON_REF>\t.\tPASS\tEND=1100\tGT:DP:GQ\t0/0:30:60\n"),
                registry(root),
            )
        self.assertEqual("AA", rows[0]["RESULT"])


class OverlappingCallableIntervalsAreMergedTest(unittest.TestCase):
    def test_a_position_inside_a_longer_earlier_interval_is_covered(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "callable.bed"
            path.write_text("chr1\t0\t5000\nchr1\t900\t950\n", encoding="utf-8")
            intervals = _load_callable_bed(path)
        self.assertEqual([(1, 5000)], intervals["1"])
        self.assertTrue(_covered_by_bed(intervals, "1", 1000))

    def test_adjacent_intervals_merge_into_one_span(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "callable.bed"
            path.write_text("chr1\t0\t100\nchr1\t100\t200\n", encoding="utf-8")
            intervals = _load_callable_bed(path)
        self.assertEqual([(1, 200)], intervals["1"])

    def test_a_position_outside_every_interval_is_not_covered(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "callable.bed"
            path.write_text("chr1\t0\t500\n", encoding="utf-8")
            intervals = _load_callable_bed(path)
        self.assertFalse(_covered_by_bed(intervals, "1", 900))
        self.assertFalse(_covered_by_bed(intervals, "2", 100))


class CurationBelongsToOneAssayTest(unittest.TestCase):
    """The array lane's judgements were certifying WGS runs."""

    def test_the_array_curation_declares_the_schemas_it_was_written_for(self):
        from reporting.section_attestations import load_curation

        curation = load_curation()
        self.assertEqual(
            ["harmonized_genera_myheritage_v1", "raw_snp_array_v1"],
            sorted(curation["applies_to_schemas"]),
        )

    def test_no_curation_exists_for_the_projection_and_that_is_said_plainly(self):
        from reporting.section_attestations import curation_for_schema

        self.assertIsNotNone(curation_for_schema("harmonized_genera_myheritage_v1"))
        self.assertIsNotNone(curation_for_schema("raw_snp_array_v1"))
        self.assertIsNone(curation_for_schema("wgs_vcf_projection_v1"))

    def test_a_curation_without_a_declared_scope_is_refused(self):
        from reporting.section_attestations import CurationError, load_curation

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "curation.json"
            payload = load_curation()
            del payload["applies_to_schemas"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(CurationError) as caught:
                load_curation(path)
        self.assertIn("applies_to_schemas", str(caught.exception))

    def _manifest(self, schema: str) -> dict:
        from scripts.build_array_case_manifest import build_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            qc_path, annotation_path = root / "qc.json", root / "annotation.json"
            qc = {
                "case_id": "CASO-A", "operational_status": "VERIFICADO",
                "gates": {"LIMITED_INTERPRETATION_GATE": {"state": "PASS"}},
                "input": {"sha256": "a" * 64, "build": "GRCh38", "strand": "forward",
                          "schema": schema},
                "metrics": {"unique_rsids": 10, "call_rate": 0.99}, "limitations": [],
            }
            annotation = {
                "case_id": "CASO-A", "input_sha256": "a" * 64, "mode": "plan-only",
                "operational_status": "PROPOSTO", "evidence_gate": {"state": "BLOCKED"},
                "observations": [], "evidence_retrievals": [], "limitations": [],
            }
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
            return build_manifest(qc, annotation, qc_path, annotation_path)

    def test_a_projection_run_attaches_no_array_judgement(self):
        manifest = self._manifest("wgs_vcf_projection_v1")
        self.assertEqual([], manifest["section_attestations"])
        state = manifest["section_attestation_curation"]
        self.assertEqual("PENDENTE", state["status"])
        self.assertIn("nenhuma curadoria", state["reason"])
        self.assertEqual("wgs_vcf_projection_v1", state["assay"])

    def test_an_array_run_still_attaches_its_263(self):
        manifest = self._manifest("harmonized_genera_myheritage_v1")
        self.assertEqual(normative.SECTION_COUNT, len(manifest["section_attestations"]))
        self.assertEqual("COMPLETA", manifest["section_attestation_curation"]["status"])

    def test_the_operation_is_named_from_the_assay_not_from_a_constant(self):
        self.assertIn("array", self._manifest("harmonized_genera_myheritage_v1")["operation"]["name"])
        projection = self._manifest("wgs_vcf_projection_v1")["operation"]["name"]
        self.assertIn("VCF", projection)
        self.assertNotIn("SNP-array", projection)

    def test_a_qc_that_names_no_assay_is_refused_with_a_reason(self):
        with self.assertRaises(ValueError) as caught:
            self._manifest_without_schema()
        self.assertIn("does not name its assay", str(caught.exception))

    def _manifest_without_schema(self):
        from scripts.build_array_case_manifest import build_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            qc_path, annotation_path = root / "qc.json", root / "annotation.json"
            qc = {
                "case_id": "C", "operational_status": "VERIFICADO",
                "gates": {"LIMITED_INTERPRETATION_GATE": {"state": "PASS"}},
                "input": {"sha256": "a" * 64}, "metrics": {}, "limitations": [],
            }
            annotation = {
                "case_id": "C", "input_sha256": "a" * 64, "mode": "plan-only",
                "operational_status": "PROPOSTO", "evidence_gate": {"state": "BLOCKED"},
                "observations": [], "evidence_retrievals": [], "limitations": [],
            }
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
            return build_manifest(qc, annotation, qc_path, annotation_path)


class TheWitnessIsReadExactlyAsWrittenTest(unittest.TestCase):
    """`1 == True` and `False == 0`, so every condition had a type-confused spelling."""

    def _witness(self, **overrides) -> dict:
        payload = {
            "post_deployment_status": "PASS", "all_pass": True, "bootstrap_verified": True,
            "critical_failures": 0,
            "ruleset": {"sha256": normative.RAW_SHA256},
            "target": {
                "authority": "http://127.0.0.1:8787",
                "resolved_addresses": ["127.0.0.1"],
                "network_class": "loopback",
            },
            "completed_at": datetime.datetime.now(datetime.timezone.utc)
            .isoformat().replace("+00:00", "Z"),
        }
        payload.update(overrides)
        return payload

    def test_the_intact_witness_still_passes(self):
        self.assertEqual("PASS", witness_verdict(self._witness())["status"])

    def test_a_boolean_where_a_count_belongs_is_refused(self):
        verdict = witness_verdict(self._witness(critical_failures=False))
        self.assertEqual("PENDENTE", verdict["status"])
        self.assertIn("critical_failures", verdict["basis"])

    def test_an_integer_where_a_boolean_belongs_is_refused(self):
        for key in ("all_pass", "bootstrap_verified"):
            with self.subTest(key=key):
                verdict = witness_verdict(self._witness(**{key: 1}))
                self.assertEqual("PENDENTE", verdict["status"])
                self.assertIn(key, verdict["basis"])

    def test_a_float_where_an_integer_belongs_is_refused(self):
        self.assertEqual(
            "PENDENTE", witness_verdict(self._witness(critical_failures=0.0))["status"]
        )


class TheTargetIndexCarriesOnlyCoordinatesTest(unittest.TestCase):
    def test_load_targets_returns_the_count_beside_the_index_not_inside_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            without = {"rsid": "rs002", "gene": "G", "label": "l", "scope": "CLINICO"}
            index, missing = load_targets(registry(root, [TARGET, without]))
        self.assertEqual(1, missing)
        self.assertEqual([("1", 1000)], list(index))
        # The whole point: every caller iterates this as a pair.
        for contig, position in index:
            self.assertIsInstance(contig, str)
            self.assertIsInstance(position, int)


if __name__ == "__main__":
    unittest.main()
