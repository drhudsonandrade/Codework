from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, env: dict[str, str] | None = None, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(
        args,
        cwd=cwd or ROOT,
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(f"$ {' '.join(args)}")
    print(result.stdout)
    if check and result.returncode != 0:
        raise SystemExit(f"command failed with exit {result.returncode}: {' '.join(args)}")
    return result


def replace_once(path: str, old: str, new: str, label: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_before_main(path: str, block: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    marker = '\n\nif __name__ == "__main__":\n'
    if marker not in text:
        raise SystemExit(f"main marker missing in {path}")
    target.write_text(text.replace(marker, "\n\n" + textwrap.dedent(block).strip() + marker, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def red_phase() -> None:
    append_before_main(
        "tests/test_policy_evaluation_binding.py",
        r'''
class PR30PolicyBoundaryRedTest(unittest.TestCase):
    """Regression proofs added before the implementation repair."""

    def test_complete_manual_pass_object_is_not_publication_authority(self):
        """A complete-looking hand-written PASS must not become Policy Control authority."""
        payload = {
            "schema": "genoma-policy-evaluation-v2",
            "producer": {"id": "genoma-policy-engine", "version": "manual"},
            "binding": {
                "case_id": "CASE-1",
                "session_id": "SESSION-1",
                "input_sha256": "a" * 64,
                "operation": {"name": "report_publication", "output": "FINAL_AUDITED_REPORT"},
                "manifest_sha256": "b" * 64,
            },
            "evaluated_manifest": {
                "case_id": "CASE-1",
                "session_id": "SESSION-1",
                "inputs": [{"sha256": "a" * 64}],
                "operation": {"name": "report_publication", "output": "FINAL_AUDITED_REPORT"},
                "qc": {"passed": False},
            },
            "ready_for_requested_operation": True,
            "ruleset": {"sha256": normative.RAW_SHA256},
            "planes": {name: {"state": "PASS"} for name in REQUIRED_PLANES},
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
        }
        verdict = _verdict_for(payload, case_id="CASE-1")
        self.assertFalse(verdict["ready_for_requested_operation"])

    def test_real_engine_output_serializes_execution_identity(self):
        """The producer must serialize case/session/input/schema and manifest digest."""
        import tempfile
        from pathlib import Path
        import sys

        root = Path(__file__).resolve().parents[1]
        policy_root = root / "policy_engine"
        if str(policy_root) not in sys.path:
            sys.path.insert(0, str(policy_root))
        from genoma_policy.engine import PolicyEngine
        from genoma_policy.ruleset import load_ruleset
        from genoma_policy.scaffold import scaffold_manifest
        from scripts.materialize_ruleset import materialize

        with tempfile.TemporaryDirectory() as td:
            ruleset_path, _evidence = materialize(Path(td))
            ruleset = load_ruleset(ruleset_path)
            manifest = scaffold_manifest(ruleset, case_id="CASE-1")
            manifest["session_id"] = "SESSION-1"
            manifest["inputs"] = [
                {"id": "input-1", "kind": "array", "source": "fixture", "sha256": "a" * 64}
            ]
            evaluation = PolicyEngine(ruleset).evaluate(manifest).to_dict()
        self.assertEqual(evaluation["schema"], "genoma-policy-evaluation-v2")
        self.assertEqual(evaluation["case_id"], "CASE-1")
        self.assertEqual(evaluation["session_id"], "SESSION-1")
        self.assertEqual(evaluation["input_sha256"], "a" * 64)
        self.assertRegex(evaluation["manifest_sha256"], r"^[0-9a-f]{64}$")
''',
    )
    append_before_main(
        "tests/test_target_expansion.py",
        r'''
class PR30StrictReferenceDecodingRedTest(unittest.TestCase):
    """Curated reference inputs fail closed on malformed UTF-8."""

    def test_gwas_associations_reject_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "associations.tsv"
        path.write_bytes(b"SNPS\tDISEASE/TRAIT\nrs1\tbad\xff\n")
        with self.assertRaises(UnicodeDecodeError):
            with TRAITS._open_associations(path) as handle:
                handle.read()

    def test_gwas_ancestry_rejects_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "ancestries.tsv"
        path.write_bytes(
            b"STUDY ACCESSION\tBROAD ANCESTRAL CATEGORY\tSTAGE\tNUMBER OF INDIVIDUALS\tINITIAL SAMPLE DESCRIPTION\n"
            b"GCST1\tEuropean\tinitial\t10\tbad\xff\n"
        )
        with self.assertRaises(UnicodeDecodeError):
            TRAITS.read_ancestries(path)

    def test_clinvar_bulk_rejects_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "variant_summary.txt.gz"
        raw = ("\t".join(COLUMNS) + "\n").encode("utf-8") + b"bad\xff\n"
        path.write_bytes(gzip.compress(raw))
        with self.assertRaises(UnicodeDecodeError):
            EXPAND.scan_clinvar(path)

    def test_clingen_dosage_rejects_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "dosage.tsv"
        path.write_bytes(DOSAGE_HEADER.encode("utf-8") + b"\nHFE\t1\tbad\xff\n")
        with self.assertRaises(UnicodeDecodeError):
            EXPAND.read_clingen_dosage(path)
''',
    )

    result = run(
        sys.executable,
        "-m",
        "unittest",
        "tests.test_policy_evaluation_binding.PR30PolicyBoundaryRedTest",
        "tests.test_target_expansion.PR30StrictReferenceDecodingRedTest",
        "-v",
        check=False,
    )
    if result.returncode == 0:
        raise SystemExit("RED phase unexpectedly passed; the targeted regressions did not reproduce")
    required = (
        "test_complete_manual_pass_object_is_not_publication_authority",
        "test_real_engine_output_serializes_execution_identity",
        "test_gwas_associations_reject_invalid_utf8",
        "test_gwas_ancestry_rejects_invalid_utf8",
        "test_clinvar_bulk_rejects_invalid_utf8",
        "test_clingen_dosage_rejects_invalid_utf8",
    )
    missing = [name for name in required if name not in result.stdout]
    if missing:
        raise SystemExit(f"RED phase did not execute expected tests: {missing}")
    print("RED VERIFIED: current HEAD reproduces both blocking root causes")
    run("git", "checkout", "--", "tests/test_policy_evaluation_binding.py", "tests/test_target_expansion.py")


def implement_policy_envelope() -> None:
    write(
        "policy_engine/genoma_policy/models.py",
        r'''
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

POLICY_EVALUATION_SCHEMA = "genoma-policy-evaluation-v2"
POLICY_EVALUATION_PRODUCER = "genoma-policy-engine"


def canonical_manifest_sha256(manifest: dict[str, Any]) -> str:
    """Digest the exact logical execution manifest using one deterministic JSON form."""
    raw = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def evaluation_binding(manifest: dict[str, Any]) -> dict[str, Any]:
    """Identity that binds one policy evaluation to the manifest it actually judged."""
    inputs = manifest.get("inputs") if isinstance(manifest.get("inputs"), list) else []
    input_hashes = {
        str(item.get("sha256") or "").strip()
        for item in inputs
        if isinstance(item, dict) and str(item.get("sha256") or "").strip()
    }
    input_sha256 = next(iter(input_hashes)) if len(input_hashes) == 1 else ""
    operation = manifest.get("operation") if isinstance(manifest.get("operation"), dict) else {}
    return {
        "case_id": str(manifest.get("case_id") or "").strip(),
        "session_id": str(manifest.get("session_id") or "").strip(),
        "input_sha256": input_sha256,
        "operation": copy.deepcopy(operation),
        "manifest_sha256": canonical_manifest_sha256(manifest),
    }


class OperationalStatus(str, Enum):
    EXECUTADO = "EXECUTADO"
    VERIFICADO = "VERIFICADO"
    INFERIDO = "INFERIDO"
    PROPOSTO = "PROPOSTO"
    NAO_DISPONIVEL = "NÃO DISPONÍVEL"


class ClaimNature(str, Enum):
    FATO_CONFIRMADO = "FATO CONFIRMADO"
    INFERENCIA = "INFERÊNCIA"
    ASSOCIACAO = "ASSOCIAÇÃO"
    HIPOTESE = "HIPÓTESE"
    DESCONHECIDO = "DESCONHECIDO"


class Domain(str, Enum):
    CLINICO = "CLÍNICO"
    PREDISPOSICAO = "PREDISPOSIÇÃO"
    PESQUISA = "PESQUISA"
    CURIOSIDADE = "CURIOSIDADE"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    P5 = "P5"


class GateState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


@dataclass(frozen=True)
class RulesetSection:
    number: int
    title: str
    body: str
    sha256: str

    @property
    def rule_id(self) -> str:
        return f"GENOMA-V3.4-S{self.number:03d}"


@dataclass(frozen=True)
class GateResult:
    gate: str
    state: GateState
    reasons: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "state": self.state.value,
            "reasons": list(self.reasons),
            "evidence_refs": list(self.evidence_refs),
            "blocking": self.blocking,
        }


@dataclass
class EvaluationReport:
    ruleset: dict[str, Any]
    evaluated_manifest: dict[str, Any] = field(default_factory=dict)
    gates: list[GateResult] = field(default_factory=list)
    section_coverage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    planes: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking_failures(self) -> list[GateResult]:
        return [g for g in self.gates if g.blocking and g.state == GateState.FAIL]

    @property
    def pending_blockers(self) -> list[GateResult]:
        return [g for g in self.gates if g.blocking and g.state == GateState.PENDING]

    @property
    def ready(self) -> bool:
        return not self.blocking_failures and not self.pending_blockers

    def to_dict(self) -> dict[str, Any]:
        snapshot = copy.deepcopy(self.evaluated_manifest)
        binding = evaluation_binding(snapshot)
        producer = {
            "id": POLICY_EVALUATION_PRODUCER,
            "version": str(self.metadata.get("engine_version") or ""),
        }
        return {
            "schema": POLICY_EVALUATION_SCHEMA,
            "producer": producer,
            "case_id": binding["case_id"],
            "session_id": binding["session_id"],
            "input_sha256": binding["input_sha256"],
            "operation": copy.deepcopy(binding["operation"]),
            "manifest_sha256": binding["manifest_sha256"],
            "binding": binding,
            "evaluated_manifest": snapshot,
            "ready_for_requested_operation": self.ready,
            "ruleset": self.ruleset,
            "gates": [g.to_dict() for g in self.gates],
            "section_coverage": self.section_coverage,
            "metadata": self.metadata,
            "planes": self.planes,
        }
''',
    )
    replace_once(
        "policy_engine/genoma_policy/engine.py",
        "from __future__ import annotations\n\nfrom pathlib import Path\n",
        "from __future__ import annotations\n\nfrom copy import deepcopy\nfrom pathlib import Path\n",
        "engine deepcopy import",
    )
    replace_once(
        "policy_engine/genoma_policy/engine.py",
        "        report = EvaluationReport(ruleset=self.ruleset.metadata())",
        "        report = EvaluationReport(\n            ruleset=self.ruleset.metadata(),\n            evaluated_manifest=deepcopy(manifest),\n        )",
        "engine manifest snapshot",
    )

    write(
        "reporting/policy_control.py",
        r'''
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
def _runtime() -> tuple[Any, Any]:
    """Load one in-process Policy Control Plane from the sealed canonical ruleset."""
    try:
        from policy_engine.genoma_policy.engine import PolicyEngine
        from policy_engine.genoma_policy.models import evaluation_binding
        from policy_engine.genoma_policy.ruleset import load_ruleset, verify_external_manifest
        from scripts.materialize_ruleset import materialize
    except (ImportError, ModuleNotFoundError) as exc:
        raise PolicyEvaluationVerificationError(
            "Policy Control Plane runtime is not importable at the publication boundary"
        ) from exc

    root = Path(__file__).resolve().parents[1]
    hash_manifest = root / "manifests" / "RULESET_V3.4.sha256"
    try:
        with TemporaryDirectory() as td:
            ruleset_path, _evidence = materialize(Path(td))
            ruleset = load_ruleset(ruleset_path)
            verify_external_manifest(ruleset, hash_manifest)
        engine = PolicyEngine(ruleset, external_manifest=hash_manifest)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PolicyEvaluationVerificationError(
            f"canonical Policy Control Plane could not be materialized and verified: {exc}"
        ) from exc
    return engine, evaluation_binding


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

    engine, evaluation_binding = _runtime()
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

    bound_case = str(expected_binding.get("case_id") or "").strip()
    if not bound_case:
        raise PolicyEvaluationVerificationError("policy evaluation case_id is missing")
    if bound_case != str(case_id):
        raise PolicyEvaluationVerificationError(
            f"policy evaluation belongs to case {bound_case!r}, not {str(case_id)!r}"
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
''',
    )

    replace_once(
        "reporting/provenance.py",
        "from reporting import deployment_target\n",
        "from reporting import deployment_target\nfrom reporting.policy_control import (\n    PolicyEvaluationVerificationError,\n    verify_policy_evaluation,\n)\n",
        "policy verifier import",
    )
    start = (ROOT / "reporting/provenance.py").read_text(encoding="utf-8")
    method_start = start.index("    def _policy_binding_refusal(")
    method_end = start.index("    def policy_verdict(", method_start)
    replacement = textwrap.dedent(r'''
        def _validated_policy_evaluation(
            self, evaluated: dict[str, Any]
        ) -> tuple[dict[str, Any] | None, str | None]:
            """Re-execute the Policy Control Plane and bind the result to this payload.

            For real payloads, reading an evaluation file is never enough.  The engine output
            must carry a case/session/input/operation/manifest identity envelope, and this
            method re-runs the Policy Control Plane over the embedded manifest using the sealed
            canonical ruleset.  Only that re-executed result is returned.  A fixture may bypass
            this because fixture anchors can only produce NÃO DISPONÍVEL output and therefore
            cannot authorize a real claim.
            """
            if self._fixture_verdict:
                return evaluated, None

            control_artifacts = {
                POLICY_EVALUATION_ARTIFACT,
                POST_DEPLOYMENT_WITNESS_ARTIFACT,
                CONSENT_ARTIFACT,
            }
            input_hashes: set[str] = set()
            for name, candidate in self._artifacts.items():
                if name in control_artifacts or not isinstance(candidate.payload, dict):
                    continue
                direct = str(candidate.payload.get("input_sha256") or "").strip()
                nested_input = candidate.payload.get("input")
                nested = (
                    str(nested_input.get("sha256") or "").strip()
                    if isinstance(nested_input, dict)
                    else ""
                )
                if direct:
                    input_hashes.add(direct)
                if nested:
                    input_hashes.add(nested)
            if len(input_hashes) != 1:
                return None, (
                    "a avaliação de política não pode ser vinculada aos bytes deste payload: "
                    f"os artefatos científicos declaram {len(input_hashes)} input_sha256 distintos"
                )
            try:
                verified = verify_policy_evaluation(
                    evaluated,
                    case_id=self.case_id,
                    input_sha256=next(iter(input_hashes)),
                    required_output="FINAL_AUDITED_REPORT",
                )
            except PolicyEvaluationVerificationError as exc:
                return None, str(exc)
            return verified, None

''')
    # textwrap.dedent removed class indentation; put it back exactly four spaces.
    replacement = "\n".join(("    " + line if line else line) for line in replacement.splitlines()).lstrip("\n")
    text = start[:method_start] + replacement + "\n" + start[method_end:]
    (ROOT / "reporting/provenance.py").write_text(text, encoding="utf-8")

    replace_once(
        "reporting/provenance.py",
        "        binding = self._policy_binding_refusal(evaluated)\n        if binding is not None:\n",
        "        verified, binding = self._validated_policy_evaluation(evaluated)\n        if binding is not None:\n",
        "policy verification call",
    )
    replace_once(
        "reporting/provenance.py",
        "        planes = evaluated.get(\"planes\") if isinstance(evaluated.get(\"planes\"), dict) else {}\n        return {\n            \"ready_for_requested_operation\": evaluated.get(\"ready_for_requested_operation\") is True,",
        "        if verified is None:\n            raise ProvenanceError(\"verified policy evaluation unexpectedly missing after successful validation\")\n        planes = verified.get(\"planes\") if isinstance(verified.get(\"planes\"), dict) else {}\n        return {\n            \"ready_for_requested_operation\": verified.get(\"ready_for_requested_operation\") is True,",
        "consume re-executed verdict",
    )
    replace_once(
        "reporting/provenance.py",
        "            \"gates\": [g for g in (evaluated.get(\"gates\") or []) if isinstance(g, dict)],\n",
        "            \"gates\": [g for g in (verified.get(\"gates\") or []) if isinstance(g, dict)],\n",
        "verified gates",
    )
    replace_once(
        "reporting/provenance.py",
        "                \"origin\": \"fixture\" if self._fixture_verdict else \"policy-engine-output\",\n",
        "                \"origin\": \"fixture\" if self._fixture_verdict else \"policy-control-reexecution\",\n                \"manifest_sha256\": (verified.get(\"binding\") or {}).get(\"manifest_sha256\"),\n",
        "verified policy origin",
    )


def implement_strict_decoding() -> None:
    trait = ROOT / "scripts/build_trait_targets.py"
    text = trait.read_text(encoding="utf-8")
    count = text.count('errors="replace"')
    if count != 4:
        raise SystemExit(f"build_trait_targets.py expected 4 replacement decoders, found {count}")
    trait.write_text(text.replace('errors="replace"', 'errors="strict"'), encoding="utf-8")

    expand = ROOT / "scripts/expand_clinvar_targets.py"
    text = expand.read_text(encoding="utf-8")
    count = text.count('errors="replace"')
    if count != 2:
        raise SystemExit(f"expand_clinvar_targets.py expected 2 replacement decoders, found {count}")
    expand.write_text(text.replace('errors="replace"', 'errors="strict"'), encoding="utf-8")


def write_final_tests() -> None:
    write(
        "tests/test_policy_evaluation_binding.py",
        r'''
"""Policy Control Plane evaluations are data until re-executed at publication."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_ROOT = ROOT / "policy_engine"
if str(POLICY_ROOT) not in sys.path:
    sys.path.insert(0, str(POLICY_ROOT))

from genoma_policy.engine import PolicyEngine
from genoma_policy.gates_common import CRITICAL_FINAL_AUDIT_KEYS
from genoma_policy.models import evaluation_binding
from genoma_policy.ruleset import load_ruleset
from genoma_policy.scaffold import scaffold_manifest
from reporting.provenance import (
    POLICY_EVALUATION_ARTIFACT,
    REQUIRED_PLANES,
    Artifact,
    PayloadCompiler,
    ProvenanceError,
)
from scripts.materialize_ruleset import materialize

INPUT_SHA = "a" * 64


@lru_cache(maxsize=1)
def _ruleset():
    """Load the canonical ruleset from the sealed repository transport once for this suite."""
    with tempfile.TemporaryDirectory() as td:
        ruleset_path, _evidence = materialize(Path(td))
        return load_ruleset(ruleset_path)


def _manifest(*, case_id: str = "CASE-1", input_sha256: str = INPUT_SHA) -> dict:
    """A policy manifest that genuinely passes a FINAL_AUDITED_REPORT evaluation."""
    manifest = scaffold_manifest(_ruleset(), case_id=case_id)
    manifest["session_id"] = "SESSION-1"
    manifest["operation"].update(
        {
            "name": "report_publication",
            "analysis_relevant": True,
            "requires_real_calling": False,
            "output": "FINAL_AUDITED_REPORT",
        }
    )
    manifest["inputs"] = [
        {"id": "input-1", "kind": "array", "source": "fixture", "sha256": input_sha256}
    ]
    manifest["consent"] = {
        "verified": True,
        "version": "test-v1",
        "authorized_domains": ["research"],
    }
    manifest["qc"] = {
        "status": "EXECUTADO",
        "passed": True,
        "evidence_refs": ["fixture:qc"],
    }
    manifest["sources"] = [
        {
            "id": "fixture:attestation",
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
                "justification": "not triggered by this fixture",
                "evidence_refs": [],
            }
        )
        attestation["trace"].update(
            {"run_id": "SESSION-1", "created_at": "2026-08-22T18:46:00-03:00"}
        )
    manifest["final_audit"] = {key: True for key in CRITICAL_FINAL_AUDIT_KEYS}
    return manifest


def real_evaluation(*, case_id: str = "CASE-1", input_sha256: str = INPUT_SHA) -> dict:
    """The exact envelope emitted by the real Policy Control Plane for a passing manifest."""
    report = PolicyEngine(_ruleset()).evaluate(_manifest(case_id=case_id, input_sha256=input_sha256))
    if not report.ready:
        raise AssertionError("policy fixture is not actually ready")
    return report.to_dict()


def _verdict_for(payload: dict, *, case_id: str = "CASE-1", input_sha256: str = INPUT_SHA):
    """Compile one verdict with a scientific artifact bound to the same primary input."""
    compiler = PayloadCompiler(case_id=case_id, report_id="01")
    compiler._install_verdict(Artifact.from_payload(POLICY_EVALUATION_ARTIFACT, payload))
    compiler.register(Artifact.from_payload("subject-input", {"input_sha256": input_sha256}))
    return compiler.policy_verdict()


class PolicyEvaluationBindingTest(unittest.TestCase):
    """Only a re-executed, identity-bound Policy Control verdict may authorize publication."""

    def test_real_engine_output_serializes_required_identity(self):
        evaluation = real_evaluation()
        self.assertEqual(evaluation["schema"], "genoma-policy-evaluation-v2")
        self.assertEqual(evaluation["producer"]["id"], "genoma-policy-engine")
        self.assertTrue(evaluation["producer"]["version"])
        self.assertEqual(evaluation["case_id"], "CASE-1")
        self.assertEqual(evaluation["session_id"], "SESSION-1")
        self.assertEqual(evaluation["input_sha256"], INPUT_SHA)
        self.assertEqual(evaluation["operation"]["output"], "FINAL_AUDITED_REPORT")
        self.assertRegex(evaluation["manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(evaluation["binding"], evaluation_binding(evaluation["evaluated_manifest"]))

    def test_a_genuine_matching_evaluation_is_reexecuted_and_accepted(self):
        verdict = _verdict_for(real_evaluation())
        self.assertTrue(verdict["ready_for_requested_operation"])
        self.assertEqual(verdict["source"]["status"], "VERIFICADO")
        self.assertEqual(verdict["source"]["origin"], "policy-control-reexecution")

    def test_legacy_minimal_hand_written_pass_is_refused(self):
        payload = {
            "ready_for_requested_operation": True,
            "ruleset": {"sha256": _ruleset().sha256},
            "planes": {name: {"state": "PASS"} for name in REQUIRED_PLANES},
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
        }
        verdict = _verdict_for(payload)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertEqual(verdict["source"]["status"], "NÃO DISPONÍVEL")

    def test_complete_manual_pass_with_correct_digest_is_reexecuted_and_refused(self):
        payload = real_evaluation()
        payload["evaluated_manifest"]["qc"]["passed"] = False
        binding = evaluation_binding(payload["evaluated_manifest"])
        payload["binding"] = binding
        for key in ("case_id", "session_id", "input_sha256", "operation", "manifest_sha256"):
            payload[key] = copy.deepcopy(binding[key])
        # The forged PASS bits are deliberately left untouched.  A digest and plausible
        # producer metadata do not make them authority; re-execution must disagree and block.
        self.assertTrue(payload["ready_for_requested_operation"])
        verdict = _verdict_for(payload)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("re-execution", verdict["source"]["reason"])

    def test_cross_case_evaluation_is_not_transferable(self):
        verdict = _verdict_for(real_evaluation(case_id="CASE-OTHER"), case_id="CASE-1")
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("CASE-OTHER", verdict["source"]["reason"])

    def test_cross_input_evaluation_is_not_transferable(self):
        verdict = _verdict_for(real_evaluation(input_sha256="b" * 64), input_sha256=INPUT_SHA)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("input SHA-256", verdict["source"]["reason"])

    def test_missing_session_identity_is_refused_even_with_pass_bits(self):
        payload = real_evaluation()
        payload["evaluated_manifest"]["session_id"] = ""
        binding = evaluation_binding(payload["evaluated_manifest"])
        payload["binding"] = binding
        for key in ("case_id", "session_id", "input_sha256", "operation", "manifest_sha256"):
            payload[key] = copy.deepcopy(binding[key])
        verdict = _verdict_for(payload)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("session_id", verdict["source"]["reason"])

    def test_analysis_operation_cannot_authorize_final_report_publication(self):
        payload = real_evaluation()
        payload["evaluated_manifest"]["operation"]["output"] = "ANALYSIS"
        binding = evaluation_binding(payload["evaluated_manifest"])
        payload["binding"] = binding
        for key in ("case_id", "session_id", "input_sha256", "operation", "manifest_sha256"):
            payload[key] = copy.deepcopy(binding[key])
        verdict = _verdict_for(payload)
        self.assertFalse(verdict["ready_for_requested_operation"])
        self.assertIn("FINAL_AUDITED_REPORT", verdict["source"]["reason"])

    def test_a_non_object_never_reaches_policy_verification(self):
        for payload in ([], "PASS", None, 7):
            with self.subTest(payload=payload):
                with self.assertRaises(ProvenanceError):
                    Artifact.from_payload(POLICY_EVALUATION_ARTIFACT, payload)


if __name__ == "__main__":
    unittest.main()
''',
    )

    append_before_main(
        "tests/test_target_expansion.py",
        r'''
class StrictReferenceDecodingTest(unittest.TestCase):
    """Curated reference inputs fail closed rather than replacing malformed UTF-8."""

    def test_gwas_associations_reject_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "associations.tsv"
        path.write_bytes(b"SNPS\tDISEASE/TRAIT\nrs1\tbad\xff\n")
        with self.assertRaises(UnicodeDecodeError):
            with TRAITS._open_associations(path) as handle:
                handle.read()

    def test_gwas_ancestry_rejects_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "ancestries.tsv"
        path.write_bytes(
            b"STUDY ACCESSION\tBROAD ANCESTRAL CATEGORY\tSTAGE\tNUMBER OF INDIVIDUALS\tINITIAL SAMPLE DESCRIPTION\n"
            b"GCST1\tEuropean\tinitial\t10\tbad\xff\n"
        )
        with self.assertRaises(UnicodeDecodeError):
            TRAITS.read_ancestries(path)

    def test_clinvar_bulk_rejects_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "variant_summary.txt.gz"
        raw = ("\t".join(COLUMNS) + "\n").encode("utf-8") + b"bad\xff\n"
        path.write_bytes(gzip.compress(raw))
        with self.assertRaises(UnicodeDecodeError):
            EXPAND.scan_clinvar(path)

    def test_clingen_dosage_rejects_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "dosage.tsv"
        path.write_bytes(DOSAGE_HEADER.encode("utf-8") + b"\nHFE\t1\tbad\xff\n")
        with self.assertRaises(UnicodeDecodeError):
            EXPAND.read_clingen_dosage(path)
''',
    )


def implement_release_boundary() -> None:
    write(
        "scripts/prepare_report_release.py",
        r'''
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.policy_control import (
    PolicyEvaluationVerificationError,
    verify_policy_evaluation,
)

REQUIRED_PUBLICATION = ("consent_verified", "qc_verified", "evidence_verified", "placeholders_resolved")
REQUIRED_PLANES = ("policy_control", "scientific_data", "evidence", "audit")


def _curated_input_sha256(curated: dict[str, Any]) -> str:
    """The primary subject input the curated manifest says its findings came from."""
    direct = str(curated.get("input_sha256") or "").strip()
    if direct:
        return direct
    array_artifacts = curated.get("array_artifacts") if isinstance(curated.get("array_artifacts"), dict) else {}
    value = str(array_artifacts.get("input_sha256") or "").strip()
    if value:
        return value
    wgs_artifacts = curated.get("wgs_artifacts") if isinstance(curated.get("wgs_artifacts"), dict) else {}
    return str(wgs_artifacts.get("sha256") or "").strip()


def _blocked_policy(reason: str) -> dict[str, Any]:
    """Fail-closed policy shape consumed by the renderer when verification cannot run."""
    return {
        "ready_for_requested_operation": False,
        "planes": {name: {"state": "BLOCKED"} for name in REQUIRED_PLANES},
        "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "BLOCKED", "blocking": True}],
        "source": {"status": "NÃO DISPONÍVEL", "reason": reason},
    }


def assemble_release(curated: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Assemble a release only from a Policy Control verdict re-executed for this case."""
    result = copy.deepcopy(curated)
    blockers: list[str] = []

    case_id = str(curated.get("case_id") or "").strip()
    input_sha256 = _curated_input_sha256(curated)
    try:
        if not case_id:
            raise PolicyEvaluationVerificationError("curated manifest case_id is missing")
        if not input_sha256:
            raise PolicyEvaluationVerificationError("curated manifest primary input SHA-256 is missing")
        verified_policy = verify_policy_evaluation(
            policy,
            case_id=case_id,
            input_sha256=input_sha256,
            required_output="FINAL_AUDITED_REPORT",
        )
        result["policy_evaluation"] = copy.deepcopy(verified_policy)
        result["policy_evaluation_verification"] = {
            "status": "VERIFICADO",
            "method": "policy-control-reexecution",
            "manifest_sha256": verified_policy["manifest_sha256"],
        }
    except PolicyEvaluationVerificationError as exc:
        reason = str(exc)
        verified_policy = _blocked_policy(reason)
        result["policy_evaluation"] = verified_policy
        result["policy_evaluation_verification"] = {
            "status": "NÃO DISPONÍVEL",
            "method": "policy-control-reexecution",
            "reason": reason,
        }
        blockers.append("policy_evaluation_binding")

    publication = result.get("publication_gate") if isinstance(result.get("publication_gate"), dict) else {}
    for key in REQUIRED_PUBLICATION:
        if publication.get(key) is not True:
            blockers.append(key)

    if verified_policy.get("ready_for_requested_operation") is not True:
        blockers.append("policy_evaluation")

    planes = verified_policy.get("planes") if isinstance(verified_policy.get("planes"), dict) else {}
    for name in REQUIRED_PLANES:
        plane = planes.get(name) if isinstance(planes.get(name), dict) else {}
        if plane.get("state") != "PASS":
            blockers.append(f"plane:{name}")

    gates = verified_policy.get("gates") if isinstance(verified_policy.get("gates"), list) else []
    final_audit = next((g for g in gates if isinstance(g, dict) and g.get("gate") == "FINAL_AUDIT_GATE"), None)
    if not isinstance(final_audit, dict) or final_audit.get("state") != "PASS":
        blockers.append("FINAL_AUDIT_GATE")

    blockers = list(dict.fromkeys(blockers))
    publication = dict(publication)
    publication["passed"] = not blockers
    result["publication_gate"] = publication
    result["report_release_status"] = "VERIFICADO" if not blockers else "NÃO DISPONÍVEL"
    result["report_release_blockers"] = blockers
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    curated = json.loads(Path(args.curated).read_text(encoding="utf-8"))
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    result = assemble_release(curated, policy)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "report_release_status": result["report_release_status"], "blockers": result["report_release_blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    )
    write(
        "tests/test_report_release_assembly.py",
        r'''
import copy
import unittest

from tests.test_policy_evaluation_binding import INPUT_SHA, real_evaluation


def curated(*, consent: bool = True, evidence: bool = True):
    return {
        "case_id": "CASE-1",
        "array_artifacts": {"input_sha256": INPUT_SHA},
        "publication_gate": {
            "consent_verified": consent,
            "qc_verified": True,
            "evidence_verified": evidence,
            "placeholders_resolved": True,
            "passed": False,
        },
    }


class ReportReleaseAssemblyTest(unittest.TestCase):
    def test_reexecuted_policy_plus_verified_prerequisites_releases_reports(self):
        from scripts.prepare_report_release import assemble_release

        policy = real_evaluation()
        result = assemble_release(curated(), policy)
        self.assertTrue(result["publication_gate"]["passed"])
        self.assertEqual(result["policy_evaluation"], policy)
        self.assertEqual(result["policy_evaluation_verification"]["status"], "VERIFICADO")
        self.assertEqual(result["report_release_status"], "VERIFICADO")

    def test_policy_pass_cannot_override_missing_evidence_or_consent(self):
        from scripts.prepare_report_release import assemble_release

        result = assemble_release(curated(consent=False, evidence=False), real_evaluation())
        self.assertFalse(result["publication_gate"]["passed"])
        self.assertEqual(result["report_release_status"], "NÃO DISPONÍVEL")
        self.assertIn("consent_verified", result["report_release_blockers"])
        self.assertIn("evidence_verified", result["report_release_blockers"])

    def test_forged_complete_pass_is_blocked_by_policy_reexecution(self):
        from genoma_policy.models import evaluation_binding
        from scripts.prepare_report_release import assemble_release

        policy = real_evaluation()
        policy["evaluated_manifest"]["qc"]["passed"] = False
        binding = evaluation_binding(policy["evaluated_manifest"])
        policy["binding"] = binding
        for key in ("case_id", "session_id", "input_sha256", "operation", "manifest_sha256"):
            policy[key] = copy.deepcopy(binding[key])
        result = assemble_release(curated(), policy)
        self.assertFalse(result["publication_gate"]["passed"])
        self.assertEqual(result["policy_evaluation_verification"]["status"], "NÃO DISPONÍVEL")
        self.assertIn("policy_evaluation_binding", result["report_release_blockers"])


if __name__ == "__main__":
    unittest.main()
''',
    )


def green_phase() -> None:
    run("git", "diff", "--check")
    run(
        sys.executable,
        "-m",
        "unittest",
        "tests.test_policy_evaluation_binding",
        "tests.test_report_release_assembly",
        "tests.test_target_expansion.StrictReferenceDecodingTest",
        "-v",
    )
    run(
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "policy_engine/tests",
        "-p",
        "test_policy_engine.py",
        "-v",
        env={"PYTHONPATH": str(ROOT / "policy_engine")},
    )
    run(sys.executable, "scripts/validate_repo.py")
    run(sys.executable, "scripts/verify_supply_chain_lock.py")
    run(
        sys.executable,
        "-m",
        "unittest",
        "tests.test_pr30_regressions",
        "tests.test_reporting_provenance_regressions",
        "tests.test_authority_regressions",
        "-v",
    )
    print("GREEN VERIFIED: blocker repairs pass targeted policy/reference/provenance gates")


def main() -> None:
    red_phase()
    implement_policy_envelope()
    implement_strict_decoding()
    write_final_tests()
    implement_release_boundary()
    green_phase()


if __name__ == "__main__":
    main()
