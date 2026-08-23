from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

MANIFEST_PATH = Path(__file__).with_name("reference_v3_manifest.json")
RULESET_TEMPLATE_PREFIX = "GENOMA-HUDSON-RULESET-v"
CURRENT_RULESET_TEMPLATE_SOURCE = "GENOMA-HUDSON-RULESET-v3.4"
CURRENT_RULESET_TEMPLATE_LABEL = "GENOMA-RULESET-v3.4"
# Leading applied to one rendered line; a line taller than its box is clipped by Word.
SINGLE_LINE_LEADING = 1.2

SYSTEM_REPLACEMENTS = {
    "MODELO REUTILIZÁVEL v3.0": "RESULTADO GENÔMICO v3.0",
    "MODELO EDITÁVEL": "RESULTADO GERADO",
    "NÃO INSERIDOS": "CONTROLADOS",
    "MODELO — NÃO É RESULTADO GENÉTICO": "PUBLICAÇÃO CONTROLADA — RESULTADO GENÔMICO",
    "MODELO — NÃO É RESULTADO": "PUBLICAÇÃO CONTROLADA",
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


def _validate_controlled_span_sources(payload: dict[str, Any]) -> None:
    for report_id, meta in payload.get("reports", {}).items():
        for item in meta.get("controlled_spans", []):
            source = str(item.get("source_text", ""))
            if source.startswith(RULESET_TEMPLATE_PREFIX) and source != CURRENT_RULESET_TEMPLATE_SOURCE:
                raise TemplateV3Error(
                    f"noncanonical ruleset marker in v3 reference manifest for report {report_id}: {source}"
                )


def _validate_page_size_pt(report_id: str, meta: dict[str, Any]) -> None:
    page_size = meta.get("page_size_pt")
    if not isinstance(page_size, list) or len(page_size) != 2:
        raise TemplateV3Error(
            f"invalid page_size_pt for v3 reference report {report_id}: {page_size!r}"
        )
    for value in page_size:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TemplateV3Error(
                f"invalid page_size_pt for v3 reference report {report_id}: {page_size!r}"
            )
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise TemplateV3Error(
                f"invalid page_size_pt for v3 reference report {report_id}: {page_size!r}"
            ) from exc
        if not math.isfinite(number) or number <= 0:
            raise TemplateV3Error(
                f"invalid page_size_pt for v3 reference report {report_id}: {page_size!r}"
            )


def load_reference_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    index = json.loads(path.read_text(encoding="utf-8"))
    if index.get("schema") != "genoma-editorial-v3-reference-manifest-v1":
        raise TemplateV3Error("invalid v3 reference manifest schema")
    index_reports = index.get("reports")
    if not isinstance(index_reports, dict) or set(index_reports) != {f"{i:02d}" for i in range(1, 12)}:
        raise TemplateV3Error("v3 reference manifest must contain report IDs 01..11")
    for rid, summary in index_reports.items():
        if not isinstance(summary, dict):
            raise TemplateV3Error(f"invalid v3 reference report metadata: {rid}")
        _validate_page_size_pt(rid, summary)

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
        for rid, summary in index_reports.items():
            detail = payload["reports"][rid]
            if not isinstance(detail, dict):
                raise TemplateV3Error(f"invalid compressed v3 reference report metadata: {rid}")
            _validate_page_size_pt(rid, detail)
            for key in ("filename", "sha256", "page_count", "page_size_pt"):
                if detail.get(key) != summary.get(key):
                    raise TemplateV3Error(f"v3 reference index/detail mismatch: {rid}:{key}")
        _validate_controlled_span_sources(payload)
        return payload
    _validate_controlled_span_sources(index)
    return index


def resolve_template_pdf(
    report_id: str,
    template_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    manifest = manifest or load_reference_manifest()
    meta = manifest["reports"][report_id]
    path = template_dir / meta["filename"]
    if not path.is_file():
        raise TemplateV3Error(f"v3 template not installed: {path}")
    actual = _sha256(path)
    if actual != meta["sha256"]:
        raise TemplateV3Error(f"v3 template checksum mismatch for {meta['filename']}: {actual}")
    return path, meta


def verify_template_pack(
    template_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or load_reference_manifest()
    verified: list[dict[str, Any]] = []
    for rid in sorted(manifest["reports"]):
        path, meta = resolve_template_pdf(rid, template_dir, manifest)
        reader = PdfReader(str(path))
        if len(reader.pages) != int(meta["page_count"]):
            raise TemplateV3Error(f"v3 template page-count mismatch for report {rid}")
        verified.append(
            {
                "report_id": rid,
                "filename": path.name,
                "sha256": meta["sha256"],
                "pages": len(reader.pages),
            }
        )
    return {
        "schema": "genoma-editorial-v3-template-pack-verification-v1",
        "status": "VERIFICADO",
        "verified_reports": len(verified),
        "reports": verified,
    }


def _register_fonts() -> dict[str, str]:
    candidates = {
        "regular": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ],
        "bold": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        ],
        "mono_bold": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
        ],
    }
    result: dict[str, str] = {}
    for key, paths in candidates.items():
        path = next((candidate for candidate in paths if Path(candidate).is_file()), None)
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
    return tuple(int(value[index : index + 2], 16) / 255.0 for index in (0, 2, 4))  # type: ignore[return-value]


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
    return {
        "value": str(raw),
        "color": default_color,
        "font_size_pt": None,
        "bold": True,
    }


