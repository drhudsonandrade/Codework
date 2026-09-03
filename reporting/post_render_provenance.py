"""Provenance binding for legitimate mutations performed after the initial render gate.

FINAL report data is compiled with one anchor per printed execution-manifest key. Editorial
preparation is allowed to add renderer-disclosure keys, but those additions happen after the
initial publication gate. This module makes that narrow mutation explicit: it first proves the
incoming payload is still valid, adds the values and matching case-control anchors together,
rebuilds the provenance digest/floor/distribution, and proves the resulting payload again.

There is intentionally no generic "repair provenance" API here. Only execution-manifest
updates supplied by the renderer are supported; arbitrary scientific or clinical payload
changes must go back through the normal compiler and source artifacts.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Mapping

from reporting.provenance import (
    Anchor,
    _anchor_name_for_execution_manifest,
    provenance_block,
    provenance_blockers,
    render_value,
)


class PostRenderProvenanceError(RuntimeError):
    """A post-render mutation could not be proven safe for publication."""


def _anchors_from_block(block: dict[str, Any]) -> dict[str, Anchor]:
    """Rehydrate the already-validated provenance fields so the block can be rebuilt."""
    fields = block.get("fields")
    if not isinstance(fields, dict):
        raise PostRenderProvenanceError("provenance fields are unavailable after validation")
    anchors: dict[str, Anchor] = {}
    for name, raw in fields.items():
        if not isinstance(raw, dict):
            raise PostRenderProvenanceError(f"malformed provenance anchor: {name}")
        try:
            anchors[str(name)] = Anchor(
                kind=str(raw["kind"]),
                artifact=str(raw["artifact"]),
                artifact_sha256=str(raw["artifact_sha256"]),
                locator=str(raw["locator"]),
                observed_value=str(raw["observed_value"]),
                operational_status=str(raw["operational_status"]),
                basis=str(raw["basis"]),
            )
        except KeyError as exc:
            raise PostRenderProvenanceError(
                f"malformed provenance anchor {name}: missing {exc.args[0]}"
            ) from exc
    return anchors


def bind_execution_manifest_updates(
    data: dict[str, Any],
    updates: Mapping[str, Any],
    *,
    basis: str,
) -> dict[str, Any]:
    """Return data with renderer manifest updates and matching provenance anchors.

    The operation is fail-closed in both directions. A pre-existing mismatch is never
    "healed" by rebuilding the block, and a mistake in the newly constructed anchors is
    caught before the caller receives the updated payload.
    """
    before = provenance_blockers(data)
    if before:
        raise PostRenderProvenanceError(
            "pre-render provenance gate failed: " + ", ".join(before)
        )
    if not isinstance(updates, Mapping) or not updates:
        return deepcopy(data)
    if not str(basis).strip():
        raise PostRenderProvenanceError("post-render provenance basis is required")

    updated = deepcopy(data)
    manifest = updated.get("execution_manifest")
    if not isinstance(manifest, dict):
        manifest = {"status": str(manifest) if manifest else "NÃO DISPONÍVEL"}
    else:
        manifest = dict(manifest)

    block = updated.get("provenance")
    if not isinstance(block, dict):
        raise PostRenderProvenanceError("FINAL payload has no provenance block")
    anchors = _anchors_from_block(block)

    for raw_key, value in updates.items():
        key = str(raw_key)
        if not key:
            raise PostRenderProvenanceError("execution-manifest keys may not be empty")
        manifest[key] = value
        rendered = render_value(value)
        anchor_name = _anchor_name_for_execution_manifest(key)
        anchors[anchor_name] = Anchor(
            kind="case_control",
            artifact="case_control",
            artifact_sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            locator=anchor_name,
            observed_value=rendered,
            operational_status="VERIFICADO",
            basis=basis,
        )

    updated["execution_manifest"] = manifest
    updated["provenance"] = provenance_block(anchors)

    after = provenance_blockers(updated)
    if after:
        raise PostRenderProvenanceError(
            "post-render provenance gate failed: " + ", ".join(after)
        )
    return updated


__all__ = [
    "PostRenderProvenanceError",
    "bind_execution_manifest_updates",
]
