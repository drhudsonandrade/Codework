from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

RULESET = {
    "status": "VIGENTE",
    "version": "v3.3",
    "effective_date": "14/08/2026",
    "sha256": "187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a",
}

HARMONIZED_COLUMNS = [
    "RSID", "CHROMOSOME", "POSITION", "CONSENSUS_RESULT", "STATUS",
    "GENERA_RESULT", "MYHERITAGE_RESULT", "SOURCES",
]
RAW_COLUMNS = ["RSID", "CHROMOSOME", "POSITION", "RESULT"]
ALLOWED_CHROMS = {str(i) for i in range(1, 23)} | {"X", "Y", "MT", "M"}
MISSING_GENOTYPES = {"", "--", "NA", "N/A", "NULL", "."}
DIPLOID_SNP = re.compile(r"^[ACGT]{2}$")
HAPLOID_SNP = re.compile(r"^[ACGT]$")
INDEL = re.compile(r"^(?:II|DD|ID|DI)$")

BASELINE_RSIDS = [
    "rs1799807", "rs1803274", "rs17580", "rs28929474", "rs738409",
    "rs1799853", "rs1057910", "rs9923231", "rs4149056", "rs776746",
    "rs1799930", "rs4307059", "rs429358", "rs7412",
]


@dataclass(frozen=True)
class SourceInfo:
    kind: str
    member_name: str | None
    metadata: dict[str, str]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _text_stream(path: Path) -> tuple[TextIO, SourceInfo]:
    """Open plain/gzip/zip CSV text. ZIP must contain exactly one regular data file."""
    lower = path.name.lower()
    if lower.endswith(".gz"):
        fh = gzip.open(path, "rt", encoding="utf-8-sig", errors="replace", newline="")
        return fh, SourceInfo("gzip", None, {})
    if lower.endswith(".zip"):
        zf = zipfile.ZipFile(path)
        members = [x for x in zf.infolist() if not x.is_dir()]
        if len(members) != 1:
            zf.close()
            raise ValueError(f"ZIP must contain exactly one data file; found {len(members)}")
        raw = zf.open(members[0], "r")
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        text._genoma_zipfile = zf  # type: ignore[attr-defined]
        return text, SourceInfo("zip", members[0].filename, {})
    return path.open("rt", encoding="utf-8-sig", errors="replace", newline=""), SourceInfo("plain", None, {})


def _read_header_and_metadata(fh: TextIO) -> tuple[list[str], dict[str, str]]:
    metadata: dict[str, str] = {}
    while True:
        line = fh.readline()
        if line == "":
            raise ValueError("empty data file")
        stripped = line.rstrip("\r\n")
        if stripped.startswith("##") and "=" in stripped[2:]:
            k, v = stripped[2:].split("=", 1)
            metadata[k.strip().lower()] = v.strip()
            continue
        if stripped.startswith("#"):
            lower = stripped.lower()
            if "forward (+) strand" in lower or "forward strand" in lower:
                metadata["strand"] = "forward"
                metadata["strand_evidence"] = stripped.lstrip("#").strip()
            continue
        if stripped.strip() == "":
            continue
        header = [x.strip().upper() for x in next(csv.reader([stripped]))]
        return header, metadata


