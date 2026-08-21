from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from array_pipeline.qc import (
    FORWARD_STRANDS,
    HARMONIZED_COLUMNS,
    INTERPRETABLE_OVERLAP_STATUSES,
    RAW_COLUMNS,
    REVERSE_STRANDS,
    UNRESOLVED_OVERLAP_STATUSES,
    _canonical_gt,
    _read_header_and_metadata,
    _text_stream,
    sha256_file,
)
from array_pipeline.targets import build_query_plan, load_target_manifest, sha256_json
from evidence_adapters import get_adapter

import normative

RULESET = normative.ruleset_block()

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
    inputs = qc.get("input", {})
    strand = inputs.get("strand")
    strand_evidence = inputs.get("strand_evidence")
    # Prefer the verdict the QC published. The old proxy — "the evidence string is not the
    # literal 'NÃO DISPONÍVEL'" — is satisfied by any non-empty text, including an
    # attestation that failed structural verification.
    verified = inputs.get("strand_evidence_verified")
    if verified is None:
        verified = strand_evidence not in {None, "", "NÃO DISPONÍVEL"}
    forward = strand in FORWARD_STRANDS and bool(verified)

    if str(strand or "").strip().lower() in REVERSE_STRANDS:
        # A determinate reverse verdict disqualifies every locus, whatever its sources say.
        # Cross-platform consensus would otherwise return INFERIDO here — a status
        # `completeness._classify` accepts — and the allele comparison it admits runs against
        # the complement of what the registry means.
        return (
            "NÃO DISPONÍVEL",
            f"file reported on the reverse strand ({strand}); the reported allele is the "
            "complement of the one the registry names",
        )

    if schema.startswith("harmonized"):
        sources = (row.get("SOURCES") or "").strip()
        status = (row.get("STATUS") or "").strip().lower()
        # Presence in both platforms is not agreement between them. Reporting a record the
        # harmonizer flagged as conflicting or ambiguous as "cross-platform consensus" would
        # resolve the conflict by assertion, which sections 4 and 7 forbid.
        if status in UNRESOLVED_OVERLAP_STATUSES:
            return "NÃO DISPONÍVEL", f"unresolved cross-platform record ({status}); not auto-resolved"
        # An allowlist, so a status this module has never seen is refused rather than
        # assumed clean. A real harmonized export emitted ten distinct STATUS values and one
        # of them was unknown here.
        if status not in INTERPRETABLE_OVERLAP_STATUSES:
            return "NÃO DISPONÍVEL", f"unrecognised harmonizer status ({status}); not assumed interpretable"
        if sources == "GM":
            # Agreement proves both vendors used the same strand convention, not which one:
            # if both reported the reverse strand an AG call would read TC in both files and
            # they would agree perfectly while both were flipped.
            if forward:
                return "VERIFICADO", "cross-platform consensus with documented forward-strand provenance"
            return (
                "INFERIDO",
                "cross-platform consensus establishes mutual consistency between vendors, "
                "not absolute strand orientation",
            )
        if sources == "M" and forward:
            return "VERIFICADO", "MyHeritage forward-strand source metadata"
        if sources == "G":
            return "INFERIDO", "Genera-only locus; orientation is not independently verified"
        return "NÃO DISPONÍVEL", "source-specific orientation evidence unavailable"
    if forward:
        return "VERIFICADO", str(strand_evidence)
    return "NÃO DISPONÍVEL", "source-specific orientation evidence unavailable"


def check_coordinate(
    observation: dict[str, Any], target: dict[str, Any], build: str | None
) -> tuple[str, str]:
    """Compare the observed coordinate with the registry's canonical one.

    The observation used to be accepted on its rsID alone, because the registry held no
    coordinates to compare against. An rsID is a label: a file that carries the right label
    at the wrong position is a file annotated on another assembly, or a file whose
    coordinate column has been rebuilt by a tool nobody recorded. Either way the locus is
    not the locus the registry means, and interpreting it produces a finding about a
    position that was never interrogated.

    Returns an operational status and the basis for it, in the vocabulary the rest of the
    pipeline uses. Anything short of an actual match is refused rather than downgraded, but
    a registry with no coordinate for the locus is NÃO DISPONÍVEL, not a mismatch — there is
    nothing to disagree with.
    """
    coordinates = target.get("coordinates") if isinstance(target.get("coordinates"), dict) else {}
    if coordinates.get("status") != "VERIFICADO":
        return (
            "NÃO DISPONÍVEL",
            f"registro não traz coordenada canônica para {target.get('rsid')}: "
            f"{coordinates.get('reason') or 'coordenada ausente'}",
        )
    if build not in ("GRCh37", "GRCh38"):
        return (
            "NÃO DISPONÍVEL",
            "build do caso não verificado; sem build não há coordenada canônica com que comparar",
        )
    expected = coordinates.get(build)
    if not isinstance(expected, dict):
        return ("NÃO DISPONÍVEL", f"registro não traz coordenada em {build} para este locus")
    if expected.get("ambiguous_positions"):
        return (
            "NÃO DISPONÍVEL",
            f"o ClinVar registra este rsid em {expected['ambiguous_positions']} posições "
            f"distintas em {build}; não há coordenada única para conferir",
        )

    observed_chromosome = str(observation.get("chromosome") or "").strip().upper().removeprefix("CHR")
    expected_chromosome = str(expected.get("chromosome") or "").strip().upper()
    try:
        observed_position = int(str(observation.get("position") or "").strip())
    except ValueError:
        return ("NÃO DISPONÍVEL", "posição observada não é um inteiro")

    if observed_chromosome != expected_chromosome or observed_position != int(expected["position"]):
        return (
            "NÃO DISPONÍVEL",
            f"coordenada divergente em {build}: o arquivo traz "
            f"chr{observed_chromosome}:{observed_position:,} e o registro "
            f"chr{expected_chromosome}:{int(expected['position']):,}. O rsid casa e a posição "
            "não; o arquivo está em outra montagem ou a coluna de coordenadas foi reescrita.",
        )
    return (
        "VERIFICADO",
        f"coordenada confere com o registro em {build} "
        f"(chr{expected_chromosome}:{int(expected['position']):,}, "
        f"{expected.get('reference_allele')}>{expected.get('alternate_allele')})",
    )


