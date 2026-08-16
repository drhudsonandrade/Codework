#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.qc import inspect_array, write_outputs


def main() -> int:
    p = argparse.ArgumentParser(description="GENOMA v3.3 fail-closed SNP-array QC and baseline observation extractor")
    p.add_argument("--input", required=True)
    p.add_argument("--case-id", required=True)
    p.add_argument("--build", choices=["GRCh37", "GRCh38"])
    p.add_argument("--strand", choices=["forward", "plus", "+"])
    p.add_argument("--platform")
    p.add_argument("--build-evidence")
    p.add_argument("--strand-evidence")
    p.add_argument("--min-call-rate", type=float, default=0.95)
    p.add_argument("--max-overlap-conflict-rate", type=float, default=0.005)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()

    result = inspect_array(
        Path(args.input),
        case_id=args.case_id,
        build=args.build,
        strand=args.strand,
        platform=args.platform,
        build_evidence=args.build_evidence,
        strand_evidence=args.strand_evidence,
        min_call_rate=args.min_call_rate,
        max_overlap_conflict_rate=args.max_overlap_conflict_rate,
    )
    paths = write_outputs(result, Path(args.output_dir))
    ready = result["gates"]["LIMITED_INTERPRETATION_GATE"]["state"] == "PASS"
    print(json.dumps({"status": result["operational_status"], "ready": ready, "outputs": paths}, ensure_ascii=False))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
