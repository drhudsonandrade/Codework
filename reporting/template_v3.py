from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

MANIFEST_PATH = Path(__file__).with_name("reference_v3_manifest.json")

SYSTEM_REPLACEMENTS = {
    "MODELO REUTILIZÁVEL v3.0": "RESULTADO GENÔMICO v3.0",
    "MODELO EDITÁVEL": "RESULTADO GERADO",
    "NÃO INSERIDOS": "CONTROLADOS",
    "MODELO — NÃO É RESULTADO GENÉTICO": "PUBLICAÇÃO CONTROLADA — RESULTADO GENÔMICO",
    "MODELO — NÃO É RESULTADO": "PUBLICAÇÃO CONTROLADA",
    "GENOMA-HUDSON-RULESET-v3." + "3": "GENOMA--RULESET-v3.4",
    "MODELO SEM DADOS PESSOAIS": "RESULTADO GENÔMICO",
    "Campos em azul são placeholders obrigatórios ou condicionais; preencher com dado rastreável ou declarar NÃO DISPONÍVEL.":
        "Dados ausentes permanecem NÃO DISPONÍVEL; consulte limitações, fontes e status operacional.",
    "MODEL_EXPLANATION":
        "Resultado gerado sob controle de QC, evidência e publicação. Achados capazes de alterar conduta exigem confirmação apropriada.",
}


class TemplateV3Error(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_reference_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    index = json.loads(path.read_text(encoding="utf-8"))
    if index.get("schema") != "genoma-editorial-v3-reference-manifest-v1":
        raise TemplateV3Error("invalid v3 reference manifest schema")
    index_reports = index.get("reports")
    if not isinstance(index_reports, dict) or set(index_reports) != {f"{i:02d}" for i in range(1, 12)}:
        raise TemplateV3Error("v3 reference manifest must contain report IDs 01..11")

    compressed = index.get("compressed_detail")
    if compressed:
        detail_path = path.parent / str(compressed)
        if not detail_path.is_file():
            raise TemplateV3Error(f"v3 compressed reference detail missing: {detail_path}")
        try:
            packed = base64.b64decode(detail_path.read_text(encoding="ascii").strip(), validate=True)
            payload = json.loads(gzip.decompress(packed).decode("utf-8"))
        except Exception as exc:
            raise TemplateV3Error("invalid compressed v3 reference manifest") from exc
        if payload.get("schema") != index.get("schema") or set(payload.get("reports", {})) != set(index_reports):
            raise TemplateV3Error("compressed v3 reference manifest identity mismatch")
        # High-level reviewable index must agree with compressed coordinate inventory.
        for rid, summary in index_reports.items():
            detail = payload["reports"][rid]
            for key in ("filename", "sha256", "page_count"):
                if detail.get(key) != summary.get(key):
                    raise TemplateV3Error(f"v3 reference index/detail mismatch: {rid}:{key}")
        return payload

    # Backward-compatible monolithic manifest.
    return index


def resolve_template_pdf(report_id: str, template_dir: Path, manifest: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any]]:
    manifest = manifest or load_reference_manifest()
    meta = manifest["reports"][report_id]
    path = template_dir / meta["filename"]
    if not path.is_file():
        raise TemplateV3Error(f"v3 template not installed: {path}")
    actual = _sha256(path)
    if actual != meta["sha256"]:
        raise TemplateV3Error(f"v3 template checksum mismatch for {meta['filename']}: {actual}")
    return path, meta


