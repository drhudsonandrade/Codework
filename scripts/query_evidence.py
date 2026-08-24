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

from evidence_adapters import ADAPTERS, get_adapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, choices=sorted(ADAPTERS))
    parser.add_argument("--query", required=True, help="JSON object or @path/to/query.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.query.startswith("@"):
        query = json.loads(Path(args.query[1:]).read_text(encoding="utf-8"))
    else:
        query = json.loads(args.query)
    if not isinstance(query, dict):
        raise SystemExit("query must be a JSON object")
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snapshot = get_adapter(args.source).query(query, checked_at=checked_at)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if snapshot.get("status") == "VERIFICADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
