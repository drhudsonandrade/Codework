from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from array_pipeline.qc import (
    HARMONIZED_COLUMNS,
    RAW_COLUMNS,
    _canonical_gt,
    _read_header_and_metadata,
    _text_stream,
    sha256_file,
)
from array_pipeline.targets import build_query_plan, load_target_manifest, sha256_json
from evidence_adapters import get_adapter

RULESET = {
    "status": "VIGENTE",
    "version": "v3.4",
    "effective_date": "17/08/2026",
    "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
}

UNSUPPORTED_ARRAY_CLAIMS = [
    "genome-wide negative/exclusion claims",
    "CNV",
    "SV",
    "repeat expansions",
    "HLA typing",
    "CYP2D6 structural/hybrid/copy-number diplotyping",
    "mosaicism from read-level evidence",
    "deep intronic/non-assayed variation",
]


def _stable_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _orientation(row: dict[str, str], schema: str, qc: dict[str, Any]) -> tuple[str, str]:
    strand = qc.get("input", {}).get("strand")
    strand_evidence = qc.get("input", {}).get("strand_evidence")
    if schema.startswith("harmonized"):
        sources = (row.get("SOURCES") or "").strip()
        if sources == "GM":
            return "VERIFICADO", "cross-platform consensus"
        if sources == "M" and strand == "forward" and strand_evidence not in {None, "NÃO DISPONÍVEL"}:
            return "VERIFICADO", "MyHeritage forward-strand source metadata"
        if sources == "G":
            return "INFERIDO", "Genera-only locus; orientation is not independently verified"
        return "NÃO DISPONÍVEL", "source-specific orientation evidence unavailable"
    if strand in {"forward", "plus", "+"} and strand_evidence not in {None, "NÃO DISPONÍVEL"}:
        return "VERIFICADO", str(strand_evidence)
    return "NÃO DISPONÍVEL", "source-specific orientation evidence unavailable"


