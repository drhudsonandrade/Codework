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
from typing import Any, Callable

import normative
from reporting.assay import UnknownAssayError, assay_for_schema

UNAVAILABLE = "NÃO DISPONÍVEL"

#: A resolver receives the compiled payload and returns a string, or None to leave the
#: field unavailable. Returning None is a legitimate, common outcome.
Resolver = Callable[[dict[str, Any]], Any]


def _section(payload: dict[str, Any], title: str) -> Any:
    sections = payload.get("sections")
    return sections.get(title) if isinstance(sections, dict) else None


def _manifest(payload: dict[str, Any], key: str) -> Any:
    manifest = payload.get("execution_manifest")
    if isinstance(manifest, dict):
        return manifest.get(key)
    if isinstance(manifest, list):
        evidence_id = key.lower().removesuffix("_sha256").replace("_", "-")
        for step in manifest:
            refs = step.get("evidence_refs") if isinstance(step, dict) else None
            if isinstance(refs, list) and evidence_id in refs:
                return evidence_id
    return None


def _count_findings(payload: dict[str, Any], predicate: Callable[[dict], bool]) -> Any:
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return None
    return str(sum(1 for f in findings if isinstance(f, dict) and predicate(f)))

def _assay(payload: dict[str, Any]):
    input_block = payload.get("input")
    schema = input_block.get("schema") if isinstance(input_block, dict) else None
    return assay_for_schema(schema)


def _qc_reference(payload: dict[str, Any]) -> Any:
    assay = _assay(payload)
    direct = _manifest(payload, f"{assay.evidence_prefix.upper()}_QC_SHA256")
    if direct:
        return direct
    manifest = payload.get("execution_manifest")
    if isinstance(manifest, dict):
        pgx = {
            key: manifest[key]
            for key in ("PGX_PASSPORT_SHA256", "COMPLETENESS_MATRIX_SHA256")
            if manifest.get(key)
        }
        if pgx:
            return pgx
    return None


def _count_findings_with_field(
    payload: dict[str, Any],
    field: str,
    predicate: Callable[[dict], bool],
) -> Any:
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return None
    typed = [finding for finding in findings if isinstance(finding, dict)]
    if len(typed) != len(findings) or any(field not in finding for finding in typed):
        return None
    return str(sum(1 for finding in typed if predicate(finding)))



