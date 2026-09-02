"""Derive reference build and strand convention from the array's own content.

A real harmonized consumer-array export carries no `##reference=` or `##strand=` header, so
`BUILD_STRAND_GATE` blocks it and nothing downstream can run. Until now the only ways
forward were to leave the data unusable or to hand-write an attestation asserting a build
and strand nobody had checked — the second being exactly the unsupported claim this project
exists to prevent.

Both facts are, however, *derivable from the file itself*, and the derivation is falsifiable:

**Build.** Marker coordinates differ between GRCh37 and GRCh38. Comparing the observed
positions of a panel of markers against both assemblies yields a count for each; a build is
declared only when one assembly matches and the other does not.

**Strand.** For a SNP whose two plus-strand alleles are known, a reverse-strand export
reports their complements. `rs429358` (plus alleles T/C) would appear as A/G. Observing only
letters from the plus set — and none from the complement set — is positive evidence for the
plus strand. Palindromic SNPs (A/T, C/G) are excluded automatically: a flip maps A↔T and
C↔G, so they read identically on both strands and carry no information about orientation.

The probe refuses to conclude on weak or contradictory evidence rather than guessing, and
the attestation it emits embeds the per-marker evidence, so a reader can recompute the
verdict instead of trusting it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from array_pipeline.qc import (
    UNRESOLVED_OVERLAP_STATUSES,
    detect_schema,
    _canonical_gt,
    _read_header_and_metadata,
    _text_stream,
    sha256_file,
)

SCHEMA = "genoma-array-provenance-probe-v1"
MARKERS_SCHEMA = "genoma-array-provenance-markers-v1"

COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}
VALID_ALLELES = frozenset(COMPLEMENT)

#: Minimum markers that must agree before a build or strand is declared. One matching
#: marker is a coincidence; the threshold makes the conclusion rest on a panel.
MIN_BUILD_MARKERS = 3
MIN_STRAND_MARKERS = 3

UNAVAILABLE = "NÃO DISPONÍVEL"


class ProvenanceProbeError(ValueError):
    """The probe could not run, as distinct from reaching an inconclusive verdict."""


def load_markers(path: Path) -> dict[str, Any]:
    """Read the two-assembly marker table, refusing anything a strand verdict cannot rest on.

    Every rule is enforced here — schema, non-empty table, object entries, unique rsids,
    coordinates present, well-formed alleles, palindromes flagged — because this is the only
    loader. `array_pipeline.qc` delegates to it rather than re-implementing the checks: two
    copies of the same rules eventually disagree, and the one that drifted would be the one
    licensing a strand verdict.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != MARKERS_SCHEMA:
        raise ProvenanceProbeError(f"unsupported marker table schema: {payload.get('schema')!r}")
    if not str(payload.get("source") or "").strip():
        raise ProvenanceProbeError("marker table must cite its source")
    markers = payload.get("markers")
    if not isinstance(markers, list) or not markers:
        raise ProvenanceProbeError("marker table must contain markers")
    seen_rsids: set[str] = set()
    for marker in markers:
        if not isinstance(marker, dict):
            raise ProvenanceProbeError("marker table entries must be objects")
        raw_rsid = marker.get("rsid")
        if not isinstance(raw_rsid, str) or not raw_rsid.strip():
            raise ProvenanceProbeError("marker rsid must be a non-empty string")
        rsid = raw_rsid.strip()
        normalized_rsid = rsid.lower()
        if normalized_rsid in seen_rsids:
            raise ProvenanceProbeError(f"{rsid}: duplicate marker rsid")
        seen_rsids.add(normalized_rsid)
        for build in ("grch37", "grch38"):
            spec = marker.get(build)
            if not isinstance(spec, dict) or "chromosome" not in spec or "position" not in spec:
                raise ProvenanceProbeError(f"{rsid}: missing {build} coordinates")
            position = spec.get("position")
            if (
                isinstance(position, bool)
                or not isinstance(position, int)
                or position < 1
            ):
                raise ProvenanceProbeError(
                    f"{rsid}: {build} position must be a positive integer"
                )
        alleles = marker.get("plus_alleles")
        if not isinstance(alleles, list) or len(alleles) != 2:
            raise ProvenanceProbeError(f"{rsid}: plus_alleles must list two alleles")
        normalized = [str(allele or "").strip().upper() for allele in alleles]
        if any(allele not in VALID_ALLELES for allele in normalized):
            raise ProvenanceProbeError(
                f"{rsid}: plus_alleles must contain only A, C, G or T; got {alleles!r}"
            )
        if len(set(normalized)) != 2:
            raise ProvenanceProbeError(
                f"{rsid}: plus_alleles must describe two distinct alleles"
            )
        marker["plus_alleles"] = normalized
        if set(normalized) == {COMPLEMENT[normalized[0]], COMPLEMENT[normalized[1]]} and not marker.get("palindromic"):
            # A/T and C/G are their own complement pair; a table that failed to flag one
            # would silently contribute a meaningless vote to the strand verdict.
            raise ProvenanceProbeError(f"{rsid}: palindromic pair must be flagged")
    return payload


