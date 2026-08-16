from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DESIGN = {
    "navy": "0B1F33",
    "teal": "0F766E",
    "amber": "A16207",
    "cream": "FFFAEB",
    "light_gray": "F2F4F7",
    "border": "D0D5DD",
    "text": "17212B",
    "slate": "667085",
    "blue": "175CD3",
    "a4_mm": (210, 297),
}


def _hex(value: str):
    from reportlab.lib.colors import HexColor
    return HexColor("#" + value)


def _safe(value: Any, default: str = "NÃO DISPONÍVEL") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _pdf(rendered: dict[str, Any], path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    metadata = rendered["metadata"]
    data = rendered.get("data", {})
    title = metadata["title"]
    report_id = metadata["report_id"]
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=17 * mm, leftMargin=17 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=title, author="GENOMA")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="GenomaTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=colors.white, spaceAfter=7 * mm))
    styles.add(ParagraphStyle(name="GenomaSubtitle", parent=styles["BodyText"], fontName="Helvetica", fontSize=10.5, leading=15, textColor=_hex("D7E3EF")))
    styles.add(ParagraphStyle(name="GenomaH1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=_hex(DESIGN["teal"]), spaceBefore=6 * mm, spaceAfter=3 * mm))
    styles.add(ParagraphStyle(name="GenomaBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=14, textColor=_hex(DESIGN["text"]), spaceAfter=2.5 * mm))
    styles.add(ParagraphStyle(name="GenomaSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=_hex(DESIGN["slate"])))
    styles.add(ParagraphStyle(name="GenomaCallout", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=8.7, leading=12.5, textColor=_hex(DESIGN["amber"])))

    story: list[Any] = []
    story.append(Paragraph(f"GENOMA / {report_id} / MODELO REUTILIZÁVEL v3.0", styles["GenomaSmall"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Table([[""]], colWidths=[176 * mm], rowHeights=[0.35 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), _hex(DESIGN["border"]))])))
    story.append(Spacer(1, 5 * mm))

    banner = Table(
        [
            [Paragraph(title, styles["GenomaTitle"])],
            [Paragraph("RESULTADO GENÔMICO · Saída determinística com rastreabilidade, limites metodológicos e linguagem técnica/leiga.", styles["GenomaSubtitle"])],
        ],
        colWidths=[176 * mm],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _hex(DESIGN["navy"])),
                ("LEFTPADDING", (0, 0), (-1, -1), 10 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10 * mm),
                ("TOPPADDING", (0, 0), (-1, 0), 9 * mm),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 9 * mm),
            ]
        )
    )
    story.append(banner)
    story.append(Spacer(1, 5 * mm))

    case_id = _safe(data.get("case_id"))
    post = _safe(data.get("post_deployment_status"), "PENDENTE")
    meta = Table(
        [
            [Paragraph("CASO", styles["GenomaSmall"]), Paragraph("RULESET", styles["GenomaSmall"]), Paragraph("STATUS", styles["GenomaSmall"])],
            [Paragraph(case_id, styles["GenomaBody"]), Paragraph("v3.3 · VIGENTE · 14/08/2026", styles["GenomaBody"]), Paragraph(f"POST-DEPLOYMENT {post}", styles["GenomaBody"])],
        ],
        colWidths=[53 * mm, 73 * mm, 50 * mm],
    )
    meta.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _hex(DESIGN["light_gray"])),
                ("LINEABOVE", (0, 0), (-1, 0), 1.6, _hex(DESIGN["teal"])),
                ("BOX", (0, 0), (-1, -1), 0.4, _hex(DESIGN["border"])),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _hex(DESIGN["border"])),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    story.append(meta)
    story.append(Spacer(1, 5 * mm))

    warning = "FINAL liberado somente após consentimento, QC, Evidence Gate, Policy Plane e FINAL_AUDIT_GATE. Dados ausentes permanecem NÃO DISPONÍVEL."
    callout = Table([[Paragraph(warning, styles["GenomaCallout"])]], colWidths=[176 * mm])
    callout.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _hex(DESIGN["cream"])),
                ("BOX", (0, 0), (-1, -1), 0.6, _hex(DESIGN["amber"])),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
            ]
        )
    )
    story.append(callout)

    story.append(Paragraph("Resumo executivo", styles["GenomaH1"]))
    story.append(Paragraph(_safe(data.get("summary")), styles["GenomaBody"]))

    section_data = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    model_sections: list[str] = []
    for line in rendered.get("markdown", "").splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            if name not in {"Achados estruturados", "Execution Manifest", "Fontes", "Limitações", "Resumo executivo"} and name not in model_sections:
                model_sections.append(name)
    for section in model_sections:
        story.append(Paragraph(section, styles["GenomaH1"]))
        story.append(Paragraph(_safe(section_data.get(section)), styles["GenomaBody"]))

    story.append(Paragraph("Achados estruturados", styles["GenomaH1"]))
    findings = data.get("findings") if isinstance(data.get("findings"), list) else []
    if not findings:
        story.append(Paragraph("NÃO DISPONÍVEL", styles["GenomaBody"]))
    else:
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            rows = [["Campo", "Valor"]] + [[k.replace("_", " ").title(), _safe(v)] for k, v in finding.items()]
            table_data = [[Paragraph(str(c), styles["GenomaBody"]) for c in row] for row in rows]
            table = Table(table_data, colWidths=[48 * mm, 128 * mm], repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), _hex(DESIGN["teal"])),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.35, _hex(DESIGN["border"])),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
                    ]
                )
            )
            story.append(KeepTogether([table, Spacer(1, 3 * mm)]))

    for heading, value in (("Fontes", data.get("sources")), ("Limitações", data.get("limitations"))):
        story.append(Paragraph(heading, styles["GenomaH1"]))
        story.append(Paragraph(_safe(value), styles["GenomaBody"]))

    story.append(Paragraph("Execution Manifest", styles["GenomaH1"]))
    story.append(Paragraph(_safe(data.get("execution_manifest")), styles["GenomaSmall"]))

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(_hex(DESIGN["slate"]))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawCentredString(A4[0] / 2, 8.5 * mm, f"GENOMA · {report_id} · v3.0 · página {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def _set_cell_shading(cell, fill: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def _set_cell_border(cell, **edges) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        if edge not in edges:
            continue
        tag = "w:" + edge
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        for key, value in edges[edge].items():
            element.set(qn("w:" + key), str(value))


def _docx(rendered: dict[str, Any], path: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    metadata = rendered["metadata"]
    data = rendered.get("data", {})
    report_id = metadata["report_id"]
    doc = Document()
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Mm(16)
    section.bottom_margin = Mm(17)
    section.left_margin = Mm(17)
    section.right_margin = Mm(17)

    normal = doc.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(9.5)
    normal.font.color.rgb = RGBColor.from_string(DESIGN["text"])
    for name, size, color in (("Title", 24, DESIGN["navy"]), ("Heading 1", 15, DESIGN["teal"]), ("Heading 2", 12, DESIGN["navy"])):
        style = doc.styles[name]
        style.font.name = "Aptos Display"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)

    header = section.header.paragraphs[0]
    header.text = f"GENOMA / {report_id} / MODELO REUTILIZÁVEL v3.0"
    header.style = doc.styles["Normal"]
    header.runs[0].font.size = Pt(7.5)
    header.runs[0].font.color.rgb = RGBColor.from_string(DESIGN["slate"])
    paragraph_properties = header._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "4")
    bottom.set(qn("w:color"), DESIGN["border"])
    borders.append(bottom)
    paragraph_properties.append(borders)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run = footer.add_run(f"GENOMA · {report_id} · v3.0 · página ")
    footer_run.font.size = Pt(7.5)
    footer_run.font.color.rgb = RGBColor.from_string(DESIGN["slate"])
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)

    banner = doc.add_table(rows=2, cols=1)
    banner.autofit = False
    banner.columns[0].width = Mm(176)
    for cell in (banner.cell(0, 0), banner.cell(1, 0)):
        _set_cell_shading(cell, DESIGN["navy"])
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    paragraph = banner.cell(0, 0).paragraphs[0]
    paragraph.paragraph_format.space_before = Pt(12)
    paragraph.paragraph_format.space_after = Pt(4)
    run = paragraph.add_run(metadata["title"])
    run.bold = True
    run.font.name = "Aptos Display"
    run.font.size = Pt(24)
    run.font.color.rgb = RGBColor(255, 255, 255)
    paragraph = banner.cell(1, 0).paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(12)
    run = paragraph.add_run("RESULTADO GENÔMICO · Saída determinística com rastreabilidade, limites metodológicos e linguagem técnica/leiga.")
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor.from_string("D7E3EF")
    doc.add_paragraph().paragraph_format.space_after = Pt(1)

    meta = doc.add_table(rows=2, cols=3)
    meta.autofit = False
    widths = [Mm(53), Mm(73), Mm(50)]
    for row_index, row in enumerate(meta.rows):
        for index, cell in enumerate(row.cells):
            cell.width = widths[index]
            _set_cell_shading(cell, DESIGN["light_gray"])
            _set_cell_border(
                cell,
                top={"val": "single", "sz": "6" if row_index == 0 else "2", "color": DESIGN["teal"] if row_index == 0 else DESIGN["border"]},
                bottom={"val": "single", "sz": "2", "color": DESIGN["border"]},
                left={"val": "single", "sz": "2", "color": DESIGN["border"]},
                right={"val": "single", "sz": "2", "color": DESIGN["border"]},
            )
    labels = ["CASO", "RULESET", "STATUS"]
    values = [_safe(data.get("case_id")), "v3.3 · VIGENTE · 14/08/2026", f"POST-DEPLOYMENT {_safe(data.get('post_deployment_status'), 'PENDENTE')}"]
    for index, label in enumerate(labels):
        run = meta.cell(0, index).paragraphs[0].add_run(label)
        run.bold = True
        run.font.size = Pt(7.5)
        run.font.color.rgb = RGBColor.from_string(DESIGN["slate"])
    for index, value in enumerate(values):
        run = meta.cell(1, index).paragraphs[0].add_run(value)
        run.font.size = Pt(9.5)
        run.font.color.rgb = RGBColor.from_string(DESIGN["text"])

    doc.add_paragraph()
    callout = doc.add_table(rows=1, cols=1)
    _set_cell_shading(callout.cell(0, 0), DESIGN["cream"])
    _set_cell_border(
        callout.cell(0, 0),
        top={"val": "single", "sz": "6", "color": DESIGN["amber"]},
        bottom={"val": "single", "sz": "6", "color": DESIGN["amber"]},
        left={"val": "single", "sz": "6", "color": DESIGN["amber"]},
        right={"val": "single", "sz": "6", "color": DESIGN["amber"]},
    )
    run = callout.cell(0, 0).paragraphs[0].add_run("FINAL liberado somente após consentimento, QC, Evidence Gate, Policy Plane e FINAL_AUDIT_GATE. Dados ausentes permanecem NÃO DISPONÍVEL.")
    run.bold = True
    run.font.size = Pt(8.5)
    run.font.color.rgb = RGBColor.from_string(DESIGN["amber"])

    def heading(text: str):
        paragraph = doc.add_paragraph(text, style="Heading 1")
        paragraph.paragraph_format.space_before = Pt(13)
        paragraph.paragraph_format.space_after = Pt(5)
        return paragraph

    def body(value: Any):
        paragraph = doc.add_paragraph(_safe(value))
        paragraph.paragraph_format.space_after = Pt(5)
        return paragraph

    heading("Resumo executivo")
    body(data.get("summary"))
    section_data = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    model_sections: list[str] = []
    for line in rendered.get("markdown", "").splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            if name not in {"Achados estruturados", "Execution Manifest", "Fontes", "Limitações", "Resumo executivo"} and name not in model_sections:
                model_sections.append(name)
    for section_name in model_sections:
        heading(section_name)
        body(section_data.get(section_name))

    heading("Achados estruturados")
    findings = data.get("findings") if isinstance(data.get("findings"), list) else []
    if not findings:
        body("NÃO DISPONÍVEL")
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        table = doc.add_table(rows=1, cols=2)
        table.autofit = False
        table.columns[0].width = Mm(48)
        table.columns[1].width = Mm(128)
        for index, label in enumerate(("Campo", "Valor")):
            cell = table.rows[0].cells[index]
            _set_cell_shading(cell, DESIGN["teal"])
            run = cell.paragraphs[0].add_run(label)
            run.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
        for key, value in finding.items():
            cells = table.add_row().cells
            cells[0].text = key.replace("_", " ").title()
            cells[1].text = _safe(value)
            for cell in cells:
                _set_cell_border(
                    cell,
                    top={"val": "single", "sz": "2", "color": DESIGN["border"]},
                    bottom={"val": "single", "sz": "2", "color": DESIGN["border"]},
                    left={"val": "single", "sz": "2", "color": DESIGN["border"]},
                    right={"val": "single", "sz": "2", "color": DESIGN["border"]},
                )

    heading("Fontes")
    body(data.get("sources"))
    heading("Limitações")
    body(data.get("limitations"))
    heading("Execution Manifest")
    body(data.get("execution_manifest"))
    doc.core_properties.title = metadata["title"]
    doc.core_properties.subject = "GENOMA v3.0 report artifact"
    doc.core_properties.keywords = "GENOMA,v3.3,genomics,report"
    doc.save(path)


def write_editorial_bundle(rendered: dict[str, Any], output_dir: Path, *, stem: str | None = None) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = rendered["metadata"]
    stem = stem or f"{metadata['report_id']}-{metadata['slug']}"
    pdf = output_dir / f"{stem}.pdf"
    docx = output_dir / f"{stem}.docx"
    _pdf(rendered, pdf)
    _docx(rendered, docx)
    return {"pdf": pdf, "docx": docx}