def verify_template_pack(template_dir: Path, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = manifest or load_reference_manifest()
    verified: list[dict[str, Any]] = []
    for rid in sorted(manifest["reports"]):
        path, meta = resolve_template_pdf(rid, template_dir, manifest)
        reader = PdfReader(str(path))
        if len(reader.pages) != int(meta["page_count"]):
            raise TemplateV3Error(f"v3 template page-count mismatch for report {rid}")
        verified.append({"report_id": rid, "filename": path.name, "sha256": meta["sha256"], "pages": len(reader.pages)})
    return {
        "schema": "genoma-editorial-v3-template-pack-verification-v1",
        "status": "VERIFICADO",
        "verified_reports": len(verified),
        "reports": verified,
    }


def _register_fonts() -> dict[str, str]:
    candidates = {
        "regular": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"],
        "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"],
        "mono_bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf"],
    }
    result: dict[str, str] = {}
    for key, paths in candidates.items():
        path = next((p for p in paths if Path(p).is_file()), None)
        if path:
            name = f"GenomaV3_{key}"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path))
            result[key] = name
    result.setdefault("regular", "Helvetica")
    result.setdefault("bold", "Helvetica-Bold")
    result.setdefault("mono_bold", "Courier-Bold")
    return result


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _field_value(fields: dict[str, Any], item: dict[str, Any]) -> Any | None:
    keys = (item["field_id"], f"{item['token']}#{item['occurrence']}", item["token"])
    for key in keys:
        if key in fields:
            return fields[key]
    return None