def _read_markers_from_array(path: Path, wanted: set[str]) -> dict[str, dict[str, str]]:
    """Read just the wanted markers out of an array file, keyed by rsid.

    Only the requested rsids are retained: the probe needs a handful of loci out of hundreds
    of thousands, and holding the rest would trade memory for nothing.
    """
    import csv

    found: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    duplicates: set[str] = set()
    fh, _ = _text_stream(path)
    try:
        header, _meta = _read_header_and_metadata(fh)
        try:
            schema = detect_schema(header)
        except ValueError as exc:
            raise ProvenanceProbeError(str(exc)) from exc
        genotype_column = (
            "CONSENSUS_RESULT" if schema.startswith("harmonized") else "RESULT"
        )
        for row in csv.DictReader(fh, fieldnames=header):
            rsid = (row.get("RSID") or "").strip().lower()
            if rsid not in wanted:
                continue
            if rsid in seen:
                duplicates.add(rsid)
                found.pop(rsid, None)
                continue
            seen.add(rsid)
            status = (row.get("STATUS") or "").strip()
            if status.lower() in UNRESOLVED_OVERLAP_STATUSES:
                continue
            found[rsid] = {
                "chromosome": (row.get("CHROMOSOME") or "").strip().upper(),
                "position": (row.get("POSITION") or "").strip(),
                "genotype": _canonical_gt(row.get(genotype_column)) or "",
                "status": status,
            }
    finally:
        fh.close()
    for rsid in duplicates:
        found.pop(rsid, None)
    return found


def probe(array_path: Path, markers_path: Path) -> dict[str, Any]:
    """Return a verdict for build and strand, with the per-marker evidence behind each."""
    table = load_markers(Path(markers_path))
    markers = {str(m["rsid"]).lower(): m for m in table["markers"]}
    observed = _read_markers_from_array(Path(array_path), set(markers))

    build_evidence: list[dict[str, Any]] = []
    grch37 = grch38 = 0
    for rsid, marker in sorted(markers.items()):
        row = observed.get(rsid)
        if row is None or not row["position"].isdigit():
            continue
        position = int(row["position"])
        chromosome = row["chromosome"]
        hit37 = chromosome == str(marker["grch37"]["chromosome"]).upper() and position == int(marker["grch37"]["position"])
        hit38 = chromosome == str(marker["grch38"]["chromosome"]).upper() and position == int(marker["grch38"]["position"])
        grch37 += int(hit37)
        grch38 += int(hit38)
        build_evidence.append(
            {
                "rsid": rsid,
                "observed": f"{chromosome}:{position}",
                "grch37": f"{marker['grch37']['chromosome']}:{marker['grch37']['position']}",
                "grch38": f"{marker['grch38']['chromosome']}:{marker['grch38']['position']}",
                "matches": "GRCh37" if hit37 and not hit38 else ("GRCh38" if hit38 and not hit37 else "nenhum"),
            }
        )

    if grch37 >= MIN_BUILD_MARKERS and grch38 == 0:
        build, build_status = "GRCh37", "VERIFICADO"
    elif grch38 >= MIN_BUILD_MARKERS and grch37 == 0:
        build, build_status = "GRCh38", "VERIFICADO"
    else:
        build, build_status = None, UNAVAILABLE

    strand_evidence: list[dict[str, Any]] = []
    plus = minus = 0
    for rsid, marker in sorted(markers.items()):
        row = observed.get(rsid)
        if row is None or not row["genotype"]:
            continue
        if marker.get("palindromic"):
            strand_evidence.append(
                {"rsid": rsid, "genotype": row["genotype"], "verdict": "não informativo (palindrômico)"}
            )
            continue
        letters = set(row["genotype"])
        if not letters <= set(COMPLEMENT):
            # Indel codes (II/DD/DI) carry no strand information.
            strand_evidence.append(
                {"rsid": rsid, "genotype": row["genotype"], "verdict": "não informativo (não é SNP)"}
            )
            continue
        plus_set = {str(a).upper() for a in marker["plus_alleles"]}
        minus_set = {COMPLEMENT[a] for a in plus_set}
        fits_plus = letters <= plus_set
        fits_minus = letters <= minus_set
        if fits_plus and not fits_minus:
            plus += 1
            verdict = "plus"
        elif fits_minus and not fits_plus:
            minus += 1
            verdict = "minus"
        else:
            verdict = "ambíguo"
        strand_evidence.append(
            {
                "rsid": rsid,
                "genotype": row["genotype"],
                "plus_alleles": sorted(plus_set),
                "minus_alleles": sorted(minus_set),
                "verdict": verdict,
            }
        )

    if plus >= MIN_STRAND_MARKERS and minus == 0:
        strand, strand_status = "forward", "VERIFICADO"
    elif minus >= MIN_STRAND_MARKERS and plus == 0:
        # The file is internally consistent but reported on the reverse strand. That is a
        # determinate answer, and it is *not* usable as "forward": downstream comparisons
        # against plus-strand references would be inverted.
        strand, strand_status = "reverse", "VERIFICADO"
    else:
        strand, strand_status = None, UNAVAILABLE

    return {
        "schema": SCHEMA,
        "evaluated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_sha256": sha256_file(Path(array_path)),
        "marker_table": {
            "id": table.get("id"),
            "version": table.get("version"),
            "source": table.get("source"),
            "verification_status": table.get("verification_status", "PROPOSTO"),
        },
        "build": {
            "status": build_status,
            "value": build,
            "grch37_matches": grch37,
            "grch38_matches": grch38,
            "threshold": MIN_BUILD_MARKERS,
            "evidence": build_evidence,
        },
        "strand": {
            "status": strand_status,
            "value": strand,
            "plus_matches": plus,
            "minus_matches": minus,
            "threshold": MIN_STRAND_MARKERS,
            "evidence": strand_evidence,
        },
    }


