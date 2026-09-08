#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sealed_ruleset import SealedRulesetError, verify_transport

ROOT = Path(__file__).resolve().parents[1]

SEALED_DIR = ROOT / "normative" / "sealed"
COMMAND_TIMEOUT_SECONDS = 180
PROCESS_TERMINATION_GRACE_SECONDS = 0.5
OUTPUT_TAIL_BYTES = 6000

# Two independent axes, never collapsed into one another.
# operational_status answers "did the check actually run?"
# result answers "what did the check conclude?"
EXECUTED = "EXECUTADO"
UNAVAILABLE = "NÃO DISPONÍVEL"
PASS = "PASS"
FAIL = "FAIL"
ERROR = "ERROR"


def _decode_tail(value: bytes | str | None, *, limit: int = OUTPUT_TAIL_BYTES) -> str:
    """Decode the bounded tail of subprocess output, replacing incomplete UTF-8 bytes."""
    if value is None:
        return ""
    raw = value.encode("utf-8", errors="replace") if isinstance(value, str) else value
    return raw[-limit:].decode("utf-8", errors="replace")


def _command_evidence(stdout: bytes | str | None, stderr: bytes | str | None) -> str:
    """Label and combine bounded stdout and stderr for the audit record."""
    return "STDOUT\n" + _decode_tail(stdout) + "\nSTDERR\n" + _decode_tail(stderr)


