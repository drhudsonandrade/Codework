from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from scripts.genoma_audit import (
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
)


class _AuditBaseline:
    def __init__(self, runner=audit):
        self._runner = runner
        self._snapshot = None

    def report(self) -> dict:
        if self._snapshot is None:
            self._snapshot = self._runner(allow_template_sealed_only=True)
        return deepcopy(self._snapshot)


_BASELINE_AUDIT = _AuditBaseline()
_REPOSITORY_CONTRACT_PASS = CommandOutcome(
    launched=True,
    returncode=0,
    evidence="STDOUT\nPASS\trepository_contract\nSTDERR\n",
)


def _repository_contract_pass_run(cmd, **kwargs):
    if any(Path(str(part)).as_posix() == "scripts/validate_repo.py" for part in cmd):
        return _REPOSITORY_CONTRACT_PASS
    return run(cmd, **kwargs)


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


class AuditTestOptimizationContractTest(unittest.TestCase):
    def test_baseline_holder_runs_once_and_returns_isolated_copies(self):
        runner = mock.Mock(return_value={"checks": []})
        baseline = _AuditBaseline(runner)
        first = baseline.report()
        first["checks"].append({"id": "MUTATED"})
        second = baseline.report()
        runner.assert_called_once_with(allow_template_sealed_only=True)
        self.assertEqual(second, {"checks": []})
        self.assertIsNot(first, second)

    def test_repository_contract_pass_stub_delegates_every_other_command(self):
        delegated = CommandOutcome(launched=True, returncode=7, evidence="delegated")
        module = sys.modules[__name__]
        with mock.patch.object(module, "run", return_value=delegated) as runner:
            contract = _repository_contract_pass_run([sys.executable, "scripts/validate_repo.py"])
            other = _repository_contract_pass_run([sys.executable, "scripts/verify_supply_chain_lock.py"])
            lookalike = _repository_contract_pass_run([sys.executable, "scripts/validate_repo.py.bak"])
        self.assertEqual(contract.result, PASS)
        self.assertIs(other, delegated)
        self.assertIs(lookalike, delegated)
        self.assertEqual(
            runner.call_args_list,
            [
                mock.call([sys.executable, "scripts/verify_supply_chain_lock.py"]),
                mock.call([sys.executable, "scripts/validate_repo.py.bak"]),
            ],
        )


class GenomaAuditTest(unittest.TestCase):
    def test_audit_never_grants_post_deployment(self):
        result = _BASELINE_AUDIT.report()
        self.assertEqual(result["post_deployment_status"], "PENDENTE")
        self.assertIn("Production Witness", result["post_deployment_note"])

    def test_all_four_planes_are_explicit(self):
        result = _BASELINE_AUDIT.report()
        self.assertEqual(set(result["four_planes"]), {"policy_control", "scientific_data", "evidence", "audit"})
        ids = {x["id"] for x in result["checks"]}
        self.assertIn("PYTHON_RUNTIME", ids)
        self.assertIn("SCIENTIFIC_DATA_PLANE_ARRAY", ids)
        self.assertIn("EVIDENCE_ANNOTATION_PLANE", ids)
        self.assertIn("SUPPLY_CHAIN_LOCK", ids)
        self.assertIn("TEMPLATE_BINARY_SOURCE_STORE", ids)

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
        with mock.patch("scripts.genoma_audit.ruleset_check", return_value=failing), mock.patch(
            "scripts.genoma_audit.run", side_effect=_repository_contract_pass_run
        ):
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
        report = _BASELINE_AUDIT.report()
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
        report = _BASELINE_AUDIT.report()
        self.assertEqual(report["schema"], "genoma-v0.8-four-plane-audit-v2")
        self.assertIn(report["operational_status"], {EXECUTED, UNAVAILABLE})
        self.assertIn(report["result"], {PASS, FAIL, "ERROR"})

    def test_blocking_failures_are_derived_from_results_not_from_availability(self):
        report = _BASELINE_AUDIT.report()
        expected = [c["id"] for c in report["checks"] if c["blocking"] and c["result"] != PASS]
        self.assertEqual(report["blocking_failures"], expected)

    def test_grch38_unavailable_gate_is_fail_closed(self):
        with mock.patch(
            "scripts.genoma_audit._grch38_strategy_probe", side_effect=OSError("probe unreadable")
        ), mock.patch("scripts.genoma_audit.run", side_effect=_repository_contract_pass_run):
            report = audit(allow_template_sealed_only=True)
        gate = next(c for c in report["checks"] if c["id"] == "GRCH38_NO_PERMANENT_HIGHMEM_STRATEGY")
        self.assertEqual((gate["operational_status"], gate["result"]), (UNAVAILABLE, "ERROR"))
        self.assertTrue(gate["blocking"])
        self.assertIn("GRCH38_NO_PERMANENT_HIGHMEM_STRATEGY", report["unavailable_checks"])
        self.assertIn("GRCH38_NO_PERMANENT_HIGHMEM_STRATEGY", report["blocking_failures"])
        self.assertEqual(report["operational_status"], UNAVAILABLE)
        self.assertEqual(report["result"], "ERROR")
        self.assertEqual(report["four_planes"]["audit"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
