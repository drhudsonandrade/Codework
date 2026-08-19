#!/usr/bin/env python3
"""Derive the clinically assessed allele of each target from dbSNP and ClinVar.

`array_pipeline/completeness.py` promotes a locus to NÃO DETECTADO only when the target
registry declares which allele was being looked for. Without that, a cleanly called locus
stays OBSERVADO and no absence can be stated — which is why all 29 targets sat in OBSERVADO
and the matrix could never say "tested and absent".

The assessed allele is not something to type from memory. It is derived here:

1. **dbSNP** supplies the reference base, from the SPDI `deleted_sequence`, which is
   authoritative and always on the plus strand.
2. **ClinVar** supplies the alternate that carries a clinical assertion, from each record's
   `canonical_spdi`.
3. The two are joined **by coordinate**, not by text. A plain rsid search in ClinVar returns
   unrelated records — querying `rs6025` also returns an LRRK2 variant — so a record counts
   only when its SPDI position equals the dbSNP GRCh38 position for that rsid.

Where ClinVar carries no assertion, or carries assertions for more than one alternate, the
target is left without an assessed allele and the reason is recorded. Picking one would be
inventing the clinical question the locus is being asked.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_provenance_markers import fetch_refsnp, frequency_alleles, placements

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_TARGETS = ROOT / "config/partial_genome_annotation_targets.json"
DEFAULT_EVIDENCE = ROOT / "docs/evidence/ASSESSED_ALLELES_CLINVAR.json"
SCHEMA = "genoma-assessed-allele-curation-v1"

REQUEST_INTERVAL_SECONDS = 0.4
BASES = frozenset("ACGT")

#: ClinVar classifications that constitute a clinical assertion about the alternate allele.
#: A record with no assertion, or one asserting benignity, does not tell us which allele the
#: locus is being interrogated *for*.
ASSERTING = (
    "pathogenic",
    "likely pathogenic",
    "risk factor",
    "drug response",
    "association",
)
#: Classifications that explicitly say the alternate is not the clinical question.
NON_ASSERTING = ("benign", "likely benign")


class CurationError(RuntimeError):
    pass


def _get(url: str, *, attempts: int = 4) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "genoma-assessed-allele/1.0"}
    )
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise CurationError(f"eutils fetch failed for {url} after {attempts} attempts: {last}")


def clinvar_records(rsid: str) -> list[dict[str, Any]]:
    """Every ClinVar summary the rsid text search returns, unfiltered."""
    term = urllib.parse.quote(rsid)
    found = _get(f"{EUTILS}/esearch.fcgi?db=clinvar&term={term}&retmax=50&retmode=json")
    ids = found.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    time.sleep(REQUEST_INTERVAL_SECONDS)
    summary = _get(f"{EUTILS}/esummary.fcgi?db=clinvar&id={','.join(ids[:50])}&retmode=json")
    result = summary.get("result", {})
    return [result[uid] for uid in result.get("uids", []) if uid in result]


def _classification(record: dict[str, Any]) -> str:
    for key in ("germline_classification", "clinical_significance", "somatic_classification"):
        block = record.get(key)
        if isinstance(block, dict) and block.get("description"):
            return str(block["description"])
    return ""


def _spdi(record: dict[str, Any]) -> tuple[str, int, str, str] | None:
    variation = (record.get("variation_set") or [{}])[0]
    raw = variation.get("canonical_spdi") or ""
    parts = raw.split(":")
    if len(parts) != 4:
        return None
    sequence, position, deleted, inserted = parts
    if not position.isdigit():
        return None
    return sequence, int(position), deleted.upper(), inserted.upper()


def cpic_variant_alleles(rsid: str, registry: dict[str, Any] | None) -> dict[str, list[str]]:
    """Which named CPIC alleles this rsid defines, and with which base.

    CPIC is the right source for a pharmacogenomic target. ClinVar classifies TPMT*3B as
    `Benign/Likely benign` — correctly, for *disease* — while CPIC defines it as a
    no-function allele that changes thiopurine dosing. Reading only ClinVar therefore left
    real pharmacogenetic targets with no assessed allele.
    """
    out: dict[str, list[str]] = {}
    for gene, spec in (registry or {}).get("genes", {}).items():
        for allele, definition in (spec.get("alleles") or {}).items():
            for position in definition.get("defining", []):
                if str(position.get("rsid", "")).lower() == rsid:
                    out.setdefault(str(position["allele"]).upper(), []).append(allele)
    return out


def curate_target(rsid: str, pgx_registry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Join dbSNP's reference base with the alternate a source actually asserts.

    CPIC first for pharmacogenomic targets, then ClinVar, and dbSNP allele frequency to
    separate a real clinical alternate from a rare substitution sharing the coordinate.
    """
    refsnp = fetch_refsnp(rsid)
    time.sleep(REQUEST_INTERVAL_SECONDS)
    grch38 = placements(refsnp).get("GRCh38")
    if grch38 is None or not grch38.get("reference_allele"):
        return {
            "rsid": rsid,
            "assessed_allele": None,
            "status": "NÃO DISPONÍVEL",
            "reason": "dbSNP has no GRCh38 placement with a single-base reference allele",
        }

    # SPDI positions are 0-based; the placement is 1-based.
    expected_position = int(grch38["position"]) - 1
    reference = grch38["reference_allele"]

    matched: list[dict[str, Any]] = []
    considered = 0
    for record in clinvar_records(rsid):
        considered += 1
        spdi = _spdi(record)
        if spdi is None:
            continue
        _sequence, position, deleted, inserted = spdi
        # Coordinate join: a text search for an rsid also returns unrelated variants.
        if position != expected_position or deleted != reference:
            continue
        if inserted == reference or inserted not in BASES:
            continue  # the reference-identity record, or an indel
        classification = _classification(record)
        lowered = classification.lower()
        asserts = any(term in lowered for term in ASSERTING) and not all(
            term in lowered for term in NON_ASSERTING
        )
        matched.append(
            {
                "alternate": inserted,
                "classification": classification,
                "asserts_clinical_relevance": asserts,
                "accession": record.get("accession"),
                "title": record.get("title"),
                "canonical_spdi": (record.get("variation_set") or [{}])[0].get("canonical_spdi"),
            }
        )

    asserting = sorted({m["alternate"] for m in matched if m["asserts_clinical_relevance"]})
    frequencies = frequency_alleles(refsnp)
    base: dict[str, Any] = {
        "dbsnp_frequencies": frequencies,
        "rsid": rsid,
        "reference_allele": reference,
        "grch38": {"chromosome": grch38["chromosome"], "position": grch38["position"]},
        "dbsnp_build": refsnp.get("last_update_build_id"),
        "clinvar_records_considered": considered,
        "clinvar_records_at_this_coordinate": matched,
    }
    cpic = cpic_variant_alleles(rsid, pgx_registry)
    base["cpic_defined_alleles"] = cpic

    if len(cpic) == 1:
        allele, names = next(iter(cpic.items()))
        base.update(
            {
                "assessed_allele": allele,
                "status": "VERIFICADO",
                "source": "CPIC",
                "reason": (
                    f"CPIC defines {', '.join(sorted(names))} by base {allele} at this position; "
                    "a pharmacogenomic target's assessed allele is the one its guideline names"
                ),
            }
        )
        return base
    if len(cpic) > 1:
        # The same two-source test used below for ClinVar. rs1142345 defines TPMT*3A/*3C
        # with C and TPMT*41 with G, but dbSNP observes only C in a cohort — so requiring
        # population support disambiguates without arbitrating between the definitions.
        observed = sorted(a for a in cpic if frequencies.get(a, 0.0) > 0.0)
        if len(observed) == 1:
            detail = "; ".join(
                "{}={}".format(base_, ", ".join(sorted(names)))
                for base_, names in sorted(cpic.items())
            )
            base.update(
                {
                    "assessed_allele": observed[0],
                    "status": "VERIFICADO",
                    "source": "CPIC + dbSNP frequency",
                    "reason": (
                        f"CPIC defines alleles by {', '.join(sorted(cpic))} at this position "
                        f"({detail}), "
                        f"and dbSNP observes only {observed[0]} in a population cohort "
                        f"({frequencies.get(observed[0])})"
                    ),
                }
            )
            return base
        base.update(
            {
                "assessed_allele": None,
                "status": "NÃO DISPONÍVEL",
                "source": "CPIC",
                "reason": (
                    f"CPIC defines different alleles by different bases here ({', '.join(sorted(cpic))}) "
                    f"and dbSNP observes {len(observed)} of them in a cohort; the locus "
                    "interrogates more than one question"
                ),
            }
        )
        return base

    # Frequency separates a real clinical alternate from a rare substitution that happens to
    # share the coordinate. rs4244285 carries 19 ClinVar records asserting A (CYP2C19*2) and
    # one asserting T; counting records would be arbitration, but requiring the alternate to
    # be observed in a population cohort is a second independent source agreeing.
    supported = sorted(a for a in asserting if frequencies.get(a, 0.0) > 0.0)
    if len(asserting) > 1 and len(supported) == 1:
        base.update(
            {
                "assessed_allele": supported[0],
                "status": "VERIFICADO",
                "source": "ClinVar + dbSNP frequency",
                "reason": (
                    f"ClinVar asserts {', '.join(asserting)} at this coordinate, and dbSNP reports a "
                    f"population frequency only for {supported[0]} "
                    f"({frequencies.get(supported[0])}); the others are not observed in the cohort"
                ),
            }
        )
        return base

    if len(asserting) == 1:
        base.update(
            {
                "assessed_allele": asserting[0],
                "status": "VERIFICADO",
                "source": "ClinVar",
                "reason": (
                    "ClinVar carries exactly one clinically asserted alternate at the dbSNP "
                    "GRCh38 coordinate for this rsid"
                ),
            }
        )
    elif not asserting:
        base.update(
            {
                "assessed_allele": None,
                "status": "NÃO DISPONÍVEL",
                "reason": (
                    "no ClinVar record at this coordinate carries a pathogenic, risk-factor, "
                    "drug-response or association assertion; the allele being interrogated is "
                    "therefore not established"
                ),
            }
        )
    else:
        base.update(
            {
                "assessed_allele": None,
                "status": "NÃO DISPONÍVEL",
                "reason": (
                    f"ClinVar asserts more than one alternate at this coordinate ({', '.join(asserting)}); "
                    "choosing one would invent the clinical question this locus is being asked"
                ),
            }
        )
    return base


