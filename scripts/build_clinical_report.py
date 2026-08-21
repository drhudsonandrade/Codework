#!/usr/bin/env python3
"""Compile report 01 (Relatório de Genoma Clínico) from the curated clinical join.

Report 01 is the document a reader will treat as "the result", which makes it the one where
screening most easily reads as diagnosis. Three refusals are built into what it can print.

**The clinical question is not derivable.** Sections asking for the indication, the phenotype
and the pedigree stay NÃO DISPONÍVEL unless an operator supplies them, because a genotype file
does not carry why it was ordered. A report that filled them in from the findings would be
reasoning backwards from the answer.

**Priority is not computed.** `FindingBuilder` requires the field, and it is declared absent:
triage is a clinical decision about a person whose history this pipeline has never seen.

**Negative findings get their own section and their own sentence.** NÃO DETECTADO licenses a
statement about one locus and nothing else; NÃO TESTADO licenses nothing at all. Report 09
exists to keep those apart and report 01 inherits the distinction verbatim rather than
restating it loosely.
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

from array_pipeline.clinical_findings import (
    ACHADO_PRELIMINAR,
    ACIONAVEL,
    GENOTIPO_DE_RISCO,
    NAO_INTERROGADO,
    NEGATIVO,
    PORTADOR,
    PREDISPOSICAO,
    SEM_INTERPRETACAO,
)
from reporting.provenance import Artifact, PayloadCompiler

REPORT_ID = "01"

#: Report 01's section titles, exactly as reporting/catalog.json declares them. The engine
#: looks sections up by catalogue title, so a paraphrase renders an empty section while the
#: anchored text sits unreachable under a key nobody reads.
SECTIONS = (
    "Identificação e controle",
    "Resumo clínico executivo",
    "Pergunta clínica, fenótipo e heredograma",
    "Achados clínicos e diagnósticos",
    "Predisposições, risco e achados negativos",
    "Confirmação, pontos cegos e reanálise",
    "Fontes e Execution Manifest",
)

UNAVAILABLE = "NÃO DISPONÍVEL"

#: Kinds that put a locus in the "achados" section rather than the negative one. Read from
#: the findings artifact, never recomputed here.
REPORTABLE = (ACIONAVEL, PORTADOR, GENOTIPO_DE_RISCO)


def _describe(finding: dict[str, Any]) -> str:
    gene = finding.get("gene") or "sem gene declarado"
    conditions = ", ".join(finding["clinvar"].get("conditions", [])[:3]) or "condição não nomeada"
    return (
        f"{gene} {finding['rsid']} {finding.get('genotype') or UNAVAILABLE} "
        f"[{finding['interpretation']}] — {conditions}"
    )


def _executive_summary(payload: dict[str, Any]) -> str:
    totals = payload["totals"]
    reportable = sum(totals.get(f"kind_{kind}", 0) for kind in REPORTABLE)
    return (
        f"{reportable} de {totals['loci']} loci do registro sustentam um achado clínico "
        f"({totals.get('kind_' + ACIONAVEL, 0)} acionáveis, "
        f"{totals.get('kind_' + PORTADOR, 0)} de portador, "
        f"{totals.get('kind_' + GENOTIPO_DE_RISCO, 0)} genótipos de risco). "
        f"{totals.get('kind_' + NEGATIVO, 0)} loci foram interrogados e não carregam o alelo "
        f"avaliado; {totals.get('kind_' + NAO_INTERROGADO, 0)} não foram interrogados e não "
        f"admitem nenhuma afirmação. Triagem por microarranjo de SNP não é diagnóstico e não "
        "exclui condição."
    )


#: How many loci of one reportable class are described one by one before the rest become a
#: stated count. Uncapped, this section grew with the registry rather than with the case: a
#: representative array produced 4,065 reportable loci and a 28 MB payload, in which the
#: findings that matter were indistinguishable from the ones that did not.
MAX_FINDINGS_DETAILED_PER_CLASS = 200

#: Classes that are never truncated, whatever the count. An actionable finding is the reason
#: this report exists; omitting one to keep a document small would be the single worst thing
#: this pipeline could do, and a large actionable count is itself information the reader
#: needs rather than a formatting problem to be solved.
NEVER_TRUNCATED = (ACIONAVEL,)


def _split_reportable(
    findings: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split reportable findings into the ones described individually and the ones omitted.

    Takes the raw findings list rather than the payload so the compiler's transforms can
    recompute it from the artifact they were handed, instead of closing over a value this
    module worked out separately. Order within a class is the artifact's own, which is
    deterministic, so two runs over the same case describe the same loci.
    """
    detailed: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    for kind in REPORTABLE:
        items = [f for f in findings if f["interpretation"] == kind]
        if kind in NEVER_TRUNCATED:
            detailed.extend(items)
            continue
        detailed.extend(items[:MAX_FINDINGS_DETAILED_PER_CLASS])
        omitted.extend(items[MAX_FINDINGS_DETAILED_PER_CLASS:])
    return detailed, omitted


