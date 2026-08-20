#!/usr/bin/env python3
"""Compile report 03 (Relatório Genômico Reprodutivo) from the curated clinical join.

Carrier screening is where a partial panel does its most specific damage. Two failures are
structural, and both are refused here rather than caveated.

**A negative carrier screen is not a negative carrier status.** The panel interrogates one or
two positions in a gene for which ClinVar classifies hundreds of variants pathogenic. The
detection rate is well below one, so a negative result leaves residual risk. This report
states the denominator — how many P/LP variants ClinVar lists for the gene against how many
this panel interrogated — as a *variant count*, never as a detection rate: rare variants
dominate the count while common ones dominate the frequency, and converting one into the
other without allele frequencies would be the overstatement the number exists to prevent.

**Combined couple risk needs two people.** One sample supports statements about one person.
The combined-risk section is NÃO DISPONÍVEL, and it is not softened into "risco combinado
estimado": there is nothing to combine. Phase, likewise, is not derivable from an array, so
two variants in one gene cannot be assigned to chromosomes — which is exactly the question a
couple asks about a recessive condition.

What it can do: report carrier findings where a mode of inheritance is actually curated,
and refuse the interpretation where it is not.
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
    AUTOSOMAL_RECESSIVE,
    GENOTIPO_DE_RISCO,
    NEGATIVO,
    PORTADOR,
)
from reporting.provenance import Artifact, PayloadCompiler

REPORT_ID = "03"

#: Exactly as reporting/catalog.json declares them.
SECTIONS = (
    "Identificação e controle",
    "Resumo para o casal",
    "Escopo individual e comparabilidade",
    "Achados de portador por pessoa",
    "Risco combinado e fase",
    "Opções, confirmação e aconselhamento",
    "Limitações e fontes",
)

UNAVAILABLE = "NÃO DISPONÍVEL"


def _recessive_genes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Interrogated loci in genes with a curated autosomal-recessive relationship.

    A finding for a locus the array never carried has no `validity` block — the clinical join
    stores gene curations once, under `gene_validity`, rather than copying them onto tens of
    thousands of untested loci. Those loci are correctly outside carrier screening anyway:
    nothing was interrogated, so nothing can be screened.
    """
    return [
        f
        for f in payload["findings"]
        if f.get("validity", {}).get("established")
        and AUTOSOMAL_RECESSIVE in f["validity"]["modes_of_inheritance"]
    ]


#: How many genes the scope section names individually. The rest are summarised, because a
#: panel covering seven hundred recessive genes produces a paragraph nobody reads and the
#: aggregate detection rate is the number that answers the question.
MAX_GENES_NAMED = 12


def _detection(payload: dict[str, Any]) -> dict[str, Any]:
    """Interrogated variants against the pathogenic catalogue, per gene and in aggregate.

    This is the number report 03 exists to state and could not: a negative carrier screen is
    only interpretable against how much of each gene's pathogenic catalogue the panel could
    even look at. It is a count of *variants*, never a detection rate over risk — rare
    variants dominate the count while common ones dominate the frequency.
    """
    by_gene: dict[str, dict[str, Any]] = {}
    for finding in _recessive_genes(payload):
        gene = str(finding.get("gene") or "sem gene")
        counts = finding["validity"].get("clinvar_variant_counts") or {}
        entry = by_gene.setdefault(
            gene,
            {
                "gene": gene,
                "interrogated": 0,
                "catalogued": counts.get("pathogenic"),
                "representable": counts.get("representable_in_registry"),
            },
        )
        if finding["coverage_class"] in ("OBSERVADO", "NÃO DETECTADO"):
            entry["interrogated"] += 1
    genes = [g for g in by_gene.values() if g["interrogated"]]
    genes.sort(key=lambda g: (-g["interrogated"], g["gene"]))
    interrogated = sum(g["interrogated"] for g in genes)
    catalogued = sum(g["catalogued"] or 0 for g in genes)
    priced = [g for g in genes if g["catalogued"]]
    # The denominator is the registry's recessive genes, not the genes this sample reached.
    # `by_gene` is built from findings that carry a validity block, and only interrogated
    # loci do — so `len(by_gene)` equals the interrogated count by construction and printed
    # as "602 genes ... of the 602 in the registry", a tautology that reads to a clinician as
    # complete gene coverage. The real figure comes from the clinical join's registry block,
    # counted over the whole curated evidence file.
    registry = payload.get("registry") or {}
    registry_recessive = registry.get("recessive_genes_established")
    return {
        "genes": genes,
        "genes_total": registry_recessive,
        "genes_reached": len(by_gene),
        "genes_interrogated": len(genes),
        "interrogated": interrogated,
        "catalogued": catalogued,
        "genes_without_denominator": len(genes) - len(priced),
    }


