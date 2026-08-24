#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def evaluate_consent(manifest: dict[str, Any], *, requested_purpose: str) -> dict[str, Any]:
    errors: list[str] = []
    sample_id = str(manifest.get("sample_id") or "").strip()
    consent = manifest.get("consent") if isinstance(manifest.get("consent"), dict) else {}
    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}

    if not sample_id:
        errors.append("sample_id missing")
    if consent.get("status") != "VERIFICADO":
        errors.append("consent.status must be VERIFICADO")
    if not str(consent.get("consent_id") or "").strip():
        errors.append("consent.consent_id missing")
    if not str(consent.get("version") or "").strip():
        errors.append("consent.version missing")
    purposes = consent.get("purposes") if isinstance(consent.get("purposes"), list) else []
    if requested_purpose not in purposes:
        errors.append(f"requested purpose not authorized: {requested_purpose}")
    if provenance.get("status") != "VERIFICADO":
        errors.append("provenance.status must be VERIFICADO")
    if not str(provenance.get("source") or "").strip():
        errors.append("provenance.source missing")
    if not str(provenance.get("chain_of_custody_ref") or "").strip():
        errors.append("provenance.chain_of_custody_ref missing")

    return {
        "schema": "genoma-consent-provenance-gate-v1",
        "gate": "CONSENT_PROVENANCE_GATE",
        "status": "VERIFICADO" if not errors else "NÃO DISPONÍVEL",
        "sample_id": sample_id or None,
        "requested_purpose": requested_purpose,
        "ready_for_first_dna_read": not errors,
        "secondary_findings": consent.get("secondary_findings", "NÃO DISPONÍVEL"),
        "consent_id": consent.get("consent_id"),
        "consent_version": consent.get("version"),
        "provenance_ref": provenance.get("chain_of_custody_ref"),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--purpose", default="genomic_analysis")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = evaluate_consent(manifest, requested_purpose=args.purpose)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ready_for_first_dna_read"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
