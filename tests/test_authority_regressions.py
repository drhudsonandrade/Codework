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
    """The shipped case-dossier example, which must stay loadable and consent-free."""
    def test_shipped_example_loads_with_notes_and_empty_consent(self):
        """The example loads, carries its notes, and declares no consent it has not been given."""
        root = Path(__file__).resolve().parents[1]
        source = root / "config/case_dossier.example.json"
        raw = json.loads(source.read_text(encoding="utf-8"))
        self.assertIn("notes", raw)
        self.assertTrue(all(value in ("", [], None) for value in raw["consent"].values()))
        dossier = load_dossier(source, expected_case_id=raw["case_id"])
        self.assertFalse(dossier["consent_documented"])
        self.assertEqual(dossier["consent"], {})


class OnePageSummaryIdentityTest(unittest.TestCase):
    """The identity check behind the one-page summary."""
    def test_two_artifacts_without_input_identity_are_refused(self):
        """`None != None` is false, so absence used to satisfy the equality check.

        A passport and a matrix that both omit `input_sha256` were compiled as describing the
        same array — the one thing this comparison exists to establish.
        """
        from scripts.build_one_page_summary import build_payload

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            matrix = root / "matrix.json"
            passport = root / "passport.json"
            matrix.write_text(json.dumps({"operational_status": "VERIFICADO"}), encoding="utf-8")
            passport.write_text(json.dumps({"case_id": "CASE"}), encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                build_payload(matrix_path=matrix, passport_path=passport)
            self.assertIn("input_sha256", str(caught.exception))


class WgsQcSummaryValidationTest(unittest.TestCase):
    """What the WGS QC summary may call VERIFICADO."""
    def test_invalid_record_cannot_claim_verified(self):
        """A record failing schema validation cannot claim VERIFICADO."""
        summary = audit_summary({"schema": "wrong"})
        self.assertEqual(summary["status"], UNAVAILABLE)
        self.assertTrue(summary["problems"])


    def test_an_unrepresentable_integer_metric_is_a_problem_not_a_crash(self):
        """JSON integers are arbitrary precision; `math.isfinite` is not.

        A metric arriving as an int too large to convert to float raised OverflowError out of
        `audit_summary`, so the record died instead of reporting the value as not finite —
        the very outcome the finiteness branch exists to produce.
        """
        record = wgs_qc_record(case_id="CASE")
        record["metrics"]["mean_depth"] = 10**400
        summary = audit_summary(record)
        self.assertEqual(summary["status"], UNAVAILABLE)
        self.assertTrue(
            any("mean_depth" in problem for problem in summary["problems"]),
            summary["problems"],
        )
        # And the count must agree with the refusal. `audit_summary` used its own test —
        # "is it an int or a float?" — so the same value was reported as not finite *and*
        # listed among the laboratory's measurements, inflating `measured_count` with a
        # number the record had just rejected.
        self.assertNotIn("mean_depth", summary["measured"])
        self.assertEqual(summary["measured_count"], len(summary["measured"]))

    def test_invalid_metric_is_not_counted_as_measured(self):
        """A metric with an unrecognised status is not counted as measured."""
        record = wgs_qc_record(case_id="CASE")
        record["metrics"]["mean_depth"] = {"status": "DESCONHECIDO"}
        summary = audit_summary(record)
        self.assertEqual(summary["status"], UNAVAILABLE)
        self.assertNotIn("mean_depth", summary["measured"])
        self.assertTrue(summary["problems"])

    def test_identity_fields_must_be_non_empty_text(self):
        """JSON containers and numbers cannot become verified identity through str()."""
        for key in ("case_id", "laboratory"):
            for value in ({}, [], 7, True):
                with self.subTest(key=key, value=value):
                    record = wgs_qc_record(case_id="CASE")
                    record[key] = value
                    summary = audit_summary(record)
                    self.assertEqual(summary["status"], UNAVAILABLE)
                    self.assertTrue(any(key in p for p in summary["problems"]))


    def test_non_finite_metrics_are_rejected(self):
        """NaN and the infinities are rejected as metric values."""
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
    """Handles opened while constructing a stream are closed when construction fails."""
    def test_gzip_raw_handle_is_closed_when_wrapper_construction_fails(self):
        """The raw gzip handle is closed when the wrapper around it fails to construct."""
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
    """How the consent input set treats the files it is given."""
    def test_same_input_listed_twice_is_rejected(self):
        """The same input listed twice is rejected rather than de-duplicated."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reads.fastq"
            path.write_bytes(b"reads")
            with self.assertRaisesRegex(ConsentError, "mais de uma vez"):
                input_set_sha256([path, path])


class SectionCurationValidationTest(unittest.TestCase):
    """What a section curation file must satisfy before its attestations are honoured."""
    @staticmethod
    def _payload(schema="array"):
        """A minimal valid curation payload for this schema."""
        return {
            "schema": CURATION_SCHEMA,
            "ruleset": {"sha256": normative.RAW_SHA256},
            "applies_to_schemas": [schema],
            "sections": {},
        }

    def test_overlapping_curations_are_rejected(self):
        """Two curations claiming the same schema are rejected instead of silently merged."""
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
        """An unreadable curation file raises, rather than being treated as not applicable."""
        with tempfile.TemporaryDirectory() as td:
            invalid = Path(td) / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            with patch("reporting.section_attestations.CURATIONS", (invalid,)):
                with self.assertRaisesRegex(CurationError, "ilegível"):
                    curation_for_schema("array")

    def test_arbitrary_section_hash_is_rejected(self):
        """A section hash that matches no known section is rejected."""
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
        """A NOT_APPLICABLE justification reused across sections is reported."""
        def entry(reason):
            """One NOT_APPLICABLE section entry carrying this justification."""
            return {
                "applicability": "NOT_APPLICABLE",
                "decision": "NOT_APPLICABLE",
                "status": "NÃO DISPONÍVEL",
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
