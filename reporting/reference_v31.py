from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import template_v3

INDEX_PATH = Path(__file__).with_name("reference_v3_manifest.json")


class ReferenceV31Error(RuntimeError):
    pass


def _validate_identity(index: dict[str, Any], payload: dict[str, Any]) -> None:
    if payload.get("schema") != index.get("schema"):
        raise ReferenceV31Error("rebuilt v3.1 coordinate manifest schema mismatch")
    if payload.get("reference_suite") != "GENOMA v3.1":
        raise ReferenceV31Error("rebuilt coordinate manifest is not GENOMA v3.1")
    reports = payload.get("reports")
    index_reports = index.get("reports")
    if not isinstance(reports, dict) or not isinstance(index_reports, dict) or set(reports) != set(index_reports):
        raise ReferenceV31Error("rebuilt v3.1 coordinate report set mismatch")
    for rid, summary in index_reports.items():
        detail = reports[rid]
        for key in ("filename", "sha256", "page_count", "placeholder_count"):
            if detail.get(key) != summary.get(key):
                raise ReferenceV31Error(f"rebuilt v3.1 coordinate identity mismatch: {rid}:{key}")


def load_verified_reference(template_dir: Path) -> dict[str, Any]:
    """Load the pinned coordinate manifest, or deterministically rebuild it fail-closed.

    The rebuilt payload is accepted only when the exact encoded SHA-256 matches the
    immutable digest stored in the reviewable v3.1 index. No generated coordinates are
    trusted merely because compilation completed.
    """
    try:
        return template_v3.load_reference_manifest(INDEX_PATH)
    except template_v3.TemplateV3Error as original:
        if "compressed reference detail missing" not in str(original):
            raise ReferenceV31Error(str(original)) from original

    from scripts.build_report_coordinate_pack import compile_pack, encode_pack

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    payload = compile_pack(template_dir, INDEX_PATH)
    _validate_identity(index, payload)
    encoded = encode_pack(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    expected = str(index.get("compressed_detail_sha256") or "")
    if digest != expected:
        raise ReferenceV31Error(
            f"deterministically rebuilt v3.1 coordinate pack SHA-256 mismatch: {digest} != {expected}"
        )
    return payload
