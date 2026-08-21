"""Cross-platform conflicts must never be resolved by assertion.

Ruleset section 4 requires conflicts to stay recorded and never be arbitrarily resolved,
and section 7 forbids assuming either platform is correct when they disagree. Two defects
violated that: `_orientation` keyed only off `SOURCES`, so a record the harmoniser had
flagged as conflicting was reported as "cross-platform consensus"/VERIFICADO; and the
CROSS_PLATFORM_GATE answered PASS while listing unresolved records as failure `reasons`.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.annotation import _orientation
from array_pipeline.qc import UNRESOLVED_OVERLAP_STATUSES, inspect_array

QC_CONTEXT = {
    "input": {
        "strand": "forward",
        "strand_evidence": "declared",
        "strand_evidence_verified": True,
    }
}

#: A real harmonized export declares no build/strand metadata at all. Consensus alone must
#: not be promoted to verified orientation in that case.
QC_NO_STRAND_EVIDENCE = {
    "input": {
        "strand": "NÃO DISPONÍVEL",
        "strand_evidence": "NÃO DISPONÍVEL",
        "strand_evidence_verified": False,
    }
}


def _attestation(input_sha: str, asserted_value: str) -> str:
    return json.dumps(
        {
            "status": "VERIFICADO",
            "decision": "SATISFIED",
            "asserted_value": asserted_value,
            "justification": "synthetic fixture for infrastructure testing only",
            "evidence_refs": ["synthetic-fixture"],
            "trace": {
                "attestation_id": "test-array-conflicts",
                "created_at": "2026-08-17T00:00:00Z",
                "actor_type": "SOFTWARE",
                "actor_id": "tests",
                "method": "deterministic fixture",
                "run_id": "tests",
                "input_sha256": [input_sha],
                "output_sha256": [],
                "tool_versions": {"python": "3"},
            },
        }
    )


def _fixture(rows: list[str]):
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / "array.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(
            "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,"
            "GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"
        )
        for row in rows:
            handle.write(row + "\n")
    return directory, path, hashlib.sha256(path.read_bytes()).hexdigest()


class OrientationTest(unittest.TestCase):
    def test_consensus_with_documented_strand_provenance_is_verified(self):
        status, basis = _orientation({"SOURCES": "GM", "STATUS": "consensus"}, "harmonized_v1", QC_CONTEXT)
        self.assertEqual(status, "VERIFICADO")
        self.assertIn("cross-platform consensus", basis)
        self.assertIn("forward-strand provenance", basis)

    def test_consensus_without_strand_evidence_is_only_inferido(self):
        """Agreement proves the vendors matched each other, not which strand they used.

        If both reported the reverse strand, an AG call reads TC in both files: they agree
        perfectly while both are flipped. A real harmonized export declares no strand
        metadata at all, and 9 of its 14 baseline markers were being marked VERIFICADO on
        the strength of consensus alone.
        """
        status, basis = _orientation(
            {"SOURCES": "GM", "STATUS": "consensus"}, "harmonized_v1", QC_NO_STRAND_EVIDENCE
        )
        self.assertEqual(status, "INFERIDO")
        self.assertIn("mutual consistency", basis)
        self.assertIn("not absolute strand orientation", basis)

    def test_unverified_strand_evidence_does_not_count_as_evidence(self):
        """The old proxy accepted any non-empty string as strand evidence."""
        context = {
            "input": {
                "strand": "forward",
                "strand_evidence": "o laboratório disse que é forward",
                "strand_evidence_verified": False,
            }
        }
        status, _ = _orientation({"SOURCES": "GM", "STATUS": "consensus"}, "harmonized_v1", context)
        self.assertEqual(status, "INFERIDO")

    def test_an_unrecognised_harmonizer_status_is_refused_not_assumed_clean(self):
        """A denylist fails open; a status neither list anticipated was treated as clean."""
        status, basis = _orientation(
            {"SOURCES": "GM", "STATUS": "some_future_harmonizer_state"}, "harmonized_v1", QC_CONTEXT
        )
        self.assertEqual(status, "NÃO DISPONÍVEL")
        self.assertIn("unrecognised", basis)

    def test_the_ambiguous_duplicate_status_emitted_by_real_data_is_unresolved(self):
        """Found in a real export: the same rsid twice in one vendor file with `II|DD`."""
        self.assertIn("genera_ambiguous_duplicate", UNRESOLVED_OVERLAP_STATUSES)
        status, basis = _orientation(
            {"SOURCES": "G", "STATUS": "genera_ambiguous_duplicate"}, "harmonized_v1", QC_CONTEXT
        )
        self.assertEqual(status, "NÃO DISPONÍVEL")
        self.assertNotIn("consensus", basis)

    def test_unresolved_records_are_never_reported_as_consensus(self):
        for unresolved in sorted(UNRESOLVED_OVERLAP_STATUSES):
            status, basis = _orientation(
                {"SOURCES": "GM", "STATUS": unresolved}, "harmonized_v1", QC_CONTEXT
            )
            self.assertEqual(status, "NÃO DISPONÍVEL", f"{unresolved} was treated as resolved")
            self.assertNotIn("consensus", basis)
            self.assertIn(unresolved, basis)

    def test_status_matching_is_case_and_whitespace_tolerant(self):
        status, _ = _orientation(
            {"SOURCES": "GM", "STATUS": "  Genotype_Conflict "}, "harmonized_v1", QC_CONTEXT
        )
        self.assertEqual(status, "NÃO DISPONÍVEL")


class CrossPlatformGateTest(unittest.TestCase):
    def _inspect(self, rows, **kwargs):
        directory, path, sha = _fixture(rows)
        try:
            return inspect_array(
                path,
                case_id="TEST-NO-PERSONAL-DATA",
                build="GRCh37",
                strand="forward",
                build_evidence=_attestation(sha, "GRCh37"),
                strand_evidence=_attestation(sha, "forward"),
                min_call_rate=0.5,
                max_overlap_conflict_rate=0.99,
                **kwargs,
            )
        finally:
            directory.cleanup()

    def test_gate_never_reports_pass_together_with_failure_reasons(self):
        result = self._inspect(
            [
                "rs1799807,3,165548529,CT,consensus,CT,CT,GM",
                "rsC1,1,111,AG,coordinate_conflict,AG,AG,GM",
                "rsA1,2,222,CT,ambiguous_overlap,CT,CT,GM",
            ]
        )
        gate = result["gates"]["CROSS_PLATFORM_GATE"]
        if gate["state"] == "PASS":
            self.assertEqual(gate["reasons"], [], "PASS must not carry failure reasons")

    def test_unresolved_records_are_reported_in_their_own_field(self):
        result = self._inspect(
            [
                "rs1799807,3,165548529,CT,consensus,CT,CT,GM",
                "rsC1,1,111,AG,coordinate_conflict,AG,AG,GM",
                "rsA1,2,222,CT,ambiguous_overlap,CT,CT,GM",
            ]
        )
        gate = result["gates"]["CROSS_PLATFORM_GATE"]
        self.assertEqual(gate["unresolved_records"]["coordinate_conflict"], 1)
        self.assertEqual(gate["unresolved_records"]["ambiguous_overlap"], 1)
        self.assertIn("excluded from interpretation", gate["unresolved_record_policy"])

    def test_clean_array_reports_no_unresolved_records(self):
        result = self._inspect(
            [
                "rs1799807,3,165548529,CT,consensus,CT,CT,GM",
                "rs17580,14,94847262,AT,consensus,AT,AT,GM",
            ]
        )
        gate = result["gates"]["CROSS_PLATFORM_GATE"]
        self.assertEqual(gate["unresolved_records"], {})
        self.assertEqual(gate["state"], "PASS")
        self.assertEqual(gate["reasons"], [])


if __name__ == "__main__":
    unittest.main()
