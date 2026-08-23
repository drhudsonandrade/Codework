from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts.genoma_audit import (
    ERROR,
    EXECUTED,
    FAIL,
    PASS,
    UNAVAILABLE,
    CommandOutcome,
    _decode_tail,
    audit,
    command_check,
    inspection_check,
    ruleset_check,
    run,
    template_binary_source_check,
)


def _process_is_running(pid: int) -> bool:
    """True only while the process is still executing.

    A terminated descendant stays visible under /proc as a zombie until it is reaped.
    Containers without a reaping init (CI job containers among them) never reap it, so
    presence of the directory alone would report a killed process as still alive.
    """
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False
    for line in status.splitlines():
        if line.startswith("State:"):
            return not line.split(":", 1)[1].strip().startswith(("Z", "X"))
    return True


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

    def test_absent_template_source_is_unavailable_not_a_failed_conclusion(self):
        """An unsent one-shot transport is NÃO DISPONÍVEL, never a FAIL verdict.

        Under --allow-sealed-only the tool exits 0 and states that the sealed
        parts are absent. Reporting that as FAIL claims the audit concluded
        something is wrong with the template source, when in truth it never had
        one to inspect.
        """
        outcome = CommandOutcome(
            launched=True,
            returncode=0,
            evidence="STDOUT\n...\nSTDERR\n",
            stdout_text=json.dumps(
                {
                    "binary_materialization": UNAVAILABLE,
                    "manifest_identity": "VERIFICADO",
                    "missing_parts": [f"tplpart-{i:03d}" for i in range(48)],
                    "reason": "binary source parts are not materialized in this checkout.",
                },
                ensure_ascii=False,
            ),
        )
        check = template_binary_source_check(outcome, blocking=False)
        self.assertEqual(check["operational_status"], UNAVAILABLE)
        self.assertEqual(check["result"], ERROR)
        self.assertIn("48 sealed part(s) absent", check["evidence"])

    def test_corrupted_template_source_stays_a_blocking_failure(self):
        """Tampering must stay louder than absence, not collapse into the same verdict."""
        outcome = CommandOutcome(
            launched=True,
            returncode=2,
            evidence="STDOUT\nNÃO DISPONÍVEL: ValueError: sealed template part integrity failure: ['tplpart-007']\nSTDERR\n",
            stdout_text="NÃO DISPONÍVEL: ValueError: sealed template part integrity failure: ['tplpart-007']",
        )
        check = template_binary_source_check(outcome, blocking=True)
        self.assertEqual(check["operational_status"], EXECUTED)
        self.assertEqual(check["result"], FAIL)
        self.assertTrue(check["blocking"])

    def test_absent_and_corrupted_template_sources_are_distinguishable(self):
        """The regression itself: both used to produce EXECUTADO/FAIL."""
        absent = template_binary_source_check(
            CommandOutcome(
                launched=True,
                returncode=0,
                evidence="STDOUT\n...\nSTDERR\n",
                stdout_text=json.dumps({"binary_materialization": UNAVAILABLE}, ensure_ascii=False),
            ),
            blocking=False,
        )
        corrupted = template_binary_source_check(
            CommandOutcome(launched=True, returncode=2, evidence="STDOUT\nintegrity failure\nSTDERR\n"),
            blocking=True,
        )
        self.assertNotEqual(
            (absent["operational_status"], absent["result"]),
            (corrupted["operational_status"], corrupted["result"]),
        )

    def test_materialized_template_source_passes(self):
        outcome = CommandOutcome(
            launched=True,
            returncode=0,
            evidence="STDOUT\n...\nSTDERR\n",
            stdout_text=json.dumps(
                {"binary_materialization": "VERIFICADO", "reports": 11, "parts": 48}, ensure_ascii=False
            ),
        )
        check = template_binary_source_check(outcome, blocking=True)
        self.assertEqual(check["operational_status"], EXECUTED)
        self.assertEqual(check["result"], PASS)

    def test_exit_zero_without_a_recognised_verdict_fails_closed(self):
        """Silence is not unavailability and is certainly not success."""
        for stdout_text in ("", "ok", '{"binary_materialization": "TALVEZ"}', "{not json"):
            with self.subTest(stdout=stdout_text):
                check = template_binary_source_check(
                    CommandOutcome(
                        launched=True, returncode=0, evidence="STDOUT\n\nSTDERR\n", stdout_text=stdout_text
                    ),
                    blocking=True,
                )
                self.assertEqual(check["operational_status"], EXECUTED)
                self.assertEqual(check["result"], FAIL)

    def test_a_template_tool_that_never_launched_is_unavailable(self):
        check = template_binary_source_check(
            CommandOutcome(launched=False, returncode=None, evidence="LAUNCH FAILED", exception_type="OSError"),
            blocking=True,
        )
        self.assertEqual(check["operational_status"], UNAVAILABLE)
        self.assertEqual(check["result"], ERROR)

    def test_run_captures_stdout_and_stderr_separately(self):
        outcome = run(
            [
                sys.executable,
                "-c",
                "import sys; print('out-marker'); print('err-marker', file=sys.stderr); raise SystemExit(3)",
            ]
        )
        self.assertEqual(outcome.returncode, 3)
        self.assertIn("STDOUT\nout-marker", outcome.evidence)
        self.assertIn("STDERR\nerr-marker", outcome.evidence)

    def test_run_timeout_is_fail_closed_and_preserves_partial_output(self):
        outcome = run(
            [
                sys.executable,
                "-c",
                "import sys,time; print('partial-stdout', flush=True); print('partial-stderr', file=sys.stderr, flush=True); time.sleep(5)",
            ],
            timeout_seconds=1.0,
        )
        self.assertEqual(outcome.returncode, 124)
        self.assertIn("TIMEOUT after 1.0s", outcome.evidence)
        self.assertIn("partial-stdout", outcome.evidence)
        self.assertIn("partial-stderr", outcome.evidence)

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
            outcome = run([sys.executable, "-c", parent], timeout_seconds=1.0)
            evidence = outcome.evidence
            elapsed = time.monotonic() - started
            self.assertEqual(outcome.returncode, 124, evidence)
            self.assertLess(elapsed, 3.0, evidence)
            self.assertTrue(pid_file.is_file(), evidence)
            child_pid = int(pid_file.read_text())
            deadline = time.monotonic() + 1.0
            while _process_is_running(child_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(_process_is_running(child_pid), f"descendant survived timeout: {child_pid}")

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX-only")
    def test_run_timeout_kills_descendants_when_the_leader_already_exited(self):
        """The leader exiting first must not spare the tree it left holding the pipes.

        This is the case a leader-alive check cannot see: by the time the timeout
        fires, ``process.poll()`` already reports 0, yet the descendant is still
        running with the inherited stdout/stderr that keep ``communicate()``
        blocked. Cleanup has to signal the group regardless of the leader.
        """
        with tempfile.TemporaryDirectory() as td:
            pid_file = Path(td) / "orphan.pid"
            # The descendant inherits this process's pipes and outlives the budget.
            child = "import time; time.sleep(30)"
            parent = (
                "import pathlib,subprocess,sys; "
                f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
                f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
                "sys.exit(0)"
            )
            started = time.monotonic()
            outcome = run([sys.executable, "-c", parent], timeout_seconds=1.0)
            elapsed = time.monotonic() - started
            evidence = outcome.evidence

            self.assertTrue(outcome.timed_out, evidence)
            self.assertEqual(outcome.returncode, 124, evidence)
            self.assertLess(elapsed, 5.0, f"cleanup overran its budget: {elapsed}s\n{evidence}")
            self.assertTrue(pid_file.is_file(), evidence)

            child_pid = int(pid_file.read_text())
            deadline = time.monotonic() + 2.0
            while _process_is_running(child_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(
                _process_is_running(child_pid),
                f"orphaned descendant survived the timeout: {child_pid}\n{evidence}",
            )

    def test_multibyte_tail_decoding_is_robust_when_slice_starts_mid_character(self):
        raw = ("á" * 4000).encode("utf-8")
        decoded = _decode_tail(raw, limit=5999)
        self.assertTrue(decoded)
        self.assertLessEqual(len(decoded.encode("utf-8", errors="replace")), 6002)


class ExecutionVersusResultTest(unittest.TestCase):
    """A command that ran and failed is EXECUTADO/FAIL, never NÃO DISPONÍVEL."""

    def test_exit_zero_is_executed_and_pass(self):
        outcome = run([sys.executable, "-c", "raise SystemExit(0)"])
        self.assertTrue(outcome.launched)
        self.assertEqual(outcome.operational_status, EXECUTED)
        self.assertEqual(outcome.result, PASS)
        check = command_check("SAMPLE", outcome)
        self.assertEqual((check["operational_status"], check["result"]), (EXECUTED, PASS))

    def test_nonzero_exit_is_executed_and_fail(self):
        outcome = run([sys.executable, "-c", "raise SystemExit(1)"])
        self.assertTrue(outcome.launched)
        self.assertEqual(outcome.operational_status, EXECUTED)
        self.assertEqual(outcome.result, FAIL)
        check = command_check("SAMPLE", outcome)
        self.assertEqual((check["operational_status"], check["result"]), (EXECUTED, FAIL))
        self.assertNotEqual(check["operational_status"], UNAVAILABLE)

    def test_missing_executable_is_unavailable_and_error(self):
        outcome = run([str(Path(tempfile.gettempdir()) / "genoma-nonexistent-binary-xyz")])
        self.assertFalse(outcome.launched)
        self.assertIsNone(outcome.returncode)
        self.assertEqual(outcome.operational_status, UNAVAILABLE)
        self.assertEqual(outcome.result, "ERROR")
        check = command_check("SAMPLE", outcome)
        self.assertEqual(check["exception_type"], "FileNotFoundError")
        self.assertTrue(check["exception_message"])

    def test_oserror_on_launch_is_unavailable_and_error(self):
        with mock.patch("scripts.genoma_audit.subprocess.Popen", side_effect=OSError("no fork available")):
            outcome = run([sys.executable, "-c", "pass"])
        self.assertFalse(outcome.launched)
        self.assertEqual(outcome.operational_status, UNAVAILABLE)
        self.assertEqual(outcome.result, "ERROR")
        self.assertEqual(outcome.exception_type, "OSError")

    def test_timeout_ran_so_it_is_executed_and_fail(self):
        outcome = run([sys.executable, "-c", "import time; time.sleep(5)"], timeout_seconds=1.0)
        self.assertTrue(outcome.launched)
        self.assertTrue(outcome.timed_out)
        self.assertEqual(outcome.operational_status, EXECUTED)
        self.assertEqual(outcome.result, FAIL)

    def test_failed_content_assertion_on_a_successful_command_is_fail_not_unavailable(self):
        outcome = CommandOutcome(launched=True, returncode=0, evidence="no marker here")
        check = command_check("SAMPLE", outcome, assertion=False)
        self.assertEqual((check["operational_status"], check["result"]), (EXECUTED, FAIL))

    def test_inspection_that_cannot_run_is_unavailable_and_error(self):
        def probe():
            raise OSError("unreadable surface")

        check = inspection_check("SAMPLE", probe)
        self.assertEqual((check["operational_status"], check["result"]), (UNAVAILABLE, "ERROR"))
        self.assertEqual(check["exception_type"], "OSError")

    def test_inspection_that_runs_and_concludes_false_is_executed_and_fail(self):
        check = inspection_check("SAMPLE", lambda: (False, "missing artifact"))
        self.assertEqual((check["operational_status"], check["result"]), (EXECUTED, FAIL))
        self.assertNotIn("exception_type", check)


class RulesetProvenanceTest(unittest.TestCase):
    """The ruleset block is derived from the validator, never asserted."""

    def test_verified_ruleset_reports_identity_from_the_sealed_artifact(self):
        check, block = ruleset_check()
        self.assertEqual(check["result"], PASS)
        self.assertEqual(block["status"], "VIGENTE")
        self.assertEqual(block["version"], "v3.4")
        self.assertEqual(block["effective_date"], "17/08/2026")
        self.assertEqual(block["identity_source"], "normative/sealed/MANIFEST.json")

    def test_unverifiable_ruleset_claims_no_version_and_no_verified_status(self):
        with tempfile.TemporaryDirectory() as td:
            check, block = ruleset_check(Path(td))
        self.assertNotEqual(check["result"], PASS)
        self.assertIsNone(block["status"])
        self.assertIsNone(block["version"])
        self.assertIsNone(block["effective_date"])
        self.assertIsNone(block["sha256"])
        self.assertNotIn("VERIFICADO", str(block))

    def test_failing_ruleset_gate_blocks_the_audit_and_the_normative_gate(self):
        failing = (
            {"id": "RULESET_SEALED_IDENTITY", "operational_status": EXECUTED, "result": FAIL, "blocking": True, "evidence": "x"},
            {"operational_status": EXECUTED, "result": FAIL, "status": None, "version": None,
             "effective_date": None, "canonical_filename": None, "sha256": None, "identity_source": None},
        )
        with mock.patch("scripts.genoma_audit.ruleset_check", return_value=failing):
            report = audit(allow_template_sealed_only=True)
        self.assertEqual(report["ruleset"]["normative_gate"], "BLOCKED")
        self.assertIn("RULESET_SEALED_IDENTITY", report["blocking_failures"])
        self.assertEqual(report["four_planes"]["policy_control"], "BLOCKED")
        self.assertEqual(report["four_planes"]["audit"], "BLOCKED")
        self.assertNotEqual(report["result"], PASS)
        self.assertIsNone(report["ruleset"]["version"])

    def test_failing_repository_contract_blocks_the_normative_gate(self):
        unavailable = CommandOutcome(
            launched=False, returncode=None, evidence="boom",
            exception_type="FileNotFoundError", exception_message="boom",
        )

        real_run = run

        def fake_run(cmd, **kwargs):
            if any("validate_repo.py" in str(part) for part in cmd):
                return unavailable
            return real_run(cmd, **kwargs)

        with mock.patch("scripts.genoma_audit.run", side_effect=fake_run):
            report = audit(allow_template_sealed_only=True)
        self.assertEqual(report["ruleset"]["normative_gate"], "BLOCKED")
        self.assertIn("REPOSITORY_CONTRACT", report["unavailable_checks"])
        self.assertEqual(report["operational_status"], UNAVAILABLE)
        self.assertEqual(report["result"], "ERROR")


class ReportContractTest(unittest.TestCase):
    def test_every_check_carries_both_axes_independently(self):
        report = audit(allow_template_sealed_only=True)
        for check in report["checks"]:
            self.assertIn(check["operational_status"], {EXECUTED, UNAVAILABLE}, check["id"])
            self.assertIn(check["result"], {PASS, FAIL, "ERROR"}, check["id"])
            # The two axes are independent: only a check that never ran may be ERROR.
            if check["result"] == "ERROR":
                self.assertEqual(check["operational_status"], UNAVAILABLE, check["id"])
            if check["operational_status"] == UNAVAILABLE:
                self.assertEqual(check["result"], "ERROR", check["id"])
            self.assertNotIn("state", check, check["id"])

    def test_report_declares_the_two_axis_schema(self):
        report = audit(allow_template_sealed_only=True)
        self.assertEqual(report["schema"], "genoma-v0.8-four-plane-audit-v2")
        self.assertIn(report["operational_status"], {EXECUTED, UNAVAILABLE})
        self.assertIn(report["result"], {PASS, FAIL, "ERROR"})

    def test_blocking_failures_are_derived_from_results_not_from_availability(self):
        report = audit(allow_template_sealed_only=True)
        expected = [c["id"] for c in report["checks"] if c["blocking"] and c["result"] != PASS]
        self.assertEqual(report["blocking_failures"], expected)


if __name__ == "__main__":
    unittest.main()
