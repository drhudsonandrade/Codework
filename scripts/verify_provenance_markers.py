#!/usr/bin/env python3
"""Verify the provenance marker table against dbSNP, the authoritative source.

`config/array_provenance_markers.json` decides which reference build and which strand a
SNP-array file uses, and that verdict unlocks `BUILD_STRAND_GATE` for everything
downstream. The table was curated by hand and shipped as `PROPOSTO` precisely because an
error in it is the one mistake in this design that propagates silently into every report.

This script removes the hand-curation from the trust chain. It fetches each marker from the
dbSNP RefSNP API and compares four things per assembly:

* the chromosome, derived from the RefSeq accession (`NC_000019` -> 19);
* the 1-based position (SPDI positions are 0-based, so this adds one);
* the allele pair, read from the SPDI deleted/inserted sequences — **SPDI is always
  expressed on the plus strand of the reference**, which is exactly the convention the
  strand probe needs;
* whether the pair is palindromic, recomputed rather than trusted.

It writes an evidence file recording every comparison. `tests/test_provenance_markers.py`
then checks the shipped table against that evidence offline, so CI does not depend on
network access while the table still cannot drift from what dbSNP said.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.provenance_probe import COMPLEMENT, load_markers

REFSNP_URL = "https://api.ncbi.nlm.nih.gov/variation/v0/refsnp/{rsid}"
DEFAULT_EVIDENCE = ROOT / "docs/evidence/ARRAY_PROVENANCE_MARKERS_DBSNP.json"
SCHEMA = "genoma-provenance-marker-verification-v1"

#: NCBI asks for at most three requests a second without an API key.
REQUEST_INTERVAL_SECONDS = 0.4


class MarkerVerificationError(RuntimeError):
    pass


def _chromosome_from_accession(seq_id: str) -> str | None:
    """`NC_000019.10` -> `19`; 23 and 24 are X and Y."""
    if not seq_id.startswith("NC_"):
        return None
    try:
        number = int(seq_id.split(".")[0].removeprefix("NC_"))
    except ValueError:
        return None
    if 1 <= number <= 22:
        return str(number)
    return {23: "X", 24: "Y", 12920: "MT"}.get(number)


def _numeric_rsid(rsid: str) -> str:
    numeric = _numeric_rsid(rsid)
    return numeric


def fetch_refsnp(rsid: str, *, timeout: int = 30) -> dict[str, Any]:
    normalized = str(rsid or "").strip().lower()
    numeric = normalized.removeprefix("rs")
    if not numeric or not numeric.isdecimal():
        raise MarkerVerificationError(
            f"{rsid!r}: rsid must be a non-empty 'rs' identifier containing decimal digits"
        )
    request = urllib.request.Request(
        REFSNP_URL.format(rsid=numeric),
        headers={"Accept": "application/json", "User-Agent": "genoma-provenance-verifier/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MarkerVerificationError(
            f"{rsid}: dbSNP HTTP {exc.code}: {exc.reason}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MarkerVerificationError(f"{rsid}: dbSNP fetch failed: {exc}") from exc


def placements(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract one record per assembly: chromosome, 1-based position, reference allele."""
    out: dict[str, dict[str, Any]] = {}
    snapshot = payload.get("primary_snapshot_data") or {}
    for placement in snapshot.get("placements_with_allele", []):
        traits = placement.get("placement_annot", {}).get("seq_id_traits_by_assembly", [])
        names = [t.get("assembly_name", "") for t in traits]
        if not names:
            continue
        assembly = "GRCh37" if names[0].startswith("GRCh37") else ("GRCh38" if names[0].startswith("GRCh38") else None)
        if assembly is None:
            continue
        chromosome = _chromosome_from_accession(placement.get("seq_id", ""))
        if chromosome is None:
            continue
        submitted: set[str] = set()
        reference: str | None = None
        position: int | None = None
        for allele in placement.get("alleles", []):
            spdi = allele.get("allele", {}).get("spdi")
            if not spdi:
                continue
            deleted = spdi.get("deleted_sequence")
            if deleted and len(deleted) == 1 and deleted in COMPLEMENT:
                # Position and reference must come from the same reference SPDI allele.
                reference = deleted
                position = int(spdi["position"]) + 1  # SPDI is 0-based
            inserted = spdi.get("inserted_sequence")
            if inserted and len(inserted) == 1 and inserted in COMPLEMENT:
                submitted.add(inserted)
        if position is None:
            continue
        out[assembly] = {
            "assembly_name": names[0],
            "seq_id": placement.get("seq_id"),
            "chromosome": chromosome,
            "position": position,
            "reference_allele": reference,
            "submitted_alleles": sorted(submitted),
        }
    return out


