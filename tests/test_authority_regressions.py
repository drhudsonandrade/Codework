from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import normative
from reporting.case_dossier import load_dossier
from reporting.consent import ConsentError, input_set_sha256
from reporting.section_attestations import (
    CurationError,
    SCHEMA as CURATION_SCHEMA,
    curation_for_schema,
    validate_curation,
)
from array_pipeline.qc import _text_stream
from reporting.wgs_qc_record import UNAVAILABLE, audit_summary
from tests.attestations import wgs_qc_record


class CaseDossierExampleTest(unittest.TestCase):
    def test_shipped_example_loads_with_notes_and_empty_consent(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "config/case_dossier.example.json"
        raw = json.loads(source.read_text(encoding="utf-8"))
        self.assertIn("notes", raw)
        self.assertTrue(all(value in ("", [], None) for value in raw["consent"].values()))
        dossier = load_dossier(source, expected_case_id=raw["case_id"])
        self.assertFalse(dossier["consent_documented"])
        self.assertEqual(dossier["consent"], {})


class WgsQcSummaryValidationTest(unittest.TestCase):
    def test_invalid_record_cannot_claim_verified(self):
        summary = audit_summary({"schema": "wrong"})
        self.assertEqual(summary["status"], UNAVAILABLE)
        self.assertTrue(summary["problems"])


    def test_invalid_metric_is_not_counted_as_measured(self):
        record = wgs_qc_record(case_id="CASE")
        record["metrics"]["mean_depth"] = {"status": "DESCONHECIDO"}
        summary = audit_summary(record)
        self.assertEqual(summary["status"], UNAVAILABLE)
        self.assertNotIn("mean_depth", summary["measured"])
        self.assertTrue(summary["problems"])


    def test_non_finite_metrics_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                record = wgs_qc_record(case_id="CASE")
                record["metrics"]["mean_depth"] = value
                summary = audit_summary(record)
                self.assertEqual(summary["status"], UNAVAILABLE)
                self.assertTrue(
                    any("número finito" in problem for problem in summary["problems"])
                )


class StreamConstructionCleanupTest(unittest.TestCase):
    def test_gzip_raw_handle_is_closed_when_wrapper_construction_fails(self):
        raw = MagicMock()
        with (
            patch("array_pipeline.qc.gzip.open", return_value=raw),
            patch(
                "array_pipeline.qc.io.BufferedReader",
                side_effect=RuntimeError("fixture failure"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                _text_stream(Path("fixture.csv.gz"))
        raw.close.assert_called_once_with()


class ConsentInputSetTest(unittest.TestCase):
    def test_same_input_listed_twice_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reads.fastq"
            path.write_bytes(b"reads")
            with self.assertRaisesRegex(ConsentError, "mais de uma vez"):
                input_set_sha256([path, path])


class SectionCurationValidationTest(unittest.TestCase):
    @staticmethod
    def _payload(schema="array"):
        return {
            "schema": CURATION_SCHEMA,
            "ruleset": {"sha256": normative.RAW_SHA256},
            "applies_to_schemas": [schema],
            "sections": {},
        }

    def test_overlapping_curations_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "first.json"
            second = Path(td) / "second.json"
            payload = self._payload()
            first.write_text(json.dumps(payload), encoding="utf-8")
            second.write_text(json.dumps(payload), encoding="utf-8")
            with patch("reporting.section_attestations.CURATIONS", (first, second)):
                with self.assertRaisesRegex(CurationError, "mais de uma curadoria"):
                    curation_for_schema("array")

    def test_invalid_curation_file_is_not_treated_as_non_applicable(self):
        with tempfile.TemporaryDirectory() as td:
            invalid = Path(td) / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            with patch("reporting.section_attestations.CURATIONS", (invalid,)):
                with self.assertRaisesRegex(CurationError, "ilegível"):
                    curation_for_schema("array")

    def test_arbitrary_section_hash_is_rejected(self):
        payload = self._payload()
        payload["sections"] = {
            "0": {
                "applicability": "APPLICABLE",
                "decision": "SATISFIED",
                "status": "VERIFICADO",
                "justification": "fixture",
                "rule_sha256": "a" * 64,
                "evidence_refs": ["ruleset-v3.4"],
            }
        }
        problems = validate_curation(payload)
        self.assertTrue(any("canonical section" in problem for problem in problems))

    def test_any_reused_not_applicable_justification_is_reported(self):
        def entry(reason):
            return {
                "applicability": "NOT_APPLICABLE",
                "decision": "NOT_APPLICABLE",
                "status": UNAVAILABLE,
                "justification": reason,
                "rule_sha256": "a" * 64,
                "evidence_refs": [],
            }

        problems = validate_curation({
            "sections": {
                "1": entry("reused"),
                "2": entry("reused"),
                "3": entry("distinct"),
            }
        })
        self.assertTrue(any("reuse justification" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
