#!/usr/bin/env python3
"""Fail-closed freshness gate executed before any real DNA read.

The gate deliberately separates *discovering the newest candidate* from *promoting it*.
A newly released tool/resource is never placed directly in front of real DNA. It must be
built and exercised on non-sensitive canary data first, then recorded as VERIFICADO.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_time(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_stale(checked_at: str | None, max_age_hours: float, now: datetime) -> bool:
    parsed = _parse_time(checked_at)
    if parsed is None or parsed > now:
        return True
    return (now - parsed).total_seconds() > max_age_hours * 3600


def evaluate_readiness(state: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    blockers: list[str] = []
    max_age_hours = float(state.get("max_age_hours", 24))

    if _is_stale(state.get("checked_at"), max_age_hours, now):
        blockers.append("freshness_state:stale")

    component_results: list[dict[str, Any]] = []
    for raw in state.get("components", []):
        if not isinstance(raw, dict):
            blockers.append("component:malformed")
            continue
        name = str(raw.get("name") or "unnamed-component")
        validated = str(raw.get("validated_version") or "")
        latest = str(raw.get("latest_version") or "")
        canary = raw.get("candidate_canary")
        promotion = raw.get("promotion_status")
        reasons: list[str] = []
        if not validated or not latest:
            reasons.append("version_unavailable")
        elif validated != latest:
            reasons.append("newer_candidate_not_promoted")
        if canary != "PASS":
            reasons.append("canary_not_pass")
        if promotion != "VERIFICADO":
            reasons.append("not_verified")
        for reason in reasons:
            blockers.append(f"{name}:{reason}")
        component_results.append(
            {
                "name": name,
                "validated_version": validated or None,
                "latest_version": latest or None,
                "candidate_canary": canary,
                "promotion_status": promotion,
                "state": "PASS" if not reasons else "FAIL",
                "reasons": reasons,
            }
        )

    source_results: list[dict[str, Any]] = []
    for raw in state.get("evidence_sources", []):
        if not isinstance(raw, dict):
            blockers.append("evidence_source:malformed")
            continue
        name = str(raw.get("name") or "unnamed-source")
        status = raw.get("status")
        source_max_age = float(raw.get("max_age_hours", max_age_hours))
        reasons: list[str] = []
        if status != "VERIFICADO":
            reasons.append("not_verified")
        if _is_stale(raw.get("checked_at"), source_max_age, now):
            reasons.append("stale")
        for reason in reasons:
            blockers.append(f"{name}:{reason}")
        source_results.append(
            {
                "name": name,
                "status": status,
                "checked_at": raw.get("checked_at"),
                "state": "PASS" if not reasons else "FAIL",
                "reasons": reasons,
            }
        )

    return {
        "schema": "genoma-pre-dna-freshness-gate-v1",
        "evaluated_at": now.isoformat().replace("+00:00", "Z"),
        "checked_at": state.get("checked_at"),
        "max_age_hours": max_age_hours,
        "ready_for_dna": not blockers,
        "blockers": blockers,
        "components": component_results,
        "evidence_sources": source_results,
        "rule": "latest discovered candidate must equal validated/promoted version and have PASS canary before real DNA",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    state = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = evaluate_readiness(state)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["ready_for_dna"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
