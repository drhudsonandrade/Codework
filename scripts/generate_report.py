#!/usr/bin/env python3
"""Generate GENOMA report artifacts from structured, already-curated JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.editorial_v3 import write_editorial_bundle
from reporting.engine import ReportReleaseError, render_document, write_bundle


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--report", required=True, help="01..11")
    p.add_argument("--mode", choices=["MODEL", "FINAL"], default="MODEL")
    p.add_argument("--input", help="curated JSON; required for FINAL")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--stem")
    args = p.parse_args()
    if args.mode == "FINAL" and not args.input:
        raise SystemExit("FINAL mode requires --input")
    data = json.loads(Path(args.input).read_text(encoding="utf-8")) if args.input else {}
    try:
        rendered = render_document(args.report, data, mode=args.mode)
        output_dir = Path(args.output_dir)
        paths = write_bundle(rendered, output_dir, stem=args.stem)
        paths.update(write_editorial_bundle(rendered, output_dir, stem=args.stem))
    except (ReportReleaseError, RuntimeError, ValueError) as exc:
        print(f"REPORT BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
