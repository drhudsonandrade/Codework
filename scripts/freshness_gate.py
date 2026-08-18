#!/usr/bin/env python3
"""Fail-closed freshness gate executed before any real DNA read.

The gate deliberately separates *discovering the newest candidate* from *promoting it*.
A newly released tool/resource is never placed directly in front of real DNA. It must be
built and exercised on non-sensitive canary data first, then recorded as VERIFICADO.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence_adapters import ADAPTERS
from scripts.runtime_stack import MANAGED_RUNTIME_PACKAGES

REQUIRED_COMPONENTS = frozenset(MANAGED_RUNTIME_PACKAGES)
REQUIRED_EVIDENCE_SOURCES = frozenset(ADAPTERS)


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

    # An absence of complaints is not readiness. A truncated state carrying nothing but a
    # fresh timestamp used to satisfy every loop below vacuously and report ready_for_dna,
    # so coverage of the required sets is asserted explicitly before anything else.
    observed_components = {
        str(x.get("name")) for x in state.get("components", []) or [] if isinstance(x, dict) and x.get("name")
    }
    for missing in sorted(REQUIRED_COMPONENTS - observed_components):
        blockers.append(f"{missing}:component_absent")

    observed_sources = {
        str(x.get("name")) for x in state.get("evidence_sources", []) or [] if isinstance(x, dict) and x.get("name")
    }
    for missing in sorted(REQUIRED_EVIDENCE_SOURCES - observed_sources):
        blockers.append(f"{missing}:evidence_source_absent")

    component_results: list[dict[str, Any]] = []
    for raw in state.get("components", []) or []:
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
    for raw in state.get("evidence_sources", []) or []:
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
        "required_components": sorted(REQUIRED_COMPONENTS),
        "required_evidence_sources": sorted(REQUIRED_EVIDENCE_SOURCES),
        "rule": "every required component and evidence source must be present, promoted and fresh; latest discovered candidate must equal the validated/promoted version and have a PASS canary before real DNA",
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
