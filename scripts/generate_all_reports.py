#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.editorial_v3 import EditorialRenderError, write_editorial_bundle
from reporting.engine import ReportReleaseError, load_catalog, render_document, write_bundle
from reporting.template_v3 import TemplateV3Error
from scripts.prepare_report_release import assemble_release


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--policy", help="actual policy evaluation JSON; if omitted, a staged evaluation.json is used when present")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--strict", action="store_true", help="exit non-zero when publication is blocked; required in production workflows")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    policy_path = Path(args.policy) if args.policy else Path("evaluation.json")
    if policy_path.is_file():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        data = assemble_release(data, policy)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "REPORT_RELEASE_INPUT.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    publication = data.get("publication_gate") if isinstance(data.get("publication_gate"), dict) else {}
    if publication.get("passed") is not True:
        blocked = {
            "schema": "genoma-report-release-block-v2",
            "status": "NÃO DISPONÍVEL",
            "reason": "publication gate not released by verified prerequisites plus the actual policy evaluation",
            "blockers": data.get("report_release_blockers", []),
            "required_next_step": "complete scientific curation, evidence retrieval, consent/QC attestations and FINAL_AUDIT_GATE; rerun policy evaluation",
            "strict_mode": args.strict,
        }
        (out / "REPORTS_BLOCKED.json").write_text(json.dumps(blocked, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(blocked, ensure_ascii=False, indent=2))
        return 2 if args.strict else 0

    generated: dict[str, dict[str, str]] = {}
    try:
        for report_id in sorted(load_catalog()):
            rendered = render_document(report_id, data, mode="FINAL")
            paths = write_bundle(rendered, out)
            paths.update(write_editorial_bundle(rendered, out))
            generated[report_id] = {key: str(value) for key, value in paths.items()}
    except (ReportReleaseError, EditorialRenderError, TemplateV3Error) as exc:
        blocked = {
            "schema": "genoma-report-render-block-v1",
            "status": "NÃO DISPONÍVEL",
            "reason": f"{type(exc).__name__}: {exc}",
            "strict_mode": args.strict,
            "generated_before_block": sorted(generated),
        }
        (out / "REPORTS_BLOCKED.json").write_text(json.dumps(blocked, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(blocked, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    manifest = {
        "schema": "genoma-eleven-report-release-v2",
        "status": "EXECUTADO",
        "report_count": len(generated),
        "reports": generated,
    }
    (out / "REPORT_RELEASE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