def _signal_process_tree(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    """Signal the running process group on POSIX or the direct process elsewhere."""
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except ProcessLookupError:
        return


def _finish_timed_out_process(
    process: subprocess.Popen[bytes],
    timeout_exc: subprocess.TimeoutExpired,
) -> tuple[bytes | str | None, bytes | str | None]:
    """Terminate a timed-out process, escalate if necessary, and recover its output."""
    stdout = timeout_exc.stdout
    stderr = timeout_exc.stderr
    _signal_process_tree(process, signal.SIGTERM)
    try:
        final_stdout, final_stderr = process.communicate(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired as term_exc:
        stdout = term_exc.stdout if term_exc.stdout is not None else stdout
        stderr = term_exc.stderr if term_exc.stderr is not None else stderr
        _signal_process_tree(process, signal.SIGKILL)
        final_stdout, final_stderr = process.communicate()
    if final_stdout is not None:
        stdout = final_stdout
    if final_stderr is not None:
        stderr = final_stderr
    return stdout, stderr


@dataclass(frozen=True)
class CommandOutcome:
    """Outcome of one audited subprocess, keeping execution and result separate.

    ``launched`` records whether the operating system actually started the process.
    A process that started and exited non-zero is EXECUTADO/FAIL: it ran, it failed.
    Only a process that could never start (missing executable, permission denied,
    resource exhaustion) is NÃO DISPONÍVEL/ERROR.
    """

    launched: bool
    returncode: int | None
    evidence: str
    timed_out: bool = False
    exception_type: str | None = None
    exception_message: str | None = None

    @property
    def operational_status(self) -> str:
        return EXECUTED if self.launched else UNAVAILABLE

    @property
    def result(self) -> str:
        if not self.launched:
            return ERROR
        return PASS if self.returncode == 0 else FAIL

    @property
    def succeeded(self) -> bool:
        return self.launched and self.returncode == 0


def run(cmd: list[str], *, timeout_seconds: float = COMMAND_TIMEOUT_SECONDS) -> CommandOutcome:
    """Run an audit command with a timeout and distinguish launch failure from execution failure."""
    try:
        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        # The tool is genuinely unavailable: nothing ever executed.
        return CommandOutcome(
            launched=False,
            returncode=None,
            evidence=f"LAUNCH FAILED\n{type(exc).__name__}: {exc}\ncommand: {cmd}",
            exception_type=type(exc).__name__,
            exception_message=str(exc),
        )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = _finish_timed_out_process(process, exc)
        evidence = _command_evidence(stdout, stderr)
        # The process ran; it simply did not finish in time. That is a failure, not
        # an unavailability.
        return CommandOutcome(
            launched=True,
            returncode=124,
            evidence=f"TIMEOUT after {timeout_seconds}s\n{evidence}",
            timed_out=True,
            exception_type=type(exc).__name__,
            exception_message=f"timed out after {timeout_seconds}s",
        )
    return CommandOutcome(
        launched=True,
        returncode=process.returncode,
        evidence=_command_evidence(stdout, stderr),
    )


def _python_runtime_evidence() -> tuple[bool, str]:
    """Describe the active Python executable and whether it exists as a file."""
    executable = Path(sys.executable) if sys.executable else Path()
    payload = {
        "python_executable": sys.executable,
        "python_prefix": sys.prefix,
        "python_base_prefix": sys.base_prefix,
        "virtualenv_active": bool(os.environ.get("VIRTUAL_ENV")) or sys.prefix != sys.base_prefix,
    }
    return (
        bool(sys.executable) and executable.is_file(),
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


def _check(
    name: str,
    operational_status: str,
    result: str,
    evidence: str,
    *,
    blocking: bool = True,
    exception_type: str | None = None,
    exception_message: str | None = None,
) -> dict:
    """Build an audit check while keeping operational status and result independent."""
    payload = {
        "id": name,
        "operational_status": operational_status,
        "result": result,
        "blocking": blocking,
        "evidence": evidence,
    }
    if exception_type is not None:
        payload["exception_type"] = exception_type
    if exception_message is not None:
        payload["exception_message"] = exception_message
    return payload


def command_check(
    name: str,
    outcome: CommandOutcome,
    *,
    blocking: bool = True,
    assertion: bool | None = None,
) -> dict:
    """Build a check from a subprocess outcome.

    ``assertion`` lets a caller add a content requirement on top of the exit code:
    a command that exited 0 but whose output does not prove what the check needs is
    still EXECUTADO, and its result is FAIL — never NÃO DISPONÍVEL.
    """
    result = outcome.result
    if result == PASS and assertion is False:
        result = FAIL
    return _check(
        name,
        outcome.operational_status,
        result,
        outcome.evidence,
        blocking=blocking,
        exception_type=outcome.exception_type,
        exception_message=outcome.exception_message,
    )


def inspection_check(name: str, probe, *, blocking: bool = True) -> dict:
    """Build a check from an in-process probe returning ``(ok, evidence)``.

    The inspection itself is EXECUTADO whenever it completes. If the probe cannot
    run at all (unreadable path, decoding failure) the check is NÃO DISPONÍVEL/ERROR
    and carries the exception, rather than being reported as a plain FAIL.
    """
    try:
        ok, evidence = probe()
    except (OSError, UnicodeError, ValueError) as exc:
        return _check(
            name,
            UNAVAILABLE,
            ERROR,
            f"INSPECTION FAILED\n{type(exc).__name__}: {exc}",
            blocking=blocking,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
        )
    return _check(name, EXECUTED, PASS if ok else FAIL, evidence, blocking=blocking)


def ruleset_check(sealed_dir: Path = SEALED_DIR) -> tuple[dict, dict]:
    """Verify the sealed canonical ruleset and derive its identity from that result.

    Returns ``(check, ruleset_block)``. Identity fields are populated only from the
    verified artifact: when verification fails the block reports no version, no date
    and no VERIFICADO, so the audit can never declare a ruleset it did not verify.
    """
    try:
        evidence = verify_transport(sealed_dir)
    except SealedRulesetError as exc:
        check = _check(
            "RULESET_SEALED_IDENTITY",
            EXECUTED,
            FAIL,
            f"sealed ruleset verification failed\n{type(exc).__name__}: {exc}",
            exception_type=type(exc).__name__,
            exception_message=str(exc),
        )
    except (OSError, UnicodeError) as exc:
        check = _check(
            "RULESET_SEALED_IDENTITY",
            UNAVAILABLE,
            ERROR,
            f"sealed ruleset transport unreadable\n{type(exc).__name__}: {exc}",
            exception_type=type(exc).__name__,
            exception_message=str(exc),
        )
    else:
        check = _check(
            "RULESET_SEALED_IDENTITY",
            EXECUTED,
            PASS,
            json.dumps(evidence, ensure_ascii=False, sort_keys=True),
        )
        return check, {
            "operational_status": EXECUTED,
            "result": PASS,
            "status": evidence["status"],
            "version": evidence["version"],
            "effective_date": evidence["effective_date"],
            "canonical_filename": evidence["canonical_filename"],
            "sha256": evidence["raw_sha256"],
            "identity_source": str(Path(sealed_dir).relative_to(ROOT) / "MANIFEST.json")
            if Path(sealed_dir).is_relative_to(ROOT)
            else str(Path(sealed_dir) / "MANIFEST.json"),
        }

    return check, {
        "operational_status": check["operational_status"],
        "result": check["result"],
        "status": None,
        "version": None,
        "effective_date": None,
        "canonical_filename": None,
        "sha256": None,
        "identity_source": None,
        "note": "Ruleset identity is unproven at this SHA; no normative version is claimed.",
    }


def _plane(checks: list[dict], ids: set[str]) -> str:
    """Require a nonempty selection of passing checks before marking a plane as passing."""
    selected = [c for c in checks if c["id"] in ids]
    return "PASS" if selected and all(c["result"] == PASS for c in selected) else "BLOCKED"


def _array_data_plane_probe() -> tuple[bool, str]:
    """Check that the required array implementation and workflow files exist."""
    required_array = [
        ROOT / "workflows/array.nf",
        ROOT / "array_pipeline/qc.py",
        ROOT / "array_pipeline/annotation.py",
        ROOT / "array_pipeline/targets.py",
        ROOT / "config/partial_genome_annotation_targets.json",
        ROOT / ".github/workflows/genoma-snp-array.yml",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required_array if not p.is_file()]
    evidence = ", ".join(str(p.relative_to(ROOT)) for p in required_array)
    if missing:
        evidence = f"missing: {json.dumps(missing, ensure_ascii=False)}\nrequired: {evidence}"
    return not missing, evidence


def _evidence_plane_probe() -> tuple[bool, str]:
    """Check that the adapter source declares every required evidence provider."""
    adapters = (ROOT / "evidence_adapters/__init__.py").read_text(encoding="utf-8")
    evidence_sources = ["clinvar", "clingen", "cpic", "clinpgx", "gnomad", "pgs_catalog"]
    missing = [x for x in evidence_sources if f'"{x}"' not in adapters]
    evidence = "official/primary adapter registry: " + ", ".join(evidence_sources)
    if missing:
        evidence = f"missing adapters: {json.dumps(missing, ensure_ascii=False)}\n{evidence}"
    return not missing, evidence


def _grch38_strategy_probe() -> tuple[bool, str]:
    """Check that the reference strategy document and bundle verifier exist."""
    prebuilt = ROOT / "scripts/verify_prebuilt_bwa_mem2_bundle.py"
    strategy = ROOT / "docs/GRCH38_COMPUTE_STRATEGY.md"
    return prebuilt.is_file() and strategy.is_file(), (
        "prebuilt checksum-locked index verifier + explicit ephemeral/self-hosted fallback"
    )


def _personal_fixtures_probe() -> tuple[bool, str]:
    """List local file paths matching the configured personal-data name patterns."""
    personal_patterns = ("dados dna", "dna_harmonizado", "myheritage_raw", "genera_raw")
    tracked_like = []
    for p in ROOT.rglob("*"):
        if p.is_file():
            low = str(p.relative_to(ROOT)).lower().replace("_", " ").replace("-", " ")
            if any(x in low for x in personal_patterns):
                tracked_like.append(str(p.relative_to(ROOT)))
    return not tracked_like, json.dumps(tracked_like, ensure_ascii=False)


def audit(*, allow_template_sealed_only: bool = False) -> dict:
    """Collect checks and plane results without granting post-deployment approval."""
    checks: list[dict] = []

    checks.append(inspection_check("PYTHON_RUNTIME", _python_runtime_evidence))

    ruleset_gate, ruleset_block = ruleset_check()
    checks.append(ruleset_gate)

    checks.append(command_check("REPOSITORY_CONTRACT", run(
        [sys.executable, "scripts/validate_repo.py"])))
    checks.append(command_check("SUPPLY_CHAIN_LOCK", run(
        [sys.executable, "scripts/verify_supply_chain_lock.py"])))

    cmd = [sys.executable, "scripts/verify_template_store.py"]
    if allow_template_sealed_only:
        cmd.append("--allow-sealed-only")
    template = run(cmd)
    checks.append(
        command_check(
            "TEMPLATE_IDENTITY_CONTRACT",
            template,
            assertion='"manifest_identity": "VERIFICADO"' in template.evidence,
        )
    )
    checks.append(
        command_check(
            "TEMPLATE_BINARY_SOURCE_STORE",
            template,
            blocking=not allow_template_sealed_only,
            assertion='"binary_materialization": "VERIFICADO"' in template.evidence,
        )
    )

    checks.append(inspection_check("SCIENTIFIC_DATA_PLANE_ARRAY", _array_data_plane_probe))
    checks.append(inspection_check("EVIDENCE_ANNOTATION_PLANE", _evidence_plane_probe))
    # The GRCh38 runtime/reference strategy is a mandatory safety gate: if it cannot
    # execute or prove the configured strategy, the audit must not report PASS.
    checks.append(inspection_check("GRCH38_NO_PERMANENT_HIGHMEM_STRATEGY", _grch38_strategy_probe))
    checks.append(inspection_check("NO_PERSONAL_GENOTYPE_FIXTURES", _personal_fixtures_probe))

    planes = {
        "policy_control": _plane(
            checks,
            {
                "PYTHON_RUNTIME",
                "RULESET_SEALED_IDENTITY",
                "REPOSITORY_CONTRACT",
                "SUPPLY_CHAIN_LOCK",
            },
        ),
        "scientific_data": _plane(checks, {"SCIENTIFIC_DATA_PLANE_ARRAY"}),
        "evidence": _plane(checks, {"EVIDENCE_ANNOTATION_PLANE"}),
        "audit": "PASS" if all(c["result"] == PASS for c in checks if c["blocking"]) else "BLOCKED",
    }
    blocking_failures = [c["id"] for c in checks if c["blocking"] and c["result"] != PASS]
    unavailable = [c["id"] for c in checks if c["operational_status"] == UNAVAILABLE]
    blocking_unavailable = [
        c["id"] for c in checks if c["blocking"] and c["operational_status"] == UNAVAILABLE
    ]

    # The normative gate binds the ruleset block to the checks that prove it. A failing
    # or unverifiable ruleset blocks the audit instead of being reported as VIGENTE.
    ruleset_block = dict(ruleset_block)
    ruleset_block["normative_gate"] = (
        "PASS"
        if ruleset_gate["result"] == PASS and "REPOSITORY_CONTRACT" not in blocking_failures
        else "BLOCKED"
    )

    return {
        "schema": "genoma-v0.8-four-plane-audit-v2",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ruleset": ruleset_block,
        "operational_status": UNAVAILABLE if unavailable else EXECUTED,
        "result": PASS if not blocking_failures else (ERROR if blocking_unavailable else FAIL),
        "four_planes": planes,
        "checks": checks,
        "blocking_failures": blocking_failures,
        "unavailable_checks": unavailable,
        "post_deployment_status": "PENDENTE",
        "post_deployment_note": (
            "This audit never grants POST-DEPLOYMENT PASS. Only the independent live "
            "Production Witness on the exact merged main SHA may do so."
        ),
    }


def main() -> int:
    """Write and print the audit result, returning a nonzero code for a blocking outcome."""
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="audit.json")
    p.add_argument("--allow-template-sealed-only", action="store_true")
    args = p.parse_args()
    payload = audit(allow_template_sealed_only=args.allow_template_sealed_only)
    Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    # Exit status follows the blocking result axis; availability is reported independently.
    return 0 if payload["result"] == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
