#!/usr/bin/env python3
"""Compile report 06 (Farmacogenômica e Cartão Genômico de Anestesia) from artifacts.

Like report 09, every printed value is anchored to a locator inside a pipeline artifact and
re-checked by PROVENANCE_GATE at render time. The sections most worth faking here — a
diplotype, a metabolizer phenotype, an anaesthesia clearance — are derived from the passport,
which withholds each of them unless its preconditions actually hold.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.completeness import build_completeness_matrix, write_matrix
from array_pipeline.pharmacogenomics import build_pharmacogenomic_passport, write_passport
from reporting.provenance import Artifact, PayloadCompiler

REPORT_ID = "06"

#: Exactly as reporting/catalog.json declares them.
SECTIONS = (
    "Identificação e controle",
    "Resumo farmacogenômico",
    "Medicações e fenoconversão",
    "Camada técnica por gene",
    "Diplótipo condicional e risco residual",
    "Requisição de sequenciamento",
    "Cartão genômico de anestesia",
    "Plano de atualização",
    "Limitações e fontes",
)

UNAVAILABLE = "NÃO DISPONÍVEL"


def _percent(value: float) -> str:
    """A fraction as a percentage with one decimal, for printing on the page."""
    return f"{value * 100:.1f}%"


def _locus_text(locus: dict) -> str:
    """Print a genotype only for an interpretable locus.

    The matrix already withholds the genotype for a NÃO REPORTÁVEL record, but printing
    `genotype or classification` made every consumer depend on that upstream guard being
    right. Deciding here as well means a regression upstream degrades the line to the
    classification rather than publishing an arbitrated call.
    """
    if locus.get("interpretable") and locus.get("genotype"):
        return f"{locus['rsid']}={locus['genotype']}"
    return f"{locus['rsid']}={locus.get('classification') or UNAVAILABLE}"


def _gene_layer(genes: list) -> str:
    """The per-gene coverage paragraph, naming each gene's interrogated loci."""
    parts = []
    for record in genes:
        loci = ", ".join(_locus_text(x) for x in record["loci"])
        parts.append(
            f"{record['gene']} ({record['interrogated_loci']}/{record['total_loci']} interpretáveis): {loci}"
            f" | diplótipo: {record['diplotype']['status']}"
            f" | fenótipo: {record['phenotype']['status']}"
        )
    return "; ".join(parts)


def _percent_or_unavailable(value) -> str:
    """A percentage when there is a number, NÃO DISPONÍVEL otherwise.

    Never 0%: a missing measurement and a measured zero are different facts, and printing the
    second for the first states a result nobody produced.
    """
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else UNAVAILABLE


def _conditional_layer(genes: list) -> str:
    """The conditional diplotypes and phenotypes, with the residual that qualifies them.

    This layer was computed into the passport and rendered nowhere. The two artifacts of one
    run therefore disagreed about what had been derived: the report said "Nenhum diplótipo
    foi estabelecido nesta execução" and printed `fenótipo: NÃO DISPONÍVEL` for CYP2C19,
    while the passport delivered beside it carried
    `conditional_phenotype: INFERIDO -> Normal Metabolizer` for the same gene — under a
    residual of 0.245 in African American/Afro-Caribbean, a quarter of the altered-function
    allele frequency left unexcluded, and a lower bound at that.

    A phenotype that exists in the machine-readable artifact and not in the document is worse
    than either publishing it or not computing it: whoever reads the JSON gets the label
    without the paragraph that qualifies it, and whoever reads the report is told nothing was
    derived. It is published here, and the residual is not separable from it.
    """
    lines: list[str] = []
    for record in genes:
        discrimination = record.get("discrimination") or {}
        diplotype = discrimination.get("conditional_diplotype") or {}
        if diplotype.get("status") != "INFERIDO":
            reasons = "; ".join(diplotype.get("reasons") or []) or UNAVAILABLE
            lines.append(f"{record['gene']}: sem diplótipo condicional — {reasons}")
            continue

        residual = discrimination.get("residual") or {}
        phenotype = discrimination.get("conditional_phenotype") or {}
        altered = _percent_or_unavailable(residual.get("worst_altered"))
        uncertain = _percent_or_unavailable(residual.get("worst_uncertain"))
        bound = "" if residual.get("bounded") else " (limite inferior)"
        phenotype_text = (
            f"fenótipo condicional {phenotype['value']}"
            if phenotype.get("status") == "INFERIDO"
            else f"fenótipo condicional {UNAVAILABLE} — {phenotype.get('reason', UNAVAILABLE)}"
        )
        lines.append(
            f"{record['gene']}: {diplotype['value']} "
            f"({diplotype['alleles_tested']} alelos testados, "
            f"{diplotype['alleles_not_excluded']} não excluídos); {phenotype_text}. "
            f"Risco residual{bound}: função alterada {altered} em "
            f"{residual.get('worst_population') or UNAVAILABLE}, função incerta {uncertain} em "
            f"{residual.get('worst_uncertain_population') or UNAVAILABLE}."
        )
    return " | ".join(lines) if lines else "nenhum gene com camada condicional nesta execução"