#: Strand verdicts that BUILD_STRAND_GATE exists to establish. `reverse` is a determinate
#: verdict too, and a true one — but it is knowledge that the file is flipped, never
#: permission to interpret it as though it were not.
ATTESTABLE_STRANDS = frozenset({"forward"})


def attestation_from_probe(result: dict[str, Any], kind: str) -> str | None:
    """Render a probe verdict as the structured attestation `qc.inspect_array` accepts.

    Returns None when the verdict cannot support the gate, so an unusable verdict cannot
    become an attestation by omission. Two cases return None, and the second was a real hole:

    * the probe was inconclusive — there is nothing to attest;
    * the probe determined the file is on the **reverse** strand. This module used to emit a
      full VERIFICADO/SATISFIED attestation for that verdict, whose justification read
      "Veredito: reverse". Handed to `run_snp_array.py --strand forward` — the only strand
      the CLI offers — it validated, because nothing compared the attestation's verdict with
      the declared value. BUILD_STRAND_GATE passed and the run reported operational_status
      VERIFICADO on a file whose every allele is the complement of what the registries mean.
      The probe's own honest finding was the credential that certified the opposite of it.

    `qc._verified_provenance` now also refuses an attestation whose `asserted_value`
    disagrees with the declared one, so the two halves fail closed independently.
    """
    if kind not in {"reference_build", "strand"}:
        raise ProvenanceProbeError(f"unknown attestation kind: {kind!r}")
    if (result.get("marker_table") or {}).get("verification_status") != "VERIFICADO":
        return None
    block = result["build"] if kind == "reference_build" else result["strand"]
    if block["status"] != "VERIFICADO" or not block["value"]:
        return None
    if kind == "strand" and str(block["value"]).lower() not in ATTESTABLE_STRANDS:
        return None

    if kind == "reference_build":
        justification = (
            f"Build determinado por concordância de coordenadas: {block['grch37_matches']} marcadores "
            f"coincidem com GRCh37 e {block['grch38_matches']} com GRCh38, sobre a tabela "
            f"{result['marker_table']['id']} {result['marker_table']['version']}. Veredito: {block['value']}."
        )
    else:
        justification = (
            f"Fita determinada por conjunto de alelos: {block['plus_matches']} marcadores não "
            f"palindrômicos compatíveis apenas com a fita plus e {block['minus_matches']} apenas com a "
            f"minus, sobre a tabela {result['marker_table']['id']} {result['marker_table']['version']}. "
            f"Veredito: {block['value']}."
        )

    payload = {
        "status": "VERIFICADO",
        "decision": "SATISFIED",
        # The verdict in machine-readable form, so the gate can check that the value being
        # declared is the value this attestation actually establishes.
        "asserted_value": block["value"],
        "justification": justification,
        "evidence_refs": [
            f"array-provenance-probe:{kind}",
            f"marker-table:{result['marker_table']['id']}:{result['marker_table']['version']}",
        ],
        "trace": {
            "attestation_id": f"provenance-probe-{kind}-{result['input_sha256'][:16]}",
            "created_at": result["evaluated_at"],
            "actor_type": "SOFTWARE",
            "actor_id": "array_pipeline.provenance_probe",
            "method": (
                "coordinate concordance against a pinned two-assembly marker table"
                if kind == "reference_build"
                else "plus/minus allele-set discrimination over non-palindromic markers"
            ),
            "run_id": f"probe-{result['input_sha256'][:16]}",
            "input_sha256": [result["input_sha256"]],
            "output_sha256": [],
            "tool_versions": {
                "array_pipeline.provenance_probe": "v1",
                "marker_table": f"{result['marker_table']['id']}:{result['marker_table']['version']}",
            },
            "marker_table_verification_status": result["marker_table"]["verification_status"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
