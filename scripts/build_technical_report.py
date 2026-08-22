#!/usr/bin/env python3
"""Compile report 05 (Relatório Técnico de Métodos, QC e Limitações) from artifacts.

This is the report an auditor reads to decide whether to believe the others, so every
number in it must come from a measurement rather than a description of one. It is also the
only report in the suite that can be produced with no curated clinical registry at all:
each value is a QC metric, a gate state, a provenance verdict or a coverage count that the
pipeline already computed.

The report deliberately publishes its own weaknesses — unresolved cross-platform records,
withheld genotypes, structural blind spots, the strand basis — because a technical report
that only listed what worked would be the least honest document in the suite.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.completeness import CLASSES, build_completeness_matrix, write_matrix
from reporting.assay import Assay, assay_for
from reporting.provenance import Artifact, PayloadCompiler

REPORT_ID = "05"

#: Exactly as reporting/catalog.json declares them.
SECTIONS = (
    "Identificação e controle",
    "Resumo leigo do exame",
    "Contrato de entrada e cadeia de custódia",
    "Plataforma e desempenho analítico",
    "Pipeline reproduzível",
    "Genome Completeness Matrix",
    "Runtime/Resource Gate",
    "Limitações e fontes",
)

UNAVAILABLE = "NÃO DISPONÍVEL"


def _pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%" if isinstance(value, (int, float)) else UNAVAILABLE


def _platform_text(qc: dict, assay: Assay) -> str:
    metrics, inputs = qc["metrics"], qc["input"]
    return (
        f"Método: {assay.name}. Esquema {inputs['schema']}; "
        f"plataforma {inputs.get('platform') or UNAVAILABLE}. "
        f"{metrics['rows']} linhas, {metrics['unique_rsids']} rsids únicos, "
        f"{metrics['unique_coordinates']} coordenadas únicas "
        f"({metrics['duplicate_coordinate_rows']} linhas compartilham coordenada com outra). "
        f"Origem por plataforma: {json.dumps(metrics['source_counts'], ensure_ascii=False)}."
    )


def _pipeline_text(qc: dict, probe: dict | None) -> str:
    inputs = qc["input"]
    parts = [
        f"Build de referência {inputs['build']} "
        f"(proveniência verificada: {inputs.get('build_evidence_verified')}); "
        f"convenção de fita {inputs['strand']} "
        f"(proveniência verificada: {inputs.get('strand_evidence_verified')})."
    ]
    if probe:
        build, strand = probe["build"], probe["strand"]
        parts.append(
            f"Determinados pelo probe de proveniência a partir do próprio arquivo: build por "
            f"concordância de coordenadas ({build['grch37_matches']} GRCh37 vs "
            f"{build['grch38_matches']} GRCh38, limiar {build['threshold']}); fita por conjunto "
            f"de alelos ({strand['plus_matches']} plus vs {strand['minus_matches']} minus, "
            f"limiar {strand['threshold']}), com marcadores palindrômicos excluídos por não "
            f"carregarem informação de orientação. Tabela de marcadores "
            f"{probe['marker_table']['id']} {probe['marker_table']['version']}, "
            f"status {probe['marker_table']['verification_status']}."
        )
    else:
        parts.append(
            "Nenhum probe de proveniência foi executado nesta análise; build e fita vêm "
            "exclusivamente do que o arquivo ou o operador declararam."
        )
    return " ".join(parts)


def _qc_text(qc: dict) -> str:
    metrics = qc["metrics"]
    gates = "; ".join(f"{name}={gate['state']}" for name, gate in sorted(qc["gates"].items()))
    lines = [
        f"Call rate {_pct(metrics['call_rate'])} "
        f"({metrics['valid_calls']}/{metrics['rows']} chamadas válidas), "
        f"limiar operacional {_pct(qc['gates']['CALLABILITY_GATE'].get('threshold'))}.",
        f"Genótipos chamados inválidos: {metrics['invalid_called_consensus_genotypes']}.",
        f"Heterozigosidade autossômica {_pct(metrics['autosomal_heterozygosity_rate'])}.",
        f"Call rate por plataforma — Genera {_pct(metrics.get('genera_call_rate'))}, "
        f"MyHeritage {_pct(metrics.get('myheritage_call_rate'))}.",
        f"Concordância no overlap direto {_pct(metrics.get('direct_overlap_concordance'))} "
        f"({metrics['direct_overlap_consensus']} consenso, "
        f"{metrics['direct_overlap_genotype_conflicts']} conflitos de genótipo; "
        f"taxa de conflito {_pct(metrics.get('direct_overlap_conflict_rate'))}, "
        f"limiar {_pct(qc['gates']['CROSS_PLATFORM_GATE'].get('max_conflict_rate'))}).",
        f"Gates: {gates}.",
    ]
    # A gate state on its own does not say what went wrong. Printing "STRUCTURE_GATE=FAIL"
    # and stopping leaves the one thing a reader needs — which check failed and by how much
    # — in a QC file nobody reading this report will open.
    reserved = [
        (name, gate)
        for name, gate in sorted(qc["gates"].items())
        if gate.get("state") not in ("PASS", "NOT_APPLICABLE")
    ]
    if reserved:
        lines.append(
            "Razões dos gates que não passaram: "
            + "; ".join(
                f"{name} ({gate.get('state')}): "
                + ("; ".join(str(r) for r in (gate.get("reasons") or [])) or "sem razão registrada")
                for name, gate in reserved
            )
            + "."
        )
    else:
        # Said out loud, because "no reasons listed" and "every gate passed" look identical
        # when the sentence is simply absent.
        lines.append("Nenhum gate do QC ficou com ressalva: todos passaram ou não se aplicam.")
    return " ".join(lines)


def _limitations_text(qc: dict, matrix: dict, assay: Assay) -> str:
    unresolved = qc["gates"]["CROSS_PLATFORM_GATE"].get("unresolved_records") or {}
    total_unresolved = sum(unresolved.values())
    withheld = sum(1 for e in matrix["entries"] if e.get("genotype_withheld"))
    blind = ", ".join(str(b["class"]) for b in matrix["structural_blind_spots"])
    notes = qc["gates"]["STRUCTURE_GATE"].get("notes") or []
    text = [
        f"Registros não resolvidos, excluídos da interpretação: {total_unresolved} "
        f"({json.dumps(unresolved, ensure_ascii=False)}). Conflitos nunca são arbitrados.",
        f"Alvos com genótipo retido por não serem interpretáveis: {withheld}.",
        f"Classes de variação que a plataforma não resolve em nenhum locus: {blind}.",
        # Both halves used to be constants describing an array. The first is simply false of
        # a WGS projection, which carries DP and GQ on every call: a report that understates
        # the evidence it holds is as wrong as one that overstates it.
        assay.depth_note,
        assay.genome_wide_note,
    ]
    if notes:
        text.append("Observações estruturais do QC: " + "; ".join(str(n) for n in notes) + ".")
    return " ".join(text)


def _reproducibility_text(qc: dict, matrix: dict, probe: dict | None) -> str:
    parts = [
        f"Entrada SHA-256 {qc['input']['sha256']} ({qc['input']['size_bytes']} bytes, "
        f"contêiner {qc['input']['container']}).",
        f"Matriz de completude SHA-256 {matrix['sha256']}.",
        f"Registro de alvos {matrix['target_manifest']['id']} "
        f"{matrix['target_manifest']['version']} (SHA-256 {matrix['target_manifest']['sha256']}).",
        "Toda etapa é determinística e reexecutável a partir desses hashes; os gates "
        "recomputam seus veredictos em vez de reler um PASS anterior.",
    ]
    if probe:
        parts.append(f"Probe de proveniência avaliado em {probe['evaluated_at']}.")
    return " ".join(parts)


def build_payload(
    qc_path: Path,
    matrix_path: Path,
    probe_path: Path | None,
    policy_evaluation: Path | None = None,
    post_deployment_witness: Path | None = None,
    consent: Path | None = None,
) -> dict:
    qc = Artifact.from_path("array-qc", qc_path)
    assay = assay_for(qc.payload)
    matrix = Artifact.from_path("completeness-matrix", matrix_path)
    probe = Artifact.from_path("provenance-probe", probe_path) if probe_path else None

    case_id = qc.payload.get("case_id") or UNAVAILABLE
    compiler = PayloadCompiler(
        case_id=str(case_id),
        report_id=REPORT_ID,
        policy_evaluation=policy_evaluation,
        post_deployment_witness=post_deployment_witness,
        consent=consent,
    )
    compiler.register(qc)
    compiler.register(matrix)
    if probe:
        compiler.register(probe)

    qc_verified = qc.payload.get("operational_status") == "VERIFICADO"
    status = "VERIFICADO" if qc_verified else UNAVAILABLE
    probe_payload = probe.payload if probe else None

    compiler.derive(
        "summary",
        artifact="array-qc",
        locator="metrics",
        status=status,
        basis=f"métricas centrais medidas pelo QC ({assay.name})",
        kind="qc_metric",
        transform=lambda m: (
            f"{m['rows']} variantes analisadas, call rate {_pct(m['call_rate'])}, "
            f"concordância cross-platform {_pct(m.get('direct_overlap_concordance'))}. "
            f"Gate de interpretação limitada: "
            f"{qc.payload['gates']['LIMITED_INTERPRETATION_GATE']['state']}."
        ),
    )

    compiler.section_derived(
        "Identificação e controle",
        artifact="array-qc", locator="input.sha256", status=status,
        basis="SHA-256 do arquivo efetivamente analisado", kind="computed",
        transform=lambda sha: f"Caso {case_id}; entrada SHA-256 {sha}; "
        f"avaliado em {qc.payload['evaluated_at']}.",
    )
    compiler.section_derived(
        "Plataforma e desempenho analítico",
        artifact="array-qc", locator="metrics", status=status,
        basis="contagens estruturais medidas no arquivo", kind="qc_metric",
        transform=lambda _m: _platform_text(qc.payload, assay),
    )
    compiler.section_derived(
        "Contrato de entrada e cadeia de custódia",
        artifact="array-qc", locator="input", status=status,
        basis="proveniência de build e fita conforme verificada pelo QC", kind="computed",
        transform=lambda _i: _pipeline_text(qc.payload, probe_payload),
    )
    compiler.section_derived(
        "Resumo leigo do exame",
        artifact="array-qc", locator="gates", status=status,
        basis="métricas e limiares operacionais dos gates", kind="qc_metric",
        transform=lambda _g: _qc_text(qc.payload),
    )
    compiler.section_derived(
        "Limitações e fontes",
        artifact="completeness-matrix", locator="structural_blind_spots", status=status,
        basis="registros não resolvidos, genótipos retidos e limites da plataforma",
        kind="computed",
        transform=lambda _b: _limitations_text(qc.payload, matrix.payload, assay),
    )
    compiler.section_derived(
        "Pipeline reproduzível",
        artifact="completeness-matrix", locator="sha256", status=status,
        basis="hashes que tornam a execução reexecutável", kind="computed",
        transform=lambda _s: _reproducibility_text(qc.payload, matrix.payload, probe_payload),
    )
    compiler.section_derived(
        "Genome Completeness Matrix",
        artifact="completeness-matrix", locator="totals", status=status,
        basis="cobertura por classe operacional", kind="computed",
        transform=lambda t: "Cobertura do registro de alvos — "
        + "; ".join(f"{name}: {t['class_' + name]}" for name in CLASSES)
        + f". Interpretáveis: {t['interpretable']}/{t['targets']}.",
    )

    # The Runtime/Resource Gate governs NGS calling — reference index, aligner, caller
    # compatibility. An array run opens none of those, so the honest entry is that the gate
    # was not applicable here, not a borrowed PASS from some other session.
    compiler.section_stated(
        "Runtime/Resource Gate",
        "NÃO APLICÁVEL a esta execução: o Runtime/Resource Gate governa chamada de variantes "
        "em NGS (FASTA/FAI/dicionário, índices de alinhador, compatibilidade caller–referência). "
        "Nem uma análise de array nem uma projeção de VCF já chamado abre esses recursos: "
        "nenhuma das duas alinha leituras nem chama variantes. Nenhum PASS de outra sessão é "
        "herdado, conforme a seção 259.",
        kind="case_control",
        basis="escopo do gate frente ao tipo de execução",
        status="VERIFICADO",
    )

    # One finding per gate, so a reader sees each verdict and its stated reasons rather
    # than a single aggregate that could hide a blocked prerequisite.
    for name in sorted(qc.payload["gates"]):
        gate = qc.payload["gates"][name]
        builder = compiler.finding(f"QC-{name}", basis=f"gate do QC ({assay.short})")
        builder.stated("domain", f"QC — {assay.short}", kind="case_control", basis="plano de dados científicos", status="VERIFICADO")
        builder.derived(
            "nature", artifact="array-qc", locator=f"gates.{name}.state",
            status=status, basis="estado do gate", kind="computed",
            transform=lambda s: f"gate {s}",
        )
        builder.derived(
            "status", artifact="array-qc", locator=f"gates.{name}.state",
            status=status, basis="estado operacional do gate", kind="computed",
        )
        builder.derived(
            "qc", artifact="array-qc", locator=f"gates.{name}.reasons",
            status=status, basis="motivos declarados pelo gate", kind="computed",
            transform=lambda r: "; ".join(str(x) for x in r) if r else "nenhum motivo de bloqueio",
        )
        builder.stated(
            "observed_data",
            json.dumps({k: v for k, v in gate.items() if k not in {"reasons", "state"}}, ensure_ascii=False)
            or UNAVAILABLE,
            kind="case_control", basis="parâmetros e contagens do gate", status="VERIFICADO",
        )
        builder.stated("priority", "TECNICO", kind="case_control", basis="escopo do relatório", status="VERIFICADO")
        builder.stated(
            "interpretation",
            "Gate técnico; não constitui achado clínico nem interpretação de variante.",
            kind="case_control", basis="escopo declarado do relatório 05", status="VERIFICADO",
        )
        builder.unavailable("evidence_refs", basis="gates de QC não consultam evidência externa")
        builder.unavailable("uncertainties", basis="incerteza técnica está nas seções de limitações")
        builder.unavailable("confirmation", basis="nenhuma confirmação ortogonal foi executada")
        builder.add()

    sources = [f"array-qc:{qc.sha256}", f"completeness-matrix:{matrix.sha256}"]
    if probe:
        sources.append(f"provenance-probe:{probe.sha256}")
    compiler.state(
        "sources", sources, kind="case_control",
        basis="artefatos que originaram cada valor deste relatório", status="VERIFICADO",
    )
    compiler.derive(
        "limitations", artifact="array-qc", locator="limitations", status=status,
        basis="limitações declaradas pelo QC", kind="computed",
        transform=lambda items: " ".join(str(x) for x in items),
    )

    return compiler.compile(
        execution_manifest={
            "status": qc.payload.get("operational_status", UNAVAILABLE),
            "ARRAY_QC_SHA256": qc.sha256,
            "COMPLETENESS_MATRIX_SHA256": matrix.sha256,
            **({"PROVENANCE_PROBE_SHA256": probe.sha256} if probe else {}),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--qc", required=True)
    parser.add_argument("--targets", required=True)
    parser.add_argument("--provenance-probe")
    parser.add_argument("--matrix-out", required=True)
    parser.add_argument("--payload-out", required=True)
    args = parser.parse_args()

    matrix = build_completeness_matrix(Path(args.input), Path(args.qc), Path(args.targets))
    matrix_path = write_matrix(matrix, Path(args.matrix_out))
    payload = build_payload(
        Path(args.qc), matrix_path, Path(args.provenance_probe) if args.provenance_probe else None
    )
    out = Path(args.payload_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "matrix": str(matrix_path), "payload": str(out),
        "operational_status": payload["operational_status"],
        "gates_reported": len(payload["findings"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
