from __future__ import annotations

from typing import Any

from .gates_common import (
    ALLOWED_DOMAIN,
    ALLOWED_NATURE,
    ALLOWED_OPERATIONAL,
    ALLOWED_PRIORITY,
    RUNTIME_REQUIRED_KEYS,
    _as_bool,
    _gate,
    _get_list,
)
from .ruleset import RulesetError, enforce_unique_active_ruleset, verify_external_manifest


class CoreGates:
    def _ruleset_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        try:
            enforce_unique_active_ruleset(self.ruleset.path.parent, self.ruleset.path)
            if self.external_manifest:
                verify_external_manifest(self.ruleset, self.external_manifest)
        except RulesetError as exc:
            reasons.append(str(exc))
        declared = manifest.get("ruleset", {}) if isinstance(manifest.get("ruleset"), dict) else {}
        if not declared:
            reasons.append("manifest ruleset identity is missing")
        else:
            if declared.get("status") != self.ruleset.status:
                reasons.append("manifest ruleset status differs from canonical VIGENTE")
            if declared.get("version") != self.ruleset.version:
                reasons.append("manifest ruleset version differs from canonical v3.4")
            if declared.get("effective_date") != self.ruleset.effective_date:
                reasons.append("manifest ruleset effective date differs from canonical ruleset")
            if declared.get("canonical_filename") != self.ruleset.canonical_filename:
                reasons.append("manifest ruleset canonical filename differs from canonical ruleset")
            if declared.get("sha256") != self.ruleset.sha256:
                reasons.append("manifest ruleset SHA-256 differs from canonical ruleset")
        return _gate("RULESET_GATE", not reasons, reasons)

    def _taxonomy_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if not isinstance(claim, dict):
                reasons.append(f"claim[{idx}] is not an object")
                continue
            if claim.get("nature") not in ALLOWED_NATURE:
                reasons.append(f"claim[{idx}] has invalid or missing nature")
            if claim.get("domain") not in ALLOWED_DOMAIN:
                reasons.append(f"claim[{idx}] has invalid or missing domain")
            if claim.get("status") not in ALLOWED_OPERATIONAL:
                reasons.append(f"claim[{idx}] has invalid or missing operational status")
            if claim.get("priority") not in ALLOWED_PRIORITY:
                reasons.append(f"claim[{idx}] has invalid or missing priority")
        return _gate("TAXONOMY_GATE", not reasons, reasons)

    def _provenance_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if not _as_bool(operation.get("analysis_relevant")):
            return _gate("DATA_PROVENANCE_GATE", True)
        reasons: list[str] = []
        inputs = _get_list(manifest, "inputs")
        if not inputs:
            reasons.append("analysis-relevant operation has no input artifacts")
        for idx, artifact in enumerate(inputs):
            if not isinstance(artifact, dict):
                reasons.append(f"input[{idx}] is not an object")
                continue
            for field in ("id", "kind", "source", "sha256"):
                if not artifact.get(field):
                    reasons.append(f"input[{idx}] missing {field}")
            if artifact.get("transformed") and not artifact.get("parent_sha256"):
                reasons.append(f"input[{idx}] transformed without parent provenance")
        return _gate("DATA_PROVENANCE_GATE", not reasons, reasons)

    def _consent_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if not _as_bool(operation.get("analysis_relevant")):
            return _gate("CONSENT_GATE", True)
        consent = manifest.get("consent", {}) if isinstance(manifest.get("consent"), dict) else {}
        reasons: list[str] = []
        if not _as_bool(consent.get("verified")):
            reasons.append("consent/scope not verified")
        if not consent.get("version"):
            reasons.append("consent version missing")
        if not consent.get("authorized_domains"):
            reasons.append("authorized domains missing")
        return _gate("CONSENT_GATE", not reasons, reasons)

    def _qc_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if not _as_bool(operation.get("analysis_relevant")):
            return _gate("QC_GATE", True)
        qc = manifest.get("qc", {}) if isinstance(manifest.get("qc"), dict) else {}
        reasons: list[str] = []
        if qc.get("status") not in {"EXECUTADO", "VERIFICADO"}:
            reasons.append("QC is not EXECUTADO or VERIFICADO")
        if qc.get("passed") is not True:
            reasons.append("QC did not pass")
        if not qc.get("evidence_refs"):
            reasons.append("QC evidence_refs missing")
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if (
                isinstance(claim, dict)
                and claim.get("technical_quality_flag") == "LOW"
                and claim.get("nature") == "FATO CONFIRMADO"
            ):
                reasons.append(f"claim[{idx}] promoted despite low technical quality")
        return _gate("QC_GATE", not reasons, reasons)

    def _runtime_resource_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if not _as_bool(operation.get("requires_real_calling")):
            return _gate("RUNTIME_RESOURCE_GATE", True)
        runtime = manifest.get("runtime_resource_gate", {}) if isinstance(manifest.get("runtime_resource_gate"), dict) else {}
        reasons: list[str] = []
        if runtime.get("session_id") != manifest.get("session_id"):
            reasons.append("runtime/resource gate was not executed for this session")
        checks = runtime.get("checks", {}) if isinstance(runtime.get("checks"), dict) else {}
        for key in RUNTIME_REQUIRED_KEYS:
            item = checks.get(key, {}) if isinstance(checks.get(key), dict) else {}
            if item.get("status") != "EXECUTADO":
                reasons.append(f"runtime check {key} is not EXECUTADO")
            if not item.get("evidence_ref"):
                reasons.append(f"runtime check {key} lacks evidence_ref")
        if runtime.get("inherited_from_previous_session") is True:
            reasons.append("runtime gate cannot inherit PASS from another session")
        return _gate("RUNTIME_RESOURCE_GATE", not reasons, reasons)
