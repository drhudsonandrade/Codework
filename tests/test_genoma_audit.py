from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.genoma_audit import _decode_tail, audit, run


class GenomaAuditTest(unittest.TestCase):
    def test_audit_never_grants_post_deployment(self):
        result = audit(allow_template_sealed_only=True)
        self.assertEqual(result["post_deployment_status"], "PENDENTE")
        self.assertIn("Production Witness", result["post_deployment_note"])

    def test_all_four_planes_are_explicit(self):
        result = audit(allow_template_sealed_only=True)
        self.assertEqual(set(result["four_planes"]), {"policy_control", "scientific_data", "evidence", "audit"})
        ids = {x["id"] for x in result["checks"]}
        self.assertIn("PYTHON_RUNTIME", ids)
        self.assertIn("SCIENTIFIC_DATA_PLANE_ARRAY", ids)
        self.assertIn("EVIDENCE_ANNOTATION_PLANE", ids)
        self.assertIn("SUPPLY_CHAIN_LOCK", ids)
        self.assertIn("TEMPLATE_BINARY_SOURCE_STORE", ids)

    def test_run_captures_stdout_and_stderr_separately(self):
        rc, evidence = run(
            [
                sys.executable,
                "-c",
                "import sys; print('out-marker'); print('err-marker', file=sys.stderr); raise SystemExit(3)",
            ]
        )
        self.assertEqual(rc, 3)
        self.assertIn("STDOUT\nout-marker", evidence)
        self.assertIn("STDERR\nerr-marker", evidence)

    def test_run_timeout_is_fail_closed_and_preserves_partial_output(self):
        expired = subprocess.TimeoutExpired(
            cmd=["fixture"],
            timeout=1,
            output=b"partial-stdout",
            stderr=b"partial-stderr",
        )
        with patch("scripts.genoma_audit.subprocess.run", side_effect=expired):
            rc, evidence = run(["fixture"], timeout_seconds=1)
        self.assertEqual(rc, 124)
        self.assertIn("TIMEOUT after 1s", evidence)
        self.assertIn("partial-stdout", evidence)
        self.assertIn("partial-stderr", evidence)

    def test_multibyte_tail_decoding_is_robust_when_slice_starts_mid_character(self):
        raw = ("á" * 4000).encode("utf-8")
        decoded = _decode_tail(raw, limit=5999)
        self.assertTrue(decoded)
        self.assertLessEqual(len(decoded.encode("utf-8", errors="replace")), 6002)


if __name__ == "__main__":
    unittest.main()
