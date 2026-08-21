from __future__ import annotations

from typing import Any

from .gates_common import (ALLOWED_DOMAIN, ALLOWED_NATURE, ALLOWED_OPERATIONAL, ALLOWED_OUTPUT, ALLOWED_PRIORITY, RUNTIME_REQUIRED_KEYS, _as_bool, _gate, _get_list)
from .ruleset import RulesetError, enforce_unique_active_ruleset, verify_external_manifest

class CoreGates:
    def _manifest_structure_gate(self, manifest: dict[str, Any]):
        """Refuse a manifest that cannot be honestly evaluated.

        `analysis_relevant` and `requires_real_calling` switch the provenance, consent, QC
        and runtime gates off when false. A manifest that omits `operation`, or supplies a
        non-boolean, therefore silences those gates while still reporting PASS. The
        execution-manifest schema already declares these fields required; this enforces the
        same contract at evaluation time so a malformed manifest fails closed instead of
        quietly disabling the control plane.
        """
        reasons: list[str] = []
        for key in ("case_id", "session_id"):
            value = manifest.get(key)
            if not isinstance(value, str) or not value.strip():
                reasons.append(f"{key} is missing or not a non-empty string")
        if not isinstance(manifest.get("ruleset"), dict):
            reasons.append("ruleset block is missing or not an object")
        if not isinstance(manifest.get("section_attestations"), list):
            reasons.append("section_attestations is missing or not a list")

        operation = manifest.get("operation")
        if not isinstance(operation, dict):
            reasons.append("operation block is missing or not an object")
        else:
            if not isinstance(operation.get("name"), str) or not operation["name"].strip():
                reasons.append("operation.name is missing or not a non-empty string")
            for key in ("analysis_relevant", "requires_real_calling"):
                if not isinstance(operation.get(key), bool):
                    reasons.append(f"operation.{key} must be declared explicitly as a boolean")
            if operation.get("output") not in ALLOWED_OUTPUT:
                reasons.append(f"operation.output must be one of {sorted(ALLOWED_OUTPUT)}")
        return _gate("MANIFEST_STRUCTURE_GATE", not reasons, reasons)

    def _ruleset_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        try:
            enforce_unique_active_ruleset(self.ruleset.path.parent, self.ruleset.path)
            if self.external_manifest:
                verify_external_manifest(self.ruleset, self.external_manifest)
        except RulesetError as exc:
            reasons.append(str(exc))
        # A manifest must declare the normative identity it was produced under, in full.
        # The test was `not in (None, canonical)`, so an omitted version or SHA-256 passed:
        # the gate could only catch a *wrong* declaration, never a missing one, and a
        # manifest bound to no ruleset at all was indistinguishable from one bound to this
        # ruleset. Absence is now its own reason.
        declared = manifest.get("ruleset", {}) if isinstance(manifest.get("ruleset"), dict) else {}
        if not declared:
            reasons.append("manifest declares no ruleset block; the normative identity it was produced under is unstated")
        else:
            for field, canonical in (("version", self.ruleset.version), ("sha256", self.ruleset.sha256)):
                value = declared.get(field)
                if value is None: reasons.append(f"manifest ruleset {field} is missing; a manifest must name the ruleset it is bound to")
                elif value != canonical: reasons.append(f"manifest ruleset {field} differs from the canonical ruleset")
        return _gate("RULESET_GATE", not reasons, reasons)

    def _taxonomy_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if not isinstance(claim, dict): reasons.append(f"claim[{idx}] is not an object"); continue
            if claim.get("nature") not in ALLOWED_NATURE: reasons.append(f"claim[{idx}] has invalid or missing nature")
            if claim.get("domain") not in ALLOWED_DOMAIN: reasons.append(f"claim[{idx}] has invalid or missing domain")
            if claim.get("status") not in ALLOWED_OPERATIONAL: reasons.append(f"claim[{idx}] has invalid or missing operational status")
            if claim.get("priority") not in ALLOWED_PRIORITY: reasons.append(f"claim[{idx}] has invalid or missing priority")
        return _gate("TAXONOMY_GATE", not reasons, reasons)

    def _provenance_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if not _as_bool(operation.get("analysis_relevant")): return _gate("DATA_PROVENANCE_GATE", True)
        reasons: list[str] = []; inputs = _get_list(manifest, "inputs")
        if not inputs: reasons.append("analysis-relevant operation has no input artifacts")
        for idx, artifact in enumerate(inputs):
            if not isinstance(artifact, dict): reasons.append(f"input[{idx}] is not an object"); continue
            for field in ("id", "kind", "source", "sha256"):
                if not artifact.get(field): reasons.append(f"input[{idx}] missing {field}")
            if artifact.get("transformed") and not artifact.get("parent_sha256"): reasons.append(f"input[{idx}] transformed without parent provenance")
        return _gate("DATA_PROVENANCE_GATE", not reasons, reasons)

    def _consent_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if not _as_bool(operation.get("analysis_relevant")): return _gate("CONSENT_GATE", True)
        consent = manifest.get("consent", {}) if isinstance(manifest.get("consent"), dict) else {}; reasons: list[str] = []
        if not _as_bool(consent.get("verified")): reasons.append("consent/scope not verified")
        if not consent.get("version"): reasons.append("consent version missing")
        if not consent.get("authorized_domains"): reasons.append("authorized domains missing")
        return _gate("CONSENT_GATE", not reasons, reasons)

    def _qc_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if not _as_bool(operation.get("analysis_relevant")): return _gate("QC_GATE", True)
        qc = manifest.get("qc", {}) if isinstance(manifest.get("qc"), dict) else {}; reasons: list[str] = []
        if qc.get("status") not in {"EXECUTADO", "VERIFICADO"}: reasons.append("QC is not EXECUTADO or VERIFICADO")
        if qc.get("passed") is not True: reasons.append("QC did not pass")
        if not qc.get("evidence_refs"): reasons.append("QC evidence_refs missing")
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if isinstance(claim, dict) and claim.get("technical_quality_flag") == "LOW" and claim.get("nature") == "FATO CONFIRMADO": reasons.append(f"claim[{idx}] promoted despite low technical quality")
        return _gate("QC_GATE", not reasons, reasons)

    def _runtime_resource_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if not _as_bool(operation.get("requires_real_calling")): return _gate("RUNTIME_RESOURCE_GATE", True)
        runtime = manifest.get("runtime_resource_gate", {}) if isinstance(manifest.get("runtime_resource_gate"), dict) else {}; reasons: list[str] = []
        if runtime.get("session_id") != manifest.get("session_id"): reasons.append("runtime/resource gate was not executed for this session")
        checks = runtime.get("checks", {}) if isinstance(runtime.get("checks"), dict) else {}
        for key in RUNTIME_REQUIRED_KEYS:
            item = checks.get(key, {}) if isinstance(checks.get(key), dict) else {}
            if item.get("status") != "EXECUTADO": reasons.append(f"runtime check {key} is not EXECUTADO")
            if not item.get("evidence_ref"): reasons.append(f"runtime check {key} lacks evidence_ref")
        if runtime.get("inherited_from_previous_session") is True: reasons.append("runtime gate cannot inherit PASS from another session")
        return _gate("RUNTIME_RESOURCE_GATE", not reasons, reasons)