def _is_dark(hex_color: str) -> bool:
    value = hex_color.lstrip("#")
    red, green, blue = [int(value[index : index + 2], 16) for index in (0, 2, 4)]
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) < 100


def _fit_single_line_size(
    text: str,
    max_width: float,
    start_size: float,
    font_name: str,
    max_height: float | None = None,
) -> float:
    """Shrink a single line until it fits the box on both axes.

    Width alone is not enough: the DOCX renderer clips a line whose leading exceeds the
    textbox height, so a value that fits horizontally can still be cut off vertically.
    """
    text = " ".join(str(text).split())
    size = float(start_size)
    while size > 4.2 and (
        pdfmetrics.stringWidth(text, font_name, size) > max_width
        or (max_height is not None and size * SINGLE_LINE_LEADING > max_height)
    ):
        size -= 0.2
    return max(4.2, size)


def _draw_fit_text(
    c: canvas.Canvas,
    text: str,
    *,
    x: float,
    y_top: float,
    max_width: float,
    max_height: float,
    font_size: float,
    font_name: str,
    color: str,
    page_height: float,
) -> float:
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
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        leading = size * 1.18
        if len(lines) * leading <= max_height and all(
            pdfmetrics.stringWidth(line, font_name, size) <= max_width + 0.1
            for line in lines
        ):
            c.setFont(font_name, size)
            c.setFillColorRGB(*_hex_to_rgb(color))
            first_baseline = page_height - y_top - size
            for index, line in enumerate(lines):
                c.drawString(x, first_baseline - index * leading, line)
            return size
        size -= 0.25
    c.setFont(font_name, min_size)
    c.setFillColorRGB(*_hex_to_rgb(color))
    c.drawString(x, page_height - y_top - min_size, text)
    return min_size


def _replacement_geometry(
    item: dict[str, Any],
    page_width: float,
    page_items: list[dict[str, Any]] | None = None,
) -> tuple[list[float], list[float]]:
    bbox = [float(value) for value in item["bbox"]]
    cell = item.get("cell_bbox")
    if cell:
        cell = [float(value) for value in cell]
        right = cell[2] - 5.0
        bottom = min(cell[3] - 2.0, bbox[3] + 11.0)
        for peer in page_items or []:
            if peer is item or peer.get("cell_bbox") != item.get("cell_bbox"):
                continue
            peer_bbox = [float(value) for value in peer["bbox"]]
            vertical_overlap = min(bbox[3], peer_bbox[3]) - max(bbox[1], peer_bbox[1])
            if peer_bbox[0] > bbox[0] and vertical_overlap > 1.0:
                right = min(right, peer_bbox[0] - 4.0)
            if (
                peer_bbox[1] > bbox[1]
                and abs(peer_bbox[0] - bbox[0]) < max(6.0, (bbox[2] - bbox[0]) * 0.5)
            ):
                bottom = min(bottom, peer_bbox[1] - 1.0)
        draw = [
            bbox[0],
            bbox[1] - 0.5,
            max(bbox[2], right),
            max(bbox[3], bottom),
        ]
    else:
        draw = [
            bbox[0],
            bbox[1] - 0.5,
            max(bbox[2], page_width - 32.7),
            bbox[3] + 10.0,
        ]
    cover = [bbox[0] - 0.8, bbox[1] - 0.8, bbox[2] + 0.8, bbox[3] + 0.8]
    return cover, draw