def extract_target_observations(
    path: Path,
    target_rsids: set[str],
    qc: dict[str, Any],
    targets_by_rsid: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Read only target loci into the annotation workspace; never duplicate the full chip."""
    wanted = {x.lower() for x in target_rsids}
    by_rsid = {k.lower(): v for k, v in (targets_by_rsid or {}).items()}
    case_build = str((qc.get("input") or {}).get("build") or "") or None
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
            observation = {
                "rsid": rsid,
                "chromosome": (row.get("CHROMOSOME") or "").strip(),
                "position": (row.get("POSITION") or "").strip(),
                "genotype": _canonical_gt(gt),
                # The file's own text, kept beside the canonical form. `_canonical_gt` sorts
                # the alleles, which is what makes two vendors comparable and is also what
                # destroys any ordering the file carried. Keeping both means the canonical
                # form is a derivation rather than a replacement.
                "genotype_as_reported": (gt or "").strip(),
                # An array reports two alleles at a position and says nothing about which
                # chromosome each sits on. Stated on every observation so no consumer has to
                # infer it from the absence of a phase field.
                "phase_status": "UNPHASED",
                "phase_basis": (
                    "genotipagem por microarranjo não resolve fase; diplótipo exige "
                    "evidência de fase que este ensaio não produz"
                ),
                "status": (row.get("STATUS") or "observed").strip(),
                "sources": (row.get("SOURCES") or "single_source").strip(),
                "orientation_operational_status": orientation_status,
                "orientation_basis": orientation_basis,
            }
            target = by_rsid.get(rsid)
            if target is not None:
                status, basis = check_coordinate(observation, target, case_build)
                observation["coordinate_operational_status"] = status
                observation["coordinate_basis"] = basis
            found[rsid].append(observation)
    finally:
        fh.close()
    return {k: v for k, v in found.items() if v}


def _observation_status(rows: list[dict[str, Any]]) -> str:
    """The status of one locus, from every check that was actually made about it.

    It read the orientation alone. `check_coordinate` was computed per observation, written
    onto the record — and consumed by nothing: a locus whose coordinate diverged from the
    registry, which is proof the file is annotated on another assembly, still reached
    VERIFICADO because its strand happened to be established. On the first real array,
    rs4307059 was VERIFICADO with `coordinate_operational_status: NÃO DISPONÍVEL` beside it.

    Both must hold. A coordinate the registry could not supply is not a failure of the file,
    but it is not a verification either: an rsID is a label, and nothing checked that this
    label sits where the registry means. Such a locus is INFERIDO — usable, and not
    presented as confirmed.
    """
    if len(rows) != 1:
        # More than one row for one rsid is an unresolved duplicate; choosing between them
        # would be the arbitration sections 4 and 7 forbid.
        return "NÃO DISPONÍVEL"
    row = rows[0]
    if row.get("orientation_operational_status") != "VERIFICADO":
        return "INFERIDO"
    coordinate = row.get("coordinate_operational_status")
    if coordinate == "VERIFICADO":
        return "VERIFICADO"
    # A divergent coordinate is a positive finding of disagreement, not a gap: the rsid
    # matches and the position does not, so this locus is not the locus the registry means.
    if coordinate is None:
        return "INFERIDO"
    return "INFERIDO" if "não traz coordenada" in str(row.get("coordinate_basis") or "") else "NÃO DISPONÍVEL"


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
    # Passed so each observation can be checked against the registry's canonical coordinate
    # instead of being accepted on its rsID alone.
    targets_by_rsid = {str(x["rsid"]).lower(): x for x in manifest["targets"]}
    observations = extract_target_observations(input_path, target_ids, qc, targets_by_rsid)
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
                "observation_operational_status": _observation_status(rows),
                "interpretation": "not automatically interpreted; evidence snapshot requires curation",
            }
        )

    payload = {
        "schema": "genoma-partial-genome-annotation-v1",
        "operational_status": operational_status,
        "mode": mode,
        "evaluated_at": now,
        "ruleset": normative.attested_ruleset_block(),
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