def _is_called(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().upper() not in MISSING_GENOTYPES


def _is_valid_consensus(value: str | None) -> bool:
    if not _is_called(value):
        return False
    v = value.strip().upper()
    return bool(DIPLOID_SNP.fullmatch(v) or HAPLOID_SNP.fullmatch(v) or INDEL.fullmatch(v))


def _canonical_gt(value: str | None) -> str | None:
    if not _is_called(value):
        return None
    v = value.strip().upper()
    if DIPLOID_SNP.fullmatch(v):
        return "".join(sorted(v))
    if v in {"ID", "DI"}:
        return "DI"
    return v


def _gate(state: str, reasons: list[str], **extra: Any) -> dict[str, Any]:
    return {"state": state, "reasons": reasons, **extra}


def _metadata_attestation(kind: str, text: str, input_sha: str) -> str:
    payload = {
        "status": "VERIFICADO",
        "decision": "SATISFIED",
        "justification": f"The source file explicitly declares {kind}: {text}",
        "evidence_refs": [f"input-metadata:{kind}"],
        "trace": {
            "attestation_id": f"input-metadata-{kind}-{input_sha[:16]}",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "actor_type": "SOFTWARE",
            "actor_id": "array_pipeline.qc",
            "method": "source-file metadata parsing",
            "run_id": f"input-{input_sha[:16]}",
            "input_sha256": [input_sha],
            "output_sha256": [],
            "tool_versions": {"array_pipeline": "v0.8"},
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _verified_provenance(value: str | None, input_sha: str) -> bool:
    if not value:
        return False
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("status") != "VERIFICADO" or payload.get("decision") != "SATISFIED":
        return False
    if not isinstance(payload.get("justification"), str) or not payload["justification"].strip():
        return False
    refs = payload.get("evidence_refs")
    if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or not x.strip() for x in refs):
        return False
    trace = payload.get("trace")
    if not isinstance(trace, dict):
        return False
    for field in ("attestation_id", "created_at", "actor_type", "actor_id", "method", "run_id"):
        if not isinstance(trace.get(field), str) or not trace[field].strip():
            return False
    if trace.get("actor_type") not in {"HUMAN", "SOFTWARE", "SERVICE"}:
        return False
    try:
        datetime.fromisoformat(trace["created_at"].replace("Z", "+00:00"))
    except ValueError:
        return False
    hashes = trace.get("input_sha256")
    if not isinstance(hashes, list) or input_sha.lower() not in {str(x).lower() for x in hashes}:
        return False
    tools = trace.get("tool_versions")
    if not isinstance(tools, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in tools.items()):
        return False
    return True


def inspect_array(
    path: Path,
    *,
    case_id: str,
    build: str | None = None,
    strand: str | None = None,
    platform: str | None = None,
    build_evidence: str | None = None,
    strand_evidence: str | None = None,
    min_call_rate: float = 0.95,
    max_overlap_conflict_rate: float = 0.005,
) -> dict[str, Any]:
    """QC a raw or harmonized SNP-array file without pretending it is WGS.

    This gate intentionally owns only array-level structure/callability/provenance and
    direct cross-platform concordance. It does not infer CNV/SV/phase, does not turn
    missing assayed loci into negative clinical evidence, and does not promote a marker
    to a clinical result. Provenance evidence must be a structured VERIFICADO/SATISFIED
    attestation bound to this exact input SHA-256; plain prose never unlocks the gate.
    """
    path = path.resolve()
    input_sha = sha256_file(path)
    input_size = path.stat().st_size

    fh, src = _text_stream(path)
    try:
        header, metadata = _read_header_and_metadata(fh)
        if header == HARMONIZED_COLUMNS:
            schema = "harmonized_genera_myheritage_v1"
        elif header == RAW_COLUMNS:
            schema = "raw_snp_array_v1"
        else:
            raise ValueError(f"unsupported SNP-array CSV header: {header}")

        if build is None:
            ref = metadata.get("reference", "")
            if ref.lower() in {"build37", "grch37", "hg19"}:
                build = "GRCh37"
            elif ref.lower() in {"build38", "grch38", "hg38"}:
                build = "GRCh38"
        if strand is None and metadata.get("strand"):
            strand = metadata.get("strand")
        if build_evidence is None and metadata.get("reference"):
            build_evidence = _metadata_attestation("reference_build", metadata.get("reference", ""), input_sha)
        if strand_evidence is None and metadata.get("strand_evidence"):
            strand_evidence = _metadata_attestation("strand", metadata.get("strand_evidence", ""), input_sha)
        if platform is None:
            platform = metadata.get("chip")

        build_evidence_verified = _verified_provenance(build_evidence, input_sha)
        strand_evidence_verified = _verified_provenance(strand_evidence, input_sha)

        reader = csv.DictReader(fh, fieldnames=header)
        total = 0
        unique_rsids: set[str] = set()
        duplicate_rsids = 0
        invalid_positions = 0
        invalid_chromosomes = 0
        chromosome_counts: Counter[str] = Counter()
        status_counts: Counter[str] = Counter()
        source_counts: Counter[str] = Counter()
        valid_calls = 0
        invalid_called_genotypes = 0
        autosomal_diploid = 0
        autosomal_het = 0
        g_present = g_calls = m_present = m_calls = 0
        overlap_consensus = overlap_conflict = 0
        marker_hits: dict[str, dict[str, Any]] = {}
        coordinate_seen: set[tuple[str, str]] = set()
        duplicate_coordinate_rows = 0

        for row in reader:
            total += 1
            rsid = (row.get("RSID") or "").strip()
            chrom = (row.get("CHROMOSOME") or "").strip().upper()
            pos = (row.get("POSITION") or "").strip()
            if rsid in unique_rsids:
                duplicate_rsids += 1
            else:
                unique_rsids.add(rsid)
            try:
                if int(pos) <= 0:
                    invalid_positions += 1
            except Exception:
                invalid_positions += 1
            if chrom not in ALLOWED_CHROMS:
                invalid_chromosomes += 1
            chromosome_counts[chrom] += 1
            coord = (chrom, pos)
            if coord in coordinate_seen:
                duplicate_coordinate_rows += 1
            else:
                coordinate_seen.add(coord)

            if schema.startswith("harmonized"):
                gt = row.get("CONSENSUS_RESULT")
                status = (row.get("STATUS") or "").strip()
                sources = (row.get("SOURCES") or "").strip()
                status_counts[status] += 1
                source_counts[sources] += 1
                if "G" in sources:
                    g_present += 1
                    if _is_called(row.get("GENERA_RESULT")):
                        g_calls += 1
                if "M" in sources:
                    m_present += 1
                    if _is_called(row.get("MYHERITAGE_RESULT")):
                        m_calls += 1
                if status == "consensus":
                    overlap_consensus += 1
                elif status == "genotype_conflict":
                    overlap_conflict += 1
            else:
                gt = row.get("RESULT")

            if _is_valid_consensus(gt):
                valid_calls += 1
            elif _is_called(gt):
                invalid_called_genotypes += 1

            v = (gt or "").strip().upper()
            if chrom in {str(i) for i in range(1, 23)} and DIPLOID_SNP.fullmatch(v):
                autosomal_diploid += 1
                if v[0] != v[1]:
                    autosomal_het += 1

            if rsid in BASELINE_RSIDS:
                if schema.startswith("harmonized"):
                    marker_sources = (row.get("SOURCES") or "").strip()
                    if marker_sources == "GM":
                        orientation_status = "VERIFICADO"
                        orientation_basis = "cross-platform consensus"
                    elif marker_sources == "M" and strand == "forward" and strand_evidence_verified:
                        orientation_status = "VERIFICADO"
                        orientation_basis = "MyHeritage forward-strand source metadata"
                    elif marker_sources == "G":
                        orientation_status = "INFERIDO"
                        orientation_basis = "Genera-only marker; orientation inferred from harmonization context, not independently verified"
                    else:
                        orientation_status = "NÃO DISPONÍVEL"
                        orientation_basis = "source-specific orientation not independently verified"
                else:
                    orientation_status = "VERIFICADO" if strand in {"forward", "plus", "+"} and strand_evidence_verified else "NÃO DISPONÍVEL"
                    orientation_basis = strand_evidence or "source-specific orientation evidence absent"
                marker_hits[rsid] = {
                    "rsid": rsid,
                    "chromosome": chrom,
                    "position": int(pos) if pos.isdigit() else pos,
                    "genotype": _canonical_gt(gt),
                    "status": row.get("STATUS") if schema.startswith("harmonized") else "observed",
                    "sources": row.get("SOURCES") if schema.startswith("harmonized") else "single_source",
                    "genera_result": _canonical_gt(row.get("GENERA_RESULT")) if schema.startswith("harmonized") else None,
                    "myheritage_result": _canonical_gt(row.get("MYHERITAGE_RESULT")) if schema.startswith("harmonized") else None,
                    "orientation_operational_status": orientation_status,
                    "orientation_basis": orientation_basis,
                }
    finally:
        fh.close()

    call_rate = valid_calls / total if total else 0.0
    overlap_denom = overlap_consensus + overlap_conflict
    overlap_concordance = overlap_consensus / overlap_denom if overlap_denom else None
    overlap_conflict_rate = overlap_conflict / overlap_denom if overlap_denom else None
    het_rate = autosomal_het / autosomal_diploid if autosomal_diploid else None

    structure_reasons: list[str] = []
    structure_notes: list[str] = []
    if total == 0:
        structure_reasons.append("no rows")
    if duplicate_rsids:
        if schema.startswith("harmonized"):
            structure_reasons.append(f"duplicate RSID rows={duplicate_rsids}")
        else:
            structure_notes.append(
                f"raw source contains duplicate RSID rows={duplicate_rsids}; retained as vendor provenance and must be disambiguated during harmonization"
            )
    if invalid_positions:
        structure_reasons.append(f"invalid positions={invalid_positions}")
    if invalid_chromosomes:
        structure_reasons.append(f"invalid chromosomes={invalid_chromosomes}")
    structure_state = "PASS" if not structure_reasons else "FAIL"

    build_reasons: list[str] = []
    if build not in {"GRCh37", "GRCh38"}:
        build_reasons.append("reference build not explicitly verified")
    elif not build_evidence_verified:
        build_reasons.append("reference build provenance is not a structured VERIFICADO/SATISFIED attestation bound to input SHA-256")
    if strand not in {"forward", "plus", "+"}:
        build_reasons.append("strand convention not explicitly verified")
    elif not strand_evidence_verified:
        build_reasons.append("strand provenance is not a structured VERIFICADO/SATISFIED attestation bound to input SHA-256")
    build_state = "PASS" if not build_reasons else "BLOCKED"

    call_reasons: list[str] = []
    if call_rate < min_call_rate:
        call_reasons.append(f"call_rate {call_rate:.6f} < operational threshold {min_call_rate:.6f}")
    if invalid_called_genotypes:
        call_reasons.append(f"invalid called consensus genotypes={invalid_called_genotypes}")
    call_state = "PASS" if not call_reasons else "FAIL"

    cross_reasons: list[str] = []
    cross_state = "NOT_APPLICABLE"
    if schema.startswith("harmonized"):
        cross_state = "PASS"
        if overlap_conflict_rate is not None and overlap_conflict_rate > max_overlap_conflict_rate:
            cross_reasons.append(
                f"overlap conflict rate {overlap_conflict_rate:.6f} > operational threshold {max_overlap_conflict_rate:.6f}"
            )
            cross_state = "FAIL"
        coordinate_conflicts = status_counts.get("coordinate_conflict", 0)
        ambiguous = status_counts.get("ambiguous_overlap", 0)
        if coordinate_conflicts or ambiguous:
            cross_reasons.append(
                f"retained unresolved overlap records: coordinate_conflict={coordinate_conflicts}, ambiguous_overlap={ambiguous}"
            )

    ready_for_limited_interpretation = all(
        x == "PASS" for x in (structure_state, build_state, call_state)
    ) and cross_state in {"PASS", "NOT_APPLICABLE"}

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema": "genoma-snp-array-qc-v1",
        "operational_status": "VERIFICADO" if ready_for_limited_interpretation else "NÃO DISPONÍVEL",
        "evaluated_at": now,
        "ruleset": RULESET,
        "case_id": case_id,
        "input": {
            "path_name": path.name,
            "sha256": input_sha,
            "size_bytes": input_size,
            "container": src.kind,
            "member_name": src.member_name,
            "schema": schema,
            "metadata": metadata,
            "build": build or "NÃO DISPONÍVEL",
            "build_evidence": build_evidence or "NÃO DISPONÍVEL",
            "strand": strand or "NÃO DISPONÍVEL",
            "strand_evidence": strand_evidence or "NÃO DISPONÍVEL",
            "platform": platform or "NÃO DISPONÍVEL",
        },
        "metrics": {
            "rows": total,
            "unique_rsids": len(unique_rsids),
            "duplicate_rsid_rows": duplicate_rsids,
            "unique_coordinates": len(coordinate_seen),
            "duplicate_coordinate_rows": duplicate_coordinate_rows,
            "valid_calls": valid_calls,
            "call_rate": call_rate,
            "invalid_called_consensus_genotypes": invalid_called_genotypes,
            "autosomal_diploid_snp_calls": autosomal_diploid,
            "autosomal_heterozygous_calls": autosomal_het,
            "autosomal_heterozygosity_rate": het_rate,
            "chromosome_counts": dict(sorted(chromosome_counts.items())),
            "status_counts": dict(status_counts),
            "source_counts": dict(source_counts),
            "genera_present_markers": g_present,
            "genera_called_markers": g_calls,
            "genera_call_rate": g_calls / g_present if g_present else None,
            "myheritage_present_markers": m_present,
            "myheritage_called_markers": m_calls,
            "myheritage_call_rate": m_calls / m_present if m_present else None,
            "direct_overlap_consensus": overlap_consensus,
            "direct_overlap_genotype_conflicts": overlap_conflict,
            "direct_overlap_concordance": overlap_concordance,
            "direct_overlap_conflict_rate": overlap_conflict_rate,
        },
        "gates": {
            "STRUCTURE_GATE": _gate(structure_state, structure_reasons, notes=structure_notes),
            "BUILD_STRAND_GATE": _gate(build_state, build_reasons),
            "CALLABILITY_GATE": _gate(call_state, call_reasons, threshold=min_call_rate),
            "CROSS_PLATFORM_GATE": _gate(cross_state, cross_reasons, max_conflict_rate=max_overlap_conflict_rate),
            "LIMITED_INTERPRETATION_GATE": _gate(
                "PASS" if ready_for_limited_interpretation else "BLOCKED",
                [] if ready_for_limited_interpretation else ["one or more prerequisite gates are not PASS"],
                scope="SNP-array loci only; no WGS-only classes, no diagnostic exclusion, no phase/CNV/SV inference",
            ),
        },
        "baseline_marker_observations": [marker_hits[x] for x in BASELINE_RSIDS if x in marker_hits],
        "baseline_markers_not_present": [x for x in BASELINE_RSIDS if x not in marker_hits],
        "limitations": [
            "SNP-array data interrogate only assayed loci and cannot establish genome-wide absence of variants.",
            "No DP/GQ/allele-balance/read-level evidence exists for array genotype calls.",
            "CNV, SV, repeat expansions, HLA, CYP2D6 structural alleles, mosaicism and deep intronic variation are not resolved by this QC module.",
            "Operational call/conflict thresholds are project QC gates, not clinical assay validation claims.",
            "Clinically actionable observations require current evidence review and appropriate confirmation before changing conduct.",
        ],
    }


def write_outputs(result: dict[str, Any], outdir: Path) -> dict[str, str]:
    outdir.mkdir(parents=True, exist_ok=True)
    qc = outdir / "array-qc.json"
    qc.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markers = outdir / "baseline-marker-observations.tsv"
    cols = [
        "rsid", "chromosome", "position", "genotype", "status", "sources",
        "genera_result", "myheritage_result", "orientation_operational_status", "orientation_basis",
    ]
    with markers.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(result["baseline_marker_observations"])
    sums = outdir / "SHA256SUMS"
    lines = [f"{sha256_file(p)}  {p.name}" for p in (qc, markers)]
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"qc": str(qc), "markers": str(markers), "sha256sums": str(sums)}