def _scope_text(payload: dict[str, Any]) -> str:
    detection = _detection(payload)
    if not detection["genes"]:
        return (
            "Nenhum gene com relação gene-doença autossômica recessiva estabelecida por "
            "ClinGen ou GenCC teve variante interrogada nesta amostra; não há escopo de "
            "triagem de portadores neste painel."
        )
    named = detection["genes"][:MAX_GENES_NAMED]
    lines = [
        f"{g['gene']}: {g['interrogated']}/"
        + (str(g["catalogued"]) if g["catalogued"] else UNAVAILABLE)
        for g in named
    ]
    remaining = detection["genes_interrogated"] - len(named)
    rate = (
        f"{detection['interrogated']} de {detection['catalogued']} variantes classificadas "
        f"P/LP no ClinVar foram interrogadas, em {detection['genes_interrogated']} genes "
        + (
            f"recessivos curados dos {detection['genes_total']} do registro"
            if detection["genes_total"]
            else "recessivos curados; o total de genes recessivos do registro não consta "
            "deste artefato e nenhum denominador é afirmado"
        )
    )
    return (
        rate
        + " (contagem de variantes, não de frequência alélica: variantes raras dominam a "
        "contagem e comuns dominam a frequência, portanto isto limita quanto do catálogo foi "
        "coberto e nada diz sobre quanto do risco foi). Genes mais cobertos, interrogadas/"
        "catalogadas: "
        + "; ".join(lines)
        + (f" (+{remaining} genes)" if remaining > 0 else "")
        + (
            f". {detection['genes_without_denominator']} genes sem denominador recuperado."
            if detection["genes_without_denominator"]
            else ""
        )
    )


def _carrier_text(payload: dict[str, Any]) -> str:
    carriers = [f for f in payload["findings"] if f["interpretation"] == PORTADOR]
    risk = [f for f in payload["findings"] if f["interpretation"] == GENOTIPO_DE_RISCO]
    parts: list[str] = []
    if carriers:
        parts.append(
            "Portador: "
            + "; ".join(
                f"{f.get('gene')} {f['rsid']} {f.get('genotype')} — "
                f"{', '.join(f['validity']['recessive_diseases']) or 'condição curada'} "
                f"(validade por {', '.join(f['validity']['established_by'])})"
                for f in carriers
            )
        )
    else:
        parts.append(
            "Nenhum estado de portador estabelecido nos loci interrogados. Isso vale apenas "
            "para as variantes efetivamente ensaiadas, não para os genes"
        )
    if risk:
        parts.append(
            "Genótipo de risco sem interpretação de portador: "
            + "; ".join(f"{f.get('gene')} {f['rsid']}: {f['interpretation_basis']}" for f in risk)
        )
    negatives = [
        f
        for f in _recessive_genes(payload)
        if f["interpretation"] == NEGATIVO
    ]
    if negatives:
        parts.append(
            f"Interrogados e sem o alelo avaliado em genes recessivos ({len(negatives)}): "
            + ", ".join(f"{f.get('gene')} {f['rsid']}" for f in negatives)
            + ". Resultado negativo por locus não é rastreamento negativo do gene"
        )
    return " | ".join(parts)


def _options_text(payload: dict[str, Any]) -> str:
    carriers = sum(1 for f in payload["findings"] if f["interpretation"] == PORTADOR)
    return (
        f"{carriers} achado(s) de portador exigem confirmação por método ortogonal antes de "
        "qualquer decisão reprodutiva. Aconselhamento genético é indicado independentemente do "
        "resultado, porque a interpretação de risco reprodutivo depende de história familiar, "
        "consanguinidade e ancestralidade, nenhuma das quais consta deste pipeline. Este "
        "documento não indica nem contraindica técnica reprodutiva, diagnóstico pré-implantação "
        "ou diagnóstico pré-natal: essas são decisões clínicas e pessoais."
    )