#: Tokens every report shares. Values come only from the compiled payload.
COMMON_RESOLVERS: dict[str, Resolver] = {
    "NOME_OU_ID_PSEUDONIMIZADO": lambda p: p.get("case_id"),
    "IDENTIFICACAO": lambda p: p.get("case_id"),
    "AMOSTRA": lambda p: p.get("case_id"),
    "TIPO_AMOSTRA_E_IDENTIFICADOR": lambda p: (
        f"{_assay(p).name}; identificador do caso {p.get('case_id')}"
        if p.get("case_id")
        else None
    ),
    # No clock here, deliberately. This table's contract is that values come only from the
    # compiled payload, and a formal issue date is an administrative fact. `REPORT_RESOLVERS`
    # is consulted first and carries the dossier's real `issue_date`, so `datetime.now()`
    # only ever spoke in the one case that matters: a case whose dossier records no issue
    # date. There the document printed today's date as its formal date of emission — a date
    # nobody registered, anchored to nothing, and indistinguishable in the rendered PDF from
    # one that had been. Absent the dossier field the token prints NÃO DISPONÍVEL, like every
    # other value this renderer was never given.
    "DATA_EMISSAO": lambda _p: None,
    "DATA": lambda _p: None,
    "VERSAO_RELATORIO": lambda _p: f"v3.0 / ruleset {normative.VERSION}",
    "VERSAO": lambda _p: f"v3.0 / ruleset {normative.VERSION}",
    "MANIFESTO_DE_ENTRADAS": lambda p: p.get("sources"),
    "RELATORIO_QC": _qc_reference,
    "LOGS_WORKFLOW_VERSOES": lambda p: json.dumps(
        p.get("execution_manifest", {}), ensure_ascii=False
    ) if isinstance(p.get("execution_manifest"), dict) else None,
    "CONCLUSAO_LIMITADA": lambda p: p.get("summary"),
    "STATUS": lambda p: p.get("operational_status"),
    "METODO": lambda p: _assay(p).name,
    "CALLER_ENSAIO": lambda p: _assay(p).depth_note,
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
    "10": {
        # A one-page summary is where "nothing found" quietly replaces "nothing was tested
        # for", so the classes are kept apart on the page rather than collapsed.
        "RESUMO_EM_ATE_60_PALAVRAS_SEM_JARGAO": lambda p: p.get("summary"),
        "STATUS": lambda p: _section(p, "Situação atual"),
        "ACHADO": lambda p: _section(p, "Achados essenciais"),
        "ACHADO_OU_NENHUM": lambda p: _section(p, "Achados essenciais"),
        "ALERTA_OU_LACUNA": lambda p: _section(p, "Alertas e pontos cegos"),
        "SIGNIFICADO": lambda p: _section(p, "Uso seguro e vínculos"),
        "SIGNIFICADO_CURTO": lambda p: _section(p, "Uso seguro e vínculos"),
        "IDS_E_VERSOES": lambda p: p.get("sources"),
        "TEMA": lambda p: _section(p, "Situação atual"),
        # Priority, action and confirmation are clinical decisions this pipeline does not
        # make. Leaving them unmapped is what makes the page print NÃO DISPONÍVEL.
    },
    # Report 01: clinical. Findings, negatives and blind spots are separate sections on
    # purpose, so the tokens that ask about each resolve to their own one — mapping them all
    # to the findings section would print a finding where the template asks for a negative.
    "01": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Identificação e controle"),
        "ACHADO_OU_NENHUM": lambda p: _section(p, "Achados clínicos e diagnósticos"),
        "GENE_VARIANTE_CONDICAO": lambda p: _section(p, "Achados clínicos e diagnósticos"),
        "INTERPRETACAO_CURTA": lambda p: _section(p, "Resumo clínico executivo"),
        "CLINICO_OU_PREDISPOSICAO": lambda p: _section(p, "Predisposições, risco e achados negativos"),
        "RESULTADO_NEGATIVO": lambda p: _section(p, "Predisposições, risco e achados negativos"),
        "GENES_E_CLASSES": lambda p: _section(p, "Predisposições, risco e achados negativos"),
        "ESCOPO_EXATO": lambda p: _section(p, "Predisposições, risco e achados negativos"),
        "GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS": lambda p: _section(
            p, "Predisposições, risco e achados negativos"
        ),
        "CONFIRMACAO": lambda p: _section(p, "Confirmação, pontos cegos e reanálise"),
        "LIMITACOES_RESIDUAIS": lambda p: _section(p, "Confirmação, pontos cegos e reanálise"),
        "ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO": lambda p: _section(
            p, "Confirmação, pontos cegos e reanálise"
        ),
        "REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS": lambda p: _section(
            p, "Confirmação, pontos cegos e reanálise"
        ),
        "CURADORIA_GENE_DOENCA_E_VARIANTE": lambda p: _section(p, "Fontes e Execution Manifest"),
        "NIVEL_E_FONTES": lambda p: _section(p, "Fontes e Execution Manifest"),
        "REGISTRO_DE_CONSULTAS": lambda p: _section(p, "Fontes e Execution Manifest"),
        "STATUS_OPERACIONAL": lambda p: p.get("operational_status"),
        "N_ACHADOS_P1_P2": lambda p: _count_findings_with_field(
            p,
            "priority",
            lambda f: str(f.get("priority")).strip().upper()
            in {"1", "2", "P1", "P2", "PRIORIDADE 1", "PRIORIDADE 2"},
        ),
        "N_CONFIRMACOES": lambda p: _count_findings_with_field(
            p, "confirmation_required", lambda f: f.get("confirmation_required") is True
        ),
    },
    # Report 02: ancestry. It measures feasibility rather than estimating origins, so the
    # tokens asking for an estimate deliberately have no resolver and print NÃO DISPONÍVEL.
    "02": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Qualidade, painel e sensibilidade"),
        "METODO_VERSAO_QUALIDADE": lambda p: _section(p, "Qualidade, painel e sensibilidade"),
        "METRICAS_E_LIMIARES": lambda p: _section(p, "Qualidade, painel e sensibilidade"),
        "N_SNP_POS_QC": lambda p: _section(p, "Qualidade, painel e sensibilidade"),
        "PLATAFORMA": lambda p: _section(p, "Qualidade, painel e sensibilidade"),
        "HAPLOGRUPO_HAPLOTIPO_IBD_AFINIDADE": lambda p: _section(p, "Linhagens materna e paterna"),
        "SUBCLADO_MT": lambda p: _section(p, "Linhagens materna e paterna"),
        "SUBCLADO_Y_OU_NA": lambda p: _section(p, "Linhagens materna e paterna"),
        "ARVORE_VERSAO": lambda p: _section(p, "Linhagens materna e paterna"),
        "NOME_VERSAO_N_AMOSTRAS": lambda p: _section(p, "Limitações e fontes"),
        "MODELO_VERSAO_REFERENCIA": lambda p: _section(p, "Limitações e fontes"),
        "LACUNAS": lambda p: _section(p, "Limitações e fontes"),
        "REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS": lambda p: _section(
            p, "Limitações e fontes"
        ),
        "REGISTRO_DE_CONSULTAS": lambda p: p.get("sources"),
    },
    # Report 03: reproductive. Couple summary and combined risk have no resolver because
    # only one person was analysed; leaving them unmapped is what prints the refusal.
    "03": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Identificação e controle"),
        "ESCOPO_A": lambda p: _section(p, "Escopo individual e comparabilidade"),
        "COBERTURA_A": lambda p: _section(p, "Escopo individual e comparabilidade"),
        "RESIDUAL": lambda p: _section(p, "Escopo individual e comparabilidade"),
        "FAIXA_RESIDUAL": lambda p: _section(p, "Escopo individual e comparabilidade"),
        "CONDICAO_GENE": lambda p: _section(p, "Achados de portador por pessoa"),
        "GENOTIPO": lambda p: _section(p, "Achados de portador por pessoa"),
        "ZIGOSIDADE": lambda p: _section(p, "Achados de portador por pessoa"),
        "AR_XL_AD_MT_OUTRO": lambda p: _section(p, "Achados de portador por pessoa"),
        "N_PORTADOR_A": lambda p: _section(p, "Achados de portador por pessoa"),
        "ACONSELHAMENTO": lambda p: _section(p, "Opções, confirmação e aconselhamento"),
        "CONFIRMACAO_VARIANTES": lambda p: _section(p, "Opções, confirmação e aconselhamento"),
        "ENCAMINHAMENTO": lambda p: _section(p, "Opções, confirmação e aconselhamento"),
        "LIMITES": lambda p: _section(p, "Limitações e fontes"),
        "LACUNAS": lambda p: _section(p, "Limitações e fontes"),
        "REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS": lambda p: _section(
            p, "Limitações e fontes"
        ),
        "REGISTRO_DE_CONSULTAS": lambda p: p.get("sources"),
    },
    # Reports 04, 07 and 08 share a producer, so they share the shape of their resolvers:
    # the association matrix, the effect direction, and the limitations that carry the
    # evidence tier. Recommendation tokens are unmapped on purpose.
    "04": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Identificação e controle"),
        "GENETICA_FENOTIPO": lambda p: _section(p, "Matriz gene–nutriente–fenótipo"),
        "GENE_RS_HGVS": lambda p: _section(p, "Matriz gene–nutriente–fenótipo"),
        "EVIDENCIA_E_EFEITO": lambda p: _section(p, "Matriz gene–nutriente–fenótipo"),
        "BETA_OR_RR_IC": lambda p: _section(p, "Matriz gene–nutriente–fenótipo"),
        "COORTE_ANCESTRALIDADE": lambda p: _section(p, "Matriz gene–nutriente–fenótipo"),
        "FATO_ASSOCIACAO_HIPOTESE": lambda p: _section(p, "Módulos de interpretação"),
        "NIVEL_EVIDENCIA": lambda p: _section(p, "Módulos de interpretação"),
        "RISCO_E_RESPOSTA": lambda p: _section(p, "Módulos de interpretação"),
        "GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS": lambda p: _section(p, "Limitações e fontes"),
        "REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS": lambda p: _section(
            p, "Limitações e fontes"
        ),
        "REGISTRO_DE_CONSULTAS": lambda p: p.get("sources"),
    },
    "07": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Identificação e controle"),
        "GENE_VARIANTE": lambda p: _section(p, "Matriz de predisposição"),
        "RISCO_IC": lambda p: _section(p, "Matriz de predisposição"),
        "EFEITO_IC": lambda p: _section(p, "Matriz de predisposição"),
        "COORTES": lambda p: _section(p, "Matriz de predisposição"),
        "MONOGENICO_PRS_ASSOCIACAO": lambda p: _section(p, "Matriz de predisposição"),
        "PROTETOR": lambda p: _section(p, "Variantes e fatores protetores"),
        "EFEITO": lambda p: _section(p, "Variantes e fatores protetores"),
        "N_PROTETORES": lambda p: _section(p, "Variantes e fatores protetores"),
        "GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS": lambda p: _section(p, "Limitações e fontes"),
        "REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS": lambda p: _section(
            p, "Limitações e fontes"
        ),
        "REGISTRO_DE_CONSULTAS": lambda p: p.get("sources"),
    },
    "08": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Identificação e controle"),
        "TRACO": lambda p: _section(p, "Cartões de traços"),
        "ASSOCIACAO": lambda p: _section(p, "Cartões de traços"),
        "EFEITO": lambda p: _section(p, "Cartões de traços"),
        "EFEITO_ESCALA": lambda p: _section(p, "Cartões de traços"),
        "N_ASSOCIACOES": lambda p: _section(p, "Cartões de traços"),
        "FISIOLOGIA": lambda p: _section(p, "Sentidos, fisiologia e preferências"),
        "PERCEPCAO": lambda p: _section(p, "Sentidos, fisiologia e preferências"),
        "REPLICADO": lambda p: _section(p, "Evidência e reprodutibilidade"),
        "MODELO_VALIDADO": lambda p: _section(p, "Evidência e reprodutibilidade"),
        "GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS": lambda p: _section(p, "Limitações e fontes"),
        "REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS": lambda p: _section(
            p, "Limitações e fontes"
        ),
        "REGISTRO_DE_CONSULTAS": lambda p: p.get("sources"),
    },
    # Report 11: the editorial guide. It describes the system, so its resolvers read the
    # analysis of the system rather than any measurement of a person.
    "11": {
        "PROCESSO": lambda p: _section(p, "Matriz de seleção"),
        "ARTEFATO": lambda p: _section(p, "Matriz de seleção"),
        "DETALHE": lambda p: _section(p, "Dicionário de campos"),
        "ESCALA_DEFINIDA_POR_MODULO": lambda p: _section(p, "Taxonomias obrigatórias"),
        "STATUS_OPERACIONAL": lambda p: p.get("operational_status"),
        "CONTROLE": lambda p: _section(p, "QA antes da publicação"),
        "SEMVER": lambda p: _section(p, "Versionamento e manutenção"),
        "MUDANCA": lambda p: _section(p, "Versionamento e manutenção"),
        "FONTE_VERSAO_DATA": lambda p: p.get("sources"),
        "REGISTRO_DE_CONSULTAS": lambda p: p.get("sources"),
    },
    "09": {
        "LABORATORIO_E_PLATAFORMA": lambda p: _section(p, "Painel de completude"),
        "N_CLASSES": lambda p: _section(p, "Matriz por classe"),
        "N_CEGOS": lambda p: _count_findings_with_field(
            p, "source", lambda f: f.get("source") == "structural_blind_spots"
        ),
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


def _resolve(
    report_id: str,
    token: str,
    payload: dict[str, Any],
    failures: list[dict[str, str]] | None = None,
) -> Any:
    """Resolve one token, recording a resolver that broke rather than swallowing it.

    A resolver raising KeyError/TypeError/ValueError returned None, which is exactly what a
    genuinely absent value returns — so "this field has no data" and "the code that reads
    this field is broken" printed the same NÃO DISPONÍVEL, and the second could persist
    through any number of runs with nothing to notice it. The field still degrades to
    NÃO DISPONÍVEL, because a broken resolver must not take the document down; what changes
    is that the breakage is now reported beside the value it cost.
    """
    for table in (REPORT_RESOLVERS.get(report_id, {}), COMMON_RESOLVERS):
        resolver = table.get(token)
        if resolver is None:
            continue
        try:
            value = resolver(payload)
        except (KeyError, TypeError, ValueError, UnknownAssayError) as exc:
            if failures is not None:
                failures.append(
                    {"token": token, "error": f"{type(exc).__name__}: {exc}"[:200]}
                )
            return None
        # A resolver that reaches a section whose content is itself NÃO DISPONÍVEL has not
        # derived anything. Counting it as derived inflates `derived_count`, and
        # `render_report_pdfs.py` refuses to publish only when that count is zero — so a
        # report whose every section was unavailable would have published as if it carried
        # measurements.
        if value not in (None, "", UNAVAILABLE):
            return value
    return None


def build_template_fields(
    report_id: str,
    payload: dict[str, Any],
    detailed_manifest: dict[str, Any],
    dossier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map every fillable placeholder of `report_id` to a value or to NÃO DISPONÍVEL.

    `dossier` carries the administrative record — identification, consent, custody,
    signatures — which no resolver can derive because it is not in the data. It takes
    precedence over the generic resolvers, which only ever supplied a fallback for those
    tokens (the case id in place of a name, today's date in place of an issue date).
    """
    from reporting.case_dossier import dossier_values

    supplied = dossier_values(dossier)
    report = (detailed_manifest.get("reports") or {}).get(report_id)
    if not isinstance(report, dict):
        raise KeyError(f"coordinate manifest has no report {report_id!r}")

    fields: dict[str, Any] = {}
    derived: list[str] = []
    unavailable: list[str] = []
    failures: list[dict[str, str]] = []
    for item in report.get("fields", []):
        if item.get("guidance_only"):
            continue
        field_id = item["field_id"]
        token = str(item.get("token", "")).strip("[] ").strip()
        value = supplied.get(token)
        if value is None:
            value = _resolve(report_id, token, payload, failures)
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
        # A resolver that raised, named. Empty on a healthy run, so a missing key can never
        # read as a check that did not happen.
        "resolver_failures": [
            {"token": token, "error": error}
            for token, error in sorted({(f["token"], f["error"]) for f in failures})
        ],
        "from_dossier": sorted(set(supplied) & set(derived)),
        "dossier_supplied": bool(supplied),
    }
