from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from .editorial_v3_hifi import DESIGN, write_editorial_bundle as _programmatic_write_editorial_bundle
from . import template_v3 as _template_v3
from .post_render_provenance import bind_execution_manifest_updates
from .provenance import provenance_blockers

_TEMPLATE_LOCK = threading.RLock()
_ORIGINAL_LOADER = _template_v3.load_reference_manifest


def _sha256(path: Path) -> str:
    """SHA-256 of a file, read in chunks so a large template is not held in memory."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verified_coordinate_manifest(
    template_dir: Path,
) -> tuple[dict[str, Any], dict[str, str | bool]]:
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
        manifest_bytes = manifest_path.read_bytes()
        actual_manifest = hashlib.sha256(manifest_bytes).hexdigest()
        if actual_manifest != manifest_meta.get("sha256"):
            raise _template_v3.TemplateV3Error(f"{mode} v3 coordinate manifest checksum mismatch")
        # The detail is verified by decoded content because DEFLATE bytes are not
        # reproducible across zlib builds. Every subsequent check uses this same immutable
        # byte capture, so the accepted hash, decoded detail and loaded inventory cannot
        # describe different filesystem reads.
        detail_result = _template_v3.verify_coordinate_detail(
            detail_path, detail_meta, manifest_bytes
        )
        # `content_sha256` is the SHA-256 of the *decoded* detail, and the decode is accepted
        # only when it equals `manifest_bytes`, so that value is always the manifest's hash.
        # Preferring it wrote `coordinate_manifest_sha256 = {"manifest": X, "detail": X}` — the
        # detail field stopped identifying the installed detail file at all. The container
        # hash is the artifact's identity; the content hash stays proof of the binding.
        actual_detail = detail_result["container_sha256"]
        try:
            detailed = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _template_v3.TemplateV3Error(
                f"{mode} v3 coordinate manifest is not valid UTF-8 JSON"
            ) from exc
        if mode == "external":
            if detailed.get("schema") != "genoma-editorial-v3-reference-manifest-v1":
                raise _template_v3.TemplateV3Error("external v3 coordinate schema mismatch")
            if set(detailed.get("reports", {})) != {f"{i:02d}" for i in range(1, 12)}:
                raise _template_v3.TemplateV3Error("external v3 coordinate report set mismatch")
            for rid, report in detailed["reports"].items():
                if not isinstance(report, dict):
                    raise _template_v3.TemplateV3Error(
                        f"invalid external v3 coordinate report metadata: {rid}"
                    )
                _template_v3._validate_page_size_pt(rid, report)
            _template_v3._validate_controlled_span_sources(detailed)
        else:
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
            # Whether the installed container is byte-identical to the pinned one.
            #
            # This is NOT the integrity control, and restoring a block here would be wrong:
            # DEFLATE bytes are not reproducible across zlib builds, so a legitimate install
            # can differ while carrying identical content. The content *is* pinned —
            # `verify_coordinate_detail` raises unless the decoded bytes equal
            # `manifest_bytes`, whose SHA-256 was already checked against the pinned manifest
            # hash a few lines above — so substituted content cannot reach here.
            #
            # It is published because a mismatch still means the installed artifact is not
            # the historical one, which an auditor should be able to see. Computing it and
            # dropping it made that fact unavailable to everyone downstream.
            "detail_container_matches_pinned": detail_result["container_sha256_matches_pinned"],
        }
    raise _template_v3.TemplateV3Error(
        "no approved v3 coordinate pair is installed; run scripts/install_report_templates.py on the exact template pack (" + ",".join(errors) + ")"
    )


class UnapprovedRendererError(RuntimeError):
    """A FINAL report was about to be produced without the approved v3.0 template pack."""


#: Written into the Execution Manifest, and read back to recognise an already-disclosed
#: payload. One constant so the writer and the recogniser cannot drift.
_PROGRAMMATIC_RENDERER = "aproximação programática (fora do pacote de modelos aprovado)"


def _assert_final_provenance(rendered: dict[str, Any]) -> None:
    """Fail closed if FINAL data drifted after the original publication gate.

    The initial gate runs inside ``render_document``. Editorial preparation may legitimately
    add renderer-disclosure keys afterwards, and callers may also accidentally mutate the
    payload between preparation and a writer. Every FINAL serialization boundary therefore
    checks the current data again. The import is local to avoid the engine/editorial cycle.
    """
    metadata = rendered.get("metadata") if isinstance(rendered.get("metadata"), dict) else {}
    if str(metadata.get("mode", "")).upper() != "FINAL":
        return
    data = rendered.get("data") if isinstance(rendered.get("data"), dict) else {}
    blockers = provenance_blockers(data)
    if blockers:
        from .engine import ReportReleaseError

        raise ReportReleaseError(
            "post-render provenance gate failed: " + ", ".join(blockers)
        )


def _disclose_programmatic_render(
    rendered: dict[str, Any], *, final_authorization: str | None = None
) -> dict[str, Any]:
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

    final_mode = str(metadata.get("mode", "")).upper() == "FINAL"

    # Both `generate_report.py` and `write_editorial_bundle` call `prepare_editorial_render`,
    # so the same payload reaches this function twice. The second call does not receive the
    # caller's `programmatic_final_authorization`, which made an authorized FINAL render fail
    # with UnapprovedRendererError on the way to disk. Disclosure is therefore idempotent —
    # but only over a payload that is *completely* disclosed: in FINAL mode the recorded
    # authorization must already be there, so a caller cannot skip the gate by pre-setting
    # the RENDERER marker on a payload it supplies.
    existing = data.get("execution_manifest")
    if isinstance(existing, dict) and existing.get("RENDERER") == _PROGRAMMATIC_RENDERER:
        recorded = existing.get("PROGRAMMATIC_FINAL_AUTHORIZATION")
        if not final_mode or (isinstance(recorded, str) and recorded.strip()):
            _assert_final_provenance(disclosed)
            return disclosed
    if final_mode and (
        not isinstance(final_authorization, str) or not final_authorization.strip()
    ):
        raise UnapprovedRendererError(
            "FINAL publishing requires the approved v3.0 template pack. Install it and set "
            "editorial_mode='template-v3' with GENOMA_REPORT_TEMPLATE_DIR, or pass an explicit "
            "programmatic_final_authorization to the publisher for a disclosed QA artifact."
        )

    updates: dict[str, Any] = {
        "RENDERER": _PROGRAMMATIC_RENDERER,
        "TEMPLATE_PACK_V3": "NÃO DISPONÍVEL",
        "PARIDADE_VISUAL": "NÃO DISPONÍVEL",
    }
    if final_mode:
        updates["PROGRAMMATIC_FINAL_AUTHORIZATION"] = final_authorization.strip()
        data = bind_execution_manifest_updates(
            data,
            updates,
            basis=(
                "disclosure recorded by reporting.editorial_v3 after the initial publication "
                "gate; values describe renderer/run context, not a genomic measurement"
            ),
        )
    else:
        # MODEL has no clinical provenance contract because it is explicitly not a result.
        # Preserve the visible renderer disclosure without fabricating anchors for a payload
        # that was never compiled as FINAL.
        manifest = data.get("execution_manifest")
        if not isinstance(manifest, dict):
            manifest = {"status": str(manifest) if manifest else "NÃO DISPONÍVEL"}
        manifest.update(updates)
        data["execution_manifest"] = manifest
    disclosed["data"] = data

    # `render_document` built `markdown` and `html` from `data` before this function ran, and
    # this function only edits `data`. `write_bundle` then wrote the updated data into the
    # JSON while writing the *pre-disclosure* Markdown and HTML — so an authorized
    # programmatic FINAL bundle declared RENDERER and PROGRAMMATIC_FINAL_AUTHORIZATION in the
    # JSON, and the two artifacts a reader actually opens said nothing about the
    # approximation. The derived views are rebuilt from the disclosed payload so all three
    # agree.
    _rerender_derived_views(disclosed)
    _assert_final_provenance(disclosed)
    return disclosed


def _rerender_derived_views(disclosed: dict[str, Any]) -> None:
    """Rebuild `markdown`/`html` from the disclosed data, in place.

    Imported here rather than at module scope: `reporting.engine` imports this module, so a
    top-level import would close the cycle.
    """
    from . import engine as _engine

    metadata = disclosed.get("metadata")
    if not isinstance(metadata, dict) or "markdown" not in disclosed:
        return
    report_id = str(metadata.get("report_id") or "")
    catalog = _engine.load_catalog()
    model = catalog.get(report_id)
    if model is None:
        return
    if str(metadata.get("mode", "")).upper() == "FINAL":
        markdown = _engine._final_markdown(report_id, model, disclosed["data"])
    else:
        markdown = _engine._model_markdown(report_id, model)
    disclosed["markdown"] = markdown
    disclosed["html"] = _engine._to_html(markdown, model["title"])


def prepare_editorial_render(
    rendered: dict[str, Any], *, programmatic_final_authorization: str | None = None
) -> dict[str, Any]:
    """Return the single payload all output writers must serialize."""
    if _template_v3.template_mode_requested(rendered):
        _assert_final_provenance(rendered)
        return rendered
    prepared = _disclose_programmatic_render(
        rendered, final_authorization=programmatic_final_authorization
    )
    _assert_final_provenance(prepared)
    return prepared


def write_editorial_bundle(
    rendered: dict[str, Any],
    output_dir: Path,
    *,
    stem: str | None = None,
    programmatic_final_authorization: str | None = None,
) -> dict[str, Path]:
    """Route final publishing through the exact v3 template engine when requested.

    Programmatic rendering remains available for development fixtures and is disclosed in
    the artifact it produces. Final template-v3 publishing fails closed if the reference
    PDF or coordinate inventory differs from its pinned identity.
    """
    if not _template_v3.template_mode_requested(rendered):
        prepared = prepare_editorial_render(
            rendered,
            programmatic_final_authorization=programmatic_final_authorization,
        )
        _assert_final_provenance(prepared)
        return _programmatic_write_editorial_bundle(
            prepared,
            output_dir,
            stem=stem,
        )

    # Validate before creating even the output directory. A FINAL payload that drifted after
    # render must leave no partial PDF/DOCX/editorial JSON behind.
    _assert_final_provenance(rendered)
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


__all__ = ["DESIGN", "prepare_editorial_render", "write_editorial_bundle"]
