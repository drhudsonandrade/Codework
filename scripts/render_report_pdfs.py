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

from reporting.case_dossier import load_dossier
from reporting.editorial_v3 import _verified_coordinate_manifest
from reporting.engine import _stamp_ruleset_into_manifest, render_document, sha256_path
from reporting.template_fill import build_template_fields
from reporting.template_v3 import TemplateV3Error, render_pdf_from_template
import reporting.template_v3 as _template_v3


# Report 11 documents the template suite itself, not a person, and carries a fixed sentinel
# in place of a case identifier. Binding a dossier to it fails by construction — which
# blocked its PDF in every orchestrated run that supplied one, the same way report 05 was
# blocked by an unpassed argument.
#
# Both halves are required and both are closed literals: a payload has to be report 11 *and*
# carry the sentinel to skip the binding. Nothing here lets a payload declare itself
# case-free, so a real case report with the wrong case_id is still refused.
SUITE_LEVEL_CASE_ID = "SUITE-EDITORIAL"
SUITE_LEVEL_REPORTS = frozenset({"11"})


def is_suite_level(report_id: str, payload: dict) -> bool:
    return report_id in SUITE_LEVEL_REPORTS and payload.get("case_id") == SUITE_LEVEL_CASE_ID


def render(
    report_id: str,
    payload_path: Path,
    template_dir: Path,
    out_path: Path,
    dossier_path: Path | None = None,
) -> dict:
    detailed, coordinate_hashes = _verified_coordinate_manifest(template_dir)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    # Stamped before the fill, not after. `render_document` adds the governing ruleset to
    # the execution manifest on its way to FINAL, so a fill built from the un-stamped
    # payload put a workflow-log field into the PDF that was missing the very identity the
    # markdown beside it printed — and left the stamped and unstamped copies disagreeing.
    payload = _stamp_ruleset_into_manifest(payload)

    dossier = None
    suite_level = is_suite_level(report_id, payload)
    if dossier_path is not None and not suite_level:
        # Bound to the analysed case: an identity block attached to another person's data
        # is the worst failure this path can cause.
        dossier = load_dossier(dossier_path, expected_case_id=str(payload.get("case_id") or ""))

    fill = build_template_fields(report_id, payload, detailed, dossier)
    if not fill["derived_count"]:
        raise TemplateV3Error(
            f"report {report_id}: no placeholder could be derived from the payload; "
            "publishing would emit the blank model"
        )

    payload = dict(payload)
    payload["editorial_mode"] = "template-v3"
    payload["template_fields"] = fill["fields"]
    payload["template_fields_complete"] = fill["unavailable_count"] == 0
    # Named so the stamp-time check knows which fields it cannot recompute: these came from
    # the operator's dossier, not from the payload. Everything else must be re-derivable.
    payload["template_fields_from_dossier"] = fill["from_dossier"]

    rendered = render_document(report_id, payload, mode="FINAL")

    # The detailed manifest carries the coordinates; the module-level loader returns identity
    # only. `editorial_v3` swaps it the same way for the same reason.
    original = _template_v3.load_reference_manifest
    _template_v3.load_reference_manifest = lambda *a, **k: detailed
    try:
        result = render_pdf_from_template(
            rendered, out_path, template_dir, strict=True, dossier=dossier
        )
    finally:
        _template_v3.load_reference_manifest = original

    return {
        "report_id": report_id,
        "pdf": str(out_path),
        # The delivered artifact's own digest. The bundle manifest hashed the markdown and
        # the HTML and never the PDF, so the file a recipient actually opens was the one
        # file nothing could verify.
        "pdf_sha256": sha256_path(out_path),
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
        "from_dossier": fill["from_dossier"],
        "dossier_supplied": fill["dossier_supplied"],
        # Stated rather than implied: without this line a reader cannot tell a report that
        # was never meant to carry identification from one whose dossier silently failed.
        "case_bound": not suite_level,
        "dossier_skipped_reason": (
            "relatório de suíte, não de caso: não recebe identificação de paciente"
            if suite_level and dossier_path is not None
            else None
        ),
        "operational_status": payload.get("operational_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-dir", required=True, help="installed template pack")
    parser.add_argument("--payload", action="append", required=True, metavar="ID=PATH")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--case-dossier", help="operator-written identification/consent record")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in args.payload:
        report_id, _, path = spec.partition("=")
        results.append(
            render(
                report_id,
                Path(path),
                Path(args.template_dir),
                out_dir / f"GENOMA-{report_id}.pdf",
                Path(args.case_dossier) if args.case_dossier else None,
            )
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
