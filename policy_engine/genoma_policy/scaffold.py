from __future__ import annotations

from typing import Any

from .ruleset import Ruleset
from .version import __version__


def scaffold_manifest(ruleset: Ruleset, *, case_id: str = "CASE-ID") -> dict[str, Any]:
    return {
        "case_id": case_id,
        "session_id": "SESSION-ID",
        "ruleset": {
            "status": ruleset.status,
            "version": ruleset.version,
            "sha256": ruleset.sha256,
            "effective_date": ruleset.effective_date,
            "canonical_filename": ruleset.canonical_filename,
        },
        "operation": {
            "name": "genomic_analysis",
            "analysis_relevant": True,
            "requires_real_calling": False,
            "output": "ANALYSIS",
        },
        "inputs": [],
        "consent": {"verified": False, "version": "", "authorized_domains": []},
        "qc": {"status": "PROPOSTO", "passed": False, "evidence_refs": []},
        "runtime_resource_gate": {"session_id": "SESSION-ID", "checks": {}},
        "sources": [],
        "claims": [],
        "execution_manifest": [],
        "section_attestations": [
            {
                "section": section.number,
                "rule_id": section.rule_id,
                "rule_sha256": section.sha256,
                "applicability": "UNRESOLVED",
                "status": "PROPOSTO",
                "decision": "UNRESOLVED",
                "justification": "Pending explicit applicability and evidence review.",
                "evidence_refs": [],
                "trace": {
                    "attestation_id": f"att:{section.rule_id}",
                    "created_at": "1970-01-01T00:00:00Z",
                    "actor_type": "SOFTWARE",
                    "actor_id": "genoma-policy-engine-scaffold",
                    "method": "scaffold",
                    "run_id": "UNASSIGNED",
                    "input_sha256": [],
                    "output_sha256": [],
                    "tool_versions": {"genoma-policy-engine": __version__},
                },
            }
            for section in ruleset.sections
        ],
        "final_audit": {},
        "post_deployment": {
            "single_active_ruleset": False,
            "bootstrap_installed": False,
            "live_smoke_passed": False,
            "live_smoke_count": 0,
            "critical_failures": None,
            "identity_recovered": None,
        },
    }
