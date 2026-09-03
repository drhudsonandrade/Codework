from __future__ import annotations

import gzip
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


class ReleaseProjectionTest(unittest.TestCase):
    def test_internal_policy_binding_is_not_copied_into_report_payload(self):
        from scripts.prepare_report_release import _public_policy_projection

        policy = {
            "result_digest": "r" * 64,
            "manifest_sha256": "m" * 64,
            "ready_for_requested_operation": True,
            "planes": {},
            "gates": [],
            "case_id": "CASE-SECRET",
            "input_sha256": "i" * 64,
            "session_id": "SESSION-SECRET",
            "evaluation_binding": {"internal": True},
            "evaluated_manifest": {"internal": True},
        }
        projected = _public_policy_projection(policy)
        self.assertEqual(projected["result_digest"], "r" * 64)
        for internal in (
            "case_id",
            "input_sha256",
            "session_id",
            "evaluation_binding",
            "evaluated_manifest",
        ):
            self.assertNotIn(internal, projected)


class PharmacogenomicIdentityTest(unittest.TestCase):
    def test_passport_and_matrix_must_name_the_same_case(self):
        from scripts.build_pharmacogenomic_report import build_payload

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            passport = root / "passport.json"
            matrix = root / "matrix.json"
            passport.write_text(
                json.dumps({"case_id": "CASE-A", "input_sha256": "a" * 64}),
                encoding="utf-8",
            )
            matrix.write_text(
                json.dumps({"case_id": "CASE-B", "input_sha256": "a" * 64}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "same non-empty case_id"):
                build_payload(passport, matrix)


class PgxPanelDigestTest(unittest.TestCase):
    def test_registry_digest_is_computed_once_and_reused(self):
        from scripts import build_pgx_panel

        registry = {
            "id": "fixture",
            "version": "1",
            "source": "fixture",
            "genes": {},
        }
        registry_calls = 0

        def digest(value):
            nonlocal registry_calls
            if value is registry:
                registry_calls += 1
                return "a" * 64
            return "b" * 64

        with patch.object(build_pgx_panel, "sha256_json", side_effect=digest):
            panel = build_pgx_panel.build_panel(registry)
        self.assertEqual(registry_calls, 1)
        self.assertEqual(panel["derived_from"]["registry_sha256"], "a" * 64)


class GwasStreamLimitTest(unittest.TestCase):
    PAYLOAD = b"column\n" + b"x" * 512

    def _assert_limited(self, path: Path) -> None:
        from scripts import build_trait_targets

        with patch.object(build_trait_targets, "MAX_UNCOMPRESSED_BYTES", 64):
            with build_trait_targets._open_associations(path) as stream:
                with self.assertRaises(ValueError):
                    stream.read()

    def test_gzip_limit_applies_to_emitted_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "associations.tsv.gz"
            with gzip.open(path, "wb") as handle:
                handle.write(self.PAYLOAD)
            self._assert_limited(path)

    def test_zip_limit_applies_to_emitted_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "associations.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("associations.tsv", self.PAYLOAD)
            self._assert_limited(path)


if __name__ == "__main__":
    unittest.main()
