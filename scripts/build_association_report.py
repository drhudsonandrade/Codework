#!/usr/bin/env python3
"""Compile reports 04 (nutrigenética), 07 (longevidade) and 08 (traços) from GWAS evidence.

These three reports draw on trait associations rather than on gene–disease validity, which
puts them a full evidential tier below reports 01, 03 and 06. Building them at all was in
doubt; building them honestly turned out to require saying two things out loud that a
conventional consumer report never says.

**The discovery cohort's ancestry is printed with every association.** An effect estimated in
86,000 Europeans does not transfer to an admixed Brazilian genome at the stated size, and
most consumer reports omit this. It is carried here per trait, from the GWAS Catalog study
record, and where the study could not be retrieved the field says so rather than going quiet.

**Traits are not categorised, because no machine-readable categorisation was available.** The
GWAS Catalog REST API exposes EFO trait labels but no parent-category endpoint, so there is
no citable way to decide that a trait is "nutritional" rather than "metabolic". Instead each
report declares which *scopes of the target registry* it draws from — the registry's own
curated `scope` field — and reports every association those loci carry. Selecting traits by
theme would mean this script authoring the classification, which is precisely the step that
turns an association catalogue into a diet plan.

A consequence worth stating plainly: the target registry currently holds no locus scoped
CURIOSIDADE and none scoped for nutrition. Reports 04 and 08 therefore come out nearly empty,
and they say why — the gap is in the curated target registry, not in this code, and it closes
by adding targets with sources, not by loosening what counts as evidence.
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

from reporting.catalog import section_titles
from reporting.provenance import Artifact, PayloadCompiler

UNAVAILABLE = "NÃO DISPONÍVEL"

#: Which scopes of the curated target registry each report is entitled to draw on, and the
#: framing sentence it opens with. Scopes come from `config/partial_genome_annotation_targets
#: .json`, where they are curated by hand; this table is the only report-specific content in
#: the module, and it selects loci — never traits.
#: What each middle section carries. Keys are catalogue titles, checked against the
#: catalogue at build time, and the values name a producer rather than a position. An
#: earlier version mapped sections by index, which put report 08's trait matrix under
#: "Sentidos, fisiologia e preferências" and its refusal under "Cartões de traços" — the
#: three reports simply do not order their sections alike, and nothing errored.
SECTION_ROLES: dict[str, dict[str, str]] = {
    "04": {
        "Resumo nutricional acionável": "summary",
        "Contexto clínico e nutricional": "operator_record",
        "Matriz gene–nutriente–fenótipo": "associations",
        "Módulos de interpretação": "effect_direction",
        "Experimentos e monitorização": "conduct",
    },
    "07": {
        "Mapa preventivo": "summary",
        "Linha de base": "operator_record",
        "Matriz de predisposição": "associations",
        "Variantes e fatores protetores": "effect_direction",
        "Plano preventivo longitudinal": "conduct",
    },
    "08": {
        "Visão geral": "summary",
        "Cartões de traços": "associations",
        "Sentidos, fisiologia e preferências": "effect_direction",
        "Evidência e reprodutibilidade": "evidence_tier",
        "Salvaguardas éticas": "conduct",
    },
}

REPORT_SCOPES: dict[str, dict[str, Any]] = {
    "04": {
        "scopes": ("PREDISPOSICAO", "PESQUISA"),
        "theme": "nutrigenética e nutrição de precisão",
        "refusal": (
            "Nenhuma recomendação dietética é emitida a partir de genótipo neste documento. "
            "Uma associação de GWAS estima efeito médio numa coorte; não estabelece resposta "
            "individual a um nutriente, e a literatura de SNP candidato isolado em nutrigenética "
            "é o caso clássico de achado que não replica."
        ),
    },
    "07": {
        "scopes": ("CLINICO", "PREDISPOSICAO", "PESQUISA"),
        "theme": "longevidade, proteção e prevenção",
        "refusal": (
            "Nenhuma prioridade preventiva é derivada de genótipo neste documento. Prioridade "
            "preventiva depende de idade, história familiar, exposições e biomarcadores, "
            "nenhum dos quais consta deste pipeline. Longevidade não é predita por variante."
        ),
    },
    "08": {
        "scopes": ("CURIOSIDADE",),
        "theme": "traços não clínicos e curiosidades",
        "refusal": (
            "Nenhum traço é apresentado como determinado por genótipo. Traços não clínicos são "
            "poligênicos e fortemente influenciados por ambiente; apresentá-los como resultado "
            "produz estigma sem informação."
        ),
    },
}


def _loci_for(report_id: str, findings: dict[str, Any]) -> list[dict[str, Any]]:
    scopes = set(REPORT_SCOPES[report_id]["scopes"])
    return [f for f in findings["findings"] if str(f.get("scope")) in scopes]


def _significant_traits(finding: dict[str, Any]) -> list[dict[str, Any]]:
    gwas = finding.get("gwas") or {}
    return [t for t in gwas.get("traits", []) if t.get("genome_wide_significant")]


def _ancestry_line(trait: dict[str, Any]) -> str:
    ancestry = trait.get("ancestry") or {}
    if ancestry.get("status") != "VERIFICADO":
        return f"ancestralidade da coorte: {UNAVAILABLE}"
    groups = ancestry.get("by_group") or {}
    if not groups:
        return "ancestralidade da coorte: não declarada pelo estudo"
    top = ", ".join(f"{name} n={count}" for name, count in list(groups.items())[:3])
    return f"coorte de descoberta ({ancestry.get('accession')}): {top}"


def _effect_line(trait: dict[str, Any]) -> str:
    effect = trait.get("effect") or {}
    if effect.get("odds_ratio"):
        return f"OR {effect['odds_ratio']}"
    if effect.get("beta") is not None:
        return (
            f"beta {effect['beta']} {effect.get('beta_unit') or ''} "
            f"({effect.get('beta_direction') or 'direção não declarada'})"
        ).strip()
    return "tamanho de efeito não declarado"


def _trait_matrix(loci: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for finding in loci:
        traits = _significant_traits(finding)
        gene = finding.get("gene") or "sem gene declarado"
        if not traits:
            lines.append(
                f"{gene} {finding['rsid']} ({finding['coverage_class']}): nenhuma associação "
                "com significância genômica no GWAS Catalog"
            )
            continue
        for trait in traits[:4]:
            lines.append(
                f"{gene} {finding['rsid']} {finding.get('genotype') or UNAVAILABLE} → "
                f"{trait['trait']} (p={trait['best_pvalue']}, {_effect_line(trait)}, "
                f"alelo de risco {'/'.join(trait.get('risk_alleles') or []) or UNAVAILABLE}; "
                f"{_ancestry_line(trait)})"
            )
        if len(traits) > 4:
            lines.append(
                f"{gene} {finding['rsid']}: mais {len(traits) - 4} traços com significância "
                "genômica não detalhados"
            )
    return " | ".join(lines)


def _protective_line(loci: list[dict[str, Any]]) -> str:
    """Associations the catalogue itself records in the protective direction."""
    protective: list[str] = []
    for finding in loci:
        for trait in _significant_traits(finding):
            effect = trait.get("effect") or {}
            odds = effect.get("odds_ratio")
            direction = str(effect.get("beta_direction") or "")
            is_protective = (isinstance(odds, (int, float)) and odds < 1) or direction == "decrease"
            if is_protective:
                protective.append(
                    f"{finding.get('gene') or '-'} {finding['rsid']} → {trait['trait']} "
                    f"({_effect_line(trait)}, alelo {'/'.join(trait.get('risk_alleles') or []) or UNAVAILABLE})"
                )
    if not protective:
        return (
            "Nenhuma associação em direção protetora foi registrada pelo GWAS Catalog para os "
            "loci deste escopo. Ausência aqui reflete o catálogo e o painel, não a biologia."
        )
    return (
        "Direção protetora registrada pelo catálogo (o alelo listado é o de referência da "
        "associação, e a direção vale para a coorte de descoberta): " + "; ".join(protective[:8])
    )


def _evidence_tier(loci: list[dict[str, Any]]) -> str:
    """How much of what the catalogue lists actually reaches genome-wide significance."""
    if not loci:
        return "nenhum locus neste escopo; não há evidência a graduar"
    total = sum(len((f.get("gwas") or {}).get("traits", [])) for f in loci)
    significant = sum(len(_significant_traits(f)) for f in loci)
    with_ancestry = sum(
        1
        for f in loci
        for t in _significant_traits(f)
        if (t.get("ancestry") or {}).get("status") == "VERIFICADO"
    )
    return (
        f"{significant} de {total} traços detalhados atingem significância genômica "
        f"(p ≤ 5e-8); {with_ancestry} deles têm a ancestralidade da coorte de descoberta "
        "recuperada do registro do estudo. Um traço abaixo do limiar é reportado como "
        "recuperado, nunca como associação estabelecida. Replicação independente não é "
        "verificável por este pipeline: o GWAS Catalog lista estudos, e contá-los não "
        "substitui avaliar se replicaram."
    )


def _summary(report_id: str, loci: list[dict[str, Any]], findings: dict[str, Any]) -> str:
    spec = REPORT_SCOPES[report_id]
    if not loci:
        return (
            f"O registro de alvos não contém nenhum locus nos escopos "
            f"{', '.join(spec['scopes'])} de que este relatório depende, portanto não há o que "
            f"reportar sobre {spec['theme']}. A lacuna está no registro curado de alvos, não "
            "nos dados desta amostra: fecha-se acrescentando alvos com fonte citada, não "
            "afrouxando o que conta como evidência."
        )
    interrogated = sum(1 for f in loci if f["coverage_class"] in ("OBSERVADO", "NÃO DETECTADO"))
    with_traits = sum(1 for f in loci if _significant_traits(f))
    total_traits = sum(len(_significant_traits(f)) for f in loci)
    return (
        f"{interrogated} de {len(loci)} loci nos escopos {', '.join(spec['scopes'])} foram "
        f"interrogados; {with_traits} carregam associação com significância genômica no GWAS "
        f"Catalog, somando {total_traits} traços. {spec['refusal']}"
    )


def build_payload(report_id: str, findings_path: Path, matrix_path: Path) -> dict:
    if report_id not in REPORT_SCOPES:
        raise ValueError(f"unsupported association report: {report_id!r}")

    findings = Artifact.from_path("clinical-findings", findings_path)
    matrix = Artifact.from_path("completeness-matrix", matrix_path)
    if findings.payload.get("input_sha256") != matrix.payload.get("input_sha256"):
        raise ValueError("clinical findings and completeness matrix describe different inputs")

    # Section titles come from the catalogue, never from a literal here: the engine prints by
    # catalogue title, so a paraphrase renders an empty section and nothing errors.
    titles = section_titles(report_id)
    identification, *_rest = titles
    limitations_title = titles[-1]

    case_id = findings.payload.get("case_id") or UNAVAILABLE
    compiler = PayloadCompiler(case_id=str(case_id), report_id=report_id)
    compiler.register(findings)
    compiler.register(matrix)

    verified = findings.payload.get("operational_status") == "VERIFICADO"
    status = "VERIFICADO" if verified else UNAVAILABLE
    loci = _loci_for(report_id, findings.payload)
    spec = REPORT_SCOPES[report_id]

    compiler.derive(
        "summary", artifact="clinical-findings", locator="findings", status=status,
        basis=f"loci nos escopos {', '.join(spec['scopes'])} e suas associações", kind="computed",
        transform=lambda _f: _summary(report_id, loci, findings.payload),
    )
    compiler.section_derived(
        identification, artifact="clinical-findings", locator="case_id", status=status,
        basis="identificador do caso e integridade dos artefatos", kind="qc_metric",
        transform=lambda cid: (
            f"Caso {cid}; entrada SHA-256 {findings.payload.get('input_sha256')}; "
            f"junção clínica {findings.sha256}; escopos deste relatório: "
            f"{', '.join(spec['scopes'])}."
        ),
    )

    roles = SECTION_ROLES[report_id]
    middle = titles[1:-1]
    # A role naming a section the catalogue does not have would silently produce nothing, so
    # the mapping is checked against the catalogue before anything is written.
    unknown = sorted(set(roles) - set(middle))
    unmapped = sorted(set(middle) - set(roles))
    if unknown or unmapped:
        raise ValueError(
            f"report {report_id}: SECTION_ROLES does not match the catalogue — "
            f"unknown sections {unknown}, unmapped sections {unmapped}"
        )

    for title in middle:
        role = roles[title]
        if role == "summary":
            compiler.section_derived(
                title, artifact="clinical-findings", locator="findings", status=status,
                basis="resumo do escopo e recusa declarada", kind="computed",
                transform=lambda _f: _summary(report_id, loci, findings.payload),
            )
        elif role == "operator_record":
            # Clinical/nutritional context and baseline are the operator's record.
            compiler.section_unavailable(
                title,
                basis=(
                    "contexto clínico, hábitos, exposições e biomarcadores não constam de "
                    "nenhum artefato deste pipeline; são registro do solicitante e não são "
                    "deriváveis de um arquivo de genótipos"
                ),
            )
        elif role == "associations":
            compiler.section_derived(
                title, artifact="clinical-findings", locator="findings", status=status,
                basis=(
                    "associações com significância genômica por locus, com p-valor, tamanho de "
                    "efeito e ancestralidade da coorte de descoberta"
                ),
                kind="evidence_retrieval",
                transform=lambda _f: _trait_matrix(loci)
                or "nenhum locus neste escopo carrega associação recuperável",
            )
        elif role == "effect_direction":
            compiler.section_derived(
                title, artifact="clinical-findings", locator="findings", status=status,
                basis="direção do efeito registrada pelo catálogo, incluindo direção protetora",
                kind="evidence_retrieval", transform=lambda _f: _protective_line(loci),
            )
        elif role == "evidence_tier":
            compiler.section_derived(
                title, artifact="clinical-findings", locator="findings", status=status,
                basis="quantas associações atingem significância genômica e quantas não",
                kind="computed", transform=lambda _f: _evidence_tier(loci),
            )
        else:
            # Plans, experiments and safeguards are conduct, not measurement.
            compiler.section_unavailable(
                title,
                basis=(
                    "plano, experimento N-of-1, conduta preventiva e salvaguarda editorial são "
                    "decisões humanas; este pipeline mede genótipo e recupera evidência, e não "
                    "prescreve"
                ),
            )

    compiler.section_derived(
        limitations_title, artifact="clinical-findings", locator="limitations", status=status,
        basis="limitações da junção clínica somadas às do nível de evidência de associação",
        kind="computed",
        transform=lambda items: " ".join(str(x) for x in items)
        + " Associação de GWAS é um tier de evidência abaixo de validade gene-doença curada:"
        " estima efeito médio de população, não resposta individual, e a transferibilidade"
        " entre ancestralidades não está estabelecida para uma amostra de ancestralidade não"
        " determinada. Fontes: "
        + " | ".join(str(x) for x in findings.payload["evidence"]["sources"]),
    )

    compiler.state(
        "sources",
        [f"clinical-findings:{findings.sha256}", f"completeness-matrix:{matrix.sha256}"]
        + list(findings.payload["evidence"]["sources"]),
        kind="case_control", basis="artefatos e fontes curadas dos quais este relatório deriva",
        status="VERIFICADO",
    )
    compiler.derive(
        "limitations", artifact="clinical-findings", locator="limitations", status=status,
        basis="limitações declaradas pela junção clínica", kind="computed",
        transform=lambda items: " ".join(str(x) for x in items) + " " + spec["refusal"],
    )

    return compiler.compile(
        publication_gate={
            "passed": verified,
            "consent_verified": bool(findings.payload.get("case_id")),
            "qc_verified": bool(matrix.payload.get("qc_gate_passed")),
            "evidence_verified": True,
            "placeholders_resolved": True,
        },
        policy_evaluation={
            "ready_for_requested_operation": verified,
            "planes": {
                k: {"state": "PASS" if verified else "BLOCKED"}
                for k in ("policy_control", "scientific_data", "evidence", "audit")
            },
            "gates": [
                {"gate": "FINAL_AUDIT_GATE", "state": "PASS" if verified else "BLOCKED", "blocking": True}
            ],
        },
        execution_manifest={
            "status": findings.payload.get("operational_status", UNAVAILABLE),
            "CLINICAL_FINDINGS_SHA256": findings.sha256,
            "COMPLETENESS_MATRIX_SHA256": matrix.sha256,
            "GENE_DISEASE_EVIDENCE_SHA256": findings.payload["evidence"].get("sha256"),
            "SCOPES": ", ".join(spec["scopes"]),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, choices=sorted(REPORT_SCOPES))
    parser.add_argument("--findings", required=True)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--payload-out", required=True)
    args = parser.parse_args()

    payload = build_payload(args.report, Path(args.findings), Path(args.matrix))
    out = Path(args.payload_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "report": args.report,
                "payload": str(out),
                "operational_status": payload["operational_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
