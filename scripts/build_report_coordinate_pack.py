#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import fitz

COMPILER_ID = "fitz-1.26.7-genoma-v2"
TOKEN_RE = re.compile(r"\[\[.*?\]\]", re.S)
CONTROLLED = [
    "MODELO REUTILIZÁVEL v3.0",
    "MODELO EDITÁVEL",
    "NÃO INSERIDOS",
    "MODELO — NÃO É RESULTADO GENÉTICO",
    "MODELO — NÃO É RESULTADO",
    "GENOMA-HUDSON-RULESET-v3.3",
    "MODELO SEM DADOS PESSOAIS",
    "Campos em azul são placeholders obrigatórios ou condicionais; preencher com dado rastreável ou declarar NÃO DISPONÍVEL.",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rgbhex(color: int) -> str:
    return f"#{color & 0xFFFFFF:06X}"


def _spans(page: fitz.Page) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    data = page.get_text("dict", sort=True)
    for bi, block in enumerate(data["blocks"]):
        for li, line in enumerate(block.get("lines", [])):
            for si, span in enumerate(line.get("spans", [])):
                out.append(
                    {
                        "text": span["text"],
                        "bbox": fitz.Rect(span["bbox"]),
                        "size": float(span["size"]),
                        "font": span["font"],
                        "color": int(span["color"]),
                        "block": bi,
                        "line": li,
                        "span": si,
                    }
                )
    return out


def _union(rects: list[fitz.Rect]) -> fitz.Rect:
    return fitz.Rect(
        min(r.x0 for r in rects),
        min(r.y0 for r in rects),
        max(r.x1 for r in rects),
        max(r.y1 for r in rects),
    )


def _background(page: fitz.Page, rect: fitz.Rect) -> str:
    pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False, colorspace=fitz.csRGB)
    points = [
        (rect.x0 - 2, rect.y0 - 2),
        (rect.x1 + 2, rect.y0 - 2),
        (rect.x0 - 2, rect.y1 + 2),
        (rect.x1 + 2, rect.y1 + 2),
        (rect.x0 - 3, (rect.y0 + rect.y1) / 2),
        (rect.x1 + 3, (rect.y0 + rect.y1) / 2),
    ]
    values: list[tuple[int, int, int]] = []
    for x, y in points:
        xi = max(0, min(pix.width - 1, int(round(x))))
        yi = max(0, min(pix.height - 1, int(round(y))))
        offset = (yi * pix.width + xi) * pix.n
        values.append(tuple(pix.samples[offset : offset + 3]))  # type: ignore[arg-type]
    r, g, b = Counter(values).most_common(1)[0][0]
    return f"#{r:02X}{g:02X}{b:02X}"


def _cell(page: fitz.Page, rect: fitz.Rect) -> list[float] | None:
    center = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    candidates: list[fitz.Rect] = []
    for drawing in page.get_drawings():
        candidate = drawing.get("rect")
        if not candidate:
            continue
        if (
            candidate.contains(center)
            and candidate.width >= rect.width + 2
            and candidate.height >= rect.height + 2
            and candidate.width < page.rect.width * 0.98
            and candidate.height < 180
        ):
            candidates.append(candidate)
    if not candidates:
        return None
    best = min(candidates, key=lambda r: r.width * r.height)
    return [round(best.x0, 3), round(best.y0, 3), round(best.x1, 3), round(best.y1, 3)]


def _tokens(page: fitz.Page) -> list[tuple[str, fitz.Rect, dict[str, Any]]]:
    spans = _spans(page)
    text = ""
    owners: list[int | None] = []
    for index, span in enumerate(spans):
        if text:
            text += "\n"
            owners.append(None)
        text += span["text"]
        owners.extend([index] * len(span["text"]))
    found: list[tuple[str, fitz.Rect, dict[str, Any]]] = []
    for match in TOKEN_RE.finditer(text):
        token = re.sub(r"\s+", "", match.group(0))
        indices = sorted(
            {
                owners[pos]
                for pos in range(match.start(), match.end())
                if owners[pos] is not None
            }
        )
        if not indices:
            continue
        rect = _union([spans[int(i)]["bbox"] for i in indices])
        found.append((token, rect, spans[int(indices[0])]))
    return found


