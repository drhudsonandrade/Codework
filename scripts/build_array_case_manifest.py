#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

RULESET = {"status": "VIGENTE", "version": "v3.3", "effective_date": "14/08/2026", "sha256": "187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(qc: dict[str, Any], annotation: dict[str, Any], qc_path: Path, annotation_path: Path) -> dict[str, Any]:
    if qc.get("operational_status") != "VERIFICADO" or qc.get("gates", {}).get("LIMITED_INTERPRETATION_GATE", {}).get("state") != "PASS":
        raise ValueError("array QC is not VERIFICADO/PASS")
    if annotation.get("case_id") != qc.get("case_id") or annotation.get("input_sha256") != qc.get("input", {}).get("sha256"):
        raise ValueError("annotation does not bind to the same case/input as QC")

    evidence_verified = annotation.get("operational_status") == "VERIFICADO" and annotation.get("evidence_gate", {}).get("state") == "PASS"
    observed = annotation.get("observations", []) if isinstance(annotation.get("observations"), list) else []
    sources = [x for x in annotation.get("evidence_retrievals", []) if isinstance(x, dict) and x.get("status") == "VERIFICADO"]
    payload: dict[str, Any] = {
        "schema": "genoma-array-curation-manifest-v1",
        "case_id": qc.get("case_id"),
        "ruleset": RULESET,
        "summary": "SNP-array Scientific Data Plane executed for interrogated target loci only. Clinical interpretation remains bounded by assay coverage, current evidence and confirmation requirements.",
        "array_artifacts": {
            "input_sha256": qc.get("input", {}).get("sha256"),
            "qc_sha256": sha256_file(qc_path),
            "annotation_sha256": sha256_file(annotation_path),
            "build": qc.get("input", {}).get("build"),
            "strand": qc.get("input", {}).get("strand"),
            "unique_rsids": qc.get("metrics", {}).get("unique_rsids"),
            "call_rate": qc.get("metrics", {}).get("call_rate"),
        },
        "capability_matrix": {
            "assayed_SNP_loci": {"status": "EXECUTADO", "method": "SNP-array observation + QC"},
            "targeted_evidence_retrieval": {"status": "VERIFICADO" if evidence_verified else ("PROPOSTO" if annotation.get("mode") == "plan-only" else "NÃO DISPONÍVEL"), "method": "bounded source-specific HTTPS adapters"},
            "CNV": {"status": "NÃO DISPONÍVEL", "reason": "not established by this SNP-array lane"},
            "SV": {"status": "NÃO DISPONÍVEL", "reason": "not established by this SNP-array lane"},
            "repeat_expansion": {"status": "NÃO DISPONÍVEL", "reason": "not established by this SNP-array lane"},
            "HLA": {"status": "NÃO DISPONÍVEL", "reason": "specialized HLA typing not executed"},
            "CYP2D6": {"status": "NÃO DISPONÍVEL", "reason": "array SNPs are insufficient for structural/hybrid/copy-number diplotyping"},
            "genome_wide_negative": {"status": "NÃO DISPONÍVEL", "reason": "non-assayed loci cannot be treated as negative evidence"}
        },
        "sources": sources,
        "claims": [],
        "findings": [],
        "sections": {
            "array_observations": observed,
            "array_qc": qc.get("gates", {}),
        },
        "limitations": annotation.get("limitations", []) + qc.get("limitations", []),
        "execution_manifest": [
            {"step": "SNP-array ingest/QC", "status": "EXECUTADO", "evidence_refs": ["array-qc"]},
            {"step": "target observation extraction", "status": "EXECUTADO", "evidence_refs": ["partial-annotation"]},
            {"step": "external evidence retrieval", "status": "VERIFICADO" if evidence_verified else ("PROPOSTO" if annotation.get("mode") == "plan-only" else "NÃO DISPONÍVEL"), "evidence_refs": [x.get("id") for x in sources]},
            {"step": "clinical curation", "status": "PROPOSTO", "evidence_refs": []},
            {"step": "final report publication", "status": "PROPOSTO", "evidence_refs": []}
        ],
        "publication_gate": {
            "passed": False,
            "consent_verified": False,
            "qc_verified": True,
            "evidence_verified": evidence_verified,
            "placeholders_resolved": False
        },
        "policy_evaluation": {
            "ready_for_requested_operation": False,
            "planes": {
                "policy_control": {"state": "PASS"},
                "scientific_data": {"state": "PASS"},
                "evidence": {"state": "PASS" if evidence_verified else "PENDING"},
                "audit": {"state": "PENDING"}
            },
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PENDING", "blocking": True}]
        },
        "post_deployment_status": "PENDING"
    }
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--qc", required=True)
    p.add_argument("--annotation", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    qc_path, annotation_path = Path(args.qc), Path(args.annotation)
    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        payload = build_manifest(qc, annotation, qc_path, annotation_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"NÃO DISPONÍVEL: {exc}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
