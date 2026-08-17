#!/usr/bin/env python3
"""Editorial artifact layer for the GENOMA v3.1 report suite."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from . import template_v3 as _template_v3

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_STORE = ROOT / "template_store" / "v3.1"
INBOX_ZIP = TEMPLATE_STORE / "inbox" / "GENOMA_REPORT_TEMPLATES_v3.1_DETERMINISTIC.zip"

# Stable public design contract used by tests and downstream renderers.
DESIGN = {
    "navy": "0B1F33",
    "teal": "0F766E",
    "amber": "A16207",
    "light_gray": "F2F4F7",
    "a4_mm": (210, 297),
}

V31_SYSTEM_REPLACEMENTS = {
    "MODELO REUTILIZÁVEL v3.1": "RESULTADO GENÔMICO v3.1",
    "MODELO EDITÁVEL": "RESULTADO GERADO",
    "NÃO INSERIDOS": "CONTROLADOS",
    "MODELO — NÃO É RESULTADO GENÉTICO": "RESULTADO GENÔMICO — VERSÃO FINAL",
    "MODELO — NÃO É RESULTADO": "RESULTADO GENÔMICO — VERSÃO FINAL",
    "MODELO SEM DADOS PESSOAIS": "RESULTADO GENÔMICO",
    "GENOMA-RULESET-v3.4": "GENOMA-RULESET-v3.4",
    "Campos em azul são placeholders obrigatórios ou condicionais; preencher com dado rastreável ou declarar NÃO DISPONÍVEL.":
        "Dados ausentes permanecem NÃO DISPONÍVEL; consulte limitações, fontes e status operacional.",
    "MODEL_EXPLANATION":
        "Resultado gerado sob controle de QC, evidência e publicação. Achados capazes de alterar conduta exigem confirmação apropriada.",
}


class EditorialRenderError(RuntimeError):
    pass


def _require_final_data(rendered: dict[str, Any]) -> None:
    meta = rendered.get("metadata") if isinstance(rendered.get("metadata"), dict) else {}
    if meta.get("mode") != "FINAL":
        return
    data = rendered.get("data") if isinstance(rendered.get("data"), dict) else {}
    publication = data.get("publication_gate") if isinstance(data.get("publication_gate"), dict) else {}
    if publication.get("passed") is not True:
        raise EditorialRenderError("FINAL editorial render blocked: publication gate not passed")


def _document_title(rendered: dict[str, Any]) -> str:
    meta = rendered.get("metadata") if isinstance(rendered.get("metadata"), dict) else {}
    return str(meta.get("title") or "GENOMA")


def _programmatic_docx(rendered: dict[str, Any], path: Path) -> None:
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.core_properties.title = _document_title(rendered)
    style = document.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(10)
    for raw in str(rendered["markdown"]).splitlines():
        if raw.startswith("# "):
            document.add_heading(raw[2:], level=1)
        elif raw.startswith("## "):
            document.add_heading(raw[3:], level=2)
        elif raw.startswith("### "):
            document.add_heading(raw[4:], level=3)
        elif raw.startswith("- "):
            document.add_paragraph(raw[2:], style="List Bullet")
        elif raw.strip() in {"```json", "```"}:
            continue
        elif raw.strip():
            document.add_paragraph(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)


def _programmatic_pdf(rendered: dict[str, Any], path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    story = []
    for raw in str(rendered["markdown"]).splitlines():
        if raw.startswith("# "):
            story.append(Paragraph(raw[2:], styles["Title"]))
        elif raw.startswith("## "):
            story.append(Paragraph(raw[3:], styles["Heading2"]))
        elif raw.startswith("### "):
            story.append(Paragraph(raw[4:], styles["Heading3"]))
        elif raw.strip() in {"```json", "```"}:
            continue
        elif raw.strip():
            story.append(Paragraph(raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), styles["BodyText"]))
        story.append(Spacer(1, 4))
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, title=_document_title(rendered)).build(story)


def _use_template(rendered: dict[str, Any]) -> bool:
    mode = str(os.environ.get("GENOMA_EDITORIAL_MODE") or "").lower()
    if mode in {"programmatic", "plain"}:
        return False
    meta = rendered.get("metadata") if isinstance(rendered.get("metadata"), dict) else {}
    return meta.get("mode") == "FINAL" or _template_v3.template_mode_requested(rendered)


def _configure_v31_replacements() -> None:
    """Install the complete v3.1 final-state replacement set atomically in memory.

    Keeping this list complete prevents template-only labels from leaking into FINAL
    artifacts after SYSTEM_REPLACEMENTS is cleared.
    """
    _template_v3.SYSTEM_REPLACEMENTS.clear()
    _template_v3.SYSTEM_REPLACEMENTS.update(V31_SYSTEM_REPLACEMENTS)


def _extract_verified_template_zip() -> Path:
    from scripts.verify_template_store import verify

    result = verify(materialize=False)
    if result.get("operational_status") != "VERIFICADO":
        raise EditorialRenderError("v3.1 template source is not verified")
    if not INBOX_ZIP.is_file():
        raise EditorialRenderError("verified runtime-extractable template ZIP is not available")
    temp = Path(tempfile.mkdtemp(prefix="genoma-v31-templates-"))
    with zipfile.ZipFile(INBOX_ZIP) as archive:
        archive.extractall(temp)
    return temp


def _template_dir() -> tuple[Path, Path | None]:
    raw = os.environ.get("GENOMA_REPORT_TEMPLATE_DIR")
    if raw:
        path = Path(raw)
        if not path.is_dir():
            raise EditorialRenderError(f"GENOMA_REPORT_TEMPLATE_DIR not found: {path}")
        return path, None
    materialized = TEMPLATE_STORE / "materialized"
    if materialized.is_dir():
        return materialized, None
    temp = _extract_verified_template_zip()
    return temp, temp


def _verified_reference(report_id: str, template_dir: Path) -> dict[str, Any]:
    try:
        manifest = _template_v3.load_reference_manifest()
        verification = _template_v3.verify_template_pack(template_dir)
    except Exception as exc:
        raise EditorialRenderError(f"v3.1 editorial reference unavailable: {type(exc).__name__}: {exc}") from exc
    if verification.get("status") != "VERIFICADO":
        raise EditorialRenderError("v3.1 template verification did not return VERIFICADO")
    reports = manifest.get("reports") if isinstance(manifest.get("reports"), dict) else {}
    if report_id not in reports:
        raise EditorialRenderError(f"report {report_id} absent from v3.1 reference manifest")
    return manifest


def write_editorial_bundle(rendered: dict[str, Any], output_dir: Path, *, stem: str | None = None) -> dict[str, Path]:
    _require_final_data(rendered)
    meta = rendered.get("metadata") if isinstance(rendered.get("metadata"), dict) else {}
    report_id = str(meta.get("report_id") or "")
    if not report_id:
        raise EditorialRenderError("missing report_id")
    stem = stem or f"{report_id}-{meta.get('slug', 'report')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    docx = output_dir / f"{stem}.docx"
    pdf = output_dir / f"{stem}.pdf"
    editorial_manifest = output_dir / f"{stem}.editorial.json"

    if not _use_template(rendered):
        _programmatic_docx(rendered, docx)
        _programmatic_pdf(rendered, pdf)
        info = {"mode": "programmatic", "template_suite": "v3.1", "status": "EXECUTADO"}
    else:
        _configure_v31_replacements()
        template_dir, cleanup = _template_dir()
        try:
            manifest = _verified_reference(report_id, template_dir)
            strict = str(os.environ.get("GENOMA_TEMPLATE_STRICT") or "1").lower() not in {"0", "false", "no"}
            pdf_info = _template_v3.render_pdf_from_template(
                report_id, rendered, template_dir, pdf, strict=strict, coordinate_manifest=manifest
            )
            docx_info = _template_v3.render_docx_from_template(
                report_id, rendered, template_dir, docx, strict=strict, coordinate_manifest=manifest
            )
            info = {
                "mode": "template-v3.1",
                "template_suite": "v3.1",
                "status": "EXECUTADO",
                "pdf": pdf_info,
                "docx": docx_info,
            }
        finally:
            if cleanup is not None:
                shutil.rmtree(cleanup, ignore_errors=True)

    editorial_manifest.write_text(json.dumps(info, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"docx": docx, "pdf": pdf, "editorial_manifest": editorial_manifest}
