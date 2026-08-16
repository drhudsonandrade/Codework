from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .editorial_v3_hifi import DESIGN, write_editorial_bundle as _programmatic_write_editorial_bundle
from .template_v3 import (
    render_docx_from_template,
    render_pdf_from_template,
    template_dir_from_environment,
    template_mode_requested,
)


def write_editorial_bundle(rendered: dict[str, Any], output_dir: Path, *, stem: str | None = None) -> dict[str, Path]:
    """Route final publishing through the exact v3 template engine when requested.

    The existing programmatic renderer remains available for development/model fixtures.
    Template-v3 fails closed if the approved external template pack is absent or mismatched.
    """
    if not template_mode_requested(rendered):
        return _programmatic_write_editorial_bundle(rendered, output_dir, stem=stem)

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = rendered["metadata"]
    stem = stem or f"{metadata['report_id']}-{metadata['slug']}"
    pdf = output_dir / f"{stem}.pdf"
    docx = output_dir / f"{stem}.docx"
    data = rendered.get("data", {}) if isinstance(rendered.get("data"), dict) else {}
    strict = bool(data.get("template_fields_complete"))
    template_dir = template_dir_from_environment()
    pdf_runtime = render_pdf_from_template(rendered, pdf, template_dir, strict=strict)
    docx_runtime = render_docx_from_template(rendered, docx, template_dir, strict=strict)
    runtime = {
        "schema": "genoma-editorial-runtime-v2",
        "report_id": metadata["report_id"],
        "code": metadata["code"],
        "accent": metadata["accent"],
        "mode": "template-v3",
        "pdf": pdf_runtime,
        "docx": docx_runtime,
        "visual_reference": "GENOMA model suite v3.0",
        "claim_rule": "PDF pixel parity and DOCX visual parity are reported separately; DOCX renderer-dependence is never promoted to pixel-identical without measured evidence.",
    }
    (output_dir / f"{stem}.editorial.json").write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"pdf": pdf, "docx": docx}


__all__ = ["DESIGN", "write_editorial_bundle"]
