from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
        return {
            "ready_for_requested_operation": self.ready,
            "ruleset": self.ruleset,
            "gates": [g.to_dict() for g in self.gates],
            "section_coverage": self.section_coverage,
            "metadata": self.metadata,
            "planes": self.planes,
        }
