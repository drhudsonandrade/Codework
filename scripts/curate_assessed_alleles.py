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
4. A small, versioned owner-reviewed decision file may settle **allele identity only** when
   classification labels are heterogeneous. Such a decision is accepted only if the live
   ClinVar record at the dbSNP coordinate independently confirms the exact accession and
   alternate; it cannot override clinical significance or manufacture an absent record.

Where neither a source assertion nor a validated curated identity decision establishes one
alternate, the target is left without an assessed allele and the reason is recorded.
"""
from __future__ import annotations

import argparse
import json
import re
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

from scripts.https_transport import is_https, policy_opener
from scripts.verify_provenance_markers import fetch_refsnp, frequency_alleles, placements

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
GWAS_CATALOG = "https://www.ebi.ac.uk/gwas/rest/api"

#: How many supporting PMIDs to record per target. The durable reference is the ClinVar
#: accession or the CPIC allele name; the PMIDs are corroboration, and a variant like
#: rs6025 links 77 of them.
MAX_CITATIONS = 10
DEFAULT_TARGETS = ROOT / "config/partial_genome_annotation_targets.json"
DEFAULT_EVIDENCE = ROOT / "docs/evidence/ASSESSED_ALLELES_CLINVAR.json"
DEFAULT_CURATED_DECISIONS = ROOT / "config/assessed_allele_curated_decisions.json"
SCHEMA = "genoma-assessed-allele-curation-v1"
CURATED_DECISIONS_SCHEMA = "genoma-assessed-allele-curated-decisions-v1"

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


def _is_asserting_classification(classification: str) -> bool:
    """Whether a ClinVar classification actually asserts pathogenicity.

    The field is free text and carries compound values separated by `;`, `/` or `|`, so it is
    split and each term judged. "Conflicting" and "uncertain" are not assertions: reading them
    as one would let a variant nobody agreed on become an assessed allele.
    """
    terms = {
        term.strip()
        for term in re.split(r"[;/|]", str(classification).lower())
        if term.strip()
    }
    return bool(terms.intersection(ASSERTING)) and not bool(
        terms.intersection(NON_ASSERTING)
    )


class CurationError(RuntimeError):
    """A curation input could not be read, or the sources disagree irreconcilably."""


def _load_curated_decisions(path: Path | None) -> dict[str, dict[str, Any]]:
    """Load owner-reviewed allele-identity decisions as data, never as output overrides.

    Validation here is intentionally structural only. ``curate_target`` performs the decisive
    check against the live coordinate-matched ClinVar records before a decision may affect a
    result. This means changing the JSON alone cannot make an unsupported allele VERIFICADO.
    """
    if path is None or not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != CURATED_DECISIONS_SCHEMA:
        raise CurationError(
            f"curated decision file must use schema {CURATED_DECISIONS_SCHEMA}"
        )
    curations = payload.get("curations")
    if not isinstance(curations, dict):
        raise CurationError("curated decision file must contain an object named curations")
    out: dict[str, dict[str, Any]] = {}
    for raw_rsid, raw in curations.items():
        rsid = str(raw_rsid).lower().strip()
        if not re.fullmatch(r"rs\d+", rsid) or not isinstance(raw, dict):
            raise CurationError(f"invalid curated decision entry: {raw_rsid!r}")
        allele = str(raw.get("assessed_allele") or "").upper()
        accession = str(raw.get("clinvar_accession") or "").strip()
        basis = str(raw.get("basis") or "").strip()
        if allele not in BASES:
            raise CurationError(f"{rsid}: curated assessed_allele must be a single A/C/G/T base")
        if not re.fullmatch(r"VCV\d+", accession):
            raise CurationError(f"{rsid}: curated ClinVar accession is malformed")
        if raw.get("status") != "VERIFICADO":
            raise CurationError(f"{rsid}: curated decision must explicitly state VERIFICADO")
        if not basis:
            raise CurationError(f"{rsid}: curated decision must state its basis")
        out[rsid] = dict(raw)
        out[rsid]["assessed_allele"] = allele
        out[rsid]["clinvar_accession"] = accession
    return out


def _get(url: str, *, attempts: int = 4) -> dict[str, Any]:
    """One JSON request to a public registry, retrying transient failures.

    Retried because a single transport error should not discard a long curation run;
    exhausting the attempts raises rather than returning an empty result, which would read
    downstream as "the registry says nothing about this locus".
    """
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "genoma-assessed-allele/1.0"}
    )
    if not is_https(request.full_url):
        raise CurationError(f"refusing a non-HTTPS transport: {url}")

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with policy_opener(is_https, "the CPIC API").open(request, timeout=45) as response:  # nosec B310
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and not 500 <= exc.code < 600:
                raise CurationError(
                    f"eutils fetch failed for {url} with non-retriable HTTP status {exc.code}"
                ) from exc
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise CurationError(f"eutils fetch failed for {url} after {attempts} attempts: {last}")


def clinvar_records(rsid: str) -> list[dict[str, Any]]:
    """Every ClinVar summary the rsid text search returns, unfiltered."""
    term = urllib.parse.quote(rsid)
    ids: list[str] = []
    retstart = 0
    count: int | None = None
    while count is None or retstart < count:
        found = _get(
            f"{EUTILS}/esearch.fcgi?db=clinvar&term={term}"
            f"&retstart={retstart}&retmax=50&retmode=json"
        )
        search = found.get("esearchresult", {})
        if count is None:
            try:
                count = int(search.get("count") or 0)
            except (TypeError, ValueError) as exc:
                raise CurationError(f"{rsid}: ClinVar esearch returned an invalid count") from exc
        page = [str(uid) for uid in search.get("idlist", []) if str(uid)]
        ids.extend(page)
        retstart += len(page)
        if not page:
            break
        if retstart < count:
            time.sleep(REQUEST_INTERVAL_SECONDS)
    if count is not None and len(ids) < count:
        raise CurationError(
            f"{rsid}: ClinVar returned {len(ids)} of {count} record ids; refusing partial curation"
        )
    records: list[dict[str, Any]] = []
    for start in range(0, len(ids), 50):
        time.sleep(REQUEST_INTERVAL_SECONDS)
        chunk = ids[start : start + 50]
        summary = _get(
            f"{EUTILS}/esummary.fcgi?db=clinvar&id={','.join(chunk)}&retmode=json"
        )
        result = summary.get("result", {})
        records.extend(result[uid] for uid in result.get("uids", []) if uid in result)
    if len(records) != len(ids):
        raise CurationError(
            f"{rsid}: ClinVar returned {len(records)} of {len(ids)} summaries; refusing partial curation"
        )
    return records


def clinvar_citations(uids: list[str]) -> dict[str, Any]:
    """PubMed ids ClinVar links to these records, newest first, plus whether the lookup ran."""
    if not uids:
        return {"status": "EXECUTADO", "pmids": [], "reason": None}
    try:
        linked = _get(
            f"{EUTILS}/elink.fcgi?dbfrom=clinvar&db=pubmed&id={','.join(uids)}&retmode=json"
        )
    except CurationError as exc:
        return {
            "status": "NÃO DISPONÍVEL",
            "pmids": [],
            "reason": (
                f"a recuperação de citações no PubMed falhou ({exc}); a lista vazia abaixo "
                "não significa que não existam publicações vinculadas"
            ),
        }
    pmids: list[str] = []
    for linkset in linked.get("linksets", []):
        for db in linkset.get("linksetdbs", []):
            if db.get("linkname") == "clinvar_pubmed":
                pmids.extend(str(x) for x in db.get("links", []))
    seen: set[str] = set()
    ordered = [p for p in pmids if not (p in seen or seen.add(p))]
    return {"status": "EXECUTADO", "pmids": ordered[:MAX_CITATIONS], "reason": None}


def gwas_risk_alleles(rsid: str) -> dict[str, Any]:
    """Risk alleles the GWAS Catalog reports for this variant, with study p-values."""
    try:
        payload = _get(f"{GWAS_CATALOG}/singleNucleotidePolymorphisms/{rsid}/associations")
    except CurationError:
        return {"available": False, "risk_alleles": {}, "studies": 0}

    associations = (payload.get("_embedded") or {}).get("associations", [])
    by_allele: dict[str, list[dict[str, Any]]] = {}
    for association in associations:
        for locus in association.get("loci", []):
            for risk in locus.get("strongestRiskAlleles", []):
                name = str(risk.get("riskAlleleName") or "")
                if not name.lower().startswith(rsid.lower() + "-"):
                    continue
                allele = name.split("-", 1)[1].strip().upper()
                if allele not in BASES:
                    continue
                by_allele.setdefault(allele, []).append(
                    {
                        "p_value": f"{association.get('pvalueMantissa')}e{association.get('pvalueExponent')}",
                        "risk_frequency": association.get("riskFrequency"),
                    }
                )
    return {
        "available": True,
        "risk_alleles": {a: len(v) for a, v in sorted(by_allele.items())},
        "evidence": {a: v[:3] for a, v in sorted(by_allele.items())},
        "studies": len(associations),
    }


def _classification(record: dict[str, Any]) -> str:
    """The clinical significance ClinVar states, under whichever key this record uses."""
    for key in ("germline_classification", "clinical_significance", "somatic_classification"):
        block = record.get(key)
        if isinstance(block, dict) and block.get("description"):
            return str(block["description"])
    return ""


def _spdi(record: dict[str, Any]) -> tuple[str, int, str, str] | None:
    """The canonical SPDI as (sequence, position, deleted, inserted), or None if absent."""
    variation = (record.get("variation_set") or [{}])[0]
    raw = variation.get("canonical_spdi") or ""
    parts = raw.split(":")
    if len(parts) != 4:
        return None
    sequence, position, deleted, inserted = parts
    if not position.isdigit():
        return None
    return sequence, int(position), deleted.upper(), inserted.upper()


def registry_source(rsid: str, registry: dict[str, Any] | None) -> str:
    """Which source actually defined this rsid in the PGx registry."""
    for spec in (registry or {}).get("genes", {}).values():
        for definition in (spec.get("alleles") or {}).values():
            if any(str(x.get("rsid", "")).lower() == rsid for x in definition.get("defining", [])):
                if str(spec.get("variant_source") or "").strip():
                    return "ClinVar (fallback)"
                return "CPIC"
    return "CPIC"


def cpic_variant_alleles(rsid: str, registry: dict[str, Any] | None) -> dict[str, list[str]]:
    """Which named CPIC alleles this rsid defines, and with which base."""
    out: dict[str, list[str]] = {}
    for spec in (registry or {}).get("genes", {}).values():
        for allele, definition in (spec.get("alleles") or {}).items():
            for position in definition.get("defining", []):
                if str(position.get("rsid", "")).lower() == rsid:
                    out.setdefault(str(position["allele"]).upper(), []).append(allele)
    return out


def _apply_curated_identity_decision(
    rsid: str,
    base: dict[str, Any],
    matched: list[dict[str, Any]],
    decision: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Apply an owner-reviewed allele identity only after ClinVar independently agrees.

    This is the key safeguard against "forcing the JSON": the curated file is not sufficient
    evidence by itself. The live coordinate join must contain the same alternate under the
    same ClinVar accession. Classification is deliberately not rewritten; the decision says
    which alternate this target interrogates, not whether every condition submission agrees
    on pathogenicity.
    """
    if not decision:
        return None
    allele = str(decision.get("assessed_allele") or "").upper()
    accession = str(decision.get("clinvar_accession") or "")
    matching = [
        record
        for record in matched
        if record.get("alternate") == allele and str(record.get("accession") or "") == accession
    ]
    if not matching:
        raise CurationError(
            f"{rsid}: curated decision requests {allele}/{accession}, but the live ClinVar "
            "coordinate join does not confirm that accession and alternate"
        )
    if allele == base.get("reference_allele"):
        raise CurationError(f"{rsid}: curated assessed allele equals the dbSNP reference base")

    result = dict(base)
    result.update(
        {
            "assessed_allele": allele,
            "status": "VERIFICADO",
            "source": "ClinVar",
            "reason": (
                str(decision.get("basis") or "").strip()
                + " The live curation run independently confirmed the same ClinVar accession, "
                "GRCh38 coordinate and alternate before applying this identity decision."
            ),
            "curated_identity_decision": {
                "status": "VERIFICADO",
                "clinvar_accession": accession,
                "source_url": decision.get("source_url"),
                "canonical_spdi": decision.get("canonical_spdi"),
                "scope": "assessed-allele identity only; clinical significance is not overridden",
            },
        }
    )
    return result


