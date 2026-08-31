from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from array_pipeline import assembly

ALLOWED_SCOPES = {"CLINICO", "PREDISPOSICAO", "PESQUISA", "CURIOSIDADE"}
ALLOWED_SOURCES = {"clinvar", "clingen", "cpic", "clinpgx", "gnomad", "pgs_catalog"}


def read_manifest_bytes(path: Path) -> str:
    """Read a target manifest, transparently decompressing a `.gz`.

    The curated registry holds twenty-nine loci and the ClinVar-derived one holds tens of
    thousands; the second is an order of magnitude too large to keep as plain JSON in the
    repository. Compression is decided by the file's own gzip magic number rather than by its
    extension, so a manifest that was compressed without being renamed still loads instead of
    failing with a decoding error that says nothing about the real cause.
    """
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        # Bounded: `gzip.decompress` expands whatever it is given, and this path takes a
        # filename from `--targets`. The ceilings live beside the ones the QC gate applies
        # to an array export, so the two cannot drift apart on what is physically plausible.
        raw = assembly.bounded_gunzip(raw, name=str(path))
    return raw.decode("utf-8")


@dataclass(frozen=True)
class Target:
    """One interrogated locus: which variant, how strongly scoped, and what to ask about it.

    `scope` is what decides whether a locus may become a clinical finding at all, so it is
    part of the target's identity rather than presentation metadata.
    """
    rsid: str
    scope: str
    label: str
    gene: str | None
    queries: dict[str, dict[str, Any]]


def _stable_json(value: Any) -> str:
    """JSON that depends only on the value: sorted keys, no incidental whitespace."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    """SHA-256 over the stable rendering, so equal content gives equal digests."""
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def load_target_manifest(path: Path) -> dict[str, Any]:
    """Read a target manifest, refusing any entry the pipeline could not act on.

    Schema, rsid shape, duplicate rsids, scope vocabulary and query sources are all checked
    here rather than at use: a duplicate locus would be interrogated twice and weighted
    twice, and an unknown scope would reach the ranking as a value it cannot place.
    """
    payload = json.loads(read_manifest_bytes(Path(path)))
    if payload.get("schema") != "genoma-partial-genome-targets-v1":
        raise ValueError("unsupported target manifest schema")
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("target manifest must contain a non-empty targets list")
    seen: set[str] = set()
    for item in targets:
        if not isinstance(item, dict):
            raise ValueError("target entry must be an object")
        rsid = str(item.get("rsid") or "").strip().lower()
        if not rsid.startswith("rs") or not rsid[2:].isdigit():
            raise ValueError(f"invalid rsid in target manifest: {rsid!r}")
        if rsid in seen:
            raise ValueError(f"duplicate target rsid: {rsid}")
        seen.add(rsid)
        scope = str(item.get("scope") or "").upper()
        if scope not in ALLOWED_SCOPES:
            raise ValueError(f"invalid scope for {rsid}: {scope}")
        queries = item.get("queries", {})
        if not isinstance(queries, dict):
            raise ValueError(f"queries for {rsid} must be an object")
        unknown = sorted(set(queries) - ALLOWED_SOURCES)
        if unknown:
            raise ValueError(f"unsupported evidence sources for {rsid}: {unknown}")
        for source, query in queries.items():
            if not isinstance(query, dict) or not query:
                raise ValueError(f"query for {rsid}/{source} must be a non-empty object")
    return payload


def targets_from_manifest(payload: dict[str, Any]) -> list[Target]:
    """Convert a validated manifest into `Target` records, normalising rsid and scope case.

    The manifest is accepted in whatever case it was written; everything downstream compares
    against the canonical spelling, so normalising happens once, here.
    """
    out: list[Target] = []
    for item in payload["targets"]:
        out.append(
            Target(
                rsid=str(item["rsid"]).lower(),
                scope=str(item["scope"]).upper(),
                label=str(item.get("label") or item["rsid"]),
                gene=str(item["gene"]) if item.get("gene") else None,
                queries={str(k): dict(v) for k, v in item.get("queries", {}).items()},
            )
        )
    return out


def build_query_plan(
    observed_rsids: Iterable[str],
    manifest: dict[str, Any],
    *,
    max_targets: int = 250,
    max_queries: int = 1000,
) -> dict[str, Any]:
    """Build a deterministic evidence plan only for assayed/observed target loci.

    This is deliberately target-first. It prevents 500k-700k chip loci from causing
    uncontrolled external API fan-out while allowing the target manifest to expand
    independently under version control.
    """
    if max_targets < 1 or max_queries < 1:
        raise ValueError("query budgets must be positive")
    observed = {str(x).lower() for x in observed_rsids}
    selected = [t for t in targets_from_manifest(manifest) if t.rsid in observed]
    selected.sort(key=lambda t: t.rsid)
    if len(selected) > max_targets:
        raise ValueError(f"target budget exceeded: {len(selected)} > {max_targets}")

    queries: list[dict[str, Any]] = []
    for target in selected:
        for source in sorted(target.queries):
            queries.append(
                {
                    "target_id": target.rsid,
                    "scope": target.scope,
                    "label": target.label,
                    "gene": target.gene,
                    "source": source,
                    "query": target.queries[source],
                }
            )
    if len(queries) > max_queries:
        raise ValueError(f"query budget exceeded: {len(queries)} > {max_queries}")

    body = {
        "schema": "genoma-partial-genome-query-plan-v1",
        "target_manifest_id": manifest.get("id"),
        "target_manifest_version": manifest.get("version"),
        "observed_target_count": len(selected),
        "query_count": len(queries),
        "max_targets": max_targets,
        "max_queries": max_queries,
        "targets": [
            {
                "rsid": x.rsid,
                "scope": x.scope,
                "label": x.label,
                "gene": x.gene,
            }
            for x in selected
        ],
        "queries": queries,
    }
    body["sha256"] = sha256_json(body)
    return body
