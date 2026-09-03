#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.annotation import (
    AdapterUnavailableError,
    annotate_partial_genome,
    write_annotation,
)


def main() -> int:
    """Run the bounded annotation plane and report its outcome through the exit code.

    Exit 2 covers two distinct situations, both of which have to stop a pipeline: the run
    was blocked before producing anything (the `ANNOTATION BLOCKED` branch), and a `live`
    run that completed but did not reach `VERIFICADO`. A `plan-only` run is `PROPOSTO` by
    construction and exits 0 — it is a plan, and refusing it for not being verified would
    make the mode useless.
    """
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
    # `AdapterUnavailableError` is a RuntimeError, so it matched none of the others and left
    # here as an unhandled traceback: no ANNOTATION BLOCKED line and no exit 2, on the one
    # failure the optional-adapter contract exists to make survivable. In `live` mode each
    # retrieval degrades to NÃO DISPONÍVEL and never reaches this; `plan-only` builds its
    # locator from the adapter, so without it there is no plan to write and the run blocks.
    except (ValueError, OSError, json.JSONDecodeError, AdapterUnavailableError) as exc:
        print(f"ANNOTATION BLOCKED: {exc}", file=sys.stderr)
        return 2
    write_annotation(result, Path(args.output))
    print(json.dumps({"status": result["operational_status"], "evidence_gate": result["evidence_gate"], "output": args.output}, ensure_ascii=False))
    if args.mode == "live" and result["operational_status"] != "VERIFICADO":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
