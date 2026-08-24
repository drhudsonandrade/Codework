#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.annotation import annotate_partial_genome, write_annotation


def main() -> int:
    p = argparse.ArgumentParser(description="GENOMA v3.4 bounded Evidence/Annotation Plane for partial SNP-array genomes")
    p.add_argument("--input", required=True)
    p.add_argument("--qc", required=True)
    p.add_argument("--targets", default=str(ROOT / "config" / "partial_genome_annotation_targets.json"))
    p.add_argument("--mode", choices=["plan-only", "live"], default="plan-only")
    p.add_argument("--max-targets", type=int, default=250)
    p.add_argument("--max-queries", type=int, default=1000)
    p.add_argument("--max-payload-bytes", type=int, default=1_500_000)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    try:
        result = annotate_partial_genome(
            Path(args.input),
            Path(args.qc),
            Path(args.targets),
            mode=args.mode,
            max_targets=args.max_targets,
            max_queries=args.max_queries,
            max_payload_bytes=args.max_payload_bytes,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ANNOTATION BLOCKED: {exc}", file=sys.stderr)
        return 2
    write_annotation(result, Path(args.output))
    print(json.dumps({"status": result["operational_status"], "evidence_gate": result["evidence_gate"], "output": args.output}, ensure_ascii=False))
    if args.mode == "live" and result["operational_status"] != "VERIFICADO":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
