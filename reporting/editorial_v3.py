from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from .editorial_v3_hifi import DESIGN, write_editorial_bundle as _programmatic_write_editorial_bundle
from . import template_v3 as _template_v3

_TEMPLATE_LOCK = threading.RLock()
_ORIGINAL_LOADER = _template_v3.load_reference_manifest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verified_external_manifest(template_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Load coordinates only from the hash-pinned external v3 template pack.

    The large coordinate inventory is intentionally not stored in the application repository.
    The repository carries only its approved SHA-256 identities. A modified pack fails closed.
    """
    index = json.loads(_template_v3.MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest_meta = index.get("external_coordinate_manifest") or {}
    detail_meta = index.get("external_coordinate_detail") or {}
    manifest_path = template_dir / str(manifest_meta.get("filename") or "")
    detail_path = template_dir / str(detail_meta.get("filename") or "")
    if not manifest_path.is_file() or not detail_path.is_file():
        raise _template_v3.TemplateV3Error("external v3 coordinate manifest/detail is missing from template pack")
    actual_manifest = _sha256(manifest_path)
    actual_detail = _sha256(detail_path)
    if actual_manifest != manifest_meta.get("sha256"):
        raise _template_v3.TemplateV3Error("external v3 coordinate manifest checksum mismatch")
    if actual_detail != detail_meta.get("sha256"):
        raise _template_v3.TemplateV3Error("external v3 coordinate detail checksum mismatch")
    detailed = _ORIGINAL_LOADER(manifest_path)
    return detailed, {
        "manifest": actual_manifest,
        "detail": actual_detail,
    }


def write_editorial_bundle(rendered: dict[str, Any], output_dir: Path, *, stem: str | None = None) -> dict[str, Path]:
    """Route final publishing through the exact v3 template engine when requested.

    Programmatic rendering remains available for development fixtures. Final template-v3
    publishing fails closed if the external reference pack or its coordinate inventory differs
    from the hash-pinned v3.0 reference identities.
    """
    if not _template_v3.template_mode_requested(rendered):
        return _programmatic_write_editorial_bundle(rendered, output_dir, stem=stem)

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = rendered["metadata"]
    stem = stem or f"{metadata['report_id']}-{metadata['slug']}"
    pdf = output_dir / f"{stem}.pdf"
    docx = output_dir / f"{stem}.docx"
    data = rendered.get("data", {}) if isinstance(rendered.get("data"), dict) else {}
    strict = bool(data.get("template_fields_complete"))
    template_dir = _template_v3.template_dir_from_environment()
    detailed_manifest, coordinate_hashes = _verified_external_manifest(template_dir)

    # template_v3's internal helpers call load_reference_manifest() without a path. Bind that
    # call to the already hash-verified external coordinate manifest for the duration of this
    # render. The lock prevents cross-request manifest races in concurrent report generation.
    with _TEMPLATE_LOCK:
        previous_loader = _template_v3.load_reference_manifest
        _template_v3.load_reference_manifest = lambda *args, **kwargs: detailed_manifest
        try:
            pdf_runtime = _template_v3.render_pdf_from_template(rendered, pdf, template_dir, strict=strict)
            docx_runtime = _template_v3.render_docx_from_template(rendered, docx, template_dir, strict=strict)
        finally:
            _template_v3.load_reference_manifest = previous_loader

    runtime = {
        "schema": "genoma-editorial-runtime-v3",
        "report_id": metadata["report_id"],
        "code": metadata["code"],
        "accent": metadata["accent"],
        "mode": "template-v3",
        "pdf": pdf_runtime,
        "docx": docx_runtime,
        "coordinate_manifest_sha256": coordinate_hashes,
        "visual_reference": "GENOMA model suite v3.0",
        "claim_rule": "PDF pixel parity and DOCX visual parity are reported separately; DOCX renderer-dependence is never promoted to pixel-identical without measured evidence.",
    }
    (output_dir / f"{stem}.editorial.json").write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"pdf": pdf, "docx": docx}


__all__ = ["DESIGN", "write_editorial_bundle"]