def _requisition_text(requisitions: list) -> str:
    """The sequencing-requisition section, which says *why* when it proposes nothing.

    An empty list has two causes — no gene carries actionable alleles, or none could be
    assessed — and the reader needs to know which, so the absence is explained rather than
    left as a blank section.
    """
    if not requisitions:
        return (
            "Nenhuma requisição de sequenciamento foi proposta: ou nenhum gene tem alelos de "
            "função alterada ou incerta por excluir, ou não há registro sobre o qual calcular."
        )
    parts = [
        f"{r['gene']}: {r['position_count']} posições resolvem "
        f"{len(r.get('alleles_resolved') or [])} alelos"
        + (
            f"; {len(r['alleles_unresolvable'])} permanecem indiscrimináveis"
            if r.get("alleles_unresolvable")
            else ""
        )
        for r in requisitions
    ]
    return (
        "PROPOSTO (não executado): " + "; ".join(parts) + ". "
        + (requisitions[0].get("scope_note") or "")
    ).strip()


def _anesthesia_text(card: dict) -> str:
    """The anaesthesia card section, or an explicit statement of why no card was issued.

    This is the one section a clinician may act on in an emergency, so an unissued card names
    the gaps that prevented it rather than printing a reassuring blank.
    """
    if card.get("status") == UNAVAILABLE and not card.get("observations"):
        gaps = _anesthesia_gaps(card)
        reason = card.get("reason") or card.get("status_reason") or "cartão não emitido"
        return f"{UNAVAILABLE} — {reason}. {gaps}{card.get('clearance_policy', '')}".strip()
    observations = "; ".join(
        f"{o['gene']} {_locus_text(o)}" for o in card.get("observations", [])
    )
    return (
        f"Status do cartão: {card.get('status', UNAVAILABLE)}. Observações: {observations}. "
        f"{_anesthesia_gaps(card)}{card.get('clearance_policy', '')}"
    ).strip()


def _anesthesia_gaps(card: dict) -> str:
    """The genes the card could not interrogate, named before the observations are read.

    Left implicit, an anaesthesia card that reads cleanly on BCHE is indistinguishable from
    one that covered the whole guideline — and the genes missing from this one are the two
    CPIC rates level A for exactly the drugs the card is consulted about.
    """
    missing = card.get("not_interrogated") or []
    if not missing:
        return ""
    parts = [
        f"{entry['gene']} (CPIC nível {entry.get('cpic_level', UNAVAILABLE)}: "
        f"{', '.join(entry.get('drugs') or []) or UNAVAILABLE})"
        for entry in missing
    ]
    return (
        f"NÃO INTERROGADO — {'; '.join(parts)}. Nenhuma posição destes genes foi ensaiada e "
        "nada neste relatório fala sobre eles; ausência de achado aqui é ausência de exame, "
        "não ausência de risco. "
    )


