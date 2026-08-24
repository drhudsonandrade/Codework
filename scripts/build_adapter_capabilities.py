#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence_adapters import ADAPTERS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vcf", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = {
        "schema": "genoma-evidence-adapter-capabilities-v1",
        "status": "VERIFICADO",
        "adapters": sorted(ADAPTERS),
        "variant_specific_sources_queried": [],
        "note": "Adapters are available. No source is marked consulted until a variant/gene-specific query produces a traceable retrieval snapshot.",
        "input_vcf": Path(args.vcf).name,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
