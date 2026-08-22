#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative
from reporting.consent import ConsentError, validate_record as validate_consent
from reporting.provenance import witness_verdict


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    qc: dict[str, Any],
    annotation: dict[str, Any],
    qc_path: Path,
    annotation_path: Path,
    *,
    consent: dict[str, Any] | None = None,
    consent_sha256: str | None = None,
    witness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the manifest the policy engine evaluates for one array case.

    Three fields the `MANIFEST_STRUCTURE_GATE` requires — `session_id`, `operation` and
    `section_attestations` — were absent, and their absence did more than fail that gate.
    `analysis_relevant` is read from `operation`, and `_as_bool(None)` is false, so the
    missing block switched DATA_PROVENANCE_GATE, CONSENT_GATE, QC_GATE and
    RUNTIME_RESOURCE_GATE off — each returning PASS without testing anything. Evaluated on a
    real case, the engine reported the whole scientific-data plane PASS while its four gates
    had been silenced by omission, and only the structure gate's own FAIL kept the run from
    being declared ready.

    Declaring the operation turns those gates back on, which means this manifest now fails
    for the reasons it should: an array run with no consent record does not pass
    CONSENT_GATE. That is the intended outcome — the gate is answering, not being skipped.
    """
    if qc.get("operational_status") != "VERIFICADO" or qc.get("gates", {}).get("LIMITED_INTERPRETATION_GATE", {}).get("state") != "PASS":
        raise ValueError("array QC is not VERIFICADO/PASS")
    if annotation.get("case_id") != qc.get("case_id") or annotation.get("input_sha256") != qc.get("input", {}).get("sha256"):
        raise ValueError("annotation does not bind to the same case/input as QC")

    evidence_verified = annotation.get("operational_status") == "VERIFICADO" and annotation.get("evidence_gate", {}).get("state") == "PASS"
    observed = annotation.get("observations", []) if isinstance(annotation.get("observations"), list) else []
    sources = [x for x in annotation.get("evidence_retrievals", []) if isinstance(x, dict) and x.get("status") == "VERIFICADO"]
    input_sha = str(qc.get("input", {}).get("sha256") or "")
    consent_block: dict[str, Any] = {
        "verified": False,
        "version": None,
        "authorized_domains": [],
        "basis": "nenhum registro de consentimento foi fornecido a esta execução",
    }
    if consent:
        try:
            validate_consent(consent, case_id=qc.get("case_id"), input_sha256=input_sha)
        except ConsentError as exc:
            # Refused, not silently downgraded: the operator supplied something they believed
            # was consent, and the manifest must say why it does not authorise this run.
            consent_block["basis"] = f"registro de consentimento recusado: {exc}"
        else:
            consent_block = {
                "verified": True,
                "version": consent.get("version"),
                "authorized_domains": list(consent.get("authorized_domains") or []),
                "subject_id": consent.get("subject_id"),
                "granted_at": consent.get("granted_at"),
                "expires_at": consent.get("expires_at"),
                "instrument": consent.get("instrument"),
                "instrument_version": consent.get("instrument_version"),
                "captured_by": consent.get("captured_by"),
                # The exact record evaluated, so the manifest and the report can be shown to
                # have acted on the same bytes.
                "record_sha256": consent_sha256,
                "basis": consent.get("basis"),
            }
    # `post_deployment_status` was the literal "PENDING" beside a POST_DEPLOYMENT_GATE that
    # reads `manifest["post_deployment"]` — a key this builder never wrote. The gate therefore
    # reported unmet criteria on every run regardless of any evidence, and the string next to
    # it was decoration nothing consulted.
    #
    # A witness changes that, and only a witness does. It is judged by the same function the
    # report compiler uses, so the engine and the report cannot reach different conclusions
    # about the same file, and only the block the live gate actually ruled on is submitted.
    post_deployment_claim: dict[str, Any] | None = None
    post_deployment_status = "PENDING"
    if witness:
        verdict = witness_verdict(witness)
        claim = witness.get("post_deployment_claim")
        if verdict["status"] == "PASS" and isinstance(claim, dict):
            post_deployment_claim = dict(claim)
            post_deployment_status = "PASS"
    payload: dict[str, Any] = {
        "schema": "genoma-array-curation-manifest-v1",
        "case_id": qc.get("case_id"),
        # Derived from the case and the exact bytes analysed, so the identifier is
        # reproducible from the artifacts and cannot be reused across inputs.
        "session_id": f"array-{qc.get('case_id')}-{input_sha[:16]}",
        "operation": {
            "name": "SNP-array curated interpretation",
            # True, and it is the whole point: this switches the provenance, consent and QC
            # gates back on. Declaring false to make them pass would be the silencing this
            # manifest previously achieved by omission.
            "analysis_relevant": True,
            # False on evidence: this lane observes an array export. It performs no read
            # alignment or variant calling, so the NGS runtime gate does not apply — and
            # says so explicitly instead of leaving the field absent.
            "requires_real_calling": False,
            "output": "ANALYSIS",
        },
        # The consent contract, read from the operator's record and *validated* against this
        # case and these bytes. It used to be copied field by field out of whatever dict the
        # caller supplied, so `{"verified": true, "version": "x", "authorized_domains":
        # ["CLÍNICO"]}` cleared CONSENT_GATE — three fields anyone can type, standing between
        # a genomic file and a published report about a person.
        "consent": consent_block,
        "qc": {
            "status": qc.get("operational_status"),
            "passed": qc.get("gates", {}).get("LIMITED_INTERPRETATION_GATE", {}).get("state") == "PASS",
            "evidence_refs": [f"array-qc:{sha256_file(qc_path)}"],
        },
        "inputs": [
            {
                "id": "array-input",
                "kind": "snp-array-export",
                "source": "consumer genotyping export, harmonized",
                "sha256": input_sha,
            },
            {
                "id": "array-qc",
                "kind": "qc-artifact",
                "source": "array_pipeline.qc",
                "sha256": sha256_file(qc_path),
                "transformed": True,
                "parent_sha256": input_sha,
            },
            {
                "id": "partial-annotation",
                "kind": "annotation-artifact",
                "source": "scripts/annotate_partial_genome.py",
                "sha256": sha256_file(annotation_path),
                "transformed": True,
                "parent_sha256": input_sha,
            },
        ],
        "section_attestations": [],
        "ruleset": normative.attested_ruleset_block(),
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
        "post_deployment_status": post_deployment_status,
    }
    if post_deployment_claim is not None:
        payload["post_deployment"] = post_deployment_claim
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--qc", required=True)
    p.add_argument("--annotation", required=True)
    p.add_argument("--output", required=True)
    p.add_argument(
        "--consent",
        help="path to the record written by scripts/capture_consent.py. It used to accept "
        "inline JSON, which meant the three fields CONSENT_GATE checks could be typed on the "
        "command line. Without a record the gate fails, which is the honest answer for a run "
        "that carries no consent instrument.",
    )
    p.add_argument(
        "--post-deployment-witness",
        help="witness written by scripts/run_live_post_deployment_smoke.py. Without it the "
        "manifest declares no post_deployment block and POST_DEPLOYMENT_GATE stays PENDENTE.",
    )
    args = p.parse_args()
    qc_path, annotation_path = Path(args.qc), Path(args.annotation)
    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        consent = None
        consent_sha256 = None
        if args.consent:
            raw = Path(args.consent).read_bytes()
            consent = json.loads(raw.decode("utf-8"))
            if not isinstance(consent, dict):
                raise ValueError("consent record must decode to a JSON object")
            consent_sha256 = hashlib.sha256(raw).hexdigest()
        witness = None
        if args.post_deployment_witness:
            witness = json.loads(
                Path(args.post_deployment_witness).read_text(encoding="utf-8")
            )
            if not isinstance(witness, dict):
                raise ValueError("post-deployment witness must decode to a JSON object")
        payload = build_manifest(
            qc, annotation, qc_path, annotation_path,
            consent=consent, consent_sha256=consent_sha256, witness=witness,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"NÃO DISPONÍVEL: {exc}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
