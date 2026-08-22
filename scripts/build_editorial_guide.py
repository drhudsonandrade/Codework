#!/usr/bin/env python3
"""Generate the editorial guide for the report suite from the catalogue and the templates.

The guide was described as not deriving from data. That is right about *patient* data and
wrong about the system: what an editor needs to know is which sections each report has, which
placeholders each template carries, which of those a resolver can answer from the pipeline,
which only the case dossier can answer, and which nothing can answer at all. All four facts
live in files under version control, so writing the guide by hand would mean maintaining a
second copy of them that goes stale the first time a resolver changes.

The number that matters is the last one. A template with 200 fillable fields of which 55 can
be derived is not a document that is 27% finished — it is a document that will print
NÃO DISPONÍVEL 145 times unless an operator fills a dossier, and an editor who does not know
that in advance will read the output as a failure. This guide states it per report, before
anything is rendered.

Nothing here reads a genotype. It is safe to regenerate and commit.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.catalog import load_catalog, section_titles
from reporting.case_dossier import SECTIONS as DOSSIER_SECTIONS
from reporting.case_dossier import dossier_values
from reporting.template_fill import COMMON_RESOLVERS, REPORT_RESOLVERS

DEFAULT_OUTPUT = ROOT / "docs/EDITORIAL_GUIDE.md"
REPORT_ID = "11"

#: Which script produces each report's payload. A report with no producer prints from a
#: fixture and says so on its face; listing that here is the point of the column.
PRODUCERS: dict[str, str] = {
    "01": "scripts/build_clinical_report.py",
    "02": "scripts/build_ancestry_report.py",
    "03": "scripts/build_reproductive_report.py",
    "04": "scripts/build_association_report.py --report 04",
    "05": "scripts/build_technical_report.py",
    "06": "scripts/build_pharmacogenomic_report.py",
    "07": "scripts/build_association_report.py --report 07",
    "08": "scripts/build_association_report.py --report 08",
    "09": "scripts/build_completeness_report.py",
    "10": "scripts/build_one_page_summary.py",
    "11": "scripts/build_editorial_guide.py",
}


def _dossier_tokens() -> set[str]:
    """Tokens the dossier can answer, obtained by asking it rather than by listing them.

    A hand-kept list would drift from `dossier_values` the moment a field is added. Feeding
    it a fully-populated dossier and reading back which tokens came out keeps the two in
    step by construction.
    """
    filled = {
        section: {field: [f"{field}-valor"] if field.startswith("authorised") or field.endswith("preferences") else f"{field}-valor"
                  for field in fields}
        for section, fields in DOSSIER_SECTIONS.items()
    }
    for section, fields in DOSSIER_SECTIONS.items():
        for field in fields:
            if field.endswith("_date") or field == "date_of_birth":
                filled[section][field] = "01/01/2000"
    return set(dossier_values(filled))


def analyse(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    dossier_tokens = _dossier_tokens()
    rows: list[dict[str, Any]] = []
    for report_id in sorted(load_catalog()):
        entry = load_catalog()[report_id]
        report_manifest = (manifest.get("reports") or {}).get(report_id) or {}
        fields = [f for f in report_manifest.get("fields", []) if not f.get("guidance_only")]
        tokens = [str(f.get("token", "")).strip("[] ").strip() for f in fields]
        resolvers = set(REPORT_RESOLVERS.get(report_id, {})) | set(COMMON_RESOLVERS)
        by_resolver = sorted({t for t in tokens if t in resolvers})
        by_dossier = sorted({t for t in tokens if t in dossier_tokens and t not in resolvers})
        unanswerable = sorted({t for t in tokens if t not in resolvers and t not in dossier_tokens})
        rows.append(
            {
                "report_id": report_id,
                "code": entry.get("code"),
                "title": entry.get("title"),
                "audience": entry.get("audience"),
                "sections": list(section_titles(report_id)),
                "producer": PRODUCERS.get(report_id),
                "fillable_fields": len(fields),
                "distinct_tokens": len(set(tokens)),
                "answered_by_resolver": by_resolver,
                "answered_by_dossier": by_dossier,
                "answered_by_nothing": unanswerable,
            }
        )
    return rows


def render(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    lines = [
        "# Guia editorial da suíte de relatórios",
        "",
        f"Gerado por `scripts/build_editorial_guide.py` em {generated}. **Não editar à mão**: ",
        "o conteúdo é derivado de `reporting/catalog.json`, do manifesto de coordenadas dos ",
        "templates selados, das tabelas de resolvers de `reporting/template_fill.py` e do ",
        "contrato de `reporting/case_dossier.py`. Editar aqui cria uma segunda cópia que ",
        "envelhece na primeira mudança de resolver.",
        "",
        "Nenhum dado de genótipo é lido para gerar este arquivo.",
        "",
        "## Como ler a contagem de campos",
        "",
        "Um template com 200 campos preenchíveis dos quais 55 são deriváveis **não** é um ",
        "documento 27% pronto. É um documento que imprimirá NÃO DISPONÍVEL 145 vezes se o ",
        "dossiê do caso não for preenchido. Cerca de 60% de todo template v3.0 é administrativo ",
        "— quem é a pessoa, quem pediu, sob qual consentimento, assinado por quem — e nada disso ",
        "sai de um arquivo de genótipos. As três colunas abaixo separam:",
        "",
        "* **resolver** — o pipeline responde a partir de artefato medido;",
        "* **dossiê** — só o operador responde, via `--dossier`;",
        "* **ninguém** — nem o pipeline nem o dossiê respondem; imprime NÃO DISPONÍVEL sempre.",
        "",
        "## Panorama",
        "",
        "| # | Código | Relatório | Campos | Resolver | Dossiê | Ninguém | Produtor de dados |",
        "|---|--------|-----------|-------:|---------:|-------:|--------:|-------------------|",
    ]
    for row in rows:
        producer = f"`{row['producer']}`" if row["producer"] else "**nenhum**"
        lines.append(
            f"| {row['report_id']} | {row['code']} | {row['title']} | {row['fillable_fields']} | "
            f"{len(row['answered_by_resolver'])} | {len(row['answered_by_dossier'])} | "
            f"{len(row['answered_by_nothing'])} | {producer} |"
        )

    totals = {
        "fields": sum(r["fillable_fields"] for r in rows),
        "resolver": sum(len(r["answered_by_resolver"]) for r in rows),
        "dossier": sum(len(r["answered_by_dossier"]) for r in rows),
        "nothing": sum(len(r["answered_by_nothing"]) for r in rows),
    }
    lines += [
        "",
        f"Total: {totals['fields']} campos preenchíveis na suíte; "
        f"{totals['resolver']} tokens distintos por relatório têm resolver, "
        f"{totals['dossier']} vêm do dossiê, {totals['nothing']} não têm origem declarada.",
        "",
        "## Por relatório",
        "",
    ]
    for row in rows:
        lines += [
            f"### {row['report_id']} — {row['title']} ({row['code']})",
            "",
            f"*Público:* {row['audience']}",
            "",
            "*Produtor de dados:* "
            + (
                f"`{row['producer']}`"
                if row["producer"]
                else "**nenhum** — imprime a partir de fixture e declara isso na face do documento"
            ),
            "",
            "*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui "
            "renderiza seção vazia):*",
            "",
        ]
        lines += [f"{i}. {title}" for i, title in enumerate(row["sections"], 1)]
        lines += [
            "",
            f"*Tokens com resolver ({len(row['answered_by_resolver'])}):* "
            + (", ".join(f"`{t}`" for t in row["answered_by_resolver"]) or "nenhum"),
            "",
            f"*Tokens que só o dossiê responde ({len(row['answered_by_dossier'])}):* "
            + (", ".join(f"`{t}`" for t in row["answered_by_dossier"]) or "nenhum"),
            "",
            f"*Tokens sem origem declarada ({len(row['answered_by_nothing'])}):* "
            + (", ".join(f"`{t}`" for t in row["answered_by_nothing"][:24]) or "nenhum")
            + (f" (+{len(row['answered_by_nothing']) - 24})" if len(row["answered_by_nothing"]) > 24 else ""),
            "",
        ]

    lines += [
        "## Regras editoriais que o código já impõe",
        "",
        "Não são recomendações; são recusas implementadas, com teste e controle negativo.",
        "",
        "1. **Nenhum valor entra num relatório sem estar ancorado a um artefato.** "
        "`reporting/provenance.py` religa cada valor ao locator de onde saiu e o "
        "`PROVENANCE_GATE` reconfere no momento de renderizar. Não existe flag de bypass.",
        "2. **Renderização estrita recusa publicar o modelo em branco.** Se nenhum campo foi "
        "substituído, `render_pdf_from_template` levanta erro em vez de emitir as páginas "
        "vazias como se fossem o relatório.",
        "3. **Placeholder é apagado, não coberto.** A redação usa `apply_redactions` do "
        "PyMuPDF: um retângulo opaco por cima deixaria o token extraível do PDF.",
        "4. **Ausência é um resultado e é ancorada como tal.** NÃO DISPONÍVEL nunca é campo "
        "vazio; carrega a razão pela qual está ausente.",
        "5. **Conflito nunca é arbitrado.** Registro cross-platform divergente, modo de herança "
        "divergente entre fontes e duplicata com genótipos diferentes viram NÃO REPORTÁVEL.",
        "6. **Consentimento é tudo-ou-nada.** Um bloco pela metade lê na página como "
        "consentimento documentado, então é rejeitado no carregamento.",
        "",
        "## Vocabulário de status (seção 261 do ruleset)",
        "",
        "| status | significa |",
        "|---|---|",
        "| EXECUTADO | a operação rodou e o resultado é dela |",
        "| VERIFICADO | foi medido e conferido contra evidência |",
        "| INFERIDO | deduzido de medição, sob suposição declarada |",
        "| PROPOSTO | desenhado, não executado |",
        "| NÃO DISPONÍVEL | não existe; a razão acompanha |",
        "",
        f"Manifesto de coordenadas: `{manifest.get('schema', 'reporting/reference_v3_manifest.json')}`, "
        f"{len(manifest.get('reports') or {})} relatórios descritos.",
        "",
    ]
    return "\n".join(lines) + "\n"


def build_payload(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    guide: str,
    policy_evaluation: Path | None = None,
    post_deployment_witness: Path | None = None,
) -> dict:
    """Report 11's payload, anchored to the guide this same run produced.

    The guide is registered as an artifact and every section reads a locator out of it, so
    the published document cannot say something the generated guide does not — the same
    binding every other report is under, applied to a document about the reports.
    """
    from reporting.provenance import Artifact, PayloadCompiler

    analysis = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports": rows,
        "totals": {
            "reports": len(rows),
            "reports_with_producer": sum(1 for r in rows if r["producer"]),
            "fillable_fields": sum(r["fillable_fields"] for r in rows),
            "tokens_with_resolver": sum(len(r["answered_by_resolver"]) for r in rows),
            "tokens_from_dossier": sum(len(r["answered_by_dossier"]) for r in rows),
            "tokens_without_origin": sum(len(r["answered_by_nothing"]) for r in rows),
        },
        "guide_markdown_bytes": len(guide.encode("utf-8")),
        "coordinate_manifest_reports": sorted((manifest.get("reports") or {})),
    }
    artifact = Artifact.from_payload("editorial-analysis", analysis)
    compiler = PayloadCompiler(
        case_id="SUITE-EDITORIAL",
        report_id=REPORT_ID,
        policy_evaluation=policy_evaluation,
        post_deployment_witness=post_deployment_witness,
    )
    compiler.register(artifact)

    titles = section_titles(REPORT_ID)
    totals = analysis["totals"]

    compiler.derive(
        "summary", artifact="editorial-analysis", locator="totals", status="VERIFICADO",
        basis="contagem de relatórios, produtores e origem dos campos", kind="computed",
        transform=lambda t: (
            f"{t['reports']} relatórios no catálogo, {t['reports_with_producer']} com produtor "
            f"de dados. {t['fillable_fields']} campos preenchíveis nos templates selados: "
            f"{t['tokens_with_resolver']} tokens têm resolver, {t['tokens_from_dossier']} só o "
            f"dossiê responde e {t['tokens_without_origin']} não têm origem declarada e "
            "imprimem NÃO DISPONÍVEL sempre."
        ),
    )
    compiler.section_derived(
        titles[0], artifact="editorial-analysis", locator="generated_at", status="VERIFICADO",
        basis="momento de geração e escopo do catálogo lido", kind="computed",
        transform=lambda ts: (
            f"Guia gerado em {ts} a partir de reporting/catalog.json, do manifesto de "
            f"coordenadas ({len(analysis['coordinate_manifest_reports'])} relatórios) e das "
            "tabelas de resolvers. Nenhum dado de genótipo é lido."
        ),
    )
    compiler.section_derived(
        titles[1], artifact="editorial-analysis", locator="reports", status="VERIFICADO",
        basis="qual produtor de dados alimenta cada relatório", kind="computed",
        transform=lambda items: "; ".join(
            f"{r['report_id']} {r['code']}: " + (r["producer"] or "sem produtor de dados")
            for r in items
        ),
    )
    compiler.section_derived(
        titles[2], artifact="editorial-analysis", locator="reports", status="VERIFICADO",
        basis="origem de cada campo preenchível, por relatório", kind="computed",
        transform=lambda items: "; ".join(
            f"{r['report_id']}: {r['fillable_fields']} campos "
            f"({len(r['answered_by_resolver'])} resolver, {len(r['answered_by_dossier'])} dossiê, "
            f"{len(r['answered_by_nothing'])} sem origem)"
            for r in items
        ),
    )
    compiler.section_stated(
        titles[3],
        "Vocabulário de status obrigatório (seção 261): EXECUTADO, VERIFICADO, INFERIDO, "
        "PROPOSTO, NÃO DISPONÍVEL. Classes de cobertura (relatório 09): OBSERVADO, "
        "NÃO DETECTADO, NO-CALL, NÃO TESTADO, NÃO REPORTÁVEL. Classes de afirmação clínica: "
        "ACHADO ACIONÁVEL, PORTADOR, GENÓTIPO DE RISCO, PREDISPOSIÇÃO, SEM INTERPRETAÇÃO "
        "ESTABELECIDA, NEGATIVO NESTE LOCUS, NÃO INTERROGADO.",
        kind="normative", basis="taxonomias impostas pelo código, não recomendadas",
        status="VERIFICADO",
    )
    compiler.section_stated(
        titles[4],
        "Toda afirmação publicada carrega: o artefato de onde saiu, o locator dentro dele, o "
        "SHA-256 do artefato, o status operacional e a base. Sem os cinco, o PROVENANCE_GATE "
        "bloqueia a renderização. Não existe flag de bypass.",
        kind="normative", basis="contrato de âncora de reporting/provenance.py", status="VERIFICADO",
    )
    compiler.section_stated(
        titles[5],
        "Ausência é resultado e é escrita como NÃO DISPONÍVEL acompanhada da razão, nunca como "
        "campo vazio. Conflito não é arbitrado: vira NÃO REPORTÁVEL com as alternativas "
        "listadas. Genótipo não é diagnóstico, e a palavra diagnóstico não é emitida por "
        "nenhum produtor de dados desta suíte.",
        kind="normative", basis="regras de linguagem que o código impõe", status="VERIFICADO",
    )
    compiler.section_stated(
        titles[6],
        "O bloco de consentimento é tudo-ou-nada: consent_id, consent_version, consent_date e "
        "authorised_purposes existem juntos ou não existem, porque um consentimento pela metade "
        "lê na página como consentimento documentado. O dossiê é vinculado ao caso analisado e "
        "recusado se o case_id divergir.",
        kind="normative", basis="validação de reporting/case_dossier.py", status="VERIFICADO",
    )
    compiler.section_stated(
        titles[7],
        "Antes de publicar: renderização estrita recusa emitir o modelo em branco se nenhum "
        "campo foi substituído; placeholders são apagados por redação real do PyMuPDF, não "
        "cobertos por retângulo; e o PDF é lido de volta para conferir que nenhum token "
        "permaneceu extraível.",
        kind="normative", basis="recusas implementadas em reporting/template_v3.py",
        status="VERIFICADO",
    )
    compiler.section_derived(
        titles[8], artifact="editorial-analysis", locator="totals.reports_with_producer",
        status="VERIFICADO", basis="cobertura de produtores como medida de manutenção",
        kind="computed",
        transform=lambda n: (
            f"{n} de {totals['reports']} relatórios têm produtor de dados versionado. "
            "Acrescentar um relatório exige acrescentar seu produtor e sua entrada em "
            "PRODUCERS; este guia é regerado a cada mudança e não deve ser editado à mão."
        ),
    )

    compiler.state(
        "sources",
        [
            f"editorial-analysis:{artifact.sha256}",
            "reporting/catalog.json",
            "reporting/template_fill.py (tabelas de resolvers)",
            "reporting/case_dossier.py (contrato do dossiê)",
            "manifesto de coordenadas dos templates v3.0 selados",
        ],
        kind="case_control", basis="arquivos versionados dos quais este guia deriva",
        status="VERIFICADO",
    )
    compiler.state(
        "limitations",
        "Este guia descreve o sistema, não uma pessoa: não contém nenhum dado de genótipo e "
        "não é um resultado clínico. As contagens de campo refletem os templates instalados no "
        "momento da geração; um pacote de templates diferente muda os números.",
        kind="normative", basis="escopo declarado do guia", status="VERIFICADO",
    )

    return compiler.compile(
        execution_manifest={
            "status": "VERIFICADO",
            "EDITORIAL_ANALYSIS_SHA256": artifact.sha256,
            "REPORTS_WITH_PRODUCER": str(totals["reports_with_producer"]),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template-dir",
        help=(
            "installed v3.0 template pack. Supplying it makes the field counts real; without "
            "it they are reported as zero and the guide says the pack was not read."
        ),
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--payload-out", help="write the report 11 payload as well")
    args = parser.parse_args()

    if args.template_dir:
        from reporting.editorial_v3 import _verified_coordinate_manifest

        manifest, _hashes = _verified_coordinate_manifest(Path(args.template_dir))
    else:
        manifest = {"reports": {}, "schema": "template pack not read"}

    rows = analyse(manifest)
    guide = render(rows, manifest)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(guide, encoding="utf-8")

    result = {
        "output": str(out),
        "reports": len(rows),
        "reports_with_producer": sum(1 for r in rows if r["producer"]),
        "fillable_fields": sum(r["fillable_fields"] for r in rows),
        "template_pack_read": bool(args.template_dir),
    }
    if args.payload_out:
        payload = build_payload(rows, manifest, guide)
        payload_out = Path(args.payload_out)
        payload_out.parent.mkdir(parents=True, exist_ok=True)
        payload_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result["payload"] = str(payload_out)
        result["operational_status"] = payload["operational_status"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
