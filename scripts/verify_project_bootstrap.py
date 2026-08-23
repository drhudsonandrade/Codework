#!/usr/bin/env python3
"""Deterministic verifier for the GENOMA v3.4 project-bootstrap attestation.

The attestation used to record ``method`` as prose — "direct verification of the
active project instructions supplied to this session". A consumer could check the
file's digest and its declared identity, but had no way to reproduce the act of
verification: no verifier command, no input digests, no result locator. Under the
project's own contract a textual claim is not technical evidence, so a status of
VERIFICADO rested on nothing a third party could re-derive.

This module derives every declared check by executing it against repository
artifacts, and emits the attestation from those results. Re-running

    python3 scripts/verify_project_bootstrap.py --check

re-derives each check and compares the regenerated document byte for byte with
the committed one, so the attestation is reproducible rather than asserted.

Every input is repository-resident: the sealed normative transport and the policy
schema. Nothing here consults a session, a network or a materialized runtime path,
which is what lets the same command produce the same bytes on any checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from policy_engine.genoma_policy.engine import PolicyEngine
from policy_engine.genoma_policy.ruleset import load_ruleset
from policy_engine.genoma_policy.scaffold import scaffold_manifest
from policy_engine.genoma_policy.version import __version__ as POLICY_ENGINE_VERSION
from scripts.sealed_ruleset import SealedRulesetError, materialize, verify_transport

SEALED_DIR = ROOT / "normative" / "sealed"
SEALED_MANIFEST = SEALED_DIR / "MANIFEST.json"
SCHEMA = ROOT / "policy_engine" / "policy" / "schema" / "execution-manifest.schema.json"
ATTESTATION = ROOT / "deploy" / "attestations" / "bootstrap-project-v3.4.json"

VERIFIER_NAME = "genoma-project-bootstrap-verifier"
VERIFIER_COMMAND = "python3 scripts/verify_project_bootstrap.py --check"
RESULT_LOCATOR = "deploy/attestations/bootstrap-project-v3.4.json#/checks"

EXPECTED_STATUS = "VIGENTE"
EXPECTED_VERSION = "v3.4"
EXPECTED_DATE = "17/08/2026"
EXPECTED_CANONICAL = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_SHA256 = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
OPERATIONAL_STATUS_CONTRACT = ["EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO", "NÃO DISPONÍVEL"]


class BootstrapVerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gate(report, name: str):
    return next(gate for gate in report.gates if gate.gate == name)


def _analysis_manifest(engine: PolicyEngine, ruleset) -> dict[str, Any]:
    """A manifest that satisfies every gate, so one probe changes one thing."""
    manifest = scaffold_manifest(ruleset, case_id="BOOTSTRAP-VERIFY")
    manifest["session_id"] = "bootstrap-verify"
    manifest["inputs"] = [{"id": "probe", "kind": "vcf", "source": "verifier", "sha256": "probe"}]
    manifest["consent"] = {"verified": True, "version": "verifier", "authorized_domains": ["research"]}
    manifest["qc"] = {"status": "EXECUTADO", "passed": True, "evidence_refs": ["verifier:qc"]}
    manifest["sources"] = [
        {
            "id": "verifier:attestation",
            "mutable": False,
            "status": "VERIFICADO",
            "accessible": True,
            "locator": "fixture://attestation",
            "retrieval_evidence": {"method": "fixture", "result_digest": "sha256:fixture"},
        }
    ]
    for attestation in manifest["section_attestations"]:
        attestation.update(
            {
                "applicability": "NOT_APPLICABLE",
                "status": "VERIFICADO",
                "decision": "NOT_APPLICABLE",
                "justification": "not triggered by this verification probe",
                "evidence_refs": [],
            }
        )
        attestation["trace"].update({"run_id": "bootstrap-verify", "created_at": "2026-08-22T18:46:00-03:00"})
    return manifest


def _derive_consult_ruleset(engine: PolicyEngine, ruleset) -> bool:
    """An analysis-relevant operation must not proceed on a divergent ruleset."""
    manifest = _analysis_manifest(engine, ruleset)
    manifest["ruleset"]["sha256"] = "0" * 64
    return _gate(engine.evaluate(manifest), "RULESET_GATE").state.value == "FAIL"


def _derive_runtime_resource_gate(engine: PolicyEngine, ruleset) -> bool:
    """Real calling must be blocked until the runtime gate ran for this session."""
    manifest = _analysis_manifest(engine, ruleset)
    manifest["operation"]["requires_real_calling"] = True
    manifest["runtime_resource_gate"] = {"session_id": "bootstrap-verify", "checks": {}}
    return _gate(engine.evaluate(manifest), "RUNTIME_RESOURCE_GATE").state.value == "FAIL"


def _derive_post_deployment_threshold(engine: PolicyEngine, ruleset) -> bool:
    """PASS requires a live 15/15 with zero critical failures, and nothing less."""
    satisfied = {
        "single_active_ruleset": True,
        "bootstrap_installed": True,
        "live_smoke_passed": True,
        "live_smoke_count": 15,
        "critical_failures": 0,
        "identity_recovered": f"{EXPECTED_VERSION}/{EXPECTED_STATUS}/{EXPECTED_DATE}",
    }
    manifest = _analysis_manifest(engine, ruleset)
    manifest["post_deployment"] = dict(satisfied)
    if _gate(engine.evaluate(manifest), "POST_DEPLOYMENT_GATE").state.value != "PASS":
        return False
    for weakened in ({"live_smoke_count": 14}, {"critical_failures": 1}, {"live_smoke_passed": False}):
        manifest = _analysis_manifest(engine, ruleset)
        manifest["post_deployment"] = {**satisfied, **weakened}
        if _gate(engine.evaluate(manifest), "POST_DEPLOYMENT_GATE").state.value == "PASS":
            return False
    return True


def _derive_fail_closed_on_conflict() -> bool:
    """Activation beside a second VIGENTE must raise, not pick a winner."""
    with tempfile.TemporaryDirectory() as td:
        destination = Path(td)
        (destination / "REGRAS_PROJETO_GENOMA_INTRUDER.txt").write_text(
            "STATUS NORMATIVO: VIGENTE\n", encoding="utf-8"
        )
        try:
            materialize(SEALED_DIR, destination)
        except SealedRulesetError:
            return True
        return False


def _derive_operational_status_contract() -> bool:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return schema.get("$defs", {}).get("operationalStatus", {}).get("enum") == OPERATIONAL_STATUS_CONTRACT


def derive_checks() -> dict[str, bool]:
    """Execute every declared check and return what was actually observed."""
    evidence = verify_transport(SEALED_DIR)
    with tempfile.TemporaryDirectory() as td:
        target, _ = materialize(SEALED_DIR, Path(td))
        ruleset = load_ruleset(target)
        engine = PolicyEngine(ruleset)
        probes: dict[str, Callable[[], bool]] = {
            "consult_ruleset_before_relevant_genetic_analysis": lambda: _derive_consult_ruleset(engine, ruleset),
            "require_status_vigente": lambda: evidence["status"] == EXPECTED_STATUS,
            "require_version_v3_4": lambda: evidence["version"] == EXPECTED_VERSION,
            "require_effective_date_2026_08_17": lambda: evidence["effective_date"] == EXPECTED_DATE,
            "fail_closed_on_missing_or_conflicting_ruleset": _derive_fail_closed_on_conflict,
            "runtime_resource_gate_before_real_calling": lambda: _derive_runtime_resource_gate(engine, ruleset),
            "operational_status_contract_present": _derive_operational_status_contract,
            "post_deployment_requires_live_15_of_15_zero_critical": lambda: _derive_post_deployment_threshold(
                engine, ruleset
            ),
        }
        return {name: bool(probe()) for name, probe in probes.items()}


def build_attestation(*, verified_at: str) -> dict[str, Any]:
    """Assemble the attestation from freshly derived results and input digests."""
    evidence = verify_transport(SEALED_DIR)
    if evidence["canonical_filename"] != EXPECTED_CANONICAL or evidence["raw_sha256"] != EXPECTED_SHA256:
        raise BootstrapVerificationError(
            "sealed transport identity does not match the attested canonical ruleset"
        )
    checks = derive_checks()
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise BootstrapVerificationError(f"refusing to attest VERIFICADO with failed checks: {failed}")
    return {
        "attestation_type": "GENOMA_PROJECT_BOOTSTRAP",
        "status": "VERIFICADO",
        "ruleset_identity": f"{EXPECTED_VERSION}/{EXPECTED_STATUS}/{EXPECTED_DATE}",
        "canonical_filename": EXPECTED_CANONICAL,
        "canonical_sha256": EXPECTED_SHA256,
        "verified_at": verified_at,
        "actor_type": "SERVICE",
        "actor_id": VERIFIER_NAME,
        "method": f"deterministic re-derivation of every check by {VERIFIER_COMMAND}",
        "verifier": {
            "name": VERIFIER_NAME,
            "version": POLICY_ENGINE_VERSION,
            "command": VERIFIER_COMMAND,
            "result_locator": RESULT_LOCATOR,
            # Digests of the artifacts the checks were derived from. A commit SHA
            # cannot appear here: the attestation is part of the commit it would
            # name. Input digests bind the same provenance without that cycle.
            "inputs": {
                "normative/sealed/MANIFEST.json": _sha256(SEALED_MANIFEST),
                "policy_engine/policy/schema/execution-manifest.schema.json": _sha256(SCHEMA),
                "canonical_ruleset_raw_sha256": EXPECTED_SHA256,
            },
        },
        "checks": checks,
        "limitations": (
            "Every check in this attestation was re-derived by executing it against the "
            "repository artifacts named in verifier.inputs; none is a textual claim. The "
            "attestation covers the deterministic core only: it does not attest to any "
            "surrounding assistant, interface or session. Regenerate it whenever the "
            "canonical ruleset, the execution schema or the verifier changes."
        ),
    }


def render(attestation: dict[str, Any]) -> str:
    return json.dumps(attestation, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="re-derive and compare against the committed attestation")
    parser.add_argument("--write", action="store_true", help="regenerate the committed attestation")
    parser.add_argument("--verified-at", help="timestamp to record; defaults to the committed one")
    args = parser.parse_args(argv)

    committed = json.loads(ATTESTATION.read_text(encoding="utf-8")) if ATTESTATION.is_file() else {}
    verified_at = args.verified_at or committed.get("verified_at")
    if not verified_at:
        parser.error("--verified-at is required when no committed attestation exists")

    try:
        attestation = build_attestation(verified_at=verified_at)
    except (BootstrapVerificationError, SealedRulesetError) as exc:
        sys.stderr.write(f"NÃO DISPONÍVEL: {type(exc).__name__}: {exc}\n")
        return 2

    payload = render(attestation)
    if args.write:
        ATTESTATION.write_text(payload, encoding="utf-8")
        sys.stdout.write(f"{ATTESTATION.relative_to(ROOT)}: {hashlib.sha256(payload.encode()).hexdigest()}\n")
        return 0
    if args.check:
        if not ATTESTATION.is_file():
            sys.stderr.write("bootstrap attestation is missing\n")
            return 2
        if ATTESTATION.read_text(encoding="utf-8") != payload:
            sys.stderr.write(
                "committed bootstrap attestation is not reproducible from its declared inputs; "
                f"re-derive with: python3 {Path(__file__).relative_to(ROOT)} --write\n"
            )
            return 3
        sys.stdout.write("bootstrap attestation reproduced exactly from its declared inputs\n")
        return 0
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