def curate_target(
    rsid: str,
    pgx_registry: dict[str, Any] | None = None,
    curated_decisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Join dbSNP's reference base with the alternate a source actually asserts."""
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

    expected_position = int(grch38["position"]) - 1
    expected_sequence = str(grch38.get("seq_id") or "")
    reference = grch38["reference_allele"]

    matched: list[dict[str, Any]] = []
    matched_uids: list[str] = []
    considered = 0
    for record in clinvar_records(rsid):
        considered += 1
        spdi = _spdi(record)
        if spdi is None:
            continue
        sequence, position, deleted, inserted = spdi
        if (
            not expected_sequence
            or sequence != expected_sequence
            or position != expected_position
            or deleted != reference
        ):
            continue
        if inserted == reference or inserted not in BASES:
            continue
        classification = _classification(record)
        asserts = _is_asserting_classification(classification)
        if record.get("uid"):
            matched_uids.append(str(record["uid"]))
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

    cpic_pmids: list[str] = []
    for gene_spec in (pgx_registry or {}).get("genes", {}).values():
        for allele, definition in (gene_spec.get("alleles") or {}).items():
            if any(str(x.get("rsid", "")).lower() == rsid for x in definition.get("defining", [])):
                cpic_pmids.extend(str(c) for c in (definition.get("citations") or []))
    time.sleep(REQUEST_INTERVAL_SECONDS)
    citations = clinvar_citations(matched_uids)
    base["references"] = {
        "clinvar_accessions": sorted({str(m["accession"]) for m in matched if m.get("accession")}),
        "clinvar_pubmed": citations["pmids"],
        "clinvar_pubmed_retrieval": {
            "status": citations["status"],
            "reason": citations["reason"],
        },
        "cpic_pubmed": sorted(set(cpic_pmids))[:MAX_CITATIONS],
    }

    curated = _apply_curated_identity_decision(
        rsid,
        base,
        matched,
        (curated_decisions or {}).get(rsid),
    )
    if curated is not None:
        return curated

    if len(cpic) == 1:
        allele, names = next(iter(cpic.items()))
        source = registry_source(rsid, pgx_registry)
        base.update(
            {
                "assessed_allele": allele,
                "status": "VERIFICADO",
                "source": source,
                "reason": (
                    f"{source} defines {', '.join(sorted(names))} by base {allele} at this "
                    "position; a pharmacogenomic target's assessed allele is the one its "
                    "source names"
                ),
            }
        )
        return base
    if len(cpic) > 1:
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
                    "source": f"{registry_source(rsid, pgx_registry)} + dbSNP frequency",
                    "reason": (
                        f"{registry_source(rsid, pgx_registry)} defines alleles by "
                        f"{', '.join(sorted(cpic))} at this position ({detail}), "
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
                "source": registry_source(rsid, pgx_registry),
                "reason": (
                    f"{registry_source(rsid, pgx_registry)} defines different alleles by "
                    f"different bases here ({', '.join(sorted(cpic))}) "
                    f"and dbSNP observes {len(observed)} of them in a cohort; the locus "
                    "interrogates more than one question"
                ),
            }
        )
        return base

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

    if not asserting:
        gwas = gwas_risk_alleles(rsid)
        base["gwas_catalog"] = gwas
        risk = gwas.get("risk_alleles") or {}
        if len(risk) == 1:
            allele = next(iter(risk))
            base.update(
                {
                    "assessed_allele": allele,
                    "status": "VERIFICADO",
                    "source": "GWAS Catalog",
                    "reason": (
                        f"the GWAS Catalogue reports a single risk allele for this variant "
                        f"({allele}, across {risk[allele]} association record(s)); it carries no "
                        "ClinVar clinical assertion, which is expected for an association SNP"
                    ),
                }
            )
            return base
        if len(risk) > 1:
            base.update(
                {
                    "assessed_allele": None,
                    "status": "NÃO DISPONÍVEL",
                    "source": "GWAS Catalog",
                    "reason": (
                        "published studies disagree on the risk allele — the GWAS Catalogue "
                        f"reports {', '.join(f'{a} ({n} record(s))' for a, n in sorted(risk.items()))} "
                        "for this variant. This is a documented contradiction in the literature, "
                        "not a gap in the data, and choosing a side would manufacture agreement"
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


def curate(
    targets_path: Path,
    pgx_registry_path: Path | None = None,
    curated_decisions_path: Path | None = DEFAULT_CURATED_DECISIONS,
) -> dict[str, Any]:
    """Determine, per target, which allele the locus is scored against — or that none is."""
    payload = json.loads(Path(targets_path).read_text(encoding="utf-8"))
    registry = (
        json.loads(Path(pgx_registry_path).read_text(encoding="utf-8"))
        if pgx_registry_path and Path(pgx_registry_path).exists()
        else None
    )
    curated_decisions = _load_curated_decisions(curated_decisions_path)
    results = [
        curate_target(str(t["rsid"]).lower(), registry, curated_decisions)
        for t in payload["targets"]
    ]
    verified = [r for r in results if r["status"] == "VERIFICADO"]
    sources = [
        "NCBI dbSNP RefSNP API (api.ncbi.nlm.nih.gov/variation/v0/refsnp) — reference base",
        "NCBI ClinVar via E-utilities (eutils.ncbi.nlm.nih.gov, db=clinvar) — asserted alternate",
        "CPIC allele definitions (config/pgx_allele_definitions.json) — pharmacogenomic targets",
        "EBI GWAS Catalog (www.ebi.ac.uk/gwas/rest/api) — risk allele for association SNPs",
        "PubMed via NCBI elink — supporting citations per target",
    ]
    if curated_decisions:
        sources.append(
            "config/assessed_allele_curated_decisions.json — owner-reviewed allele identity, "
            "accepted only after live ClinVar accession/coordinate/alternate confirmation"
        )
    return {
        "schema": SCHEMA,
        "curated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": sources,
        "method": (
            "dbSNP supplies the plus-strand reference base from the SPDI deleted_sequence; "
            "ClinVar supplies the alternate from canonical_spdi. The two are joined by "
            "coordinate, never by text. Pharmacogenomic and association sources are used in "
            "their own domains. A versioned owner-reviewed allele-identity decision may be "
            "applied only when the live ClinVar coordinate join independently confirms its "
            "exact accession and alternate; it never overrides clinical significance. A "
            "target not established by these rules remains without an assessed allele."
        ),
        "targets_curated": len(results),
        "assessed_alleles_established": len(verified),
        "results": results,
    }


def _apply_target_assessment(
    target: dict[str, Any],
    record: dict[str, Any] | None,
    evidence_name: str,
) -> None:
    """Apply one curation result without separating an allele from its attestation."""
    if record and record["assessed_allele"]:
        target.pop("assessed_allele_reason", None)
        target.pop("assessed_allele_references", None)
        target["assessed_allele"] = record["assessed_allele"]
        target["assessed_allele_status"] = "VERIFICADO"
        target["assessed_allele_source"] = record.get("source", "ClinVar")
        target["assessed_allele_evidence"] = evidence_name
        target["references"] = record.get("references", {})
    else:
        for key in (
            "assessed_allele",
            "assessed_allele_source",
            "assessed_allele_evidence",
            "assessed_allele_references",
            "references",
        ):
            target.pop(key, None)
        target["assessed_allele_status"] = record["status"] if record else "NÃO DISPONÍVEL"
        target["assessed_allele_reason"] = record["reason"] if record else "not curated"


def main() -> int:
    """Curate assessed alleles for the target registry and write the evidence artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", default=str(DEFAULT_TARGETS))
    parser.add_argument("--output", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--pgx-registry", default=str(ROOT / "config/pgx_allele_definitions.json"))
    parser.add_argument("--curated-decisions", default=str(DEFAULT_CURATED_DECISIONS))
    parser.add_argument("--apply", action="store_true", help="write assessed_allele into the registry")
    args = parser.parse_args()

    evidence = curate(
        Path(args.targets),
        Path(args.pgx_registry),
        Path(args.curated_decisions) if args.curated_decisions else None,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.apply:
        registry = json.loads(Path(args.targets).read_text(encoding="utf-8"))
        by_rsid = {r["rsid"]: r for r in evidence["results"]}
        for target in registry["targets"]:
            record = by_rsid.get(str(target["rsid"]).lower())
            _apply_target_assessment(target, record, out.name)
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