def build_payload(
    passport_path: Path,
    matrix_path: Path,
    policy_evaluation: Path | None = None,
    post_deployment_witness: Path | None = None,
    consent: Path | None = None,
) -> dict:
    """Compile the payload for the pharmacogenomic report from passport and matrix.

    The two artifacts must carry the same non-empty `input_sha256`, and that is checked
    before anything is read out of them. Without it a passport from one sample and a
    completeness matrix from another would compose into a single coherent-looking report:
    every field would be individually true and the document as a whole would be about
    nobody.

    `policy_evaluation`, `post_deployment_witness` and `consent` are optional paths, not
    optional requirements. Omitting one does not waive the corresponding gate; it leaves the
    payload without that anchor, and the publication gate in `reporting.engine` refuses to
    release a FINAL document that lacks it.
    """
    passport = Artifact.from_path("pgx-passport", passport_path)
    matrix = Artifact.from_path("completeness-matrix", matrix_path)
    passport_input = str(passport.payload.get("input_sha256") or "").strip()
    matrix_input = str(matrix.payload.get("input_sha256") or "").strip()
    if not passport_input or not matrix_input or passport_input != matrix_input:
        raise ValueError(
            "passport and completeness matrix must describe the same non-empty input_sha256"
        )

    case_id = passport.payload.get("case_id") or UNAVAILABLE
    compiler = PayloadCompiler(
        case_id=str(case_id),
        report_id=REPORT_ID,
        policy_evaluation=policy_evaluation,
        post_deployment_witness=post_deployment_witness,
        consent=consent,
    )
    compiler.register(passport)
    compiler.register(matrix)

    passport_status = str(passport.payload.get("operational_status") or UNAVAILABLE)
    status = "VERIFICADO" if passport_status == "VERIFICADO" else UNAVAILABLE

    compiler.derive(
        "summary",
        artifact="pgx-passport",
        locator="totals",
        status=status,
        basis="cobertura farmacogenômica calculada a partir da matriz de completude",
        kind="computed",
        transform=lambda t: (
            f"{t['interrogated_loci']} de {t['loci']} loci farmacogenômicos são interpretáveis "
            f"({_percent(t['interrogated_fraction'])}) em {t['genes']} genes. "
            f"Diplótipos estabelecidos: {t['genes_with_diplotype']}. "
            f"Fenótipos emitidos: {t['genes_with_phenotype']}."
        ),
    )

    compiler.section_derived(
        "Identificação e controle",
        artifact="pgx-passport",
        locator="input_sha256",
        status=status,
        basis="SHA-256 do array efetivamente analisado",
        kind="computed",
        transform=lambda sha: f"Caso {case_id}; entrada SHA-256 {sha}.",
    )

    compiler.section_derived(
        "Resumo farmacogenômico",
        artifact="pgx-passport",
        locator="genes",
        status=status,
        basis="estado de diplótipo por gene",
        kind="computed",
        transform=lambda genes: (
            # Qualified: the unconditional diplotype is one of two things this run derives,
            # and the flat sentence read as "nothing was derived" while the passport carried
            # conditional diplotypes and a metabolizer label for the same genes.
            (
                "Nenhum diplótipo incondicional foi estabelecido nesta execução"
                + (
                    "; a camada condicional abaixo registra o que foi derivado sob suposição "
                    "declarada e o risco residual dela. "
                    if any(
                        ((g.get("discrimination") or {}).get("conditional_diplotype") or {}).get("status")
                        == "INFERIDO"
                        for g in genes
                    )
                    else ", e nenhum diplótipo condicional foi derivado. "
                )
            )
            if all(g["diplotype"]["status"] == UNAVAILABLE for g in genes)
            else ""
        )
        + "Genes avaliados: "
        + ", ".join(
            f"{g['gene']} ({g['diplotype']['status']})" for g in genes
        )
        + ".",
    )

    # Phenoconversion depends on medication history, hepatic/renal function and comorbidity,
    # none of which this pipeline holds. Emitting generic drug guidance here would be the
    # most consequential invention in the whole report.
    compiler.section_derived(
        "Medicações e fenoconversão",
        artifact="pgx-passport",
        locator="prescribing_policy",
        status=status,
        basis="política de prescrição declarada pelo passaporte",
    )

    compiler.section_derived(
        "Camada técnica por gene",
        artifact="pgx-passport",
        locator="genes",
        status=status,
        basis="loci, classificações e estado de diplótipo/fenótipo por gene",
        kind="computed",
        transform=_gene_layer,
    )

    compiler.section_derived(
        "Diplótipo condicional e risco residual",
        artifact="pgx-passport",
        locator="genes",
        status=status,
        basis=(
            "diplótipo condicionado ao conjunto de alelos discriminável nesta amostra, com o "
            "risco residual dos alelos não excluídos por grupo biogeográfico"
        ),
        kind="computed",
        transform=_conditional_layer,
    )

    compiler.section_derived(
        "Requisição de sequenciamento",
        artifact="pgx-passport",
        locator="sequencing_requisitions",
        status=status,
        basis="posições que tornariam discrimináveis os alelos de função alterada ou incerta",
        kind="computed",
        transform=_requisition_text,
    )

    compiler.section_derived(
        "Cartão genômico de anestesia",
        artifact="pgx-passport",
        locator="anesthesia_card",
        status=status,
        basis="observações de loci declarados relevantes para anestesia",
        kind="computed",
        transform=_anesthesia_text,
    )

    compiler.section_derived(
        "Plano de atualização",
        artifact="pgx-passport",
        locator="pgx_registry",
        status=status,
        basis="registro de definições de alelos em vigor nesta execução",
        kind="computed",
        transform=lambda reg: (
            f"Registro de definições: {reg['id']} versão {reg['version']}, fonte {reg['source']} "
            f"(SHA-256 {reg['sha256']}). Reanálise exige nova versão do registro."
            if reg.get("id")
            else f"Registro de definições de alelos: {UNAVAILABLE} — {reg.get('reason', '')}. "
            "Sem ele, nenhum alelo estrela é nomeado e nenhum diplótipo é estabelecido."
        ),
    )

    compiler.section_derived(
        "Limitações e fontes",
        artifact="pgx-passport",
        locator="limitations",
        status=status,
        basis="limitações declaradas pelo passaporte",
        kind="computed",
        transform=lambda items: " ".join(str(x) for x in items),
    )

    # One structured finding per gene, carrying the reason a diplotype was withheld. The
    # withholding is the clinically important content, so it is reported, not omitted.
    for index, record in enumerate(passport.payload.get("genes", [])):
        gene = str(record["gene"])
        builder = compiler.finding(f"PGX-{gene}", basis="registro por gene do passaporte")
        builder.stated("domain", gene, kind="case_control", basis="gene do registro de alvos", status="VERIFICADO")
        builder.derived(
            "nature", artifact="pgx-passport", locator=f"genes[{index}].diplotype.status",
            status=status, basis="estado do diplótipo", kind="computed",
            transform=lambda s: f"diplótipo {s}",
        )
        builder.derived(
            "observed_data", artifact="pgx-passport", locator=f"genes[{index}].loci",
            status=status, basis="genótipos observados neste gene", kind="computed",
            transform=lambda loci: ", ".join(_locus_text(x) for x in loci) or UNAVAILABLE,
        )
        builder.derived(
            "qc", artifact="pgx-passport", locator=f"genes[{index}].interrogated_loci",
            status=status, basis="loci interpretáveis neste gene", kind="computed",
            transform=lambda n: f"{n} locus/loci interpretáveis",
        )
        builder.derived(
            "uncertainties", artifact="pgx-passport", locator=f"genes[{index}].diplotype.reasons",
            status=status, basis="motivos pelos quais o diplótipo foi retido", kind="computed",
            transform=lambda reasons: "; ".join(str(x) for x in reasons) or UNAVAILABLE,
        )
        builder.derived(
            "interpretation", artifact="pgx-passport", locator=f"genes[{index}].phenotype.reason",
            status=status, basis="motivo pelo qual o fenótipo não foi emitido", kind="computed",
        )
        builder.derived(
            "status", artifact="pgx-passport", locator=f"genes[{index}].phenotype.status",
            status=status, basis="estado operacional do fenótipo", kind="computed",
        )
        builder.stated(
            "priority",
            "CLINICO" if record.get("interrogated_loci") else UNAVAILABLE,
            kind="case_control", basis="escopo do registro de alvos", status="VERIFICADO",
        )
        evidence = [e for locus in record["loci"] for e in locus.get("evidence", [])]
        if evidence:
            builder.derived(
                "evidence_refs", artifact="pgx-passport", locator=f"genes[{index}].loci",
                status=status, basis="recuperações externas verificadas ligadas a este gene",
                kind="evidence_retrieval",
                transform=lambda loci: ", ".join(
                    sorted({e["id"] for x in loci for e in x.get("evidence", [])})
                ) or UNAVAILABLE,
            )
        else:
            builder.unavailable(
                "evidence_refs", basis="nenhuma recuperação externa foi executada nesta execução"
            )
        builder.unavailable(
            "confirmation", basis="nenhuma confirmação por método ortogonal foi executada nesta execução"
        )
        builder.add()

    compiler.state(
        "sources",
        [f"pgx-passport:{passport.sha256}", f"completeness-matrix:{matrix.sha256}"],
        kind="case_control",
        basis="artefatos que originaram cada valor deste relatório",
        status="VERIFICADO",
    )
    compiler.derive(
        "limitations",
        artifact="pgx-passport",
        locator="limitations",
        status=status,
        basis="limitações declaradas pelo passaporte",
        kind="computed",
        transform=lambda items: " ".join(str(x) for x in items),
    )

    return compiler.compile(
        execution_manifest={
            "status": passport_status,
            "PGX_PASSPORT_SHA256": passport.sha256,
            "COMPLETENESS_MATRIX_SHA256": matrix.sha256,
        },
    )


