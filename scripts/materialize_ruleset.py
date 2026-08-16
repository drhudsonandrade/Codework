#!/usr/bin/env python3
"""Materialize the canonical GENOMA v3.3 ruleset using the shared sealed contract."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sealed_ruleset import materialize as materialize_from_sealed

SEALED_DIR = ROOT / "normative" / "sealed"


def materialize(output_dir: Path):
    """Backward-compatible wrapper used by existing workflows and callers."""
    return materialize_from_sealed(SEALED_DIR, output_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--evidence")
    args = parser.parse_args()
    target, evidence = materialize(Path(args.output_dir))
    payload = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if args.evidence:
        evidence_path = Path(args.evidence)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(payload, encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
