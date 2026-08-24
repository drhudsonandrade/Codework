#!/usr/bin/env python3
"""Compile report 10 (Resumo Clínico Genômico — Uma Página) from the other reports.

This is the page a clinician reads in thirty seconds, which makes it the most dangerous
document in the suite: a one-page summary is where nuance goes to die, and where "nothing
found" quietly replaces "nothing was tested for".

It is therefore built as a *derivation of the reports that already refused to overstate*,
never as a fresh interpretation. Every value comes from the completeness matrix or the
pharmacogenomic passport, both of which are themselves anchored and gated, and the summary
inherits their refusals verbatim:

* the headline separates OBSERVADO from NÃO DETECTADO from the classes the platform cannot
  see at all, because collapsing them is exactly the failure a one-pager invites;
* the "next action" field is NÃO DISPONÍVEL unless something was actually established —
  this pipeline does not decide clinical conduct;
* structural blind spots appear on the page, not in a footnote of a longer report the
  reader is not going to open.
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

from array_pipeline.completeness import CLASSES, NAO_DETECTADO, NAO_REPORTAVEL, NO_CALL, OBSERVADO
from reporting.provenance import Artifact, PayloadCompiler

REPORT_ID = "10"

#: Exactly as reporting/catalog.json declares them.
SECTIONS = (
    "Situação atual",
    "Prioridade e confirmação",
    "Achados essenciais",
    "Alertas e pontos cegos",
    "Uso seguro e vínculos",
)

UNAVAILABLE = "NÃO DISPONÍVEL"


def _headline(totals: dict[str, Any]) -> str:
    """The one sentence most at risk of collapsing distinct classes into 'nothing found'."""
    return (
        f"{totals['class_' + OBSERVADO]} loci carregam o alelo avaliado, "
        f"{totals['class_' + NAO_DETECTADO]} foram testados e não o carregam, "
        f"{totals['class_' + NO_CALL]} sem chamada e "
        f"{totals['class_' + NAO_REPORTAVEL]} não reportáveis, "
        f"de {totals['targets']} alvos do registro. "
        "Ausência só é afirmável nos loci em NÃO DETECTADO, e apenas para aquele locus."
    )


def _observed_findings(matrix: dict[str, Any]) -> str:
    carried = [
        f"{e['gene'] or 'sem gene'} {e['rsid']} ({e['genotype']})"
        for e in matrix.get("entries", [])
        if e["classification"] == OBSERVADO and e.get("genotype")
    ]
    return "; ".join(carried) if carried else "nenhum locus interpretável carrega o alelo avaliado"


def _pgx_line(passport: dict[str, Any] | None) -> str:
    if not passport:
        return f"{UNAVAILABLE} — nenhum passaporte farmacogenômico foi compilado nesta execução"
    totals = passport["totals"]
    card = passport["anesthesia_card"]
    # The status word alone was the whole sentence here. On a card whose declared scope is
    # uncovered that word is the most misleading thing on the page, so the gap travels with
    # it: this is the line a clinician is most likely to read and least likely to follow up.
    missing = [entry["gene"] for entry in card.get("not_interrogated") or []]
    gap = (
        f" ({', '.join(missing)} não interrogado(s): nenhuma posição ensaiada)"
        if missing
        else ""
    )
    return (
        f"{totals['interrogated_loci']}/{totals['loci']} loci farmacogenômicos interpretáveis; "
        f"diplótipos estabelecidos {totals['genes_with_diplotype']}, "
        f"fenótipos emitidos {totals['genes_with_phenotype']}; "
        f"cartão de anestesia {card['status']}{gap}."
    )


def build_payload(
    matrix_path: Path,
    passport_path: Path | None,
    policy_evaluation: Path | None = None,
    post_deployment_witness: Path | None = None,
    consent: Path | None = None,
) -> dict:
    matrix = Artifact.from_path("completeness-matrix", matrix_path)
    passport = Artifact.from_path("pgx-passport", passport_path) if passport_path else None

    case_id = matrix.payload.get("case_id") or UNAVAILABLE
    compiler = PayloadCompiler(
        case_id=str(case_id),
        report_id=REPORT_ID,
        policy_evaluation=policy_evaluation,
        post_deployment_witness=post_deployment_witness,
        consent=consent,
    )
    compiler.register(matrix)
    if passport:
        compiler.register(passport)
        if passport.payload.get("input_sha256") != matrix.payload.get("input_sha256"):
            raise ValueError("passport and completeness matrix describe different inputs")

    verified = matrix.payload.get("operational_status") == "VERIFICADO"
    status = "VERIFICADO" if verified else UNAVAILABLE
    passport_payload = (
        passport.payload
        if passport and passport.payload.get("operational_status") == "VERIFICADO"
        else None
    )

    compiler.derive(
        "summary", artifact="completeness-matrix", locator="totals", status=status,
        basis="contagem por classe de cobertura", kind="computed", transform=_headline,
    )
    compiler.section_derived(
        "Situação atual", artifact="completeness-matrix", locator="totals", status=status,
        basis="cobertura do registro de alvos", kind="computed",
        transform=lambda t: "; ".join(f"{name}: {t['class_' + name]}" for name in CLASSES)
        + f" (de {t['targets']} alvos).",
    )

    # Clinical priority and next action are decisions, not measurements. This pipeline
    # produces neither, and a one-pager is the worst place to imply otherwise.
    compiler.section_unavailable(
        "Prioridade e confirmação",
        basis="priorização clínica e conduta de confirmação não são derivadas por este pipeline",
    )

    compiler.section_derived(
        "Achados essenciais", artifact="completeness-matrix", locator="entries", status=status,
        basis="loci interpretáveis que carregam o alelo avaliado", kind="computed",
        transform=lambda _e: _observed_findings(matrix.payload),
    )
    compiler.section_derived(
        "Alertas e pontos cegos", artifact="completeness-matrix",
        locator="structural_blind_spots", status=status,
        basis="classes de variação fora do alcance da plataforma", kind="computed",
        transform=lambda spots: "Não resolvido por array em nenhum locus: "
        + ", ".join(str(s["class"]) for s in spots)
        + ". "
        + _pgx_line(passport_payload),
    )
    compiler.section_derived(
        "Uso seguro e vínculos", artifact="completeness-matrix",
        locator="negative_statement_policy", status=status,
        basis="política de afirmação negativa herdada da matriz",
        kind="computed",
        transform=lambda policy: f"{policy} Este resumo não substitui os relatórios completos "
        f"05, 06 e 09, dos quais é derivado.",
    )

    compiler.state(
        "sources",
        [f"completeness-matrix:{matrix.sha256}"]
        + ([f"pgx-passport:{passport.sha256}"] if passport else []),
        kind="case_control", basis="relatórios dos quais esta página é derivada",
        status="VERIFICADO",
    )
    compiler.derive(
        "limitations", artifact="completeness-matrix", locator="limitations", status=status,
        basis="limitações declaradas pela matriz", kind="computed",
        transform=lambda items: " ".join(str(x) for x in items),
    )

    return compiler.compile(
        execution_manifest={
            "status": matrix.payload.get("operational_status", UNAVAILABLE),
            "COMPLETENESS_MATRIX_SHA256": matrix.sha256,
            **({"PGX_PASSPORT_SHA256": passport.sha256} if passport else {}),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--passport")
    parser.add_argument("--policy-evaluation")
    parser.add_argument("--post-deployment-witness")
    parser.add_argument("--consent")
    parser.add_argument("--payload-out", required=True)
    args = parser.parse_args()

    payload = build_payload(
        Path(args.matrix),
        Path(args.passport) if args.passport else None,
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
    print(json.dumps({"payload": str(out), "operational_status": payload["operational_status"]},
                     ensure_ascii=False, indent=2))
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
