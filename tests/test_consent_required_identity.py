from __future__ import annotations

import unittest
from datetime import date

from reporting.consent import ConsentError, REQUIRED_AFFIRMATIONS, validate_record


class ConsentRequiredIdentityTest(unittest.TestCase):
    def _valid(self):
        return {
            "schema": "genoma-consent-record-v1",
            "subject_id": "SUBJECT-1",
            "case_id": "CASE-1",
            "input_sha256": "a" * 64,
            "version": "1",
            "authorized_domains": ["CLÍNICO"],
            "granted_at": "2026-08-17T00:00:00Z",
            "instrument": "fixture",
            "instrument_version": "1",
            "captured_by": "test",
            "affirmations": {key: True for key in REQUIRED_AFFIRMATIONS},
            "verified": True,
            "basis": "deterministic test fixture",
        }

    def test_empty_case_id_is_rejected_without_runtime_binding(self):
        record = self._valid()
        record["case_id"] = ""
        with self.assertRaisesRegex(ConsentError, "case_id está vazio"):
            validate_record(record, today=date(2026, 8, 24))

    def test_empty_input_sha256_is_rejected_without_runtime_binding(self):
        record = self._valid()
        record["input_sha256"] = ""
        with self.assertRaisesRegex(ConsentError, "input_sha256 está vazio"):
            validate_record(record, today=date(2026, 8, 24))


if __name__ == "__main__":
    unittest.main()
