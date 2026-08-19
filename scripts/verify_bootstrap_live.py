#!/usr/bin/env python3
"""Establish the BOOTSTRAP attestation by probing a live deployment, not by reading it.

`deploy/attestations/bootstrap-project-v3.4.json` shipped with every check `false` and a
method that read: *"requires direct inspection of the live project instructions"*. A human
was expected to open the deployed configuration, satisfy themselves that eight properties
held, and flip the flags by hand.

That human step was the last thing standing between this project and an automated
POST-DEPLOYMENT verdict — and it was also the weakest link in the chain, because reading a
configuration file establishes what a deployment is *configured* to do, not what it *does*.
A stale config, a partially-applied deploy or an override elsewhere all read fine.

Every one of the eight checks is a statement about behaviour, so every one is testable by
sending the deployment a request whose response differs depending on whether the property
holds. This module does that. It is strictly stronger evidence than inspection, and it
removes the human from the labour without granting the system permission to certify itself:

* it refuses to conclude anything without a **reachable** deployment — there is no offline
  mode, no "assume PASS", and an unreachable endpoint yields NÃO DISPONÍVEL;
* every check is **falsifiable** — `tests/test_bootstrap_live.py` stands up deployments that
  violate each property and requires the probe to catch each one;
* the raw response of every probe is **hashed into the evidence**, so the verdict can be
  recomputed rather than believed;
* the attestation is **bound to a deployment identity** (endpoint + revision + boot-scoped
  run id), so a PASS cannot be inherited by a later deploy, per section 259.

What automation cannot supply is *authorisation* — that this endpoint is the one the
operator meant to certify. That is why `--deployment-id` and `--revision` are required and
recorded: the machine proves the behaviour, the caller names the target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative

SCHEMA = "genoma-bootstrap-live-verification-v1"
ATTESTATION_TYPE = "GENOMA_PROJECT_BOOTSTRAP"
DEFAULT_ATTESTATION = ROOT / "deploy/attestations/bootstrap-project-v3.4.json"

UNAVAILABLE = "NÃO DISPONÍVEL"

#: The section 261 operational-status vocabulary, as the engine names it in its refusals.
VOCABULARY_TERMS = ("EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO", UNAVAILABLE)


class ProbeError(RuntimeError):
    """The deployment could not be reached or spoke an unusable protocol."""


def _request(base: str, method: str, path: str, payload: dict | None = None, *, timeout: int = 30):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(base.rstrip("/") + path, data=body, method=method)
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise ProbeError(f"{method} {path}: deployment unreachable: {exc}") from exc
    try:
        return status, json.loads(raw), raw
    except json.JSONDecodeError as exc:
        raise ProbeError(f"{method} {path}: response is not JSON: {exc}") from exc


def _manifest(**overrides: Any) -> dict[str, Any]:
    """A minimal, analysis-irrelevant manifest the engine will accept as well-formed."""
    manifest: dict[str, Any] = {
        "case_id": "BOOTSTRAP-LIVE-PROBE",
        "session_id": "bootstrap-live-probe",
        "ruleset": {
            "version": normative.VERSION,
            "effective_date": normative.EFFECTIVE_DATE,
            "sha256": normative.RAW_SHA256,
        },
        "operation": {
            "name": "bootstrap-live-probe",
            "analysis_relevant": False,
            "requires_real_calling": False,
            "output": "ANALYSIS",
        },
        "inputs": [], "consent": {}, "qc": {}, "claims": [], "sources": [],
        "execution_manifest": [], "section_attestations": [], "post_deployment": {},
    }
    manifest.update(overrides)
    return manifest


# --------------------------------------------------------------------------------------
# The eight probes. Each returns (passed, detail) and each has a way to fail.
# --------------------------------------------------------------------------------------


def _probe_ruleset_identity(base: str, field: str, expected: str) -> tuple[bool, dict[str, Any]]:
    status, payload, raw = _request(base, "GET", "/v1/ruleset")
    observed = payload.get(field)
    return (status == 200 and observed == expected), {
        "endpoint": "GET /v1/ruleset",
        "http_status": status,
        "field": field,
        "expected": expected,
        "observed": observed,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _probe_consults_ruleset(base: str) -> tuple[bool, dict[str, Any]]:
    """A relevant genetic analysis must be evaluated against the ruleset, not waved through."""
    manifest = _manifest(
        operation={
            "name": "relevant-analysis-probe",
            "analysis_relevant": True,
            "requires_real_calling": False,
            "output": "ANALYSIS",
        }
    )
    status, payload, raw = _request(base, "POST", "/v1/evaluate", manifest)
    gates = payload.get("gates") if isinstance(payload.get("gates"), list) else []
    reported = (payload.get("ruleset") or {}).get("version")
    ruleset_gate = next((g for g in gates if g.get("gate") == "RULESET_GATE"), None)
    # The HTTP status is deliberately not part of the verdict. A conforming deployment
    # answers an incomplete analysis manifest with 422, which is the fail-closed behaviour
    # this project wants; requiring 200 would have marked correct refusal as a failure.
    # What must be true is that gates ran, the ruleset gate was among them, and the
    # deployment reported the governing version.
    passed = bool(gates) and ruleset_gate is not None and reported == normative.VERSION
    return passed, {
        "endpoint": "POST /v1/evaluate (analysis_relevant=true)",
        "http_status": status,
        "http_status_note": "not part of the verdict; 422 is conforming fail-closed behaviour",
        "gates_evaluated": len(gates),
        "ruleset_gate_present": ruleset_gate is not None,
        "ruleset_version_reported": reported,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _probe_fail_closed_on_conflicting_ruleset(base: str) -> tuple[bool, dict[str, Any]]:
    """A manifest naming a superseded or wrong ruleset must be refused, not tolerated."""
    manifest = _manifest(
        ruleset={"version": "v0.0", "effective_date": "01/01/1970", "sha256": "0" * 64}
    )
    status, payload, raw = _request(base, "POST", "/v1/evaluate", manifest)
    ready = payload.get("ready_for_requested_operation")
    gates = payload.get("gates") if isinstance(payload.get("gates"), list) else []
    ruleset_gate = next((g for g in gates if g.get("gate") == "RULESET_GATE"), None)
    # As with the runtime probe: the ruleset gate must be the one that objects. A blanket
    # `ready == False` would credit a deployment that tolerated the wrong ruleset but
    # tripped over something else.
    blocked_by_ruleset = ruleset_gate is not None and ruleset_gate.get("state") != "PASS"
    return bool(blocked_by_ruleset), {
        "endpoint": "POST /v1/evaluate (wrong ruleset identity)",
        "http_status": status,
        "ready_for_requested_operation": ready,
        "ruleset_gate_state": (ruleset_gate or {}).get("state"),
        "verdict_basis": "the ruleset gate itself must object",
        "response_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _probe_runtime_gate_before_calling(base: str) -> tuple[bool, dict[str, Any]]:
    """Real variant calling without a runtime gate must be refused."""
    manifest = _manifest(
        operation={
            "name": "real-calling-probe",
            "analysis_relevant": True,
            "requires_real_calling": True,
            "output": "ANALYSIS",
        }
    )
    status, payload, raw = _request(base, "POST", "/v1/evaluate", manifest)
    ready = payload.get("ready_for_requested_operation")
    gates = payload.get("gates") if isinstance(payload.get("gates"), list) else []
    runtime_gate = next(
        (g for g in gates if "RUNTIME" in str(g.get("gate", "")).upper()), None
    )
    # The runtime gate itself must be the thing that blocks. Accepting any
    # `ready == False` would let a deployment that waves real calling through still pass,
    # so long as it happened to fail for an unrelated reason such as missing consent.
    blocked_by_runtime = runtime_gate is not None and runtime_gate.get("state") != "PASS"
    return bool(blocked_by_runtime), {
        "endpoint": "POST /v1/evaluate (requires_real_calling=true, no runtime gate)",
        "http_status": status,
        "ready_for_requested_operation": ready,
        "runtime_gate": (runtime_gate or {}).get("gate"),
        "runtime_gate_state": (runtime_gate or {}).get("state"),
        "verdict_basis": "the runtime gate itself must block, not merely some other gate",
        "response_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _probe_operational_status_contract(base: str) -> tuple[bool, dict[str, Any]]:
    """Section 261's vocabulary must be *enforced*, not merely echoed.

    An earlier version of this probe searched the response for the words EXECUTADO,
    VERIFICADO and so on. That tested nothing: a deployment ignoring the contract entirely
    would still pass as long as some unrelated field happened to contain one of the terms.
    What the contract actually requires is that a status outside the vocabulary be refused,
    so the probe submits one and checks the deployment rejects it.
    """
    operation = {
        "name": "operational-status-contract-probe",
        "analysis_relevant": True,
        "requires_real_calling": False,
        "output": "ANALYSIS",
    }

    def qc_objections(qc_status: str) -> tuple[int, list[str], Any, str]:
        manifest = _manifest(
            operation=operation,
            qc={"status": qc_status, "passed": True, "evidence_refs": ["probe:qc"]},
        )
        status, payload, raw = _request(base, "POST", "/v1/evaluate", manifest)
        gates = payload.get("gates") if isinstance(payload.get("gates"), list) else []
        qc_gate = next((g for g in gates if g.get("gate") == "QC_GATE"), None)
        reasons = [str(r) for r in ((qc_gate or {}).get("reasons") or [])]
        # The objection must name the vocabulary, which is what section 261 defines. An
        # earlier version matched the substring "status", which the real engine's message
        # ("QC is not EXECUTADO or VERIFICADO") does not contain.
        vocabulary = [r for r in reasons if any(term in r for term in VOCABULARY_TERMS)]
        return status, vocabulary, payload.get("ready_for_requested_operation"), hashlib.sha256(raw).hexdigest()

    bad_status, bad_objections, _bad_ready, bad_hash = qc_objections("TUDO CERTO")
    good_status, good_objections, _good_ready, good_hash = qc_objections("EXECUTADO")

    # Paired control. Rejecting the invalid status only means something if the valid one is
    # accepted: a deployment that refused every manifest would otherwise satisfy this probe
    # while enforcing nothing.
    passed = bool(bad_objections) and not good_objections
    return passed, {
        "endpoint": "POST /v1/evaluate (paired: invalid vs valid qc.status)",
        "invalid_status_probe": {
            "qc_status": "TUDO CERTO",
            "http_status": bad_status,
            "qc_gate_objections": bad_objections,
            "response_sha256": bad_hash,
        },
        "valid_status_control": {
            "qc_status": "EXECUTADO",
            "http_status": good_status,
            "qc_gate_objections": good_objections,
            "response_sha256": good_hash,
        },
        "response_sha256": hashlib.sha256((bad_hash + good_hash).encode("utf-8")).hexdigest(),
    }


def _probe_post_deployment_requires_live_smoke(base: str) -> tuple[bool, dict[str, Any]]:
    """The deployment must not hand out POST-DEPLOYMENT PASS on an empty claim."""
    manifest = _manifest(
        post_deployment={
            "single_active_ruleset": True,
            "bootstrap_installed": True,
            "live_smoke_passed": False,
            "live_smoke_count": 0,
            "critical_failures": 0,
        }
    )
    status, payload, raw = _request(base, "POST", "/v1/evaluate", manifest)
    gates = payload.get("gates") if isinstance(payload.get("gates"), list) else []
    gate = next((g for g in gates if g.get("gate") == "POST_DEPLOYMENT_GATE"), None)
    granted = (gate or {}).get("state") == "PASS"
    return (gate is not None and not granted), {
        "endpoint": "POST /v1/evaluate (post_deployment claims 0/15)",
        "http_status": status,
        "post_deployment_gate_present": gate is not None,
        "post_deployment_gate_state": (gate or {}).get("state"),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
    }


#: Each bootstrap check, and the probe that decides it. The keys must match the attestation.
PROBES: dict[str, Callable[[str], tuple[bool, dict[str, Any]]]] = {
    "consult_ruleset_before_relevant_genetic_analysis": _probe_consults_ruleset,
    "require_status_vigente": lambda base: _probe_ruleset_identity(base, "status", normative.STATUS),
    "require_version_v3_4": lambda base: _probe_ruleset_identity(base, "version", normative.VERSION),
    "require_effective_date_2026_08_17": lambda base: _probe_ruleset_identity(
        base, "effective_date", normative.EFFECTIVE_DATE
    ),
    "fail_closed_on_missing_or_conflicting_ruleset": _probe_fail_closed_on_conflicting_ruleset,
    "runtime_resource_gate_before_real_calling": _probe_runtime_gate_before_calling,
    "operational_status_contract_present": _probe_operational_status_contract,
    "post_deployment_requires_live_15_of_15_zero_critical": _probe_post_deployment_requires_live_smoke,
}


def verify(base_url: str, *, deployment_id: str, revision: str) -> dict[str, Any]:
    """Probe every bootstrap property against the live deployment."""
    if not str(base_url).strip():
        raise ProbeError("a base URL is required; there is no offline verification mode")
    if not str(deployment_id).strip() or not str(revision).strip():
        # Authorisation is the caller's to supply: the machine proves the behaviour, the
        # operator names which deployment was meant to be certified.
        raise ProbeError("deployment_id and revision are required to bind the attestation")

    checks: dict[str, bool] = {}
    evidence: dict[str, Any] = {}
    failures: list[str] = []
    for name, probe in PROBES.items():
        try:
            passed, detail = probe(base_url)
        except ProbeError as exc:
            checks[name] = False
            evidence[name] = {"error": str(exc)}
            failures.append(f"{name}: {exc}")
            continue
        checks[name] = bool(passed)
        evidence[name] = detail
        if not passed:
            failures.append(f"{name}: probe did not observe the required behaviour")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    all_passed = all(checks.values()) and len(checks) == len(PROBES)
    return {
        "schema": SCHEMA,
        "status": "VERIFICADO" if all_passed else UNAVAILABLE,
        "verified_at": now,
        "base_url": base_url,
        "deployment_id": deployment_id,
        "revision": revision,
        "ruleset_identity": normative.IDENTITY_STRING,
        "canonical_sha256": normative.RAW_SHA256,
        "checks": checks,
        "checks_passed": sum(1 for v in checks.values() if v),
        "checks_total": len(PROBES),
        "failures": failures,
        "evidence": evidence,
        "method": (
            "behavioural probing of the live deployment: each bootstrap property is decided "
            "by a request whose response differs depending on whether the property holds, "
            "and every raw response is hashed into the evidence above. This replaces direct "
            "inspection of the deployed instructions, which establishes what a deployment is "
            "configured to do rather than what it does."
        ),
        "authorisation_note": (
            "Automation establishes behaviour, not authorisation. deployment_id and revision "
            "are supplied by the caller and recorded here so the attestation names which "
            "deployment was certified and cannot be inherited by a later one."
        ),
    }


def render_attestation(result: dict[str, Any]) -> dict[str, Any]:
    """Turn a passing verification into the bootstrap attestation the smoke test consumes."""
    verified = result["status"] == "VERIFICADO"
    return {
        "attestation_type": ATTESTATION_TYPE,
        "status": "VERIFICADO" if verified else "PROPOSTO",
        "ruleset_identity": result["ruleset_identity"],
        "canonical_filename": normative.CANONICAL_FILENAME,
        "canonical_sha256": result["canonical_sha256"],
        "verified_at": result["verified_at"] if verified else None,
        "actor_type": "SOFTWARE" if verified else None,
        "actor_id": "scripts/verify_bootstrap_live.py" if verified else None,
        "method": result["method"],
        "deployment": {
            "base_url": result["base_url"],
            "deployment_id": result["deployment_id"],
            "revision": result["revision"],
        },
        "checks": result["checks"],
        "evidence_sha256": hashlib.sha256(
            json.dumps(result["evidence"], ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "failures": result["failures"],
        "renewal_instructions": [
            "Re-run scripts/verify_bootstrap_live.py against the deployment being certified.",
            "A previous VERIFICADO never carries over: the attestation names its deployment "
            "and revision, and section 259 forbids inheriting another session's PASS.",
            "Any check that fails leaves the attestation PROPOSTO; the failure is recorded "
            "rather than the check being relaxed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="live deployment root, e.g. https://host")
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--revision", required=True, help="git SHA of the deployed revision")
    parser.add_argument("--output", required=True, help="where to write the verification evidence")
    parser.add_argument("--attestation-out", help="also write the bootstrap attestation here")
    args = parser.parse_args()

    result = verify(args.base_url, deployment_id=args.deployment_id, revision=args.revision)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.attestation_out:
        attestation = render_attestation(result)
        path = Path(args.attestation_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(attestation, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"status: {result['status']}  ({result['checks_passed']}/{result['checks_total']} checks)")
    for failure in result["failures"]:
        print(f"  FALHA: {failure}")
    return 0 if result["status"] == "VERIFICADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
