#!/usr/bin/env python3
"""Render compiled payloads into the sealed v3.0 template PDFs.

Calling `render_pdf_from_template` directly used to produce the *blank model* whenever the
manifest in play carried no field coordinates — a document that looked like a finished
report and contained nothing measured — and `strict=True` did not object, because its only
test was "no field failed to resolve", which an empty field list satisfies vacuously.

That is fixed in the renderer. This script is the supported entry point: it loads the
verified coordinate manifest, fills the placeholders from the compiled payload through
`reporting.template_fill`, and refuses to publish a report where nothing was derived.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.editorial_v3 import _verified_coordinate_manifest
from reporting.engine import render_document
from reporting.template_fill import build_template_fields
from reporting.template_v3 import TemplateV3Error, render_pdf_from_template
import reporting.template_v3 as _template_v3


def render(report_id: str, payload_path: Path, template_dir: Path, out_path: Path) -> dict:
    detailed, coordinate_hashes = _verified_coordinate_manifest(template_dir)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    fill = build_template_fields(report_id, payload, detailed)
    if not fill["derived_count"]:
        raise TemplateV3Error(
            f"report {report_id}: no placeholder could be derived from the payload; "
            "publishing would emit the blank model"
        )

    payload = dict(payload)
    payload["editorial_mode"] = "template-v3"
    payload["template_fields"] = fill["fields"]
    payload["template_fields_complete"] = fill["unavailable_count"] == 0

    rendered = render_document(report_id, payload, mode="FINAL")

    # The detailed manifest carries the coordinates; the module-level loader returns identity
    # only. `editorial_v3` swaps it the same way for the same reason.
    original = _template_v3.load_reference_manifest
    _template_v3.load_reference_manifest = lambda *a, **k: detailed
    try:
        result = render_pdf_from_template(rendered, out_path, template_dir, strict=True)
    finally:
        _template_v3.load_reference_manifest = original

    return {
        "report_id": report_id,
        "pdf": str(out_path),
        "size_bytes": out_path.stat().st_size,
        "page_count": result.get("page_count"),
        "replaced_fields": result.get("replaced_fields"),
        "redacted_placeholder_boxes": result.get("redacted_placeholder_boxes"),
        "template_sha256": result.get("template_sha256"),
        "coordinate_manifest_sha256": coordinate_hashes,
        "derived_placeholders": fill["derived_count"],
        "unavailable_placeholders": fill["unavailable_count"],
        "total_placeholders": fill["total"],
        "derived_tokens": fill["derived_tokens"],
        "operational_status": payload.get("operational_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-dir", required=True, help="installed template pack")
    parser.add_argument("--payload", action="append", required=True, metavar="ID=PATH")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in args.payload:
        report_id, _, path = spec.partition("=")
        results.append(
            render(report_id, Path(path), Path(args.template_dir), out_dir / f"GENOMA-{report_id}.pdf")
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