def _omitted_breakdown(findings: list[dict[str, Any]]) -> str:
    _detailed, omitted = _split_reportable(findings)
    counts: dict[str, int] = {}
    for f in omitted:
        counts[f["interpretation"]] = counts.get(f["interpretation"], 0) + 1
    return ", ".join(f"{kind}: {count}" for kind, count in sorted(counts.items()))


def _select_reportable(
    payload: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    detailed, omitted = _split_reportable(payload["findings"])
    counts: dict[str, int] = {}
    for f in omitted:
        counts[f["interpretation"]] = counts.get(f["interpretation"], 0) + 1
    return detailed, counts


def _findings_text(payload: dict[str, Any]) -> str:
    items = [f for f in payload["findings"] if f["interpretation"] in REPORTABLE]
    if not items:
        return (
            "Nenhum locus interrogado reúne, ao mesmo tempo, patogenicidade asserida pelo "
            "ClinVar na coordenada verificada e relação gene-doença estabelecida. Isso não é "
            "um resultado negativo do genoma: é o resultado deste painel de alvos, sobre as "
            "posições que este array ensaiou."
        )
    detailed, omitted = _select_reportable(payload)
    text = "; ".join(_describe(f) for f in detailed)
    if omitted:
        # Stated, not implied: the reader has to be able to tell a report that found 200
        # carrier loci from one that found 2,111 and described the first 200.
        rest = ", ".join(f"{count} em {kind}" for kind, count in sorted(omitted.items()))
        text += (
            f". Além dos descritos acima, {rest} não são detalhados um a um; "
            f"o limite por classe é {MAX_FINDINGS_DETAILED_PER_CLASS} e nenhum locus de "
            f"{', '.join(NEVER_TRUNCATED)} é omitido. A contagem completa está no resumo "
            "executivo e a lista integral na junção clínica que originou este relatório."
        )
    return text


#: How many loci each negative category names before the rest become a count. The count is
#: already in every label, so capping the list loses no information — while an uncapped list
#: reached 2.3 MB in one section, naming all 124,000 loci the array never carried.
MAX_LOCI_NAMED = 60


def _named(loci: list[dict[str, Any]]) -> str:
    """Up to MAX_LOCI_NAMED locus identifiers, with the remainder counted rather than listed."""
    if not loci:
        return "nenhum"
    names = ", ".join(f"{f['gene'] or '-'} {f['rsid']}" for f in loci[:MAX_LOCI_NAMED])
    if len(loci) > MAX_LOCI_NAMED:
        names += f" (+{len(loci) - MAX_LOCI_NAMED} não listados individualmente)"
    return names


def _predisposition_text(payload: dict[str, Any]) -> str:
    predisposition = [f for f in payload["findings"] if f["interpretation"] == PREDISPOSICAO]
    preliminary = [f for f in payload["findings"] if f["interpretation"] == ACHADO_PRELIMINAR]
    negative = [f for f in payload["findings"] if f["interpretation"] == NEGATIVO]
    uninterpreted = [f for f in payload["findings"] if f["interpretation"] == SEM_INTERPRETACAO]
    untested = [f for f in payload["findings"] if f["interpretation"] == NAO_INTERROGADO]
    parts = [
        "Predisposição: "
        + ("; ".join(_describe(f) for f in predisposition) if predisposition else "nenhum locus"),
        f"Interrogados e sem o alelo avaliado ({len(negative)}): " + _named(negative),
        f"Observados sem interpretação estabelecida ({len(uninterpreted)}): "
        + _named(uninterpreted),
        f"Não interrogados ({len(untested)}): " + _named(untested),
        # The one-star tier lands here, and it is named rather than folded into the
        # predisposition list: a single-submitter assertion is one laboratory's opinion, and
        # the whole reason the wider registry is safe to default to is that the report says so.
        f"Achados preliminares, revisão de uma estrela ({len(preliminary)}): "
        + _named(preliminary),
        payload["negative_statement_policy"],
    ]
    return " | ".join(parts)


def _confirmation_text(payload: dict[str, Any], matrix: dict[str, Any]) -> str:
    spots = ", ".join(str(s["class"]) for s in matrix.get("structural_blind_spots", []))
    return (
        f"{payload['totals']['confirmation_required']} achados exigem confirmação por método "
        "ortogonal antes de qualquer mudança de conduta. Classes não resolvidas por array em "
        f"nenhum locus: {spots}. "
        f"{payload['totals']['genes_without_established_validity']} genes do registro não têm "
        "relação gene-doença estabelecida por nenhum registro curado, o que impede converter "
        "variante em achado ainda que o ClinVar a classifique. Reanálise é indicada quando "
        "essas curadorias mudarem."
    )


def build_payload(findings_path: Path, matrix_path: Path, qc_path: Path, policy_evaluation: Path | None = None) -> dict:
    findings = Artifact.from_path("clinical-findings", findings_path)
    matrix = Artifact.from_path("completeness-matrix", matrix_path)
    qc = Artifact.from_path("array-qc", qc_path)

    if findings.payload.get("input_sha256") != matrix.payload.get("input_sha256"):
        raise ValueError("clinical findings and completeness matrix describe different inputs")
    if qc.payload.get("input", {}).get("sha256") != matrix.payload.get("input_sha256"):
        raise ValueError("QC artifact and completeness matrix describe different inputs")

    case_id = findings.payload.get("case_id") or UNAVAILABLE
    compiler = PayloadCompiler(case_id=str(case_id), report_id=REPORT_ID, policy_evaluation=policy_evaluation)
    compiler.register(findings)
    compiler.register(matrix)
    compiler.register(qc)

    verified = findings.payload.get("operational_status") == "VERIFICADO"
    status = "VERIFICADO" if verified else UNAVAILABLE

    compiler.derive(
        "summary", artifact="clinical-findings", locator="totals", status=status,
        basis="contagem por tipo de afirmação sustentada", kind="computed",
        transform=lambda _t: _executive_summary(findings.payload),
    )
    compiler.section_derived(
        "Identificação e controle", artifact="array-qc", locator="case_id", status=status,
        basis="identificador do caso e integridade do arquivo de entrada", kind="qc_metric",
        transform=lambda cid: (
            f"Caso {cid}; entrada SHA-256 {matrix.payload.get('input_sha256')}; "
            f"matriz de completude {matrix.sha256}; junção clínica {findings.sha256}."
        ),
    )
    compiler.section_derived(
        "Resumo clínico executivo", artifact="clinical-findings", locator="totals",
        status=status, basis="resumo das classes de afirmação", kind="computed",
        transform=lambda _t: _executive_summary(findings.payload),
    )
    # The indication, the phenotype and the pedigree are the operator's record, not the
    # array's. Deriving them from the findings would be reasoning from the answer back to
    # the question.
    compiler.section_unavailable(
        "Pergunta clínica, fenótipo e heredograma",
        basis=(
            "indicação clínica, fenótipo e heredograma não constam de nenhum artefato deste "
            "pipeline; são registro do solicitante e não são deriváveis de um arquivo de genótipos"
        ),
    )
    compiler.section_derived(
        "Achados clínicos e diagnósticos", artifact="clinical-findings", locator="findings",
        status=status, basis="loci que sustentam achado clínico sob a política de interpretação",
        kind="computed", transform=lambda _f: _findings_text(findings.payload),
    )
    compiler.section_derived(
        "Predisposições, risco e achados negativos", artifact="clinical-findings",
        locator="findings", status=status,
        basis="loci de predisposição, negativos por locus e não interrogados, mantidos separados",
        kind="computed", transform=lambda _f: _predisposition_text(findings.payload),
    )
    compiler.section_derived(
        "Confirmação, pontos cegos e reanálise", artifact="clinical-findings", locator="totals",
        status=status, basis="exigência de confirmação e limites da plataforma", kind="computed",
        transform=lambda _t: _confirmation_text(findings.payload, matrix.payload),
    )
    compiler.section_derived(
        "Fontes e Execution Manifest", artifact="clinical-findings", locator="evidence.sources",
        status="VERIFICADO", basis="fontes curadas citadas pela junção clínica",
        kind="evidence_retrieval", transform=lambda items: " | ".join(str(x) for x in items),
    )

    detailed, omitted = _select_reportable(findings.payload)
    # Positions come from one pass over the artifact rather than `.index(finding)`, which
    # was both quadratic and keyed on dict equality: two findings that compared equal would
    # have pointed every locator at the first of them.
    positions = {id(f): i for i, f in enumerate(findings.payload["findings"])}

    for finding in detailed:
        locator = f"findings[{positions[id(finding)]}]"
        builder = compiler.finding(finding["rsid"], basis="locus com achado clínico sustentado")
        builder.derived(
            "domain", artifact="clinical-findings", locator=f"{locator}.gene", status=status,
            basis="gene declarado pelo registro de alvos", kind="observation",
            transform=lambda g: str(g or "sem gene declarado"),
        )
        builder.derived(
            "nature", artifact="clinical-findings", locator=f"{locator}.interpretation",
            status=status, basis="tipo de afirmação sustentada pelo locus", kind="computed",
        )
        # Triage is a decision about a person whose history this pipeline has never seen.
        builder.unavailable(
            "priority",
            basis="priorização clínica depende de história, fenótipo e contexto assistencial",
        )
        builder.derived(
            "observed_data", artifact="clinical-findings", locator=f"{locator}.genotype",
            status=status, basis="genótipo chamado e harmonizado entre plataformas",
            kind="observation",
        )
        builder.derived(
            "qc", artifact="clinical-findings", locator=f"{locator}.coverage_basis",
            status=status, basis="base da classificação de cobertura deste locus", kind="qc_metric",
        )
        builder.derived(
            "evidence_refs", artifact="clinical-findings",
            locator=f"{locator}.clinvar.records", status="VERIFICADO",
            basis="acessos do ClinVar verificados na coordenada do alvo",
            kind="evidence_retrieval",
            transform=lambda records: ", ".join(
                f"{r.get('accession')} ({r.get('classification')}, {r.get('review_status')})"
                for r in records
            ) or UNAVAILABLE,
        )
        builder.derived(
            "interpretation", artifact="clinical-findings",
            locator=f"{locator}.interpretation_basis", status=status,
            basis="justificativa da classe de afirmação, com a fonte que a sustenta",
            kind="computed",
        )
        builder.derived(
            "uncertainties", artifact="clinical-findings", locator=f"{locator}.validity",
            status=status, basis="força e origem da validade gene-doença, e conflitos de herança",
            kind="computed",
            transform=lambda v: (
                f"Validade estabelecida por {', '.join(v.get('established_by') or []) or 'nenhuma fonte'}; "
                f"modos de herança curados {', '.join(v.get('modes_of_inheritance') or []) or UNAVAILABLE}"
                + ("; há divergência de modo de herança entre fontes" if v.get("mode_of_inheritance_conflict") else "")
                # GenCC aggregates the PanelApp submissions, so two names in `established_by`
                # can be one body of curation. Saying so here keeps the reader from counting
                # it as corroboration.
                + ("; GenCC e PanelApp coincidem neste gene e não são votos independentes"
                   if v.get("panelapp_overlaps_gencc") else "")
                + (
                    "; restrição populacional gnomAD pLI="
                    f"{v['gnomad_constraint']['pli']:.2f}"
                    if isinstance((v.get("gnomad_constraint") or {}).get("pli"), (int, float))
                    else ""
                )
                + ". Restrição populacional descreve tolerância do gene a perda de função e "
                "não estabelece relação gene-doença. "
                "Penetrância e expressividade não são estabelecidas por genótipo."
            ),
        )
        builder.stated(
            "confirmation",
            "Confirmação por método ortogonal é obrigatória antes de qualquer mudança de conduta.",
            kind="normative", basis="política de confirmação da junção clínica", status="VERIFICADO",
        )
        builder.derived(
            "status", artifact="clinical-findings", locator="operational_status",
            status=status, basis="status operacional herdado da junção clínica", kind="computed",
        )
        builder.add()

    if omitted:
        # One aggregate entry standing for the loci not described individually, so a
        # consumer reading only `findings` still sees that they exist and how many. Without
        # it the payload would be indistinguishable from a case that genuinely had 200.
        builder = compiler.finding(
            "ACHADO-RESTANTE",
            basis="agregado dos loci reportáveis não descritos um a um",
        )
        # Every count here is recomputed from the findings artifact by the transform, not
        # passed in from the value this module worked out: the compiler refuses a derived
        # value that did not come from reading the artifact, and it is right to.
        builder.derived(
            "domain", artifact="clinical-findings", locator="findings", status=status,
            basis="genes distintos entre os loci agregados", kind="computed",
            transform=lambda items: (
                f"{len({f.get('gene') for f in _split_reportable(items)[1] if f.get('gene')})} genes"
            ),
        )
        builder.derived(
            "nature", artifact="clinical-findings", locator="findings", status=status,
            basis="classes de afirmação dos loci agregados", kind="computed",
            transform=_omitted_breakdown,
        )
        builder.derived(
            "observed_data", artifact="clinical-findings", locator="findings", status=status,
            basis="contagem exata dos loci agregados", kind="observation",
            transform=lambda items: (
                f"{len(_split_reportable(items)[1])} loci reportáveis adicionais não "
                f"descritos individualmente (limite de {MAX_FINDINGS_DETAILED_PER_CLASS} "
                f"por classe; {', '.join(NEVER_TRUNCATED)} nunca é truncado)"
            ),
        )
        builder.unavailable(
            "priority",
            basis="priorização clínica depende de história, fenótipo e contexto assistencial",
        )
        builder.stated(
            "interpretation",
            "Estes loci sustentam a mesma classe de afirmação dos descritos acima e estão "
            "listados integralmente na junção clínica que originou este relatório. A omissão "
            "aqui é de espaço no documento, não de evidência.",
            kind="normative", basis="motivo declarado da agregação", status="VERIFICADO",
        )
        builder.stated(
            "confirmation",
            "Confirmação por método ortogonal é obrigatória antes de qualquer mudança de conduta.",
            kind="normative", basis="política de confirmação da junção clínica", status="VERIFICADO",
        )
        builder.derived(
            "qc", artifact="clinical-findings", locator="operational_status",
            status=status, basis="status operacional herdado da junção clínica", kind="qc_metric",
        )
        builder.derived(
            "status", artifact="clinical-findings", locator="operational_status",
            status=status, basis="status operacional herdado da junção clínica", kind="computed",
        )
        builder.derived(
            "evidence_refs", artifact="clinical-findings", locator="evidence.sources",
            status="VERIFICADO", kind="evidence_retrieval",
            basis="fontes curadas da junção clínica; acessos individuais ficam nos loci descritos",
            transform=lambda items: " | ".join(str(x) for x in items) or UNAVAILABLE,
        )
        builder.stated(
            "uncertainties",
            "As mesmas incertezas de classe declaradas nos loci descritos acima aplicam-se "
            "aqui. Penetrância e expressividade não são estabelecidas por genótipo.",
            kind="normative", basis="incertezas de classe já declaradas", status="VERIFICADO",
        )
        builder.add()

    compiler.state(
        "sources",
        [f"clinical-findings:{findings.sha256}", f"completeness-matrix:{matrix.sha256}",
         f"array-qc:{qc.sha256}"]
        + list(findings.payload["evidence"]["sources"]),
        kind="case_control", basis="artefatos e fontes curadas dos quais este relatório deriva",
        status="VERIFICADO",
    )
    compiler.derive(
        "limitations", artifact="clinical-findings", locator="limitations", status=status,
        basis="limitações declaradas pela junção clínica", kind="computed",
        transform=lambda items: " ".join(str(x) for x in items),
    )

    return compiler.compile(
        execution_manifest={
            "status": findings.payload.get("operational_status", UNAVAILABLE),
            "CLINICAL_FINDINGS_SHA256": findings.sha256,
            "COMPLETENESS_MATRIX_SHA256": matrix.sha256,
            "ARRAY_QC_SHA256": qc.sha256,
            "GENE_DISEASE_EVIDENCE_SHA256": findings.payload["evidence"].get("sha256"),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--findings", required=True, help="clinical-findings.json")
    parser.add_argument("--matrix", required=True, help="completeness matrix JSON")
    parser.add_argument("--qc", required=True, help="array-qc.json")
    parser.add_argument("--payload-out", required=True)
    args = parser.parse_args()

    payload = build_payload(Path(args.findings), Path(args.matrix), Path(args.qc))
    out = Path(args.payload_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "payload": str(out),
                "operational_status": payload["operational_status"],
                "findings": len(payload["findings"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
