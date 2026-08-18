#!/usr/bin/env python3
"""Measure static-pixel preservation of rendered v3 reports against their templates.

The repository carried a stored pixel-QA evidence file but no code that could produce it,
so the PASS it asserted could never be re-derived. This is the missing producer: it renders
each report through the real template-v3 path and compares the raster against the approved
PDF, counting only pixels OUTSIDE the compiled dynamic/control rectangles.

Comparing whole pages would be wrong — placeholders are supposed to change. The contract is
therefore: zero changed pixels outside every declared dynamic/control mask, on every page.

    python3 scripts/run_editorial_pixel_qa.py \
      --template-dir /srv/genoma/templates/v3.0 \
      --output docs/evidence/EDITORIAL_V3_STATIC_PIXEL_QA_200DPI.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.editorial_v3 import _verified_coordinate_manifest
from reporting.engine import render_document
from reporting.provenance import fixture_payload
from reporting.template_v3 import render_pdf_from_template, verify_template_pack

DEFAULT_DPI = 200
# Rasterisation of vector text is not exact at mask edges: a glyph that touches a mask
# boundary can bleed a fraction of a pixel outside it. The contract stays "zero changed
# pixels outside the masks", measured after growing each mask by this many points.
MASK_PADDING_PT = 1.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fixture_payload(report_id: str, detailed: dict[str, Any]) -> dict[str, Any]:
    """A fully-resolved, non-clinical payload: QA measures layout, never interpretation.

    Every value is anchored as `fixture`, so this passes PROVENANCE_GATE without being
    exempt from it, and its status floor stays NÃO DISPONÍVEL.
    """
    meta = detailed["reports"][report_id]
    fields = {
        item["field_id"]: "NÃO DISPONÍVEL"
        for item in meta["fields"]
        if not item.get("guidance_only")
    }
    return fixture_payload(
        case_id="CASE-PIXEL-QA-NO-PERSONAL-DATA",
        report_id=report_id,
        summary="Fixture de QA visual; não representa paciente e não contém interpretação.",
        basis="fixture de QA visual",
        extra={
            "editorial_mode": "template-v3",
            "template_fields_complete": True,
            "template_fields": fields,
        },
    )


def _mask_rects(meta: dict[str, Any], page_number: int) -> list[fitz.Rect]:
    """Every rectangle allowed to differ on this page: placeholders and controlled text."""
    rects: list[fitz.Rect] = []
    for item in meta.get("fields", []):
        if int(item.get("page", 0)) != page_number:
            continue
        for key in ("bbox", "cell_bbox"):
            box = item.get(key)
            if box:
                rects.append(fitz.Rect(*box))
    for span in meta.get("controlled_spans", []):
        if int(span.get("page", 0)) != page_number:
            continue
        box = span.get("bbox")
        if box:
            rects.append(fitz.Rect(*box))
    return rects


def _compare_page(
    reference: fitz.Page, rendered: fitz.Page, masks: list[fitz.Rect], dpi: int
) -> dict[str, Any]:
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    ref_pix = reference.get_pixmap(matrix=matrix, alpha=False)
    out_pix = rendered.get_pixmap(matrix=matrix, alpha=False)
    if (ref_pix.width, ref_pix.height) != (out_pix.width, out_pix.height):
        return {
            "comparable": False,
            "reason": f"raster size differs: {ref_pix.width}x{ref_pix.height} vs {out_pix.width}x{out_pix.height}",
            "outside_changed_pixels": None,
        }

    width, height, n = ref_pix.width, ref_pix.height, ref_pix.n
    ref = ref_pix.samples
    out = out_pix.samples

    masked = bytearray(width * height)
    for rect in masks:
        grown = fitz.Rect(rect) + (-MASK_PADDING_PT, -MASK_PADDING_PT, MASK_PADDING_PT, MASK_PADDING_PT)
        x0 = max(0, int(grown.x0 * scale) - 1)
        y0 = max(0, int(grown.y0 * scale) - 1)
        x1 = min(width, int(grown.x1 * scale) + 2)
        y1 = min(height, int(grown.y1 * scale) + 2)
        for y in range(y0, y1):
            base = y * width
            masked[base + x0 : base + x1] = b"\x01" * max(0, x1 - x0)

    changed = 0
    max_diff = 0
    for index in range(width * height):
        if masked[index]:
            continue
        offset = index * n
        for channel in range(n):
            delta = abs(ref[offset + channel] - out[offset + channel])
            if delta:
                if delta > max_diff:
                    max_diff = delta
                changed += 1
                break
    total_outside = (width * height) - sum(masked)
    return {
        "comparable": True,
        "outside_changed_pixels": changed,
        "max_channel_diff": max_diff,
        "pixels_outside_masks": total_outside,
        "outside_change_fraction": (changed / total_outside) if total_outside else 0.0,
        "raster": {"width": width, "height": height, "dpi": dpi},
        "masks": len(masks),
    }


def run(template_dir: Path, *, dpi: int = DEFAULT_DPI) -> dict[str, Any]:
    pack = verify_template_pack(template_dir)
    detailed, coordinate_hashes = _verified_coordinate_manifest(template_dir)

    reports: dict[str, Any] = {}
    aggregate_changed = 0
    aggregate_pages = 0
    comparable = True

    with tempfile.TemporaryDirectory(prefix="genoma-pixel-qa-") as work:
        for report_id in sorted(detailed["reports"]):
            meta = detailed["reports"][report_id]
            template_pdf = template_dir / meta["filename"]
            rendered_pdf = Path(work) / f"{report_id}.pdf"

            rendered = render_document(report_id, _fixture_payload(report_id, detailed), mode="FINAL")
            render_pdf_from_template(rendered, rendered_pdf, template_dir, strict=True)

            ref_doc = fitz.open(template_pdf)
            out_doc = fitz.open(rendered_pdf)
            pages: list[dict[str, Any]] = []
            report_changed = 0
            report_max = 0
            try:
                if len(ref_doc) != len(out_doc):
                    comparable = False
                    reports[report_id] = {
                        "filename": meta["filename"],
                        "sha256": meta["sha256"],
                        "comparable": False,
                        "reason": f"page count differs: {len(ref_doc)} vs {len(out_doc)}",
                    }
                    continue
                for index in range(len(ref_doc)):
                    result = _compare_page(
                        ref_doc[index], out_doc[index], _mask_rects(meta, index + 1), dpi
                    )
                    result["page"] = index + 1
                    pages.append(result)
                    if not result["comparable"]:
                        comparable = False
                        continue
                    report_changed += result["outside_changed_pixels"]
                    report_max = max(report_max, result["max_channel_diff"])
                    aggregate_pages += 1
            finally:
                ref_doc.close()
                out_doc.close()

            aggregate_changed += report_changed
            reports[report_id] = {
                "filename": meta["filename"],
                "sha256": meta["sha256"],
                "pages": len(pages),
                "qa": {
                    "outside_changed_pixels": report_changed,
                    "max_channel_diff": report_max,
                    "outside_change_fraction": (
                        sum(p.get("outside_change_fraction", 0.0) for p in pages) / len(pages)
                        if pages
                        else 0.0
                    ),
                },
                "page_detail": pages,
            }

    passed = comparable and aggregate_changed == 0
    return {
        "schema": "genoma-editorial-static-pixel-qa-v2",
        "status": "VERIFICADO" if passed else "NÃO DISPONÍVEL",
        "executed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dpi": dpi,
        "mask_padding_pt": MASK_PADDING_PT,
        "comparison_contract": (
            "Original v3.0 PDF is the immutable base; replacement overlays are confined to "
            "compiled dynamic placeholder/control rectangles. Compare raster output outside "
            "all dynamic/control masks. PASS requires exactly zero changed pixels outside "
            "masks on every page."
        ),
        "coordinate_compiler": {
            "name": detailed.get("compiler") or "fitz-1.26.7-genoma-v2",
            "manifest_sha256": coordinate_hashes.get("manifest"),
            "compressed_detail_sha256": coordinate_hashes.get("detail"),
            "field_counts": {
                rid: int(detailed["reports"][rid]["placeholder_count"])
                for rid in sorted(detailed["reports"])
            },
        },
        "template_pack": {"status": pack["status"], "verified_reports": pack["verified_reports"]},
        "aggregate": {
            "reports": len(reports),
            "reference_pages": aggregate_pages,
            "outside_changed_pixels": aggregate_changed,
            "result": "PASS" if passed else "FAIL",
        },
        "reports": reports,
        "limitations": [
            "This proves exact static-pixel preservation outside declared dynamic/control "
            "regions at the stated DPI for the pinned v3.0 PDFs. Dynamic regions are expected "
            "to differ because case data replaces placeholders.",
            "It is a layout control only. It says nothing about scientific correctness, QC or "
            "evidence, and never authorizes POST-DEPLOYMENT.",
            "DOCX renderer parity is a separate control and is not measured here.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-dir", required=True)
    parser.add_argument("--output")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    args = parser.parse_args()

    result = run(Path(args.template_dir), dpi=args.dpi)
    # Page-level detail is useful when investigating a failure but too large for evidence.
    summary = {k: v for k, v in result.items() if k != "reports"}
    summary["reports"] = {
        rid: {k: v for k, v in meta.items() if k != "page_detail"}
        for rid, meta in result["reports"].items()
    }
    payload = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["aggregate"]["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
