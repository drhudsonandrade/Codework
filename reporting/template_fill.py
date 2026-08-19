"""Fill the v3.0 template fields from a compiled, anchored payload.

The sealed templates carry 26–200 fillable placeholders each, named by semantic token:
`[[NOME_OU_ID_PSEUDONIMIZADO]]`, `[[LABORATORIO_E_PLATAFORMA]]`, `[[N_CEGOS]]`. Rendering a
report through them therefore needs a mapping from what the pipeline measured to what the
document asks for.

Most of those tokens ask for things this pipeline does not hold — a patient name, a birth
date, a requesting clinician, a collection date, a signature. **Those are filled with
NÃO DISPONÍVEL, never guessed**, which is why a rendered report shows a great many of them:
a SNP-array pipeline produced QC, coverage and pharmacogenomic observations, not a clinical
dossier. A template that came out looking complete would be the lie.

Two properties make this safe to automate:

* a resolver may only read the compiled payload, whose every value is already anchored to a
  pipeline artifact and re-checked by PROVENANCE_GATE, so nothing enters the PDF that did
  not enter the payload;
* the fill result reports `derived` and `unavailable` counts, and
  `scripts/render_report_pdfs.py` refuses to publish when nothing was derived — the same
  refusal `render_pdf_from_template` now makes on zero replacements.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

import normative

UNAVAILABLE = "NÃO DISPONÍVEL"

#: A resolver receives the compiled payload and returns a string, or None to leave the
#: field unavailable. Returning None is a legitimate, common outcome.
Resolver = Callable[[dict[str, Any]], Any]


def _section(payload: dict[str, Any], title: str) -> Any:
    sections = payload.get("sections")
    return sections.get(title) if isinstance(sections, dict) else None


def _manifest(payload: dict[str, Any], key: str) -> Any:
    manifest = payload.get("execution_manifest")
    return manifest.get(key) if isinstance(manifest, dict) else None


def _count_findings(payload: dict[str, Any], predicate: Callable[[dict], bool]) -> Any:
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return None
    return str(sum(1 for f in findings if isinstance(f, dict) and predicate(f)))


#: Tokens every report shares. Values come only from the compiled payload.
COMMON_RESOLVERS: dict[str, Resolver] = {
    "NOME_OU_ID_PSEUDONIMIZADO": lambda p: p.get("case_id"),
    "IDENTIFICACAO": lambda p: p.get("case_id"),
    "AMOSTRA": lambda p: p.get("case_id"),
    "TIPO_AMOSTRA_E_IDENTIFICADOR": lambda p: (
        f"Genotipagem por microarranjo de SNP; identificador do caso {p.get('case_id')}"
        if p.get("case_id")
        else None
    ),
    "DATA_EMISSAO": lambda _p: datetime.now(timezone.utc).strftime("%d/%m/%Y"),
    "DATA": lambda _p: datetime.now(timezone.utc).strftime("%d/%m/%Y"),
    "VERSAO_RELATORIO": lambda _p: f"v3.0 / ruleset {normative.VERSION}",
    "VERSAO": lambda _p: f"v3.0 / ruleset {normative.VERSION}",
    "MANIFESTO_DE_ENTRADAS": lambda p: p.get("sources"),
    "RELATORIO_QC": lambda p: _manifest(p, "ARRAY_QC_SHA256"),
    "LOGS_WORKFLOW_VERSOES": lambda p: json.dumps(
        p.get("execution_manifest", {}), ensure_ascii=False
    ) if isinstance(p.get("execution_manifest"), dict) else None,
    "CONCLUSAO_LIMITADA": lambda p: p.get("summary"),
    "STATUS": lambda p: p.get("operational_status"),
    "METODO": lambda _p: (
        "Genotipagem por microarranjo de SNP, harmonizada entre duas plataformas de consumo"
    ),
    "CALLER_ENSAIO": lambda _p: (
        "Chamada de genótipo pelo fornecedor do array; este pipeline não realiza chamada de "
        "variantes a partir de leituras"
    ),
}

#: Report-specific tokens, resolved from the sections that report actually compiled.
REPORT_RESOLVERS: dict[str, dict[str, Resolver]] = {
    "05": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Plataforma e desempenho analítico"),
        "PERCENTUAL": lambda p: _section(p, "Resumo leigo do exame"),
        "GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS": lambda p: _section(
            p, "Genome Completeness Matrix"
        ),
        "REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS": lambda p: _section(
            p, "Limitações e fontes"
        ),
        "MANIFESTO_DE_ENTRADAS": lambda p: _section(p, "Contrato de entrada e cadeia de custódia"),
        "REGISTRO_DE_CONSULTAS": lambda p: _section(p, "Pipeline reproduzível"),
    },
    "06": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Identificação e controle"),
        "GENE": lambda p: _section(p, "Camada técnica por gene"),
        "ESCOPO": lambda p: _section(p, "Resumo farmacogenômico"),
        # Diplotype and phenotype are the two fields a PGx report is read for, and the two
        # this pipeline most often cannot supply. They resolve from the passport's own
        # verdicts, so the page shows NÃO DISPONÍVEL where nothing was established.
        "DIPLOTIPO": lambda p: _section(p, "Camada técnica por gene"),
        "FENOTIPO_PADRONIZADO": lambda p: _section(p, "Resumo farmacogenômico"),
        "STAR_ALLELES": lambda p: _section(p, "Camada técnica por gene"),
        "TERMOS_CPIC": lambda p: _section(p, "Plano de atualização"),
        "FONTE_VERSAO": lambda p: _section(p, "Plano de atualização"),
        "VERSAO_DATA": lambda p: _section(p, "Plano de atualização"),
        "GUIDELINE_ALELO_CARTAO": lambda p: _section(p, "Cartão genômico de anestesia"),
        "FENOCONVERSAO": lambda p: _section(p, "Medicações e fenoconversão"),
        "LIMITACAO": lambda p: _section(p, "Limitações e fontes"),
        "REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS": lambda p: _section(
            p, "Limitações e fontes"
        ),
        "ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO": lambda p: _section(
            p, "Cartão genômico de anestesia"
        ),
        "DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE": lambda p: _section(
            p, "Plano de atualização"
        ),
        "PROFISSIONAIS_E_DECISOES_FORA_DO_ESCOPO": lambda p: _section(
            p, "Medicações e fenoconversão"
        ),
    },
    "09": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Painel de completude"),
        "N_CLASSES": lambda p: _section(p, "Matriz por classe"),
        "N_CEGOS": lambda p: _count_findings(p, lambda f: True),
        "REGIOES": lambda p: _section(p, "Matriz por gene/região"),
        "GENE_REGIAO": lambda p: _section(p, "Matriz por gene/região"),
        "NEGATIVO": lambda p: _section(p, "Evidência negativa"),
        "CONCLUSAO_LIMITADA": lambda p: _section(p, "Evidência negativa"),
        "LACUNA": lambda p: _section(p, "Plano para fechar lacunas"),
        "ENSAIO_COMPLEMENTAR": lambda p: _section(p, "Plano para fechar lacunas"),
        "GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS": lambda p: _section(p, "Matriz por classe"),
        "REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS": lambda p: _section(
            p, "Limitações e fontes"
        ),
    },
}


def _resolve(report_id: str, token: str, payload: dict[str, Any]) -> Any:
    for table in (REPORT_RESOLVERS.get(report_id, {}), COMMON_RESOLVERS):
        resolver = table.get(token)
        if resolver is None:
            continue
        try:
            value = resolver(payload)
        except (KeyError, TypeError, ValueError):
            return None
        if value not in (None, ""):
            return value
    return None


def build_template_fields(
    report_id: str, payload: dict[str, Any], detailed_manifest: dict[str, Any]
) -> dict[str, Any]:
    """Map every fillable placeholder of `report_id` to a value or to NÃO DISPONÍVEL."""
    report = (detailed_manifest.get("reports") or {}).get(report_id)
    if not isinstance(report, dict):
        raise KeyError(f"coordinate manifest has no report {report_id!r}")

    fields: dict[str, Any] = {}
    derived: list[str] = []
    unavailable: list[str] = []
    for item in report.get("fields", []):
        if item.get("guidance_only"):
            continue
        field_id = item["field_id"]
        token = str(item.get("token", "")).strip("[] ").strip()
        value = _resolve(report_id, token, payload)
        if value is None:
            fields[field_id] = UNAVAILABLE
            unavailable.append(token)
        else:
            fields[field_id] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            derived.append(token)

    return {
        "fields": fields,
        "derived_count": len(derived),
        "unavailable_count": len(unavailable),
        "total": len(fields),
        "derived_tokens": sorted(set(derived)),
        # Reported, not hidden: a reader must be able to see how much of the document the
        # pipeline could actually answer.
        "unavailable_tokens": sorted(set(unavailable)),
    }