def frequency_alleles(payload: dict[str, Any]) -> dict[str, float]:
    """Allele frequencies from the largest-cohort study dbSNP reports for this variant.

    dbSNP's submitted-allele list is a union over every submission and routinely contains
    all four bases for a common SNP, including alternates seen a handful of times. Comparing
    a marker table against that union produces false discrepancies, and — worse for this
    module — a strand test built on it would be uninformative at almost every site, because
    a four-allele set is its own complement.

    What the strand test actually needs is the biallelic pair that real genotypes carry, so
    this reads observed frequencies and keeps the study with the largest cohort.
    """
    best_study: str | None = None
    best_total = 0
    totals: dict[str, int] = {}
    for annotation in (payload.get("primary_snapshot_data") or {}).get("allele_annotations", []):
        for entry in annotation.get("frequency", []):
            study = entry.get("study_name")
            total = int(entry.get("total_count") or 0)
            if not study:
                continue
            totals[study] = max(totals.get(study, 0), total)
            if total > best_total:
                best_total, best_study = total, study
    if best_study is None:
        return {}

    frequencies: dict[str, float] = {}
    for annotation in (payload.get("primary_snapshot_data") or {}).get("allele_annotations", []):
        for entry in annotation.get("frequency", []):
            if entry.get("study_name") != best_study:
                continue
            allele = entry.get("observation", {}).get("inserted_sequence")
            total = int(entry.get("total_count") or 0)
            if allele and len(allele) == 1 and allele in COMPLEMENT and total:
                frequencies[allele] = round(int(entry.get("allele_count") or 0) / total, 6)
    return frequencies


def _fetch_with_retries(rsid: str, *, attempts: int = 4) -> dict[str, Any]:
    _numeric_rsid(rsid)
    last: MarkerVerificationError | None = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(max(REQUEST_INTERVAL_SECONDS, 2 ** (attempt - 1)))
        try:
            return fetch_refsnp(rsid)
        except MarkerVerificationError as exc:
            cause = exc.__cause__
            if (
                isinstance(cause, urllib.error.HTTPError)
                and cause.code != 429
                and not 500 <= cause.code < 600
            ):
                raise
            last = exc
    raise MarkerVerificationError(
        f"{rsid}: dbSNP fetch failed after {attempts} attempts: {last}"
    ) from last


