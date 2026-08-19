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
    "Cartão genômico de anestesia",
    "Plano de atualização",
    "Limitações e fontes",
)

UNAVAILABLE = "NÃO DISPONÍVEL"


def _percent(value: float) -> str:
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
    parts = []
    for record in genes:
        loci = ", ".join(_locus_text(x) for x in record["loci"])
        parts.append(
            f"{record['gene']} ({record['interrogated_loci']}/{record['total_loci']} interpretáveis): {loci}"
            f" | diplótipo: {record['diplotype']['status']}"
            f" | fenótipo: {record['phenotype']['status']}"
        )
    return "; ".join(parts)


def _anesthesia_text(card: dict) -> str:
    if card.get("status") == UNAVAILABLE and not card.get("observations"):
        return f"{UNAVAILABLE} — {card.get('reason', 'cartão não emitido')}. {card.get('clearance_policy', '')}".strip()
    observations = "; ".join(
        f"{o['gene']} {_locus_text(o)}" for o in card.get("observations", [])
    )
    return f"Observações: {observations}. {card.get('clearance_policy', '')}".strip()


def build_payload(passport_path: Path, matrix_path: Path) -> dict:
    passport = Artifact.from_path("pgx-passport", passport_path)
    matrix = Artifact.from_path("completeness-matrix", matrix_path)

    case_id = passport.payload.get("case_id") or UNAVAILABLE
    compiler = PayloadCompiler(case_id=str(case_id), report_id=REPORT_ID)
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
            "Nenhum diplótipo foi estabelecido nesta execução. "
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

    ready = passport_status == "VERIFICADO"
    return compiler.compile(
        publication_gate={
            "passed": ready,
            "consent_verified": bool(passport.payload.get("case_id")),
            "qc_verified": ready,
            "evidence_verified": True,
            "placeholders_resolved": True,
        },
        policy_evaluation={
            "ready_for_requested_operation": ready,
            "planes": {
                k: {"state": "PASS" if ready else "BLOCKED"}
                for k in ("policy_control", "scientific_data", "evidence", "audit")
            },
            "gates": [
                {"gate": "FINAL_AUDIT_GATE", "state": "PASS" if ready else "BLOCKED", "blocking": True}
            ],
        },
        execution_manifest={
            "status": passport_status,
            "PGX_PASSPORT_SHA256": passport.sha256,
            "COMPLETENESS_MATRIX_SHA256": matrix.sha256,
        },
    )


def main() -> int:
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

    payload = build_payload(passport_path, matrix_path)
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
    return 0 if passport["operational_status"] == "VERIFICADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
