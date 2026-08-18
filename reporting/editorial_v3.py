from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
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


def _verified_coordinate_manifest(template_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Load coordinates only from a hash-pinned v3 coordinate pair.

    Prefer the historical approved external pair when installed. Otherwise accept the v2
    pair produced deterministically from the exact hash-pinned v3.0 PDFs, but only if both
    generated artifacts match the SHA-256 identities carried by the repository index.
    """
    index = json.loads(_template_v3.MANIFEST_PATH.read_text(encoding="utf-8"))
    pairs = (
        ("external", index.get("external_coordinate_manifest") or {}, index.get("external_coordinate_detail") or {}),
        ("generated", index.get("generated_coordinate_manifest") or {}, index.get("generated_coordinate_detail") or {}),
    )
    errors: list[str] = []
    for mode, manifest_meta, detail_meta in pairs:
        manifest_path = template_dir / str(manifest_meta.get("filename") or "")
        detail_path = template_dir / str(detail_meta.get("filename") or "")
        if not manifest_path.is_file() or not detail_path.is_file():
            errors.append(f"{mode}:missing")
            continue
        actual_manifest = _sha256(manifest_path)
        actual_detail = _sha256(detail_path)
        if actual_manifest != manifest_meta.get("sha256") or actual_detail != detail_meta.get("sha256"):
            raise _template_v3.TemplateV3Error(f"{mode} v3 coordinate checksum mismatch")
        if mode == "external":
            detailed = _ORIGINAL_LOADER(manifest_path)
        else:
            detailed = json.loads(manifest_path.read_text(encoding="utf-8"))
            if detailed.get("schema") != "genoma-editorial-v3-reference-manifest-v2":
                raise _template_v3.TemplateV3Error("generated v3 coordinate schema mismatch")
            if set(detailed.get("reports", {})) != {f"{i:02d}" for i in range(1, 12)}:
                raise _template_v3.TemplateV3Error("generated v3 coordinate report set mismatch")
            for rid, summary in index["reports"].items():
                detail = detailed["reports"][rid]
                for key in ("filename", "sha256", "page_count", "placeholder_count"):
                    if detail.get(key) != summary.get(key):
                        raise _template_v3.TemplateV3Error(f"generated coordinate/index mismatch: {rid}:{key}")
        return detailed, {
            "mode": mode,
            "manifest": actual_manifest,
            "detail": actual_detail,
        }
    raise _template_v3.TemplateV3Error(
        "no approved v3 coordinate pair is installed; run scripts/install_report_templates.py on the exact template pack (" + ",".join(errors) + ")"
    )


class UnapprovedRendererError(RuntimeError):
    """A FINAL report was about to be produced without the approved v3.0 template pack."""


def _disclose_programmatic_render(rendered: dict[str, Any]) -> dict[str, Any]:
    """Make the fallback renderer visible in the document it produces.

    The programmatic renderer never opens an approved v3.0 template; it reconstructs a
    similar layout. Emitting that output with the same provenance as a template render
    would leave a reader unable to tell which one they are holding, so the distinction is
    written into the Execution Manifest that the page itself prints. A FINAL report must
    additionally opt in, because a fallback layout is a development affordance, not an
    approved publication path.
    """
    disclosed = deepcopy(rendered)
    metadata = disclosed.get("metadata") if isinstance(disclosed.get("metadata"), dict) else {}
    data = disclosed.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        disclosed["data"] = data

    if str(metadata.get("mode", "")).upper() == "FINAL" and data.get("allow_programmatic_final") is not True:
        raise UnapprovedRendererError(
            "FINAL publishing requires the approved v3.0 template pack. Install it and set "
            "editorial_mode='template-v3' with GENOMA_REPORT_TEMPLATE_DIR, or set "
            "allow_programmatic_final=True to acknowledge a non-approved programmatic render."
        )

    manifest = data.get("execution_manifest")
    if not isinstance(manifest, dict):
        manifest = {"status": str(manifest) if manifest else "NÃO DISPONÍVEL"}
    manifest["RENDERER"] = "aproximação programática (fora do pacote de modelos aprovado)"
    manifest["TEMPLATE_PACK_V3"] = "NÃO DISPONÍVEL"
    manifest["PARIDADE_VISUAL"] = "NÃO DISPONÍVEL"
    data["execution_manifest"] = manifest

    notice = (
        "RENDERIZAÇÃO PROGRAMÁTICA — este documento NÃO foi gerado a partir do pacote de "
        "modelos v3.0 aprovado; a paridade visual com o modelo oficial é NÃO DISPONÍVEL."
    )
    existing = data.get("limitations")
    data["limitations"] = f"{notice} {existing}".strip() if existing else notice
    return disclosed


def write_editorial_bundle(rendered: dict[str, Any], output_dir: Path, *, stem: str | None = None) -> dict[str, Path]:
    """Route final publishing through the exact v3 template engine when requested.

    Programmatic rendering remains available for development fixtures and is disclosed in
    the artifact it produces. Final template-v3 publishing fails closed if the reference
    PDF or coordinate inventory differs from its pinned identity.
    """
    if not _template_v3.template_mode_requested(rendered):
        return _programmatic_write_editorial_bundle(
            _disclose_programmatic_render(rendered), output_dir, stem=stem
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = rendered["metadata"]
    stem = stem or f"{metadata['report_id']}-{metadata['slug']}"
    pdf = output_dir / f"{stem}.pdf"
    docx = output_dir / f"{stem}.docx"
    data = rendered.get("data", {}) if isinstance(rendered.get("data"), dict) else {}
    strict = bool(data.get("template_fields_complete"))
    template_dir = _template_v3.template_dir_from_environment()
    detailed_manifest, coordinate_hashes = _verified_coordinate_manifest(template_dir)

    # Internal template helpers call load_reference_manifest() without a path. Bind that call
    # to the already hash-verified coordinate inventory for the duration of this render.
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
        "claim_rule": "PDF static-pixel parity and DOCX visual parity are reported separately; DOCX renderer-dependence is never promoted to pixel-identical without measured evidence.",
    }
    (output_dir / f"{stem}.editorial.json").write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"pdf": pdf, "docx": docx}


__all__ = ["DESIGN", "write_editorial_bundle"]
