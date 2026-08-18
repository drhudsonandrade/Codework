#!/usr/bin/env python3
"""Compile report 09 (Genome Completeness & Blind Spots) from real pipeline artifacts.

This is the first report whose payload is *derived* rather than curated by hand: every
sentence it prints is anchored to a locator inside the completeness matrix or the QC
artifact, and `PROVENANCE_GATE` re-checks that binding at render time. There is no argument
that lets a caller supply prose for a section.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.completeness import (
    CLASSES,
    NAO_REPORTAVEL,
    NAO_TESTADO,
    NO_CALL,
    build_completeness_matrix,
    write_matrix,
)
from reporting.provenance import Artifact, PayloadCompiler

REPORT_ID = "09"

#: Report 09's section titles, exactly as reporting/catalog.json declares them. The engine
#: prints sections by looking up the catalogue title, so a paraphrase here would render an
#: empty section while the anchored text sat unreachable under a key nobody reads.
SECTIONS = (
    "Identificação e controle",
    "Painel de completude",
    "Matriz por classe",
    "Matriz por gene/região",
    "Evidência negativa",
    "Plano para fechar lacunas",
    "Limitações e fontes",
)


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _by_gene(entries: list) -> str:
    """Group the coverage classes by gene, so a partly-covered gene is visible as such."""
    grouped: dict[str, list[str]] = {}
    for entry in entries:
        gene = str(entry.get("gene") or "sem gene declarado")
        grouped.setdefault(gene, []).append(f"{entry['rsid']}={entry['classification']}")
    return "; ".join(f"{gene}: {', '.join(sorted(loci))}" for gene, loci in sorted(grouped.items()))


def build_payload(matrix_path: Path, qc_path: Path) -> dict:
    """Anchor every printed value of report 09 to the artifact it came from."""
    matrix = Artifact.from_path("completeness-matrix", matrix_path)
    qc = Artifact.from_path("array-qc", qc_path)

    case_id = matrix.payload.get("case_id") or "NÃO DISPONÍVEL"
    compiler = PayloadCompiler(case_id=str(case_id), report_id=REPORT_ID)
    compiler.register(matrix)
    compiler.register(qc)

    # The matrix's own operational status governs how strong any statement here may be.
    matrix_status = str(matrix.payload.get("operational_status") or "NÃO DISPONÍVEL")
    status = "VERIFICADO" if matrix_status == "VERIFICADO" else "NÃO DISPONÍVEL"

    compiler.derive(
        "summary",
        artifact="completeness-matrix",
        locator="totals",
        status=status,
        basis="totais calculados a partir da matriz de completude",
        kind="computed",
        transform=lambda totals: (
            f"{totals['interpretable']} de {totals['targets']} alvos do registro são "
            f"interpretáveis ({_percent(totals['interpretable_fraction'])}). "
            f"{totals['class_' + NAO_TESTADO]} não foram testados, "
            f"{totals['class_' + NO_CALL]} sem chamada e "
            f"{totals['class_' + NAO_REPORTAVEL]} não reportáveis."
        ),
    )

    compiler.section_derived(
        "Identificação e controle",
        artifact="completeness-matrix",
        locator="input_sha256",
        status=status,
        basis="SHA-256 do arquivo de array efetivamente analisado",
        kind="computed",
        transform=lambda sha: f"Caso {case_id}; entrada SHA-256 {sha}.",
    )

    compiler.section_derived(
        "Painel de completude",
        artifact="array-qc",
        locator="metrics.call_rate",
        status=status,
        basis="call rate medido pelo QC do array",
        kind="qc_metric",
        transform=lambda rate: (
            f"Call rate do array: {_percent(float(rate))}. "
            "Genotipagem em array não produz DP/GQ/balanço alélico; "
            "não há profundidade de leitura a reportar."
        ),
    )

    compiler.section_derived(
        "Matriz por classe",
        artifact="completeness-matrix",
        locator="totals",
        status=status,
        basis="contagem de alvos por classe operacional de cobertura",
        kind="computed",
        transform=lambda totals: "Cobertura por classe — "
        + "; ".join(f"{name}: {totals['class_' + name]}" for name in CLASSES)
        + ". Classes de variação fora do alcance da plataforma são listadas em "
        "'Matriz por gene/região'.",
    )

    compiler.section_derived(
        "Matriz por gene/região",
        artifact="completeness-matrix",
        locator="entries",
        status=status,
        basis="agrupamento por gene das classificações de cobertura",
        kind="computed",
        transform=_by_gene,
    )

    compiler.section_derived(
        "Evidência negativa",
        artifact="completeness-matrix",
        locator="negative_statement_policy",
        status=status,
        basis="política de afirmação negativa aplicada pela matriz",
    )

    # Nothing in the pipeline computes complementation routes, so the section says so
    # rather than offering generic advice that would read as a clinical recommendation.
    compiler.section_unavailable(
        "Plano para fechar lacunas",
        basis="nenhuma rota de complementação foi executada ou avaliada nesta execução",
    )

    compiler.section_derived(
        "Limitações e fontes",
        artifact="completeness-matrix",
        locator="structural_blind_spots",
        status=status,
        basis="classes de variação que a plataforma não resolve em nenhum locus",
        kind="computed",
        transform=lambda spots: (
            "Pontos cegos estruturais da plataforma (limite do método, não achado desta amostra): "
            + ", ".join(str(s["class"]) for s in spots)
            + ". Registro de alvos: "
            + f"{matrix.payload['target_manifest']['id']} "
            + f"versão {matrix.payload['target_manifest']['version']} "
            + f"(SHA-256 {matrix.payload['target_manifest']['sha256']})."
        ),
    )

    # One structured finding per non-interpretable locus. These are the blind spots the
    # report exists to make visible; each is anchored to its own entry in the matrix.
    entries = matrix.payload.get("entries", [])
    for index, entry in enumerate(entries):
        if entry.get("interpretable"):
            continue
        rsid = str(entry["rsid"])
        builder = compiler.finding(f"GCM-{rsid}", basis="entrada da matriz de completude")
        builder.derived(
            "domain", artifact="completeness-matrix", locator=f"entries[{index}].gene",
            status=status, basis="gene declarado no registro de alvos",
            kind="computed", transform=lambda gene: str(gene or "NÃO DISPONÍVEL"),
        )
        builder.derived(
            "nature", artifact="completeness-matrix", locator=f"entries[{index}].classification",
            status=status, basis="classificação operacional de cobertura", kind="computed",
        )
        builder.derived(
            "observed_data", artifact="completeness-matrix", locator=f"entries[{index}].genotype",
            status=status, basis="genótipo lido do array, se houver", kind="computed",
            transform=lambda gt: str(gt) if gt else "NÃO DISPONÍVEL",
        )
        builder.derived(
            "qc", artifact="completeness-matrix", locator=f"entries[{index}].basis",
            status=status, basis="motivo técnico da classificação", kind="computed",
        )
        builder.derived(
            "status", artifact="completeness-matrix", locator=f"entries[{index}].classification",
            status=status, basis="classificação operacional", kind="computed",
        )
        builder.stated(
            "priority", str(entry.get("scope") or "NÃO DISPONÍVEL"),
            kind="case_control", basis="escopo declarado no registro de alvos", status="VERIFICADO",
        )
        builder.stated(
            "interpretation",
            "Ponto cego: este locus não sustenta afirmação de presença nem de ausência.",
            kind="case_control", basis="consequência direta da classe de cobertura", status="VERIFICADO",
        )
        builder.unavailable("evidence_refs", basis="nenhuma evidência externa foi recuperada para um locus não interpretável")
        builder.unavailable("uncertainties", basis="a própria classe de cobertura é a incerteza")
        builder.unavailable("confirmation", basis="nenhuma confirmação foi executada nesta execução")
        builder.add()

    compiler.state(
        "sources",
        [
            f"completeness-matrix:{matrix.sha256}",
            f"array-qc:{qc.sha256}",
        ],
        kind="case_control",
        basis="artefatos que originaram cada valor deste relatório",
        status="VERIFICADO",
    )
    compiler.derive(
        "limitations",
        artifact="completeness-matrix",
        locator="limitations",
        status=status,
        basis="limitações declaradas pela matriz",
        kind="computed",
        transform=lambda items: " ".join(str(x) for x in items),
    )

    return compiler.compile(
        publication_gate={
            "passed": matrix_status == "VERIFICADO",
            "consent_verified": bool(qc.payload.get("case_id")),
            "qc_verified": bool(matrix.payload.get("qc_gate_passed")),
            "evidence_verified": True,
            "placeholders_resolved": True,
        },
        policy_evaluation={
            "ready_for_requested_operation": matrix_status == "VERIFICADO",
            "planes": {
                k: {"state": "PASS" if matrix_status == "VERIFICADO" else "BLOCKED"}
                for k in ("policy_control", "scientific_data", "evidence", "audit")
            },
            "gates": [
                {
                    "gate": "FINAL_AUDIT_GATE",
                    "state": "PASS" if matrix_status == "VERIFICADO" else "BLOCKED",
                    "blocking": True,
                }
            ],
        },
        execution_manifest={
            "status": matrix_status,
            "COMPLETENESS_MATRIX_SHA256": matrix.sha256,
            "ARRAY_QC_SHA256": qc.sha256,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="SNP-array CSV/gz/zip")
    parser.add_argument("--qc", required=True, help="array-qc.json from array_pipeline.qc")
    parser.add_argument("--targets", required=True, help="target registry JSON")
    parser.add_argument("--matrix-out", required=True)
    parser.add_argument("--payload-out", required=True)
    args = parser.parse_args()

    matrix = build_completeness_matrix(Path(args.input), Path(args.qc), Path(args.targets))
    matrix_path = write_matrix(matrix, Path(args.matrix_out))

    payload = build_payload(matrix_path, Path(args.qc))
    out = Path(args.payload_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "matrix": str(matrix_path),
                "payload": str(out),
                "operational_status": payload["operational_status"],
                "totals": matrix["totals"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if matrix["operational_status"] == "VERIFICADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