def curate(targets_path: Path, pgx_registry_path: Path | None = None) -> dict[str, Any]:
    payload = json.loads(Path(targets_path).read_text(encoding="utf-8"))
    registry = (
        json.loads(Path(pgx_registry_path).read_text(encoding="utf-8"))
        if pgx_registry_path and Path(pgx_registry_path).exists()
        else None
    )
    results = [curate_target(str(t["rsid"]).lower(), registry) for t in payload["targets"]]
    verified = [r for r in results if r["status"] == "VERIFICADO"]
    return {
        "schema": SCHEMA,
        "curated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": [
            "NCBI dbSNP RefSNP API (api.ncbi.nlm.nih.gov/variation/v0/refsnp) — reference base",
            "NCBI ClinVar via E-utilities (eutils.ncbi.nlm.nih.gov, db=clinvar) — asserted alternate",
            "CPIC allele definitions (config/pgx_allele_definitions.json) — pharmacogenomic targets",
        ],
        "method": (
            "dbSNP supplies the plus-strand reference base from the SPDI deleted_sequence; "
            "ClinVar supplies the alternate from canonical_spdi. The two are joined by "
            "coordinate, never by text, because an rsid text search in ClinVar also returns "
            "unrelated variants. A target with no asserted alternate, or with more than one, "
            "is left without an assessed allele and the reason is recorded."
        ),
        "targets_curated": len(results),
        "assessed_alleles_established": len(verified),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", default=str(DEFAULT_TARGETS))
    parser.add_argument("--output", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--pgx-registry", default=str(ROOT / "config/pgx_allele_definitions.json"))
    parser.add_argument("--apply", action="store_true", help="write assessed_allele into the registry")
    args = parser.parse_args()

    evidence = curate(Path(args.targets), Path(args.pgx_registry))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.apply:
        registry = json.loads(Path(args.targets).read_text(encoding="utf-8"))
        by_rsid = {r["rsid"]: r for r in evidence["results"]}
        for target in registry["targets"]:
            record = by_rsid.get(str(target["rsid"]).lower())
            if record and record["assessed_allele"]:
                target["assessed_allele"] = record["assessed_allele"]
                target["assessed_allele_source"] = record.get("source", "ClinVar")
                target["assessed_allele_evidence"] = out.name
            else:
                target.pop("assessed_allele", None)
                target["assessed_allele_status"] = record["status"] if record else "NÃO DISPONÍVEL"
                target["assessed_allele_reason"] = record["reason"] if record else "not curated"
        registry["assessed_allele_curation"] = {
            "curated_at": evidence["curated_at"],
            "sources": evidence["sources"],
            "evidence": f"docs/evidence/{out.name}",
            "established": evidence["assessed_alleles_established"],
            "total": evidence["targets_curated"],
        }
        Path(args.targets).write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(
        f"alelos avaliados estabelecidos: {evidence['assessed_alleles_established']}"
        f"/{evidence['targets_curated']}"
    )
    for record in evidence["results"]:
        if record["status"] != "VERIFICADO":
            print(f"  {record['rsid']}: {record['reason'][:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