def _system_values(data: dict[str, Any]) -> dict[str, Any]:
    values = dict(SYSTEM_REPLACEMENTS)
    supplied = data.get("template_system_fields")
    if isinstance(supplied, dict):
        values.update(supplied)
    return values


def _system_value_for_source(source_text: str, systems: dict[str, Any]) -> Any | None:
    if source_text == CURRENT_RULESET_TEMPLATE_SOURCE:
        return CURRENT_RULESET_TEMPLATE_LABEL
    if source_text.startswith(RULESET_TEMPLATE_PREFIX):
        raise TemplateV3Error(f"noncanonical ruleset marker in template source: {source_text}")
    return systems.get(source_text)


def render_pdf_from_template(
    rendered: dict[str, Any],
    path: Path,
    template_dir: Path,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    report_id = str(rendered["metadata"]["report_id"])
    manifest = load_reference_manifest()
    template, meta = resolve_template_pdf(report_id, template_dir, manifest)
    data = rendered.get("data", {}) if isinstance(rendered.get("data"), dict) else {}
    fields = data.get("template_fields") if isinstance(data.get("template_fields"), dict) else {}
    systems = _system_values(data)
    fonts = _register_fonts()
    reader = PdfReader(str(template))
    writer = PdfWriter()
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
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        overlay = io.BytesIO()
        c = canvas.Canvas(overlay, pagesize=(width, height))
        changed = False
        for item in by_page_controls.get(page_no, []):
            raw = _system_value_for_source(str(item["source_text"]), systems)
            if raw is None:
                continue
            value = _normalize_value(raw, default_color=item.get("color", "#17212B"))
            x0, y0, x1, y1 = [float(number) for number in item["bbox"]]
            background = str(item["background"])
            c.setFillColorRGB(*_hex_to_rgb(background))
            c.rect(
                x0 - 0.9,
                height - y1 - 0.9,
                x1 - x0 + 1.8,
                y1 - y0 + 1.8,
                fill=1,
                stroke=0,
            )
            font_size = float(value["font_size_pt"] or item.get("font_size_pt") or 7.0)
            font_name = fonts["bold"] if value["bold"] else fonts["regular"]
            used = _draw_fit_text(
                c,
                value["value"],
                x=x0,
                y_top=y0,
                max_width=max(8.0, x1 - x0),
                max_height=max(8.0, y1 - y0 + 3.0),
                font_size=font_size,
                font_name=font_name,
                color=value["color"],
                page_height=height,
            )
            min_font = min(min_font, used)
            changed = True
            replaced_controls += 1
        for item in by_page_fields.get(page_no, []):
            if item.get("guidance_only"):
                continue
            raw = _field_value(fields, item)
            if raw is None:
                unresolved.append(item["field_id"])
                continue
            background = str(item["background"])
            default_color = "#FFFFFF" if _is_dark(background) else "#17212B"
            value = _normalize_value(raw, default_color=default_color)
            cover, draw = _replacement_geometry(item, width, by_page_fields.get(page_no, []))
            x0, y0, x1, y1 = cover
            c.setFillColorRGB(*_hex_to_rgb(background))
            c.rect(x0, height - y1, x1 - x0, y1 - y0, fill=1, stroke=0)
            dx0, dy0, dx1, dy1 = draw
            font_size = float(value["font_size_pt"] or item.get("font_size_pt") or 7.0)
            font_name = fonts["bold"] if value["bold"] else fonts["regular"]
            used = _draw_fit_text(
                c,
                value["value"],
                x=dx0,
                y_top=dy0,
                max_width=max(8.0, dx1 - dx0),
                max_height=max(8.0, dy1 - dy0),
                font_size=font_size,
                font_name=font_name,
                color=value["color"],
                page_height=height,
            )
            min_font = min(min_font, used)
            changed = True
            replaced_fields += 1
        c.save()
        if changed:
            overlay.seek(0)
            page.merge_page(PdfReader(overlay).pages[0])
        writer.add_page(page)
    if strict and unresolved:
        raise TemplateV3Error(
            f"strict v3 template rendering refused: {len(unresolved)} unresolved fields; first={unresolved[:5]}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer.write(handle)
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
    for key, value in {
        "distT": "0",
        "distB": "0",
        "distL": "0",
        "distR": "0",
        "simplePos": "0",
        "relativeHeight": "0",
        "behindDoc": "1",
        "locked": "0",
        "layoutInCell": "1",
        "allowOverlap": "1",
    }.items():
        anchor.set(key, value)
    simple = OxmlElement("wp:simplePos")
    simple.set("x", "0")
    simple.set("y", "0")
    anchor.append(simple)
    for axis in ("H", "V"):
        position = OxmlElement(f"wp:position{axis}")
        position.set("relativeFrom", "page")
        offset = OxmlElement("wp:posOffset")
        offset.text = "0"
        position.append(offset)
        anchor.append(position)
    anchor.append(inline.find(qn("wp:extent")))
    effect = OxmlElement("wp:effectExtent")
    for key in ("l", "t", "r", "b"):
        effect.set(key, "0")
    anchor.append(effect)
    anchor.append(OxmlElement("wp:wrapNone"))
    anchor.append(inline.find(qn("wp:docPr")))
    anchor.append(inline.find(qn("wp:cNvGraphicFramePr")))
    anchor.append(inline.find(qn("a:graphic")))
    inline.getparent().replace(inline, anchor)
    return anchor


def _add_vml_textbox(
    paragraph,
    *,
    bbox: list[float],
    background: str,
    text: str,
    color: str,
    font_size: float,
    box_id: str,
) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from lxml import etree

    vml_ns = "urn:schemas-microsoft-com:vml"
    x0, y0, x1, y1 = bbox
    run = OxmlElement("w:r")
    pict = OxmlElement("w:pict")
    run.append(pict)
    rect = etree.Element(f"{{{vml_ns}}}rect", nsmap={"v": vml_ns})
    rect.set("id", box_id)
    rect.set("fillcolor", background)
    rect.set("stroked", "f")
    rect.set(
        "style",
        f"position:absolute;margin-left:{x0:.3f}pt;margin-top:{y0:.3f}pt;"
        f"width:{max(5, x1-x0):.3f}pt;height:{max(7, y1-y0):.3f}pt;z-index:10;"
        "mso-position-horizontal-relative:page;mso-position-vertical-relative:page;mso-wrap-style:none",
    )
    textbox = etree.Element(f"{{{vml_ns}}}textbox", nsmap={"v": vml_ns})
    textbox.set("inset", "0,0,0,0")
    rect.append(textbox)
    content = OxmlElement("w:txbxContent")
    textbox.append(content)
    paragraph_node = OxmlElement("w:p")
    content.append(paragraph_node)
    paragraph_properties = OxmlElement("w:pPr")
    paragraph_node.append(paragraph_properties)
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:line"), str(max(120, int(font_size * 20 * 1.15))))
    spacing.set(qn("w:lineRule"), "exact")
    paragraph_properties.append(spacing)
    text_run = OxmlElement("w:r")
    paragraph_node.append(text_run)
    run_properties = OxmlElement("w:rPr")
    text_run.append(run_properties)
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), "DejaVu Sans")
    fonts.set(qn("w:hAnsi"), "DejaVu Sans")
    run_properties.append(fonts)
    color_node = OxmlElement("w:color")
    color_node.set(qn("w:val"), color.lstrip("#"))
    run_properties.append(color_node)
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), str(max(8, int(font_size * 2))))
    run_properties.append(size)
    run_properties.append(OxmlElement("w:b"))
    text_node = OxmlElement("w:t")
    text_node.text = text
    text_run.append(text_node)
    pict.append(rect)
    paragraph._p.append(run)


