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
    case_id = manifest.get("case_id")
    session_id = manifest.get("session_id")
    return {
        "case_id": case_id.strip() if isinstance(case_id, str) else "",
        "session_id": session_id.strip() if isinstance(session_id, str) else "",
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

    def to_dict(self, *, include_evaluated_manifest: bool = False) -> dict[str, Any]:
        """Serialize a public evaluation, omitting case and manifest data by default."""
        snapshot = copy.deepcopy(self.evaluated_manifest)
        binding = evaluation_binding(snapshot)
        producer = {
            "id": POLICY_EVALUATION_PRODUCER,
            "version": str(self.metadata.get("engine_version") or ""),
        }
        payload = {
            "schema": POLICY_EVALUATION_SCHEMA,
            "producer": producer,
            "manifest_sha256": binding["manifest_sha256"],
            "ready_for_requested_operation": self.ready,
            "ruleset": self.ruleset,
            "gates": [g.to_dict() for g in self.gates],
            "section_coverage": self.section_coverage,
            "metadata": self.metadata,
            "planes": self.planes,
        }
        if include_evaluated_manifest:
            payload.update(
                {
                    "case_id": binding["case_id"],
                    "session_id": binding["session_id"],
                    "input_sha256": binding["input_sha256"],
                    "operation": copy.deepcopy(binding["operation"]),
                    "binding": binding,
                    "evaluated_manifest": snapshot,
                }
            )
        return payload

    def to_internal_dict(self) -> dict[str, Any]:
        """Serialize the sealed internal artifact required for deterministic re-execution."""
        return self.to_dict(include_evaluated_manifest=True)
