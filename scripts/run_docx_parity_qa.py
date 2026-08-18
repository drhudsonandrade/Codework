#!/usr/bin/env python3
"""Measure what the DOCX artifact actually preserves, and refuse to overstate it.

The PDF is the authoritative publication artifact; the DOCX is the editable one. DOCX
rendering is renderer-dependent — Word, LibreOffice and others rasterize differently — so
"pixel-identical" is not a claim this project may make about it. The previous state was
worse than an overclaim, though: there was no measurement at all, only prose.

This measures two separable things and reports them separately:

  * STRUCTURAL parity (gated): the converted DOCX must have exactly the reference page
    count and page geometry. A blank page, a dropped page or a reflow fails here.
  * VISUAL similarity (measured, not gated on equality): the fraction of differing pixels
    and the RMSE against the reference render, recorded as observed values. A ceiling
    catches catastrophic regressions without pretending the residual difference is a defect.

Requires LibreOffice Writer (`soffice`) in the session.

    python3 scripts/run_docx_parity_qa.py \
      --template-dir /srv/genoma/templates/v3.0 \
      --output docs/evidence/EDITORIAL_V3_DOCX_PARITY.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
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
from reporting.template_v3 import render_docx_from_template, verify_template_pack

DEFAULT_DPI = 150
# Derived from measurement, not chosen a priori: the observed renderer difference on the
# approved pack sits near 5-7% of pixels with RMSE around 23. The ceiling exists only to
# catch a catastrophic regression (blank plate, wrong page, lost background), never to
# assert pixel parity — which this project explicitly does not claim for DOCX.
MAX_DIFFERING_FRACTION = 0.25
MAX_RMSE = 60.0
GEOMETRY_TOLERANCE_PT = 1.0


def _soffice() -> str:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise RuntimeError("LibreOffice (soffice) is required for DOCX parity QA")
    return exe


def convert_to_pdf(docx: Path, outdir: Path, profile: Path) -> Path:
    """Convert with an isolated profile so a shared/dirty HOME cannot change the result."""
    outdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(profile / "home"))
    (profile / "home").mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            _soffice(),
            "--headless",
            f"-env:UserInstallation=file://{profile / 'lo'}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(outdir),
            str(docx),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        env=env,
        check=False,
    )
    produced = outdir / f"{docx.stem}.pdf"
    if not produced.is_file():
        raise RuntimeError(
            f"LibreOffice did not produce a PDF for {docx.name}: "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )
    return produced


def _compare(reference: fitz.Document, rendered: fitz.Document, dpi: int) -> dict[str, Any]:
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    pages: list[dict[str, Any]] = []
    worst_fraction = 0.0
    worst_rmse = 0.0
    geometry_ok = True

    for index in range(len(reference)):
        ref_rect = reference[index].rect
        out_rect = rendered[index].rect
        same_geometry = (
            abs(ref_rect.width - out_rect.width) <= GEOMETRY_TOLERANCE_PT
            and abs(ref_rect.height - out_rect.height) <= GEOMETRY_TOLERANCE_PT
        )
        geometry_ok &= same_geometry

        ref_pix = reference[index].get_pixmap(matrix=matrix, alpha=False)
        out_pix = rendered[index].get_pixmap(matrix=matrix, alpha=False)
        if (ref_pix.width, ref_pix.height) != (out_pix.width, out_pix.height):
            pages.append(
                {
                    "page": index + 1,
                    "same_geometry": same_geometry,
                    "comparable": False,
                    "reason": "raster size differs",
                }
            )
            geometry_ok = False
            continue

        total = ref_pix.width * ref_pix.height
        channels = ref_pix.n
        ref, out = ref_pix.samples, out_pix.samples
        differing = 0
        squared = 0
        for pixel in range(total):
            offset = pixel * channels
            delta = max(abs(ref[offset + c] - out[offset + c]) for c in range(channels))
            if delta:
                differing += 1
                squared += delta * delta
        fraction = differing / total if total else 0.0
        rmse = math.sqrt(squared / total) if total else 0.0
        worst_fraction = max(worst_fraction, fraction)
        worst_rmse = max(worst_rmse, rmse)
        pages.append(
            {
                "page": index + 1,
                "comparable": True,
                "same_geometry": same_geometry,
                "reference_size_pt": [round(ref_rect.width, 2), round(ref_rect.height, 2)],
                "rendered_size_pt": [round(out_rect.width, 2), round(out_rect.height, 2)],
                "differing_pixel_fraction": round(fraction, 6),
                "rmse": round(rmse, 3),
            }
        )
    return {
        "pages": pages,
        "geometry_preserved": geometry_ok,
        "worst_differing_pixel_fraction": round(worst_fraction, 6),
        "worst_rmse": round(worst_rmse, 3),
    }


def _fixture(report_id: str, detailed: dict[str, Any]) -> dict[str, Any]:
    """Anchored as `fixture`: parity QA renders a document without claiming a result."""
    meta = detailed["reports"][report_id]
    return fixture_payload(
        case_id="CASE-DOCX-PARITY-NO-PERSONAL-DATA",
        report_id=report_id,
        summary="Fixture de paridade DOCX; não representa paciente.",
        basis="fixture de paridade DOCX",
        extra={
            "editorial_mode": "template-v3",
            "template_fields_complete": True,
            "template_fields": {
                item["field_id"]: "NÃO DISPONÍVEL"
                for item in meta["fields"]
                if not item.get("guidance_only")
            },
        },
    )


def run(template_dir: Path, *, dpi: int = DEFAULT_DPI) -> dict[str, Any]:
    pack = verify_template_pack(template_dir)
    detailed, _ = _verified_coordinate_manifest(template_dir)

    reports: dict[str, Any] = {}
    structural_ok = True
    worst_fraction = 0.0
    worst_rmse = 0.0

    with tempfile.TemporaryDirectory(prefix="genoma-docx-parity-") as work:
        workdir = Path(work)
        profile = workdir / "profile"
        for report_id in sorted(detailed["reports"]):
            meta = detailed["reports"][report_id]
            docx = workdir / f"{report_id}.docx"
            rendered = render_document(report_id, _fixture(report_id, detailed), mode="FINAL")
            render_docx_from_template(rendered, docx, template_dir, strict=True)

            entry: dict[str, Any] = {"filename": meta["filename"], "sha256": meta["sha256"]}
            try:
                converted = convert_to_pdf(docx, workdir / f"out-{report_id}", profile)
            except RuntimeError as exc:
                structural_ok = False
                entry.update({"status": "NÃO DISPONÍVEL", "reason": str(exc)[:300]})
                reports[report_id] = entry
                continue

            reference = fitz.open(template_dir / meta["filename"])
            produced = fitz.open(converted)
            try:
                expected_pages = int(meta["page_count"])
                page_match = len(produced) == expected_pages == len(reference)
                if not page_match:
                    structural_ok = False
                    entry.update(
                        {
                            "status": "NÃO DISPONÍVEL",
                            "reference_pages": len(reference),
                            "rendered_pages": len(produced),
                            "reason": "page count differs from the approved template",
                        }
                    )
                    reports[report_id] = entry
                    continue
                comparison = _compare(reference, produced, dpi)
            finally:
                reference.close()
                produced.close()

            structural_ok &= comparison["geometry_preserved"]
            worst_fraction = max(worst_fraction, comparison["worst_differing_pixel_fraction"])
            worst_rmse = max(worst_rmse, comparison["worst_rmse"])
            entry.update(
                {
                    "status": "VERIFICADO" if comparison["geometry_preserved"] else "NÃO DISPONÍVEL",
                    "pages": len(comparison["pages"]),
                    "structural_parity": {
                        "page_count_matches": True,
                        "geometry_preserved": comparison["geometry_preserved"],
                    },
                    "visual_similarity": {
                        "worst_differing_pixel_fraction": comparison["worst_differing_pixel_fraction"],
                        "worst_rmse": comparison["worst_rmse"],
                    },
                    "page_detail": comparison["pages"],
                }
            )
            reports[report_id] = entry

    within_envelope = worst_fraction <= MAX_DIFFERING_FRACTION and worst_rmse <= MAX_RMSE
    passed = structural_ok and within_envelope
    return {
        "schema": "genoma-editorial-docx-parity-v1",
        "status": "VERIFICADO" if passed else "NÃO DISPONÍVEL",
        "executed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dpi": dpi,
        "renderer": {
            "engine": "LibreOffice Writer (headless)",
            "note": "Renderer-dependent by construction; a different engine will differ.",
        },
        "contract": (
            "Structural parity is gated: the converted DOCX must carry the reference page "
            "count and page geometry. Visual similarity is measured and reported, never "
            "asserted as pixel parity, because DOCX rasterisation is renderer-dependent."
        ),
        "template_pack": {"status": pack["status"], "verified_reports": pack["verified_reports"]},
        "envelope": {
            "max_differing_pixel_fraction": MAX_DIFFERING_FRACTION,
            "max_rmse": MAX_RMSE,
            "purpose": "catch catastrophic regressions only; not a parity claim",
        },
        "aggregate": {
            "reports": len(reports),
            "structural_parity": "PASS" if structural_ok else "FAIL",
            "worst_differing_pixel_fraction": round(worst_fraction, 6),
            "worst_rmse": round(worst_rmse, 3),
            "within_envelope": within_envelope,
            "result": "PASS" if passed else "FAIL",
        },
        "reports": reports,
        "limitations": [
            "DOCX visual output is renderer-dependent. This measures LibreOffice Writer only; "
            "Word or another engine will produce different rasters.",
            "The residual difference is expected and is NOT a defect. It is recorded so a "
            "regression becomes visible, not to claim pixel parity.",
            "The PDF remains the authoritative publication artifact.",
            "This is a layout control. It says nothing about scientific correctness and never "
            "authorizes POST-DEPLOYMENT.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-dir", required=True)
    parser.add_argument("--output")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    args = parser.parse_args()

    result = run(Path(args.template_dir), dpi=args.dpi)
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