def _normalize_value(raw: Any, *, default_color: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        value = raw.get("value")
        return {
            "value": "" if value is None else str(value),
            "color": str(raw.get("color") or default_color),
            "font_size_pt": raw.get("font_size_pt"),
            "bold": bool(raw.get("bold", True)),
        }
    return {"value": str(raw), "color": default_color, "font_size_pt": None, "bold": True}


def _is_dark(hex_color: str) -> bool:
    v = hex_color.lstrip("#")
    r, g, b = [int(v[i : i + 2], 16) for i in (0, 2, 4)]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 100


def _fit_single_line_size(text: str, max_width: float, start_size: float, font_name: str) -> float:
    text = " ".join(str(text).split())
    size = float(start_size)
    while size > 4.2 and pdfmetrics.stringWidth(text, font_name, size) > max_width:
        size -= 0.2
    return max(4.2, size)


def _draw_fit_text(c: canvas.Canvas, text: str, *, x: float, y_top: float, max_width: float, max_height: float,
                   font_size: float, font_name: str, color: str, page_height: float) -> float:
    # Deterministic one- or two-line fitter. It never expands outside the declared dynamic region.
    text = " ".join(text.split())
    if not text:
        return font_size
    size = float(font_size)
    min_size = 4.2
    words = text.split(" ")
    while size >= min_size:
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if pdfmetrics.stringWidth(candidate, font_name, size) <= max_width or not current:
                current = candidate
            else:
                lines.append(current); current = word
        if current:
            lines.append(current)
        leading = size * 1.18
        if len(lines) * leading <= max_height and all(pdfmetrics.stringWidth(line, font_name, size) <= max_width + 0.1 for line in lines):
            c.setFont(font_name, size)
            c.setFillColorRGB(*_hex_to_rgb(color))
            first_baseline = page_height - y_top - size
            for i, line in enumerate(lines):
                c.drawString(x, first_baseline - i * leading, line)
            return size
        size -= 0.25
    # Last-resort clipped single line. Publication metadata will expose the reduction.
    c.setFont(font_name, min_size); c.setFillColorRGB(*_hex_to_rgb(color))
    c.drawString(x, page_height - y_top - min_size, text)
    return min_size


def _replacement_geometry(item: dict[str, Any], page_width: float, page_items: list[dict[str, Any]] | None = None) -> tuple[list[float], list[float]]:
    bbox = [float(x) for x in item["bbox"]]
    cell = item.get("cell_bbox")
    if cell:
        cell = [float(x) for x in cell]
        right = cell[2] - 5.0
        bottom = min(cell[3] - 2.0, bbox[3] + 11.0)
        # Multiple placeholders can share one large cell (notably report 10 header and two-line cards).
        # Bound each value by the next peer so one replacement can never overwrite another.
        for peer in page_items or []:
            if peer is item or peer.get("cell_bbox") != item.get("cell_bbox"):
                continue
            pb = [float(x) for x in peer["bbox"]]
            vertical_overlap = min(bbox[3], pb[3]) - max(bbox[1], pb[1])
            if pb[0] > bbox[0] and vertical_overlap > 1.0:
                right = min(right, pb[0] - 4.0)
            if pb[1] > bbox[1] and abs(pb[0] - bbox[0]) < max(6.0, (bbox[2]-bbox[0]) * 0.5):
                bottom = min(bottom, pb[1] - 1.0)
        draw = [bbox[0], bbox[1] - 0.5, max(bbox[2], right), max(bbox[3], bottom)]
    else:
        # Paragraph-like placeholders may use the remaining content width, while keeping vertical growth bounded.
        draw = [bbox[0], bbox[1] - 0.5, max(bbox[2], page_width - 32.7), bbox[3] + 10.0]
    cover = [bbox[0] - 0.8, bbox[1] - 0.8, bbox[2] + 0.8, bbox[3] + 0.8]
    return cover, draw


def _system_values(data: dict[str, Any]) -> dict[str, Any]:
    values = dict(SYSTEM_REPLACEMENTS)
    supplied = data.get("template_system_fields")
    if isinstance(supplied, dict):
        values.update(supplied)
    return values


def render_pdf_from_template(rendered: dict[str, Any], path: Path, template_dir: Path, *, strict: bool = False) -> dict[str, Any]:
    report_id = str(rendered["metadata"]["report_id"])
    manifest = load_reference_manifest()
    template, meta = resolve_template_pdf(report_id, template_dir, manifest)
    data = rendered.get("data", {}) if isinstance(rendered.get("data"), dict) else {}
    fields = data.get("template_fields") if isinstance(data.get("template_fields"), dict) else {}
    systems = _system_values(data)
    fonts = _register_fonts()
    reader = PdfReader(str(template)); writer = PdfWriter()
    by_page_fields: dict[int, list[dict[str, Any]]] = {}
    by_page_controls: dict[int, list[dict[str, Any]]] = {}
    for item in meta.get("fields", []):
        by_page_fields.setdefault(int(item["page"]), []).append(item)
    for item in meta.get("controlled_spans", []):
        by_page_controls.setdefault(int(item["page"]), []).append(item)

    unresolved: list[str] = []
    replaced_fields = 0
    replaced_controls = 0
    min_font = 99.0
    for page_no, page in enumerate(reader.pages, 1):
        w = float(page.mediabox.width); h = float(page.mediabox.height)
        overlay = io.BytesIO(); c = canvas.Canvas(overlay, pagesize=(w, h)); changed = False
        for item in by_page_controls.get(page_no, []):
            raw = systems.get(item["source_text"])
            if raw is None:
                continue
            value = _normalize_value(raw, default_color=item.get("color", "#17212B"))
            x0, y0, x1, y1 = [float(v) for v in item["bbox"]]
            bg = str(item["background"]); c.setFillColorRGB(*_hex_to_rgb(bg)); c.rect(x0 - 0.9, h - y1 - 0.9, x1 - x0 + 1.8, y1 - y0 + 1.8, fill=1, stroke=0)
            fsize = float(value["font_size_pt"] or item.get("font_size_pt") or 7.0)
            fname = fonts["bold"] if value["bold"] else fonts["regular"]
            used = _draw_fit_text(c, value["value"], x=x0, y_top=y0, max_width=max(8.0, x1 - x0), max_height=max(8.0, y1 - y0 + 3.0), font_size=fsize, font_name=fname, color=value["color"], page_height=h)
            min_font = min(min_font, used); changed = True; replaced_controls += 1
        for item in by_page_fields.get(page_no, []):
            if item.get("guidance_only"):
                continue
            raw = _field_value(fields, item)
            if raw is None:
                unresolved.append(item["field_id"]); continue
            bg = str(item["background"])
            default_color = "#FFFFFF" if _is_dark(bg) else "#17212B"
            value = _normalize_value(raw, default_color=default_color)
            cover, draw = _replacement_geometry(item, w, by_page_fields.get(page_no, []))
            x0, y0, x1, y1 = cover
            c.setFillColorRGB(*_hex_to_rgb(bg)); c.rect(x0, h - y1, x1 - x0, y1 - y0, fill=1, stroke=0)
            dx0, dy0, dx1, dy1 = draw
            fsize = float(value["font_size_pt"] or item.get("font_size_pt") or 7.0)
            fname = fonts["bold"] if value["bold"] else fonts["regular"]
            used = _draw_fit_text(c, value["value"], x=dx0, y_top=dy0, max_width=max(8.0, dx1 - dx0), max_height=max(8.0, dy1 - dy0), font_size=fsize, font_name=fname, color=value["color"], page_height=h)
            min_font = min(min_font, used); changed = True; replaced_fields += 1
        c.save()
        if changed:
            overlay.seek(0); page.merge_page(PdfReader(overlay).pages[0])
        writer.add_page(page)
    if strict and unresolved:
        raise TemplateV3Error(f"strict v3 template rendering refused: {len(unresolved)} unresolved fields; first={unresolved[:5]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        writer.write(fh)
    return {
        "mode": "template-v3",
        "template": template.name,
        "template_sha256": meta["sha256"],
        "template_status": "VERIFICADO",
        "page_count": meta["page_count"],
        "replaced_fields": replaced_fields,
        "replaced_controlled_spans": replaced_controls,
        "unresolved_fields": unresolved,
        "strict": strict,
        "minimum_rendered_font_pt": None if min_font == 99.0 else round(min_font, 2),
        "static_pixel_contract": "reference pixels outside declared dynamic/controlled regions are preserved",
    }


def _inline_to_anchor(inline):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    anchor = OxmlElement("wp:anchor")
    for key, val in {"distT":"0","distB":"0","distL":"0","distR":"0","simplePos":"0","relativeHeight":"0","behindDoc":"1","locked":"0","layoutInCell":"1","allowOverlap":"1"}.items():
        anchor.set(key, val)
    simple = OxmlElement("wp:simplePos"); simple.set("x", "0"); simple.set("y", "0"); anchor.append(simple)
    for axis in ("H", "V"):
        pos = OxmlElement(f"wp:position{axis}"); pos.set("relativeFrom", "page")
        off = OxmlElement("wp:posOffset"); off.text = "0"; pos.append(off); anchor.append(pos)
    anchor.append(inline.find(qn("wp:extent")))
    eff = OxmlElement("wp:effectExtent")
    for key in ("l", "t", "r", "b"): eff.set(key, "0")
    anchor.append(eff); anchor.append(OxmlElement("wp:wrapNone"))
    anchor.append(inline.find(qn("wp:docPr"))); anchor.append(inline.find(qn("wp:cNvGraphicFramePr"))); anchor.append(inline.find(qn("a:graphic")))
    inline.getparent().replace(inline, anchor)
    return anchor


def _add_vml_textbox(paragraph, *, bbox: list[float], background: str, text: str, color: str, font_size: float, box_id: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from lxml import etree
    V = 'urn:schemas-microsoft-com:vml'
    x0,y0,x1,y1=bbox
    run=OxmlElement('w:r'); pict=OxmlElement('w:pict'); run.append(pict)
    rect=etree.Element('{%s}rect' % V, nsmap={'v': V}); rect.set('id',box_id); rect.set('fillcolor',background); rect.set('stroked','f')
    rect.set('style',f'position:absolute;margin-left:{x0:.3f}pt;margin-top:{y0:.3f}pt;width:{max(5,x1-x0):.3f}pt;height:{max(7,y1-y0):.3f}pt;z-index:10;mso-position-horizontal-relative:page;mso-position-vertical-relative:page;mso-wrap-style:none')
    tb=etree.Element('{%s}textbox' % V, nsmap={'v': V}); tb.set('inset','0,0,0,0'); rect.append(tb)
    content=OxmlElement('w:txbxContent'); tb.append(content); p=OxmlElement('w:p'); content.append(p)
    ppr=OxmlElement('w:pPr'); p.append(ppr); spacing=OxmlElement('w:spacing'); spacing.set(qn('w:before'),'0'); spacing.set(qn('w:after'),'0'); spacing.set(qn('w:line'),str(max(120,int(font_size*20*1.15)))); spacing.set(qn('w:lineRule'),'exact'); ppr.append(spacing)
    r=OxmlElement('w:r'); p.append(r); rpr=OxmlElement('w:rPr'); r.append(rpr)
    fonts=OxmlElement('w:rFonts'); fonts.set(qn('w:ascii'),'DejaVu Sans'); fonts.set(qn('w:hAnsi'),'DejaVu Sans'); rpr.append(fonts)
    c=OxmlElement('w:color'); c.set(qn('w:val'),color.lstrip('#')); rpr.append(c)
    sz=OxmlElement('w:sz'); sz.set(qn('w:val'),str(max(8,int(font_size*2)))); rpr.append(sz); rpr.append(OxmlElement('w:b'))
    t=OxmlElement('w:t'); t.text=text; r.append(t)
    pict.append(rect); paragraph._p.append(run)


def _convert_template_pages(template_pdf: Path, work: Path, page_count: int) -> tuple[list[Path], list[Path]]:
    if shutil.which("pdftocairo") is None or shutil.which("pdftoppm") is None:
        raise TemplateV3Error("DOCX template-v3 mode requires pdftocairo and pdftoppm (poppler-utils)")
    svgs=[]; pngs=[]
    for page in range(1,page_count+1):
        svg=work/f"page-{page}.svg"; raw=work/f"page-{page}.svg.raw"
        subprocess.run(["pdftocairo","-f",str(page),"-l",str(page),"-svg",str(template_pdf),str(raw)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        raw.rename(svg)
        stem=work/f"page-{page}-fallback"
        subprocess.run(["pdftoppm","-f",str(page),"-l",str(page),"-singlefile","-r","144","-png",str(template_pdf),str(stem)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        svgs.append(svg); pngs.append(Path(str(stem)+".png"))
    return svgs,pngs


def _patch_docx_svg(docx_path: Path, svgs: list[Path]) -> None:
    from lxml import etree
    td=Path(tempfile.mkdtemp(prefix="genoma-docx-svg-"))
    try:
        with zipfile.ZipFile(docx_path) as z: z.extractall(td)
        media=td/"word"/"media"; media.mkdir(parents=True,exist_ok=True)
        ct=td/"[Content_Types].xml"; tree=etree.parse(str(ct)); root=tree.getroot(); CT="{http://schemas.openxmlformats.org/package/2006/content-types}"
        if not any(e.get("Extension")=="svg" for e in root.findall(CT+"Default")):
            e=etree.Element(CT+"Default"); e.set("Extension","svg"); e.set("ContentType","image/svg+xml"); root.append(e)
        tree.write(str(ct),xml_declaration=True,encoding="UTF-8",standalone="yes")
        rels=td/"word"/"_rels"/"document.xml.rels"; tree=etree.parse(str(rels)); rr=tree.getroot(); R="{http://schemas.openxmlformats.org/package/2006/relationships}"
        nums=[]
        for e in rr.findall(R+"Relationship"):
            rid=e.get("Id","")
            if rid.startswith("rId"):
                try: nums.append(int(rid[3:]))
                except ValueError: pass
        next_id=max(nums or [0])+1; svg_rids=[]
        for i,src in enumerate(svgs,1):
            name=f"genoma-page-{i}.svg"; shutil.copy(src,media/name); rid=f"rId{next_id}"; next_id+=1; svg_rids.append(rid)
            e=etree.Element(R+"Relationship"); e.set("Id",rid); e.set("Type","http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"); e.set("Target","media/"+name); rr.append(e)
        tree.write(str(rels),xml_declaration=True,encoding="UTF-8",standalone="yes")
        doc=td/"word"/"document.xml"; parser=etree.XMLParser(remove_blank_text=False); tree=etree.parse(str(doc),parser); dr=tree.getroot(); A="http://schemas.openxmlformats.org/drawingml/2006/main"; RNS="http://schemas.openxmlformats.org/officeDocument/2006/relationships"; ASVG="http://schemas.microsoft.com/office/drawing/2016/SVG/main"
        blips=dr.xpath("//a:blip",namespaces={"a":A})
        if len(blips) < len(svg_rids): raise TemplateV3Error("DOCX SVG patch could not find every page background")
        for blip,rid in zip(blips[:len(svg_rids)],svg_rids):
            extlst=etree.SubElement(blip,"{%s}extLst"%A); ext=etree.SubElement(extlst,"{%s}ext"%A); ext.set("uri","{96DAC541-7B7A-43D3-8B79-37D633B846F1}")
            sb=etree.SubElement(ext,"{%s}svgBlip"%ASVG,nsmap={"asvg":ASVG}); sb.set("{%s}embed"%RNS,rid)
        tree.write(str(doc),xml_declaration=True,encoding="UTF-8",standalone="yes")
        tmp=docx_path.with_suffix(".svgpatch.docx")
        with zipfile.ZipFile(tmp,"w",zipfile.ZIP_DEFLATED) as z:
            for f in td.rglob("*"):
                if f.is_file(): z.write(f,f.relative_to(td))
        tmp.replace(docx_path)
    finally:
        shutil.rmtree(td,ignore_errors=True)


def render_docx_from_template(rendered: dict[str, Any], path: Path, template_dir: Path, *, strict: bool = False) -> dict[str, Any]:
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Mm, Pt

    report_id=str(rendered["metadata"]["report_id"]); manifest=load_reference_manifest(); template,meta=resolve_template_pdf(report_id,template_dir,manifest)
    data=rendered.get("data",{}) if isinstance(rendered.get("data"),dict) else {}; fields=data.get("template_fields") if isinstance(data.get("template_fields"),dict) else {}; systems=_system_values(data)
    unresolved=[]; replaced_fields=0; replaced_controls=0
    work=Path(tempfile.mkdtemp(prefix=f"genoma-v3-{report_id}-"))
    try:
        svgs,pngs=_convert_template_pages(template,work,int(meta["page_count"]))
        doc=Document(); section=doc.sections[0]; section.page_width=Mm(210); section.page_height=Mm(297); section.top_margin=Mm(0); section.bottom_margin=Mm(0); section.left_margin=Mm(0); section.right_margin=Mm(0); section.header_distance=Mm(0); section.footer_distance=Mm(0)
        # Keep the template as immutable visual chrome; dynamic values are editable VML text boxes.
        fields_by_page={}; controls_by_page={}
        for item in meta.get("fields",[]): fields_by_page.setdefault(int(item["page"]),[]).append(item)
        for item in meta.get("controlled_spans",[]): controls_by_page.setdefault(int(item["page"]),[]).append(item)
        for page_no,png in enumerate(pngs,1):
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(0); p.paragraph_format.space_after=Pt(0); p.paragraph_format.line_spacing=Pt(1)
            inline=p.add_run().add_picture(str(png),width=Mm(210),height=Mm(297))._inline; _inline_to_anchor(inline)
            for item in controls_by_page.get(page_no,[]):
                raw=systems.get(item["source_text"])
                if raw is None: continue
                value=_normalize_value(raw,default_color=item.get("color","#17212B")); bbox=[float(x) for x in item["bbox"]]; bg=str(item["background"]); fsize=float(value["font_size_pt"] or item.get("font_size_pt") or 7.0)
                fsize=_fit_single_line_size(value["value"], max(8.0,bbox[2]-bbox[0]), fsize, _register_fonts()["bold"])
                _add_vml_textbox(p,bbox=[bbox[0]-0.7,bbox[1]-0.7,bbox[2]+0.7,bbox[3]+1.4],background=bg,text=value["value"],color=value["color"],font_size=fsize,box_id=f"GENOMA_SYS_{page_no}_{replaced_controls+1}"); replaced_controls+=1
            for item in fields_by_page.get(page_no,[]):
                if item.get("guidance_only"): continue
                raw=_field_value(fields,item)
                if raw is None: unresolved.append(item["field_id"]); continue
                bg=str(item["background"]); default="#FFFFFF" if _is_dark(bg) else "#17212B"; value=_normalize_value(raw,default_color=default); bbox=[float(x) for x in item["bbox"]]; fsize=float(value["font_size_pt"] or item.get("font_size_pt") or 7.0)
                _cover, draw = _replacement_geometry(item, float(meta["page_size_pt"][0]), fields_by_page.get(page_no, []))
                # Editable textbox follows the same peer-bounded geometry as PDF, preventing overlap.
                width=max(8.0,draw[2]-draw[0]); height=max(8.0,draw[3]-draw[1])
                fsize=_fit_single_line_size(value["value"], width, fsize, _register_fonts()["bold"])
                _add_vml_textbox(p,bbox=[draw[0],draw[1],draw[0]+width,draw[1]+height],background=bg,text=value["value"],color=value["color"],font_size=fsize,box_id=f"GENOMA_FIELD_{page_no}_{replaced_fields+1}"); replaced_fields+=1
            if page_no < len(pngs):
                br=doc.add_paragraph(); br.paragraph_format.space_before=Pt(0); br.paragraph_format.space_after=Pt(0); br.add_run().add_break(WD_BREAK.PAGE)
        path.parent.mkdir(parents=True,exist_ok=True); doc.save(path); _patch_docx_svg(path,svgs)
    finally:
        shutil.rmtree(work,ignore_errors=True)
    if strict and unresolved:
        path.unlink(missing_ok=True); raise TemplateV3Error(f"strict v3 DOCX rendering refused: {len(unresolved)} unresolved fields")
    return {
        "mode":"template-v3-svg-docx",
        "template":template.name,
        "template_sha256":meta["sha256"],
        "template_status":"VERIFICADO",
        "page_count":meta["page_count"],
        "replaced_fields":replaced_fields,
        "replaced_controlled_spans":replaced_controls,
        "unresolved_fields":unresolved,
        "strict":strict,
        "editable_dynamic_fields":True,
        "static_chrome":"SVG page plate generated from the exact v3 reference PDF",
        "pixel_identity_note":"DOCX is renderer-dependent; exact PDF pixel identity is tested separately and must not be inferred from DOCX structure.",
    }


def template_mode_requested(rendered: dict[str, Any]) -> bool:
    data=rendered.get("data") if isinstance(rendered.get("data"),dict) else {}
    return str(data.get("editorial_mode") or os.environ.get("GENOMA_EDITORIAL_MODE") or "").lower() in {"template-v3","v3-template","pixel-v3"}


def template_dir_from_environment() -> Path:
    raw=os.environ.get("GENOMA_REPORT_TEMPLATE_DIR")
    if not raw: raise TemplateV3Error("GENOMA_REPORT_TEMPLATE_DIR is required for template-v3 mode")
    return Path(raw)


__all__=["TemplateV3Error","load_reference_manifest","verify_template_pack","render_pdf_from_template","render_docx_from_template","template_mode_requested","template_dir_from_environment"]