"""Deterministic GENOMA report generation layer.

Importing the package also normalizes the low-level template renderer to the active
v3.1/v3.4 contract.  This prevents direct imports of ``reporting.template_v3`` from
falling back to legacy labels that were retained only for the renderer's historical
implementation details.
"""

from . import template_v3 as _template_v3

_ACTIVE_SYSTEM_REPLACEMENTS = {
    "MODELO REUTILIZÁVEL v3.0": "RESULTADO GENÔMICO v3.1",
    "MODELO REUTILIZÁVEL v3.1": "RESULTADO GENÔMICO v3.1",
    "MODELO EDITÁVEL": "RESULTADO GERADO",
    "NÃO INSERIDOS": "CONTROLADOS",
    "MODELO — NÃO É RESULTADO GENÉTICO": "RESULTADO GENÔMICO — VERSÃO FINAL",
    "MODELO — NÃO É RESULTADO": "RESULTADO GENÔMICO — VERSÃO FINAL",
    "GENOMA-HUDSON-RULESET-v3.3": "GENOMA-RULESET-v3.4",
    "MODELO SEM DADOS PESSOAIS": "RESULTADO GENÔMICO",
    "Campos em azul são placeholders obrigatórios ou condicionais; preencher com dado rastreável ou declarar NÃO DISPONÍVEL.":
        "Dados ausentes permanecem NÃO DISPONÍVEL; consulte limitações, fontes e status operacional.",
    "MODEL_EXPLANATION":
        "Resultado gerado sob controle de QC, evidência e publicação. Achados capazes de alterar conduta exigem confirmação apropriada.",
}
_template_v3.SYSTEM_REPLACEMENTS.clear()
_template_v3.SYSTEM_REPLACEMENTS.update(_ACTIVE_SYSTEM_REPLACEMENTS)

from .engine import ReportReleaseError, load_catalog, render_document, write_bundle

__all__ = ["ReportReleaseError", "load_catalog", "render_document", "write_bundle"]
