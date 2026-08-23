from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

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
        rc, evidence = run(
            [
                sys.executable,
                "-c",
                "import sys,time; print('partial-stdout', flush=True); print('partial-stderr', file=sys.stderr, flush=True); time.sleep(5)",
            ],
            timeout_seconds=0.25,
        )
        self.assertEqual(rc, 124)
        self.assertIn("TIMEOUT after 0.25s", evidence)
        self.assertIn("partial-stdout", evidence)
        self.assertIn("partial-stderr", evidence)

    @unittest.skipUnless(os.name == "posix" and Path("/proc").is_dir(), "requires POSIX /proc")
    def test_run_timeout_terminates_descendant_process_group_promptly(self):
        with tempfile.TemporaryDirectory() as td:
            pid_file = Path(td) / "child.pid"
            child = "import time; time.sleep(5)"
            parent = (
                "import pathlib,subprocess,sys,time; "
                f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
                f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
                "time.sleep(5)"
            )
            started = time.monotonic()
            rc, evidence = run([sys.executable, "-c", parent], timeout_seconds=0.25)
            elapsed = time.monotonic() - started
            self.assertEqual(rc, 124, evidence)
            self.assertLess(elapsed, 2.0, evidence)
            self.assertTrue(pid_file.is_file(), evidence)
            child_pid = int(pid_file.read_text())
            deadline = time.monotonic() + 1.0
            while Path(f"/proc/{child_pid}").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(Path(f"/proc/{child_pid}").exists(), f"descendant survived timeout: {child_pid}")

    def test_multibyte_tail_decoding_is_robust_when_slice_starts_mid_character(self):
        raw = ("á" * 4000).encode("utf-8")
        decoded = _decode_tail(raw, limit=5999)
        self.assertTrue(decoded)
        self.assertLessEqual(len(decoded.encode("utf-8", errors="replace")), 6002)


if __name__ == "__main__":
    unittest.main()