def _controls(page: fitz.Page) -> list[tuple[str, fitz.Rect, dict[str, Any]]]:
    spans = _spans(page)
    result: list[tuple[str, fitz.Rect, dict[str, Any]]] = []
    for source in CONTROLLED:
        for rect in page.search_for(source):
            first = next((s for s in spans if (s["bbox"] & rect).get_area() > 0), None)
            result.append((source, rect, first or {"size": 7.0, "font": "DejaVuSans", "color": 0}))
    return result


def compile_pack(template_dir: Path, reference_index: Path) -> dict[str, Any]:
    index = json.loads(reference_index.read_text(encoding="utf-8"))
    reports: dict[str, Any] = {}
    for report_id in sorted(index["reports"]):
        expected = index["reports"][report_id]
        source = template_dir / expected["filename"]
        if not source.is_file():
            raise RuntimeError(f"missing v3 reference PDF: {source}")
        actual = _sha256(source)
        if actual != expected["sha256"]:
            raise RuntimeError(f"reference PDF SHA-256 mismatch for {report_id}: {actual}")
        doc = fitz.open(source)
        if len(doc) != int(expected["page_count"]):
            raise RuntimeError(f"reference PDF page-count mismatch for {report_id}")
        occurrence: dict[str, int] = {}
        fields: list[dict[str, Any]] = []
        controls: list[dict[str, Any]] = []
        for page_number, page in enumerate(doc, 1):
            for token, rect, span in _tokens(page):
                occurrence[token] = occurrence.get(token, 0) + 1
                fields.append(
                    {
                        "field_id": f"{report_id}:P{page_number:02d}:{token[2:-2]}:{occurrence[token]:03d}",
                        "token": token,
                        "occurrence": occurrence[token],
                        "page": page_number,
                        "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
                        "cell_bbox": _cell(page, rect),
                        "font_size_pt": round(float(span["size"]), 3),
                        "font": span["font"],
                        "color": _rgbhex(int(span["color"])),
                        "background": _background(page, rect),
                        "guidance_only": token == "[[CAMPO]]",
                    }
                )
            for source_text, rect, span in _controls(page):
                controls.append(
                    {
                        "source_text": source_text,
                        "page": page_number,
                        "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
                        "font_size_pt": round(float(span["size"]), 3),
                        "font": span["font"],
                        "color": _rgbhex(int(span["color"])),
                        "background": _background(page, rect),
                    }
                )
        if len(fields) != int(expected["placeholder_count"]):
            raise RuntimeError(
                f"placeholder inventory mismatch for {report_id}: {len(fields)} != {expected['placeholder_count']}"
            )
        reports[report_id] = {
            **{k: expected[k] for k in ("filename", "sha256", "size_bytes", "page_count", "page_size_pt", "placeholder_count")},
            "fields": fields,
            "controlled_spans": controls,
        }
    return {
        "schema": "genoma-editorial-v3-reference-manifest-v2",
        "reference_suite": "GENOMA v3.0",
        "coordinate_compiler": COMPILER_ID,
        "reports": reports,
    }


def write_pack(payload: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / "GENOMA_V3_TEMPLATE_MANIFEST.v2.json"
    detail = output_dir / "reference_v3_manifest.v2.json.gz.b64"
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    manifest.write_bytes(raw)
    compressed = gzip.compress(raw, mtime=0)
    detail.write_text(base64.b64encode(compressed).decode("ascii") + "\n", encoding="ascii")
    return {
        "schema": "genoma-editorial-coordinate-build-v2",
        "status": "VERIFICADO",
        "compiler": COMPILER_ID,
        "manifest": {"path": str(manifest), "sha256": _sha256(manifest), "size_bytes": manifest.stat().st_size},
        "detail": {"path": str(detail), "sha256": _sha256(detail), "size_bytes": detail.stat().st_size},
        "reports": len(payload["reports"]),
        "pages": sum(int(x["page_count"]) for x in payload["reports"].values()),
        "placeholders": sum(len(x["fields"]) for x in payload["reports"].values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-dir", required=True)
    parser.add_argument("--reference-index", default="reporting/reference_v3_manifest.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--evidence")
    args = parser.parse_args()
    result = write_pack(
        compile_pack(Path(args.template_dir), Path(args.reference_index)),
        Path(args.output_dir),
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        path = Path(args.evidence)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
