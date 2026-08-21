#!/usr/bin/env python3
"""Write the fail-closed curation manifest for a WGS run.

Three states in this file were constants rather than measurements: `post_deployment_status`
was the literal "PASS", which only the live Production Witness may grant and which the
four-plane audit refuses to grant even to itself; `qc_verified` was the literal True while
every other publication criterion was False; and the plane states were declared rather than
evaluated. The workflow also staged an evidence snapshot, checked it was non-empty, and then
never passed it, so `sources` came out empty on every run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def count_vcf_records(path: Path) -> int:
    """Count variant records, refusing a file that is not valid UTF-8.

    `errors="replace"` turned undecodable bytes into U+FFFD and counted the line anyway, so a
    truncated or corrupt VCF produced a plausible record count instead of an error. A caller
    cannot tell a real count from a repaired one, so the repair is not offered.
    """
    import gzip
    opener = gzip.open if path.suffix == ".gz" else open
    count = 0
    try:
        with opener(path, "rt", encoding="utf-8", errors="strict") as handle:
            for line in handle:
                if line and not line.startswith("#"):
                    count += 1
    except UnicodeDecodeError as exc:
        raise SystemExit(
            f"NÃO DISPONÍVEL: {path.name} is not valid UTF-8 ({exc}); a record count read "
            "over replaced bytes would describe a file that does not exist"
        ) from exc
    return count


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--case-id", required=True)
    p.add_argument("--sample-id", required=True)
    p.add_argument("--vcf", required=True)
    p.add_argument("--runtime-gate", required=True)
    p.add_argument("--evidence", action="append", default=[])
    p.add_argument(
        "--input-qc",
        help="QC artifact for the same sample; qc_verified is derived from it and is "
        "NÃO DISPONÍVEL without it",
    )
    p.add_argument("--output", required=True)
    args = p.parse_args()

    vcf = Path(args.vcf)
    runtime = json.loads(Path(args.runtime_gate).read_text(encoding="utf-8"))
    if runtime.get("ready_for_real_calling") is not True or runtime.get("status") != "EXECUTADO":
        raise SystemExit("NÃO DISPONÍVEL: current-session Runtime/Resource Gate is not fully EXECUTADO")

    sources = []
    rejected_evidence: list[str] = []
    for value in args.evidence:
        snapshot = json.loads(Path(value).read_text(encoding="utf-8"))
        if snapshot.get("status") == "VERIFICADO":
            sources.append(snapshot)
        else:
            # Counted rather than dropped: "no sources" and "sources that failed
            # verification" are different situations and used to look identical.
            rejected_evidence.append(f"{Path(value).name}: status={snapshot.get('status')!r}")

    # The workflow staged an evidence snapshot and never passed it, so this list was empty on
    # every run and nothing said so. A curation manifest that cites nothing is not curation.
    if not sources:
        raise SystemExit(
            "NÃO DISPONÍVEL: no VERIFICADO evidence snapshot was supplied via --evidence; "
            "a curation manifest with zero sources records no curation. "
            + (f"Rejected: {'; '.join(rejected_evidence)}" if rejected_evidence else "")
        )

    # Derived from the QC artifact bound to this run, never a constant. Without the artifact
    # the honest value is that QC was not verified here, not that it was.
    qc_verified = False
    qc_basis = "NÃO DISPONÍVEL: nenhum artefato de QC foi fornecido a esta execução"
    if args.input_qc:
        qc_path = Path(args.input_qc)
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
        qc_verified = qc.get("operational_status") == "VERIFICADO" and qc.get("passed") is not False
        qc_basis = (
            f"{qc_path.name} sha256={sha256_file(qc_path)} "
            f"operational_status={qc.get('operational_status')!r}"
        )

    # "EXECUTADO" said that calling ran. It did not say that nothing filtered the result,
    # that no per-variant annotation was performed, and that several standard preparation
    # metrics were never computed — so a reader could take "SNV: EXECUTADO" for "SNV: ready
    # to interpret". Each gap is now a named NÃO DISPONÍVEL beside the step that ran, and
    # the calling entries carry the limitation instead of standing alone.
    unfiltered_note = (
        "normalização bcftools não é filtragem: nenhuma variante foi removida ou marcada por "
        "VQSR, hard filters ou modelo equivalente, e nenhuma métrica Ti/Tv, het/hom, "
        "profundidade ou balanço alélico foi calculada. Chamadas não PASS e artefatos "
        "permanecem no arquivo."
    )
    capability_matrix = {
        "SNV": {
            "status": "EXECUTADO",
            "method": "GATK HaplotypeCaller + bcftools normalization",
            "filtering": "NÃO DISPONÍVEL",
            "limitation": unfiltered_note,
        },
        "small_indel": {
            "status": "EXECUTADO",
            "method": "GATK HaplotypeCaller + bcftools normalization",
            "filtering": "NÃO DISPONÍVEL",
            "limitation": unfiltered_note,
        },
        "variant_filtering": {
            "status": "NÃO DISPONÍVEL",
            "reason": "nenhuma estratégia de filtragem validada foi executada nem aferida "
            "contra conjunto-verdade (GIAB); o VCF entregue é bruto após normalização",
        },
        "per_variant_annotation": {
            "status": "NÃO DISPONÍVEL",
            "reason": "nenhuma variante foi consultada individualmente; não há consequência, "
            "transcrito MANE, HGVS, frequência populacional nem recuperação ClinVar/ClinGen "
            "por variante. O inventário de adaptadores registra capacidade, não consulta",
        },
        "duplicate_marking": {
            "status": "NÃO DISPONÍVEL",
            "reason": "MarkDuplicates ou equivalente não foi executado; leituras duplicadas "
            "não estão marcadas e inflam a evidência de suporte a cada chamada",
        },
        "coverage_and_callability": {
            "status": "NÃO DISPONÍVEL",
            "reason": "cobertura por região e loci chamáveis não foram medidos; ausência de "
            "chamada não pode ser distinguida de região não coberta",
        },
        "contamination_and_fingerprint": {
            "status": "NÃO DISPONÍVEL",
            "reason": "contaminação cruzada e identidade da amostra não foram aferidas; a "
            "correspondência entre estes dados e este caso não foi verificada por ensaio",
        },
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
        # Read from the sealed transport rather than restated here: a constant copy of the
        # normative identity is a copy that can fall behind the norm it names.
        "ruleset": normative.attested_ruleset_block(),
        "summary": (
            "Chamada técnica de SNV/indel executada sobre um VCF que não passou por "
            "filtragem validada nem por anotação variante a variante, e cuja preparação não "
            "inclui marcação de duplicatas, cobertura por região, contaminação ou "
            "fingerprint de amostra. Interpretação clínica e publicação final permanecem "
            "bloqueadas até curadoria, Evidence Gate e Final Audit. Veja capability_matrix: "
            "cada lacuna está nomeada, não implícita."
        ),
        "wgs_artifacts": {
            "normalized_vcf": str(vcf),
            "sha256": sha256_file(vcf),
            "record_count": count_vcf_records(vcf),
        },
        "capability_matrix": capability_matrix,
        "unsupported_variant_classes": [name for name, item in capability_matrix.items() if item["status"] == "NÃO DISPONÍVEL"],
        "sources": sources,
        "rejected_evidence": rejected_evidence,
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
            "qc_verified": qc_verified,
            "qc_basis": qc_basis,
            "evidence_verified": False,
            "placeholders_resolved": False,
        },
        "policy_evaluation": {
            "ready_for_requested_operation": False,
            # This script runs no policy engine, so it reports the planes as unevaluated
            # rather than declaring two of them PASS. A state written by whoever did not
            # measure it is the same failure as the PASS below.
            "planes": {
                plane: {"state": "PENDING", "basis": "not evaluated by this script"}
                for plane in ("policy_control", "scientific_data", "evidence", "audit")
            },
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PENDING", "blocking": True}],
        },
        # PENDENTE, never PASS. Only the independent live Production Witness on the exact
        # deployed commit may grant POST-DEPLOYMENT, and the four-plane audit refuses to
        # grant it even to itself. A pipeline step writing PASS here handed out the one
        # verdict the project reserves for an external observer.
        "post_deployment_status": "PENDENTE",
        "post_deployment_note": (
            "POST-DEPLOYMENT não é concedido por este script nem por nenhum passo do "
            "pipeline; depende do Production Witness ao vivo no commit implantado."
        ),
        "runtime_gate": runtime,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
