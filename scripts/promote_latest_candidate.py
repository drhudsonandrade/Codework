#!/usr/bin/env python3
"""Create a session-scoped promotion/freshness attestation after both canaries PASS.

Promotion is deliberately fail-closed: the functional caller/editorial-runtime canary and
Nextflow orchestration canary are separate mandatory witnesses. A surrounding workflow
cannot accidentally promote a candidate merely because it forgot to check one of them.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runtime_stack import MANAGED_RUNTIME_PACKAGES


def _load_canary(path: Path, label: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "PASS":
        raise RuntimeError(f"candidate promotion refused: {label} canary is not PASS")
    return payload


def promote(functional_canary_path: Path, orchestration_canary_path: Path, inventory_path: Path, *, max_age_hours: int = 24) -> dict:
    functional = _load_canary(functional_canary_path, "functional")
    orchestration = _load_canary(orchestration_canary_path, "orchestration")
    editorial = functional.get("editorial_runtime")
    if not isinstance(editorial, dict) or editorial.get("status") != "PASS":
        raise RuntimeError("candidate promotion refused: functional canary editorial runtime is not PASS")

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(inventory, list):
        raise RuntimeError("candidate promotion refused: Conda inventory is not a list")
    versions = {
        str(x.get("name")): str(x.get("version"))
        for x in inventory
        if isinstance(x, dict) and x.get("name") and x.get("version")
    }
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    components = []
    missing = []
    for name in MANAGED_RUNTIME_PACKAGES:
        version = versions.get(name)
        if not version:
            missing.append(name)
            continue
        components.append({
            "name": name,
            "validated_version": version,
            "latest_version": version,
            "candidate_canary": "PASS",
            "functional_canary": "PASS",
            "orchestration_canary": "PASS",
            "promotion_status": "VERIFICADO",
            "resolution_scope": "latest mutually compatible version resolved from configured Conda channels in this execution",
        })
    if missing:
        raise RuntimeError("candidate promotion refused: inventory missing managed packages: " + ", ".join(missing))
    return {
        "schema": "genoma-pre-dna-freshness-state-v2",
        "checked_at": now,
        "max_age_hours": max_age_hours,
        "components": components,
        "evidence_sources": [],
        "candidate_canaries": {
            "functional": functional,
            "orchestration": orchestration,
        },
        "promotion_status": "VERIFICADO",
        "promotion_scope": "session only; both PASS canaries, immutable package inventory and image digest must be retained with execution evidence",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--functional-canary", required=True)
    p.add_argument("--orchestration-canary", required=True)
    p.add_argument("--inventory", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--max-age-hours", type=int, default=24)
    args = p.parse_args()
    state = promote(
        Path(args.functional_canary),
        Path(args.orchestration_canary),
        Path(args.inventory),
        max_age_hours=args.max_age_hours,
    )
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