def _run_poppler(command: list[str], page: int) -> None:
    """Run a Poppler converter, keeping its diagnostics instead of discarding them.

    Poppler reports the actual reason a page could not be converted on stderr. Dropping
    it leaves a bare CalledProcessError, which is the one place the failure could still
    be diagnosed.
    """
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise TemplateV3Error(
            f"{command[0]} failed on template page {page} with exit code {result.returncode}"
            + (f": {detail[-500:]}" if detail else "")
        )


def _convert_template_pages(
    template_pdf: Path,
    work: Path,
    page_count: int,
) -> tuple[list[Path], list[Path]]:
    if shutil.which("pdftocairo") is None or shutil.which("pdftoppm") is None:
        raise TemplateV3Error(
            "DOCX template-v3 mode requires pdftocairo and pdftoppm (poppler-utils)"
        )
    svgs: list[Path] = []
    pngs: list[Path] = []
    for page in range(1, page_count + 1):
        svg = work / f"page-{page}.svg"
        raw = work / f"page-{page}.svg.raw"
        _run_poppler(
            ["pdftocairo", "-f", str(page), "-l", str(page), "-svg", str(template_pdf), str(raw)],
            page,
        )
        raw.rename(svg)
        stem = work / f"page-{page}-fallback"
        _run_poppler(
            [
                "pdftoppm",
                "-f",
                str(page),
                "-l",
                str(page),
                "-singlefile",
                "-r",
                "144",
                "-png",
                str(template_pdf),
                str(stem),
            ],
            page,
        )
        svgs.append(svg)
        pngs.append(Path(str(stem) + ".png"))
    return svgs, pngs


