#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.editorial_v3 import write_editorial_bundle
from reporting.engine import ReportReleaseError, load_catalog, render_document, write_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    publication = data.get("publication_gate") if isinstance(data.get("publication_gate"), dict) else {}
    if publication.get("passed") is not True:
        blocked = {
            "schema": "genoma-report-release-block-v1",
            "status": "NÃO DISPONÍVEL",
            "reason": "publication_gate.passed is not true",
            "required_next_step": "complete scientific curation, Evidence Gate, consent/QC attestations and FINAL_AUDIT_GATE",
        }
        (out / "REPORTS_BLOCKED.json").write_text(json.dumps(blocked, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(blocked, ensure_ascii=False, indent=2))
        return 0

    generated: dict[str, dict[str, str]] = {}
    try:
        for report_id in sorted(load_catalog()):
            rendered = render_document(report_id, data, mode="FINAL")
            paths = write_bundle(rendered, out)
            paths.update(write_editorial_bundle(rendered, out))
            generated[report_id] = {key: str(value) for key, value in paths.items()}
    except ReportReleaseError as exc:
        print(f"REPORT BLOCKED: {exc}", file=sys.stderr)
        return 2

    manifest = {"schema": "genoma-eleven-report-release-v1", "status": "EXECUTADO", "reports": generated}
    (out / "REPORT_RELEASE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
