#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence_adapters import get_adapter

PROBES = {
    "clinvar": {"term": "BRCA1[gene]", "retmax": 1},
    "clingen": {"path": "classifications", "params": {"gene": "BRCA1"}},
    "cpic": {"path": "guideline_summary_view", "limit": 1},
    "clinpgx": {"path": "data/gene", "params": {"symbol": "CYP2C19", "view": "min"}},
    "gnomad": {"graphql": "query { __typename }", "variables": {}},
    "pgs_catalog": {"score_id": "PGS000001"},
}


def refresh(state: dict, *, checked_at: str) -> dict:
    result = dict(state)
    snapshots = []
    freshness_sources = []
    for name, query in PROBES.items():
        snapshot = get_adapter(name).query(query, checked_at=checked_at)
        snapshots.append(snapshot)
        freshness_sources.append({
            "name": name,
            "status": snapshot.get("status"),
            "checked_at": snapshot.get("checked_at"),
            "max_age_hours": 24,
            "locator": snapshot.get("locator"),
            "version": snapshot.get("version"),
            "retrieval_evidence": snapshot.get("retrieval_evidence", {}),
        })
    result["evidence_sources"] = freshness_sources
    result["evidence_source_snapshots"] = snapshots
    result["evidence_refresh_policy"] = "critical official source capability probes are required before real DNA; patient-specific queries occur later during curation"
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input-state", required=True)
    p.add_argument("--output-state", required=True)
    p.add_argument("--snapshots-output", required=True)
    args = p.parse_args()
    state = json.loads(Path(args.input_state).read_text(encoding="utf-8"))
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    updated = refresh(state, checked_at=checked_at)
    output = Path(args.output_state)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    snapshots = Path(args.snapshots_output)
    snapshots.parent.mkdir(parents=True, exist_ok=True)
    snapshots.write_text(json.dumps(updated["evidence_source_snapshots"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    unavailable = [s["name"] for s in updated["evidence_sources"] if s.get("status") != "VERIFICADO"]
    if unavailable:
        print("NÃO DISPONÍVEL: evidence source probes failed: " + ", ".join(unavailable), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