def _patch_docx_svg(docx_path: Path, svgs: list[Path]) -> None:
    from lxml import etree

    temp_dir = Path(tempfile.mkdtemp(prefix="genoma-docx-svg-"))
    try:
        with zipfile.ZipFile(docx_path) as archive:
            base = temp_dir.resolve()
            seen: set[str] = set()
            for member in archive.infolist():
                member_path = PurePosixPath(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise TemplateV3Error(f"unsafe DOCX archive member: {member.filename}")
                target = (base / Path(*member_path.parts)).resolve()
                if target != base and base not in target.parents:
                    raise TemplateV3Error(f"unsafe DOCX archive member: {member.filename}")
                # extractall writes members in order, so a repeated name silently replaces
                # the entry that was already validated and extracted.
                if member.filename in seen:
                    raise TemplateV3Error(f"duplicate DOCX archive member: {member.filename}")
                seen.add(member.filename)
            archive.extractall(temp_dir)
        media = temp_dir / "word" / "media"
        media.mkdir(parents=True, exist_ok=True)
        content_types = temp_dir / "[Content_Types].xml"
        tree = etree.parse(str(content_types))
        root = tree.getroot()
        content_type_ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
        if not any(
            element.get("Extension") == "svg"
            for element in root.findall(content_type_ns + "Default")
        ):
            element = etree.Element(content_type_ns + "Default")
            element.set("Extension", "svg")
            element.set("ContentType", "image/svg+xml")
            root.append(element)
        tree.write(
            str(content_types),
            xml_declaration=True,
            encoding="UTF-8",
            standalone="yes",
        )

        relationships_path = temp_dir / "word" / "_rels" / "document.xml.rels"
        tree = etree.parse(str(relationships_path))
        relationships = tree.getroot()
        relationship_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        identifiers: list[int] = []
        for element in relationships.findall(relationship_ns + "Relationship"):
            relation_id = element.get("Id", "")
            if relation_id.startswith("rId"):
                try:
                    identifiers.append(int(relation_id[3:]))
                except ValueError:
                    pass
        next_id = max(identifiers or [0]) + 1
        svg_relation_ids: list[str] = []
        for index, source in enumerate(svgs, 1):
            name = f"genoma-page-{index}.svg"
            shutil.copy(source, media / name)
            relation_id = f"rId{next_id}"
            next_id += 1
            svg_relation_ids.append(relation_id)
            element = etree.Element(relationship_ns + "Relationship")
            element.set("Id", relation_id)
            element.set(
                "Type",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            )
            element.set("Target", "media/" + name)
            relationships.append(element)
        tree.write(
            str(relationships_path),
            xml_declaration=True,
            encoding="UTF-8",
            standalone="yes",
        )

        document = temp_dir / "word" / "document.xml"
        parser = etree.XMLParser(remove_blank_text=False)
        tree = etree.parse(str(document), parser)
        document_root = tree.getroot()
        drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        relationship_attribute_ns = (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        )
        svg_ns = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"
        blips = document_root.xpath("//a:blip", namespaces={"a": drawing_ns})
        if len(blips) < len(svg_relation_ids):
            raise TemplateV3Error("DOCX SVG patch could not find every page background")
        for blip, relation_id in zip(blips[: len(svg_relation_ids)], svg_relation_ids):
            extension_list = etree.SubElement(blip, f"{{{drawing_ns}}}extLst")
            extension = etree.SubElement(extension_list, f"{{{drawing_ns}}}ext")
            extension.set("uri", "{96DAC541-7B7A-43D3-8B79-37D633B846F1}")
            svg_blip = etree.SubElement(
                extension,
                f"{{{svg_ns}}}svgBlip",
                nsmap={"asvg": svg_ns},
            )
            svg_blip.set(f"{{{relationship_attribute_ns}}}embed", relation_id)
        tree.write(
            str(document),
            xml_declaration=True,
            encoding="UTF-8",
            standalone="yes",
        )

        patched = docx_path.with_suffix(".svgpatch.docx")
        with zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in temp_dir.rglob("*"):
                if file.is_file():
                    archive.write(file, file.relative_to(temp_dir))
        patched.replace(docx_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def render_docx_from_template(
    rendered: dict[str, Any],
    path: Path,
    template_dir: Path,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Mm, Pt

    report_id = str(rendered["metadata"]["report_id"])
    manifest = load_reference_manifest()
    template, meta = resolve_template_pdf(report_id, template_dir, manifest)
    data = rendered.get("data", {}) if isinstance(rendered.get("data"), dict) else {}
    fields = data.get("template_fields") if isinstance(data.get("template_fields"), dict) else {}
    systems = _system_values(data)
    bold_font = _register_fonts()["bold"]
    unresolved: list[str] = []
    replaced_fields = 0
    replaced_controls = 0
    work = Path(tempfile.mkdtemp(prefix=f"genoma-v3-{report_id}-"))
    try:
        svgs, pngs = _convert_template_pages(template, work, int(meta["page_count"]))
        doc = Document()
        section = doc.sections[0]
        section.page_width = Mm(210)
        section.page_height = Mm(297)
        section.top_margin = Mm(0)
        section.bottom_margin = Mm(0)
        section.left_margin = Mm(0)
        section.right_margin = Mm(0)
        section.header_distance = Mm(0)
        section.footer_distance = Mm(0)
        fields_by_page: dict[int, list[dict[str, Any]]] = {}
        controls_by_page: dict[int, list[dict[str, Any]]] = {}
        for item in meta.get("fields", []):
            fields_by_page.setdefault(int(item["page"]), []).append(item)
        for item in meta.get("controlled_spans", []):
            controls_by_page.setdefault(int(item["page"]), []).append(item)
        for page_no, png in enumerate(pngs, 1):
            paragraph = doc.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = Pt(1)
            inline = paragraph.add_run().add_picture(
                str(png),
                width=Mm(210),
                height=Mm(297),
            )._inline
            _inline_to_anchor(inline)
            for item in controls_by_page.get(page_no, []):
                raw = _system_value_for_source(str(item["source_text"]), systems)
                if raw is None:
                    continue
                value = _normalize_value(raw, default_color=item.get("color", "#17212B"))
                bbox = [float(number) for number in item["bbox"]]
                background = str(item["background"])
                font_size = float(value["font_size_pt"] or item.get("font_size_pt") or 7.0)
                font_size = _fit_single_line_size(
                    value["value"],
                    max(8.0, bbox[2] - bbox[0]),
                    font_size,
                    bold_font,
                )
                _add_vml_textbox(
                    paragraph,
                    bbox=[bbox[0] - 0.7, bbox[1] - 0.7, bbox[2] + 0.7, bbox[3] + 1.4],
                    background=background,
                    text=value["value"],
                    color=value["color"],
                    font_size=font_size,
                    box_id=f"GENOMA_SYS_{page_no}_{replaced_controls+1}",
                )
                replaced_controls += 1
            for item in fields_by_page.get(page_no, []):
                if item.get("guidance_only"):
                    continue
                raw = _field_value(fields, item)
                if raw is None:
                    unresolved.append(item["field_id"])
                    continue
                background = str(item["background"])
                default_color = "#FFFFFF" if _is_dark(background) else "#17212B"
                value = _normalize_value(raw, default_color=default_color)
                font_size = float(value["font_size_pt"] or item.get("font_size_pt") or 7.0)
                _cover, draw = _replacement_geometry(
                    item,
                    float(meta["page_size_pt"][0]),
                    fields_by_page.get(page_no, []),
                )
                width = max(8.0, draw[2] - draw[0])
                height = max(8.0, draw[3] - draw[1])
                font_size = _fit_single_line_size(
                    value["value"],
                    width,
                    font_size,
                    bold_font,
                    max_height=height,
                )
                _add_vml_textbox(
                    paragraph,
                    bbox=[draw[0], draw[1], draw[0] + width, draw[1] + height],
                    background=background,
                    text=value["value"],
                    color=value["color"],
                    font_size=font_size,
                    box_id=f"GENOMA_FIELD_{page_no}_{replaced_fields+1}",
                )
                replaced_fields += 1
            if page_no < len(pngs):
                page_break = doc.add_paragraph()
                page_break.paragraph_format.space_before = Pt(0)
                page_break.paragraph_format.space_after = Pt(0)
                page_break.add_run().add_break(WD_BREAK.PAGE)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(path)
        _patch_docx_svg(path, svgs)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if strict and unresolved:
        path.unlink(missing_ok=True)
        raise TemplateV3Error(
            f"strict v3 DOCX rendering refused: {len(unresolved)} unresolved fields"
        )
    return {
        "mode": "template-v3-svg-docx",
        "template": template.name,
        "template_sha256": meta["sha256"],
        "template_status": "VERIFICADO",
        "page_count": meta["page_count"],
        "replaced_fields": replaced_fields,
        "replaced_controlled_spans": replaced_controls,
        "unresolved_fields": unresolved,
        "strict": strict,
        "editable_dynamic_fields": True,
        "static_chrome": "SVG page plate generated from the exact v3 reference PDF",
        "pixel_identity_note": "DOCX is renderer-dependent; exact PDF pixel identity is tested separately and must not be inferred from DOCX structure.",
    }


def template_mode_requested(rendered: dict[str, Any]) -> bool:
    data = rendered.get("data") if isinstance(rendered.get("data"), dict) else {}
    return str(
        data.get("editorial_mode") or os.environ.get("GENOMA_EDITORIAL_MODE") or ""
    ).lower() in {"template-v3", "v3-template", "pixel-v3"}


def template_dir_from_environment() -> Path:
    raw = os.environ.get("GENOMA_REPORT_TEMPLATE_DIR")
    if not raw:
        raise TemplateV3Error("GENOMA_REPORT_TEMPLATE_DIR is required for template-v3 mode")
    return Path(raw)


__all__ = [
    "TemplateV3Error",
    "load_reference_manifest",
    "render_docx_from_template",
    "render_pdf_from_template",
    "template_dir_from_environment",
    "template_mode_requested",
    "verify_template_pack",
]