def main() -> int:
    """Build report 06 from an array input, its QC record and the pharmacogenomic passport."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="SNP-array CSV/gz/zip")
    parser.add_argument("--qc", required=True, help="array-qc.json")
    parser.add_argument("--targets", required=True, help="target registry JSON")
    parser.add_argument("--annotation", help="partial-genome annotation JSON (links evidence)")
    parser.add_argument("--pgx-registry", help="curated, cited allele-definition registry")
    parser.add_argument(
        "--pgx-panel",
        help=(
            "CPIC defining-position panel manifest from scripts/build_pgx_panel.py. Without it "
            "coverage is measured over the curated targets only, and every other CPIC position "
            "reads as NÃO TESTADO whether or not the array carries it."
        ),
    )
    parser.add_argument("--matrix-out", required=True)
    parser.add_argument("--panel-matrix-out", help="where to write the panel coverage matrix")
    parser.add_argument("--passport-out", required=True)
    parser.add_argument("--payload-out", required=True)
    parser.add_argument("--policy-evaluation", help="policy-engine evaluation JSON")
    parser.add_argument("--post-deployment-witness", help="live post-deployment witness JSON")
    parser.add_argument("--consent", help="consent record JSON")
    args = parser.parse_args()

    if args.pgx_panel and not args.panel_matrix_out:
        parser.error("--pgx-panel requires --panel-matrix-out")

    matrix = build_completeness_matrix(Path(args.input), Path(args.qc), Path(args.targets))
    matrix_path = write_matrix(matrix, Path(args.matrix_out))

    panel_matrix_path = None
    if args.pgx_panel:
        panel_matrix = build_completeness_matrix(
            Path(args.input), Path(args.qc), Path(args.pgx_panel)
        )
        panel_matrix_path = write_matrix(panel_matrix, Path(args.panel_matrix_out))

    passport = build_pharmacogenomic_passport(
        matrix_path,
        Path(args.targets),
        annotation_path=Path(args.annotation) if args.annotation else None,
        pgx_registry_path=Path(args.pgx_registry) if args.pgx_registry else None,
        panel_matrix_path=panel_matrix_path,
    )
    passport_path = write_passport(passport, Path(args.passport_out))

    payload = build_payload(
        passport_path,
        matrix_path,
        policy_evaluation=(
            Path(args.policy_evaluation) if args.policy_evaluation else None
        ),
        post_deployment_witness=(
            Path(args.post_deployment_witness)
            if args.post_deployment_witness
            else None
        ),
        consent=Path(args.consent) if args.consent else None,
    )
    out = Path(args.payload_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "matrix": str(matrix_path),
                "passport": str(passport_path),
                "payload": str(out),
                "operational_status": payload["operational_status"],
                "totals": passport["totals"],
                "anesthesia_card": passport["anesthesia_card"]["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    publication_gate = payload.get("publication_gate") or {}
    publication_ready = (
        payload.get("operational_status") == "VERIFICADO"
        and all(
            publication_gate.get(key) is True
            for key in (
                "passed",
                "consent_verified",
                "consent_scope_verified",
                "qc_verified",
                "evidence_verified",
                "placeholders_resolved",
            )
        )
    )
    return 0 if publication_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