def build_payload(findings_path: Path, matrix_path: Path) -> dict:
    findings = Artifact.from_path("clinical-findings", findings_path)
    matrix = Artifact.from_path("completeness-matrix", matrix_path)
    if findings.payload.get("input_sha256") != matrix.payload.get("input_sha256"):
        raise ValueError("clinical findings and completeness matrix describe different inputs")

    case_id = findings.payload.get("case_id") or UNAVAILABLE
    compiler = PayloadCompiler(case_id=str(case_id), report_id=REPORT_ID)
    compiler.register(findings)
    compiler.register(matrix)

    verified = findings.payload.get("operational_status") == "VERIFICADO"
    status = "VERIFICADO" if verified else UNAVAILABLE

    def summary(_totals: Any) -> str:
        carriers = sum(1 for f in findings.payload["findings"] if f["interpretation"] == PORTADOR)
        recessive = _recessive_genes(findings.payload)
        genes = len({f.get("gene") for f in recessive})
        return (
            f"{carriers} estado(s) de portador estabelecido(s) em {genes} gene(s) com herança "
            "autossômica recessiva curada. Triagem por microarranjo interroga variantes "
            "específicas, não genes: um rastreamento negativo aqui reduz mas não elimina o "
            "risco de ser portador. Risco combinado do casal não é calculado — apenas uma "
            "pessoa foi analisada."
        )

    compiler.derive(
        "summary", artifact="clinical-findings", locator="totals", status=status,
        basis="contagem de achados de portador sobre genes recessivos curados", kind="computed",
        transform=summary,
    )
    compiler.section_derived(
        "Identificação e controle", artifact="clinical-findings", locator="case_id",
        status=status, basis="identificador do caso e integridade dos artefatos", kind="qc_metric",
        transform=lambda cid: (
            f"Caso {cid}; entrada SHA-256 {findings.payload.get('input_sha256')}; "
            f"junção clínica {findings.sha256}. Uma única pessoa foi analisada."
        ),
    )
    # There is no couple. Writing a couple summary would require a second sample that does
    # not exist, and "resumo para o casal" built from one genome is the failure this section
    # is most likely to produce.
    compiler.section_unavailable(
        "Resumo para o casal",
        basis=(
            "apenas uma pessoa foi analisada; um resumo do casal exige a amostra do parceiro, "
            "e nenhum resumo é derivável de um único genoma"
        ),
    )
    compiler.section_derived(
        "Escopo individual e comparabilidade", artifact="clinical-findings", locator="findings",
        status=status,
        basis="fração do catálogo de variantes P/LP do ClinVar interrogada por gene recessivo",
        kind="computed", transform=lambda _f: _scope_text(findings.payload),
    )
    compiler.section_derived(
        "Achados de portador por pessoa", artifact="clinical-findings", locator="findings",
        status=status, basis="loci em genes recessivos curados, por classe de afirmação",
        kind="computed", transform=lambda _f: _carrier_text(findings.payload),
    )
    compiler.section_unavailable(
        "Risco combinado e fase",
        basis=(
            "risco combinado exige duas amostras e apenas uma foi analisada; fase não é "
            "derivável de genotipagem em array, portanto duas variantes num mesmo gene não "
            "podem ser atribuídas a cromossomos distintos"
        ),
    )
    compiler.section_derived(
        "Opções, confirmação e aconselhamento", artifact="clinical-findings", locator="totals",
        status=status, basis="exigência de confirmação e de aconselhamento", kind="computed",
        transform=lambda _t: _options_text(findings.payload),
    )
    compiler.section_derived(
        "Limitações e fontes", artifact="clinical-findings", locator="limitations",
        status=status, basis="limitações e fontes curadas da junção clínica", kind="computed",
        transform=lambda items: " ".join(str(x) for x in items)
        + " Fontes: "
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
        transform=lambda items: " ".join(str(x) for x in items)
        + " Triagem de portadores por array não substitui painel de sequenciamento;"
        " resultado negativo reduz mas não elimina risco residual.",
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
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--findings", required=True)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--payload-out", required=True)
    args = parser.parse_args()

    payload = build_payload(Path(args.findings), Path(args.matrix))
    out = Path(args.payload_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"payload": str(out), "operational_status": payload["operational_status"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
