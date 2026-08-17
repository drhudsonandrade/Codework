#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def count_vcf_records(path: Path) -> int:
    import gzip
    opener = gzip.open if path.suffix == ".gz" else open
    count = 0
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line and not line.startswith("#"):
                count += 1
    return count


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--case-id", required=True)
    p.add_argument("--sample-id", required=True)
    p.add_argument("--vcf", required=True)
    p.add_argument("--runtime-gate", required=True)
    p.add_argument("--evidence", action="append", default=[])
    p.add_argument("--output", required=True)
    args = p.parse_args()

    vcf = Path(args.vcf)
    runtime = json.loads(Path(args.runtime_gate).read_text(encoding="utf-8"))
    if runtime.get("ready_for_real_calling") is not True or runtime.get("status") != "EXECUTADO":
        raise SystemExit("NÃO DISPONÍVEL: current-session Runtime/Resource Gate is not fully EXECUTADO")
    sources = []
    for value in args.evidence:
        snapshot = json.loads(Path(value).read_text(encoding="utf-8"))
        if snapshot.get("status") == "VERIFICADO":
            sources.append(snapshot)

    capability_matrix = {
        "SNV": {"status": "EXECUTADO", "method": "GATK HaplotypeCaller + bcftools normalization"},
        "small_indel": {"status": "EXECUTADO", "method": "GATK HaplotypeCaller + bcftools normalization"},
        "CNV": {"status": "NÃO DISPONÍVEL", "reason": "specialized validated CNV workflow not yet executed"},
        "SV": {"status": "NÃO DISPONÍVEL", "reason": "specialized validated structural-variant workflow not yet executed"},
        "repeat_expansion": {"status": "NÃO DISPONÍVEL", "reason": "specialized repeat-expansion workflow not yet executed"},
        "HLA": {"status": "NÃO DISPONÍVEL", "reason": "specialized HLA typing workflow not yet executed"},
        "CYP2D6": {"status": "NÃO DISPONÍVEL", "reason": "generic VCF is insufficient for CNV/hybrid/phase-sensitive diplotyping"},
        "mtDNA_specialized": {"status": "NÃO DISPONÍVEL", "reason": "dedicated mtDNA calling/haplogroup workflow not yet executed"},
    }

    payload = {
        "schema": "genoma-wgs-curation-manifest-v1",
        "case_id": args.case_id,
        "sample_id": args.sample_id,
        "ruleset": {"status": "VIGENTE", "version": "v3.3", "effective_date": "14/08/2026"},
        "summary": "Pipeline técnico executado para SNV/indel. Interpretação clínica e publicação final permanecem bloqueadas até curadoria, Evidence Gate e Final Audit.",
        "wgs_artifacts": {
            "normalized_vcf": str(vcf),
            "sha256": sha256_file(vcf),
            "record_count": count_vcf_records(vcf),
        },
        "capability_matrix": capability_matrix,
        "unsupported_variant_classes": [name for name, item in capability_matrix.items() if item["status"] == "NÃO DISPONÍVEL"],
        "sources": sources,
        "claims": [],
        "findings": [],
        "sections": {},
        "limitations": "SNV/indel technical output is not equivalent to a complete genome interpretation. Unsupported classes remain explicit blind spots.",
        "execution_manifest": [
            {"step": "WGS short-variant calling", "status": "EXECUTADO", "evidence_refs": ["runtime-gate", "normalized-vcf"]},
            {"step": "clinical curation", "status": "PROPOSTO", "evidence_refs": []},
            {"step": "final report publication", "status": "PROPOSTO", "evidence_refs": []},
        ],
        "publication_gate": {
            "passed": False,
            "consent_verified": False,
            "qc_verified": True,
            "evidence_verified": False,
            "placeholders_resolved": False,
        },
        "policy_evaluation": {
            "ready_for_requested_operation": False,
            "planes": {
                "policy_control": {"state": "PASS"},
                "scientific_data": {"state": "PASS"},
                "evidence": {"state": "PENDING"},
                "audit": {"state": "PENDING"},
            },
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PENDING", "blocking": True}],
        },
        "post_deployment_status": "PENDENTE",
        "runtime_gate": runtime,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
