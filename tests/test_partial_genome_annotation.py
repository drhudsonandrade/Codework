from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from array_pipeline.annotation import annotate_partial_genome
from array_pipeline.qc import inspect_array
from array_pipeline.targets import build_query_plan, load_target_manifest


class PartialGenomeAnnotationTest(unittest.TestCase):
    """The bounded annotation plane over a partial genome."""
    def _fixture(self, root: Path) -> Path:
        """A gzipped array fixture with one target locus and one off-target locus."""
        p = root / "array.csv.gz"
        with gzip.open(p, "wt", encoding="utf-8", newline="") as f:
            f.write("RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n")
            f.write("rs1799807,3,165548529,CT,consensus,CT,CT,GM\n")
            f.write("rs999999,1,100,AA,consensus,AA,AA,GM\n")
        return p

    def _evidence(self, array: Path, *, asserted_value: str) -> str:
        """A build/strand attestation bound to this array by its SHA-256."""
        sha = hashlib.sha256(array.read_bytes()).hexdigest()
        return json.dumps({
            "status": "VERIFICADO",
            "decision": "SATISFIED",
            "asserted_value": asserted_value,
            "justification": "Synthetic annotation fixture explicitly controls build and strand.",
            "evidence_refs": ["synthetic-annotation-fixture"],
            "trace": {
                "attestation_id": "annotation-fixture-provenance",
                "created_at": "2026-08-17T00:00:00Z",
                "actor_type": "SOFTWARE",
                "actor_id": "tests.test_partial_genome_annotation",
                "method": "deterministic fixture",
                "run_id": "unit-test",
                "input_sha256": [sha],
                "output_sha256": [],
                "tool_versions": {"test": "1"},
            },
        })

    def test_an_attestation_for_another_assembly_does_not_unlock_interpretation(self):
        """Only matching values were ever exercised, so the comparison was untested.

        If `inspect_array` stopped comparing `asserted_value` against the declared build or
        strand, every existing case here would still pass — and an attestation about GRCh38
        would release interpretation of an array declared GRCh37.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = self._fixture(root)
            qc = inspect_array(
                array,
                case_id="SYN",
                build="GRCh37",
                strand="forward",
                build_evidence=self._evidence(array, asserted_value="GRCh38"),
                strand_evidence=self._evidence(array, asserted_value="forward"),
            )
            self.assertEqual(qc["gates"]["BUILD_STRAND_GATE"]["state"], "BLOCKED")
            self.assertEqual(qc["gates"]["LIMITED_INTERPRETATION_GATE"]["state"], "BLOCKED")

            # The same fixture with a matching attestation must clear the gate, so the
            # assertion above is about the mismatch and not about the fixture being unusable.
            agreeing = inspect_array(
                array,
                case_id="SYN",
                build="GRCh37",
                strand="forward",
                build_evidence=self._evidence(array, asserted_value="GRCh37"),
                strand_evidence=self._evidence(array, asserted_value="forward"),
            )
            self.assertEqual(agreeing["gates"]["BUILD_STRAND_GATE"]["state"], "PASS")

    def test_plan_only_is_target_first_and_not_verified_evidence(self):
        """plan-only is target-first and is PROPOSTO, never verified evidence."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = self._fixture(root)
            build_evidence = self._evidence(array, asserted_value="GRCh37")
            strand_evidence = self._evidence(array, asserted_value="forward")
            qc = inspect_array(
                array,
                case_id="SYN",
                build="GRCh37",
                strand="forward",
                build_evidence=build_evidence,
                strand_evidence=strand_evidence,
            )
            qc_path = root / "qc.json"
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            target_path = Path(__file__).resolve().parents[1] / "config" / "partial_genome_annotation_targets.json"
            result = annotate_partial_genome(array, qc_path, target_path, mode="plan-only")
            self.assertEqual(result["operational_status"], "PROPOSTO")
            self.assertEqual(result["evidence_gate"]["state"], "BLOCKED")
            observed = {x["rsid"] for x in result["observations"]}
            self.assertEqual(observed, {"rs1799807"})
            self.assertGreater(result["query_plan"]["query_count"], 0)
            self.assertTrue(all(x["status"] == "PROPOSTO" for x in result["evidence_retrievals"]))
            self.assertIn("genome-wide negative/exclusion claims", result["unsupported_claims"])

    #: Two observed targets, one query each: two queries over two targets.
    TWO_TARGETS = {
        "schema": "genoma-partial-genome-targets-v1",
        "targets": [
            {"rsid": "rs1", "scope": "PESQUISA", "queries": {"clinvar": {"term": "rs1"}}},
            {"rsid": "rs2", "scope": "PESQUISA", "queries": {"clinvar": {"term": "rs2"}}},
        ],
    }

    def test_query_budget_fails_closed(self):
        """Exceeding the query budget fails closed rather than truncating the plan.

        `max_targets` is set to 2 so the target budget is satisfied and only the query budget
        can refuse. The earlier version passed `max_targets=1` and left `max_queries` at its
        default of 1000, so it was the *target* budget that raised: deleting the query-budget
        check entirely would not have failed this test.
        """
        with self.assertRaisesRegex(ValueError, "query budget"):
            build_query_plan({"rs1", "rs2"}, self.TWO_TARGETS, max_targets=2, max_queries=1)

    def test_target_budget_fails_closed(self):
        """The other budget, kept as its own test so neither can stand in for the other."""
        with self.assertRaisesRegex(ValueError, "target budget"):
            build_query_plan({"rs1", "rs2"}, self.TWO_TARGETS, max_targets=1, max_queries=1000)

    def test_default_manifest_is_well_formed_and_bounded(self):
        """The shipped default manifest is well formed and within its declared bounds."""
        path = Path(__file__).resolve().parents[1] / "config" / "partial_genome_annotation_targets.json"
        payload = load_target_manifest(path)
        self.assertEqual(payload["schema"], "genoma-partial-genome-targets-v1")
        self.assertLessEqual(len(payload["targets"]), 250)
        scopes = {x["scope"] for x in payload["targets"]}
        self.assertTrue(scopes <= {"CLINICO", "PREDISPOSICAO", "PESQUISA", "CURIOSIDADE"})


if __name__ == "__main__":
    unittest.main()