def extract_target_observations(path: Path, target_rsids: set[str], qc: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Read only target loci into the annotation workspace; never duplicate the full chip."""
    wanted = {x.lower() for x in target_rsids}
    found: dict[str, list[dict[str, Any]]] = {x: [] for x in sorted(wanted)}
    fh, _ = _text_stream(path)
    try:
        header, _metadata = _read_header_and_metadata(fh)
        if header == HARMONIZED_COLUMNS:
            schema = "harmonized_genera_myheritage_v1"
        elif header == RAW_COLUMNS:
            schema = "raw_snp_array_v1"
        else:
            raise ValueError(f"unsupported SNP-array CSV header: {header}")
        reader = csv.DictReader(fh, fieldnames=header)
        for row in reader:
            rsid = (row.get("RSID") or "").strip().lower()
            if rsid not in wanted:
                continue
            gt = row.get("CONSENSUS_RESULT") if schema.startswith("harmonized") else row.get("RESULT")
            orientation_status, orientation_basis = _orientation(row, schema, qc)
            found[rsid].append(
                {
                    "rsid": rsid,
                    "chromosome": (row.get("CHROMOSOME") or "").strip(),
                    "position": (row.get("POSITION") or "").strip(),
                    "genotype": _canonical_gt(gt),
                    "status": (row.get("STATUS") or "observed").strip(),
                    "sources": (row.get("SOURCES") or "single_source").strip(),
                    "orientation_operational_status": orientation_status,
                    "orientation_basis": orientation_basis,
                }
            )
    finally:
        fh.close()
    return {k: v for k, v in found.items() if v}


def _query_key(source: str, query: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json({"source": source, "query": query})).hexdigest()


def _live_retrieve(source: str, query: dict[str, Any], checked_at: str, *, max_payload_bytes: int) -> dict[str, Any]:
    """Execute exactly one provider request using the provider adapter request builder.

    The payload is retained only when it is valid JSON and under a strict size cap.
    This is evidence capture, not automated clinical interpretation.
    """
    adapter = get_adapter(source)
    request = adapter._request(query)  # request construction is centralized in the adapter
    locator = request.full_url
    base: dict[str, Any] = {
        "id": f"{source}:{_query_key(source, query)[:16]}",
        "source": source,
        "status": "NÃO DISPONÍVEL",
        "checked_at": checked_at,
        "locator": locator,
        "query": query,
        "retrieval_evidence": {"method": "HTTPS"},
    }
    try:
        payload, headers = adapter.transport(request)
        if len(payload) > max_payload_bytes:
            raise ValueError(f"provider payload exceeds cap: {len(payload)} > {max_payload_bytes}")
        parsed = json.loads(payload.decode("utf-8"))
        normalized = {str(k).lower(): str(v) for k, v in headers.items()}
        digest = hashlib.sha256(payload).hexdigest()
        version = normalized.get("etag") or normalized.get("last-modified") or f"snapshot-{checked_at}"
        base.update(
            {
                "status": "VERIFICADO",
                "version": version,
                "version_kind": "http-etag" if normalized.get("etag") else ("http-last-modified" if normalized.get("last-modified") else "retrieval-snapshot"),
                "retrieval_evidence": {
                    "method": "HTTPS",
                    "result_digest": digest,
                    "content_type": normalized.get("content-type"),
                    **({"etag": normalized["etag"]} if normalized.get("etag") else {}),
                    **({"last_modified": normalized["last-modified"]} if normalized.get("last-modified") else {}),
                },
                "payload": parsed,
            }
        )
    except Exception as exc:
        base["error_class"] = type(exc).__name__
        base["error"] = str(exc)[:300]
    return base


def annotate_partial_genome(
    input_path: Path,
    qc_path: Path,
    target_manifest_path: Path,
    *,
    mode: str = "plan-only",
    max_targets: int = 250,
    max_queries: int = 1000,
    max_payload_bytes: int = 1_500_000,
    checked_at: str | None = None,
) -> dict[str, Any]:
    if mode not in {"plan-only", "live"}:
        raise ValueError("mode must be plan-only or live")
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    gate = qc.get("gates", {}).get("LIMITED_INTERPRETATION_GATE", {})
    if gate.get("state") != "PASS" or qc.get("operational_status") != "VERIFICADO":
        raise ValueError("SNP-array QC/limited interpretation gate is not VERIFICADO/PASS")
    if qc.get("input", {}).get("sha256") != sha256_file(input_path):
        raise ValueError("input SHA-256 does not match QC evidence")

    manifest = load_target_manifest(target_manifest_path)
    target_ids = {str(x["rsid"]).lower() for x in manifest["targets"]}
    observations = extract_target_observations(input_path, target_ids, qc)
    plan = build_query_plan(observations.keys(), manifest, max_targets=max_targets, max_queries=max_queries)
    now = checked_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    retrievals: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []
    for item in plan["queries"]:
        key = _query_key(item["source"], item["query"])
        if key not in retrievals:
            if mode == "live":
                retrievals[key] = _live_retrieve(item["source"], item["query"], now, max_payload_bytes=max_payload_bytes)
            else:
                adapter = get_adapter(item["source"])
                request = adapter._request(item["query"])
                retrievals[key] = {
                    "id": f"{item['source']}:{key[:16]}",
                    "source": item["source"],
                    "status": "PROPOSTO",
                    "checked_at": now,
                    "locator": request.full_url,
                    "query": item["query"],
                    "retrieval_evidence": {"method": "HTTPS", "result_digest": None},
                }
        links.append({"target_id": item["target_id"], "scope": item["scope"], "source": item["source"], "retrieval_id": retrievals[key]["id"]})

    retrieval_list = [retrievals[k] for k in sorted(retrievals)]
    verified = [x for x in retrieval_list if x.get("status") == "VERIFICADO"]
    failed = [x for x in retrieval_list if x.get("status") == "NÃO DISPONÍVEL"]
    if mode == "plan-only":
        operational_status = "PROPOSTO"
    elif retrieval_list and len(verified) == len(retrieval_list):
        operational_status = "VERIFICADO"
    else:
        operational_status = "NÃO DISPONÍVEL"

    observation_records: list[dict[str, Any]] = []
    target_meta = {str(x["rsid"]).lower(): x for x in manifest["targets"]}
    for rsid in sorted(observations):
        rows = observations[rsid]
        meta = target_meta[rsid]
        observation_records.append(
            {
                "rsid": rsid,
                "scope": meta["scope"],
                "label": meta.get("label"),
                "gene": meta.get("gene"),
                "records": rows,
                "observation_operational_status": "VERIFICADO" if len(rows) == 1 and rows[0]["orientation_operational_status"] == "VERIFICADO" else ("INFERIDO" if len(rows) == 1 else "NÃO DISPONÍVEL"),
                "interpretation": "not automatically interpreted; evidence snapshot requires curation",
            }
        )

    payload = {
        "schema": "genoma-partial-genome-annotation-v1",
        "operational_status": operational_status,
        "mode": mode,
        "evaluated_at": now,
        "ruleset": RULESET,
        "case_id": qc.get("case_id"),
        "input_sha256": qc.get("input", {}).get("sha256"),
        "target_manifest": {
            "id": manifest.get("id"),
            "version": manifest.get("version"),
            "sha256": sha256_file(target_manifest_path),
        },
        "query_plan": plan,
        "observations": observation_records,
        "evidence_retrievals": retrieval_list,
        "target_evidence_links": links,
        "evidence_gate": {
            "state": "PASS" if operational_status == "VERIFICADO" else "BLOCKED",
            "verified_retrievals": len(verified),
            "failed_retrievals": len(failed),
            "total_retrievals": len(retrieval_list),
            "reason": "all planned provider retrievals verified" if operational_status == "VERIFICADO" else ("plan-only mode does not constitute evidence verification" if mode == "plan-only" else "one or more planned retrievals are unavailable"),
        },
        "unsupported_claims": UNSUPPORTED_ARRAY_CLAIMS,
        "limitations": [
            "Target registry membership authorizes evidence retrieval only; it is not a pathogenicity or treatment assertion.",
            "SNP-array data cover assayed loci only; absence of an observation is not evidence that a disease-associated variant is absent genome-wide.",
            "Source payloads are preserved as retrieval evidence but are not automatically converted into clinical conclusions without curation.",
            "Clinically actionable observations require appropriate confirmation before changing conduct.",
        ],
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def write_annotation(result: dict[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