def verify(markers_path: Path, *, offline_payloads: dict[str, dict] | None = None) -> dict[str, Any]:
    table = load_markers(markers_path)
    results: list[dict[str, Any]] = []
    discrepancies: list[str] = []

    for index, marker in enumerate(table["markers"]):
        rsid = str(marker["rsid"])
        payload = (offline_payloads or {}).get(rsid)
        if payload is None:
            if index:
                time.sleep(REQUEST_INTERVAL_SECONDS)
            try:
                payload = _fetch_with_retries(rsid)
            except MarkerVerificationError as exc:
                discrepancies.append(str(exc))
                results.append(
                    {
                        "rsid": rsid,
                        "gene": marker.get("gene"),
                        "status": "NÃO VERIFICADO",
                        "error": str(exc),
                        "assemblies": {},
                    }
                )
                continue

        observed = placements(payload)
        record: dict[str, Any] = {
            "rsid": rsid,
            "gene": marker.get("gene"),
            "dbsnp_build": payload.get("last_update_build_id"),
            "variant_type": (payload.get("primary_snapshot_data") or {}).get("variant_type"),
            "assemblies": {},
        }

        for assembly, key in (("GRCh37", "grch37"), ("GRCh38", "grch38")):
            declared = marker[key]
            actual = observed.get(assembly)
            if actual is None:
                discrepancies.append(f"{rsid}/{assembly}: dbSNP has no placement")
                record["assemblies"][assembly] = {"status": "AUSENTE", "declared": declared}
                continue
            chromosome_ok = str(declared["chromosome"]) == actual["chromosome"]
            position_ok = int(declared["position"]) == actual["position"]
            if not chromosome_ok:
                discrepancies.append(
                    f"{rsid}/{assembly}: chromosome declared {declared['chromosome']} but dbSNP says {actual['chromosome']}"
                )
            if not position_ok:
                discrepancies.append(
                    f"{rsid}/{assembly}: position declared {declared['position']} but dbSNP says {actual['position']}"
                )
            record["assemblies"][assembly] = {
                "status": "CONFERE" if chromosome_ok and position_ok else "DIVERGE",
                "declared": {"chromosome": str(declared["chromosome"]), "position": int(declared["position"])},
                "dbsnp": {"chromosome": actual["chromosome"], "position": actual["position"]},
                "seq_id": actual["seq_id"],
                "assembly_name": actual["assembly_name"],
            }

        # SPDI is expressed on the plus strand, so the pair is directly comparable. The
        # reference base is authoritative; the alternate is the highest-frequency
        # non-reference allele in the largest cohort dbSNP reports.
        placement = observed.get("GRCh38") or observed.get("GRCh37")
        declared_alleles = sorted(str(a).upper() for a in marker["plus_alleles"])
        frequencies = frequency_alleles(payload)
        record["frequencies"] = frequencies

        if placement is None or not placement.get("reference_allele"):
            discrepancies.append(f"{rsid}: no placement from which to read the reference allele")
            record["alleles"] = {"status": "AUSENTE", "declared": declared_alleles}
            results.append(record)
            continue

        reference_allele = placement["reference_allele"]
        alternates = sorted(
            ((a, f) for a, f in frequencies.items() if a != reference_allele),
            key=lambda item: item[1],
            reverse=True,
        )
        alternate_allele = alternates[0][0] if alternates and alternates[0][1] > 0 else None

        problems: list[str] = []
        if reference_allele not in declared_alleles:
            problems.append(
                f"reference allele {reference_allele} is absent from the declared pair {declared_alleles}"
            )
        if alternate_allele is None:
            problems.append("dbSNP reports no frequency-supported alternate allele")
        elif sorted({reference_allele, alternate_allele}) != declared_alleles:
            problems.append(
                f"declared pair {declared_alleles} but dbSNP reference/major-alternate is "
                f"{sorted({reference_allele, alternate_allele})}"
            )

        pair = {reference_allele, alternate_allele} if alternate_allele else set(declared_alleles)
        expected_palindromic = pair in ({"A", "T"}, {"C", "G"})
        if bool(marker.get("palindromic")) != expected_palindromic:
            problems.append(
                f"palindromic flag is {bool(marker.get('palindromic'))} but the pair "
                f"{sorted(pair)} implies {expected_palindromic}"
            )

        discrepancies.extend(f"{rsid}: {p}" for p in problems)
        record["alleles"] = {
            "status": "CONFERE" if not problems else "DIVERGE",
            "declared": declared_alleles,
            "dbsnp_reference": reference_allele,
            "dbsnp_major_alternate": alternate_allele,
            "dbsnp_alternate_frequency": frequencies.get(alternate_allele) if alternate_allele else None,
            "dbsnp_submitted_alleles": placement["submitted_alleles"],
            "declared_palindromic": bool(marker.get("palindromic")),
            "dbsnp_palindromic": expected_palindromic,
        }
        results.append(record)

    return {
        "schema": SCHEMA,
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "NCBI dbSNP RefSNP API (api.ncbi.nlm.nih.gov/variation/v0/refsnp)",
        "source_note": (
            "SPDI coordinates are 0-based and expressed on the plus strand of the reference "
            "sequence; positions below are converted to 1-based and allele pairs are taken "
            "directly as plus-strand alleles."
        ),
        "marker_table": {"id": table.get("id"), "version": table.get("version")},
        "markers_checked": len(results),
        "status": "VERIFICADO" if not discrepancies else "DIVERGE",
        "discrepancies": discrepancies,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markers", default=str(ROOT / "config/array_provenance_markers.json"))
    parser.add_argument("--output", default=str(DEFAULT_EVIDENCE))
    args = parser.parse_args()

    result = verify(Path(args.markers))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"status: {result['status']}  ({result['markers_checked']} marcadores)")
    for line in result["discrepancies"]:
        print(f"  DIVERGE: {line}")
    return 0 if result["status"] == "VERIFICADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
