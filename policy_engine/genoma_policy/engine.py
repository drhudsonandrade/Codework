from __future__ import annotations

from pathlib import Path
from typing import Any

from .gates_audit import AuditGates
from .gates_core import CoreGates
from .gates_evidence import EvidenceGates
from .gates_common import CRITICAL_FINAL_AUDIT_KEYS
from .models import EvaluationReport
from .ruleset import Ruleset, load_ruleset


class PolicyEngine(CoreGates, EvidenceGates, AuditGates):
    def __init__(self, ruleset: Ruleset, *, external_manifest: str | Path | None = None):
        self.ruleset = ruleset
        self.external_manifest = Path(external_manifest) if external_manifest else None

    @classmethod
    def from_paths(cls, ruleset_path: str | Path, external_manifest: str | Path | None = None) -> "PolicyEngine":
        return cls(load_ruleset(ruleset_path), external_manifest=external_manifest)

    def evaluate(self, manifest: dict[str, Any]) -> EvaluationReport:
        report = EvaluationReport(ruleset=self.ruleset.metadata())
        report.gates.extend([
            self._ruleset_gate(manifest), self._taxonomy_gate(manifest), self._provenance_gate(manifest),
            self._consent_gate(manifest), self._qc_gate(manifest), self._runtime_resource_gate(manifest),
            self._evidence_gate(manifest), self._capability_honesty_gate(manifest), self._clinical_safety_gate(manifest),
            self._negative_evidence_gate(manifest), self._build_harmonization_gate(manifest), self._clinvar_conflict_gate(manifest),
            self._ancestry_gate(manifest), self._reproductive_gate(manifest), self._pgx_complex_locus_gate(manifest),
            self._trait_determinism_gate(manifest), self._screening_diagnosis_gate(manifest),
            self._section_coverage_gate(manifest), self._final_audit_gate(manifest), self._post_deployment_gate(manifest),
        ])
        report.section_coverage = self._section_coverage_summary(manifest)
        report.metadata = {
            "engine": "genoma-policy-engine", "engine_version": "0.3.0", "rule_count": len(self.ruleset.sections),
            "note": "POST-DEPLOYMENT is a distinct project gate and is never inferred from unit tests or synthetic CI fixtures.",
        }
        report.planes = self._plane_summary(report.gates)
        return report


def evaluate_manifest(ruleset_path: str | Path, manifest: dict[str, Any], external_manifest: str | Path | None = None) -> EvaluationReport:
    return PolicyEngine.from_paths(ruleset_path, external_manifest).evaluate(manifest)
