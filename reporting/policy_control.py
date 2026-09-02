"""Revalidate Policy Control Plane output at the publication trust boundary.

A JSON file is transport, not authority.  The report layer therefore requires the policy
engine's identity envelope, checks that it is bound to this case/input/operation, then
re-executes the Policy Control Plane over the embedded manifest using the sealed canonical
ruleset.  Only the re-executed result is consumed.  This deliberately avoids claiming that a
file hash authenticates who wrote a file; no signing key is required because PASS is recomputed
rather than trusted.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

POLICY_EVALUATION_SCHEMA = "genoma-policy-evaluation-v2"
POLICY_EVALUATION_PRODUCER = "genoma-policy-engine"


class PolicyEvaluationVerificationError(ValueError):
    """The supplied policy artifact cannot act as publication authority."""


@lru_cache(maxsize=1)
def _runtime() -> tuple[Any, Any, Any]:
    """Load one in-process Policy Control Plane from the sealed canonical ruleset."""
    try:
        from policy_engine.genoma_policy.engine import PolicyEngine
        from policy_engine.genoma_policy.models import evaluation_binding
        from policy_engine.genoma_policy.paths import CANONICAL_MANIFEST_RELATIVE
        from policy_engine.genoma_policy.ruleset import (
            load_ruleset,
            verify_external_manifest,
        )
        from scripts.materialize_ruleset import materialize
    except (ImportError, ModuleNotFoundError) as exc:
        raise PolicyEvaluationVerificationError(
            "Policy Control Plane runtime is not importable at the publication boundary"
        ) from exc

    root = Path(__file__).resolve().parents[1]
    hash_manifest = root / CANONICAL_MANIFEST_RELATIVE
    td: TemporaryDirectory[str] | None = None
    try:
        td = TemporaryDirectory()
        ruleset_path, _evidence = materialize(Path(td.name))
        ruleset = load_ruleset(ruleset_path)
        verify_external_manifest(ruleset, hash_manifest)
        engine = PolicyEngine(ruleset, external_manifest=hash_manifest)
    except (OSError, RuntimeError, ValueError) as exc:
        if td is not None:
            td.cleanup()
        raise PolicyEvaluationVerificationError(
            f"canonical Policy Control Plane could not be materialized and verified: {exc}"
        ) from exc
    return engine, evaluation_binding, td


def verify_policy_evaluation(
    evaluation: dict[str, Any],
    *,
    case_id: str,
    input_sha256: str,
    required_output: str = "FINAL_AUDITED_REPORT",
) -> dict[str, Any]:
    """Return the re-executed verdict only when the supplied envelope binds exactly.

    The supplied PASS bits are never authority.  They are compared to a fresh evaluation of
    the embedded manifest; a hand-written object can only be accepted when the Policy Control
    Plane itself independently reaches the same result for the same case, session, input and
    requested operation.
    """
    if not isinstance(case_id, str) or not case_id.strip():
        raise PolicyEvaluationVerificationError("report case_id must be a non-empty string")
    if not isinstance(evaluation, dict) or not evaluation:
        raise PolicyEvaluationVerificationError("policy evaluation is not a non-empty JSON object")
    if evaluation.get("schema") != POLICY_EVALUATION_SCHEMA:
        raise PolicyEvaluationVerificationError(
            f"policy evaluation schema must be {POLICY_EVALUATION_SCHEMA!r}"
        )
    producer = evaluation.get("producer") if isinstance(evaluation.get("producer"), dict) else {}
    if producer.get("id") != POLICY_EVALUATION_PRODUCER or not str(producer.get("version") or "").strip():
        raise PolicyEvaluationVerificationError(
            "policy evaluation does not identify a versioned genoma-policy-engine producer"
        )
    manifest = (
        evaluation.get("evaluated_manifest")
        if isinstance(evaluation.get("evaluated_manifest"), dict)
        else None
    )
    if not manifest:
        raise PolicyEvaluationVerificationError(
            "policy evaluation does not carry the execution manifest required for re-execution"
        )

    engine, evaluation_binding, _ruleset_lifetime = _runtime()
    expected_binding = evaluation_binding(manifest)
    binding = evaluation.get("binding") if isinstance(evaluation.get("binding"), dict) else {}
    if binding != expected_binding:
        raise PolicyEvaluationVerificationError(
            "policy evaluation binding does not match the embedded manifest digest/identity"
        )
    for key in ("case_id", "session_id", "input_sha256", "operation", "manifest_sha256"):
        if evaluation.get(key) != expected_binding.get(key):
            raise PolicyEvaluationVerificationError(
                f"policy evaluation top-level {key} disagrees with its manifest binding"
            )

    bound_case = expected_binding.get("case_id")
    bound_case = bound_case.strip() if isinstance(bound_case, str) else ""
    if not bound_case:
        raise PolicyEvaluationVerificationError("policy evaluation case_id is missing")
    if bound_case != case_id.strip():
        raise PolicyEvaluationVerificationError(
            f"policy evaluation belongs to case {bound_case!r}, not {case_id.strip()!r}"
        )
    session_id = str(expected_binding.get("session_id") or "").strip()
    if not session_id:
        raise PolicyEvaluationVerificationError("policy evaluation session_id is missing")
    bound_input = str(expected_binding.get("input_sha256") or "").strip()
    if not bound_input:
        raise PolicyEvaluationVerificationError(
            "policy evaluation must identify exactly one non-empty input SHA-256"
        )
    if bound_input != str(input_sha256).strip():
        raise PolicyEvaluationVerificationError(
            "policy evaluation input SHA-256 does not match the report artifacts"
        )
    operation = expected_binding.get("operation") if isinstance(expected_binding.get("operation"), dict) else {}
    if operation.get("output") != required_output:
        raise PolicyEvaluationVerificationError(
            f"policy evaluation operation.output must be {required_output!r} for publication"
        )

    try:
        recomputed = engine.evaluate(copy.deepcopy(manifest)).to_dict()
    except (RuntimeError, TypeError, ValueError) as exc:
        raise PolicyEvaluationVerificationError(
            f"Policy Control Plane re-execution failed: {exc}"
        ) from exc
    if evaluation != recomputed:
        raise PolicyEvaluationVerificationError(
            "supplied policy evaluation does not equal Policy Control Plane re-execution"
        )
    return recomputed
