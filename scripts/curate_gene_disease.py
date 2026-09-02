#!/usr/bin/env python3
"""Curate the gene–disease evidence reports 01, 03, 04, 07 and 08 need, with citations.

Those five reports were the ones with no data producer, on the stated grounds that no
machine-readable source matches CPIC/ClinVar for gene–disease association. That is true of
*one* of the things they need and false of the others, and the difference decides which
reports can honestly be built:

``ClinGen gene-validity``  is machine-readable, versioned, expert-panel curated, and carries
                           exactly what reports 01 and 03 turn on: whether the gene–disease
                           relationship is established at all (`CLASSIFICATION`) and how it
                           is inherited (`MOI`). Carrier screening without a mode of
                           inheritance is guesswork; with it, it is arithmetic.
``GenCC``                  covers the genes ClinGen has not reached. Of the sixteen genes in
                           the target registry ClinGen curates four; GenCC — which aggregates
                           ClinGen itself with Genomics England PanelApp, PanelApp Australia,
                           Orphanet, G2P, Ambry, Labcorp and the Laboratory for Molecular
                           Medicine — covers eleven. SERPINA1 and alpha-1 antitrypsin
                           deficiency is the case that forced this: textbook autosomal
                           recessive, uncurated by any GCEP, and a report standing on ClinGen
                           alone would have withheld a real carrier finding for a
                           bureaucratic reason. GenCC is kept as a *separate* source with its
                           submitters named, never merged into ClinGen's classification.
``ClinVar``                supplies the variant-level classification, the review status
                           (how many submitters, whether they conflict) and the named
                           condition. The `trait_set` lives in the esummary payload's
                           `germline_classification`, not at the top level.
``GWAS Catalog``           supplies trait associations with p-value, effect size and — via
                           the study record — the **ancestry of the discovery cohort**. That
                           last field is why reports 04, 07 and 08 can be built at all: an
                           association discovered in 86,000 Europeans transfers poorly to an
                           admixed Brazilian genome, and a report that omits the caveat is
                           worse than one that does not exist.

The three are kept apart, never merged into a single "evidence" score. They answer different
questions at different strengths, and flattening them would let a GWAS association at
p = 1e-8 read like a Definitive ClinGen curation.

What this script will not do: assert a gene–disease relationship ClinGen has not curated. A
gene absent from the ClinGen download is recorded as absent with that word, not as "probably
established" — SERPINA1 and alpha-1 antitrypsin deficiency are textbook, and still uncurated
by a GCEP, and the report has to say which of those two facts it is standing on.
"""
from __future__ import annotations

import argparse
import csv
import io
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

from scripts.https_transport import is_https, policy_opener

from array_pipeline.clinical_findings import normalised_moi
from array_pipeline.targets import load_target_manifest, sha256_json
from scripts.curate_assessed_alleles import _spdi
from scripts.verify_provenance_markers import (
    MarkerVerificationError,
    fetch_refsnp,
    placements,
)

CLINGEN_CSV = "https://search.clinicalgenome.org/kb/gene-validity/download"
GENCC_TSV = "https://search.thegencc.org/download/action/submissions-export-tsv"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
GWAS = "https://www.ebi.ac.uk/gwas/rest/api"
GWAS_AUTHORITY = urllib.parse.urlsplit(GWAS).netloc.lower()

#: Validity classifications strong enough to speak of the relationship as established. Both
#: registries use the same words, so the set is shared.
ESTABLISHED_VALIDITY = frozenset({"Definitive", "Strong"})
#: How many *independent* GenCC submitters must agree before an aggregate stands in for a
#: ClinGen curation. One submitter is one laboratory's opinion; two is a reproduced one.
MIN_GENCC_SUBMITTERS = 2

DEFAULT_TARGETS = ROOT / "config/partial_genome_annotation_targets.json"
DEFAULT_OUTPUT = ROOT / "docs/evidence/GENE_DISEASE_VALIDITY.json"

REQUEST_INTERVAL_SECONDS = 0.34
#: Genome-wide significance. Associations weaker than this are recorded but never counted as
#: an established association, because the p < 0.05 literature is where nutrigenomics goes
#: wrong.
GENOME_WIDE_SIGNIFICANCE = 5e-8
#: How many traits per locus get a study lookup. Ancestry matters more than breadth here: an
#: unbounded fan-out would be slower and would not make any single association more usable.
MAX_TRAITS_PER_LOCUS = 12

UNAVAILABLE = "NÃO DISPONÍVEL"


class CurationError(RuntimeError):
    """A gene-disease source could not be read, so its evidence may not be published."""


def _fetch(url: str, *, attempts: int = 4, accept: str = "application/json") -> bytes:
    """Download from a curation source, retrying transient failures.

    Exhausting the attempts raises rather than returning empty bytes: an empty registry would
    read downstream as "no gene has an established relation", which is a scientific claim.
    """
    request = urllib.request.Request(
        url, headers={"Accept": accept, "User-Agent": "genoma-gene-disease-curation/1.0"}
    )
    # Refuse any transport but HTTPS before the request is opened. `urlopen` honours
    # `file:`, `ftp:` and `data:` as readily as `https:`, so a URL that reached this function
    # from a constant someone edited, a CLI flag or a manifest could make a *download* read
    # the local filesystem and hand the bytes to the caller as if a registry had published
    # them. The scheme is the one property that decides which of those happens.
    if not is_https(request.full_url):
        raise CurationError(f"refusing a non-HTTPS transport: {url}")

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with policy_opener(is_https, "this source").open(request, timeout=120) as response:  # nosec B310
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise CurationError(f"fetch failed for {url} after {attempts} attempts: {last}")


def _json(url: str) -> Any:
    """Fetch and parse JSON, turning a decode failure into a named curation refusal."""
    try:
        return json.loads(_fetch(url).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurationError(f"response from {url} is not valid UTF-8 JSON: {exc}") from exc


def fetch_clingen_validity() -> dict[str, Any]:
    """Read ClinGen's gene-validity download into per-gene curation lists.

    The file carries three banner lines, a header, and a row of plus signs before the data;
    hunting for the header by content rather than by index means a changed banner shifts
    nothing.
    """
    raw = _fetch(CLINGEN_CSV, accept="text/csv").decode("utf-8")
    rows = list(csv.reader(io.StringIO(raw)))
    header_index = next(
        (i for i, row in enumerate(rows) if row and row[0].strip() == "GENE SYMBOL"), None
    )
    if header_index is None:
        raise CurationError("ClinGen download has no 'GENE SYMBOL' header row")
    header = [cell.strip() for cell in rows[header_index]]
    curations: dict[str, list[dict[str, Any]]] = {}
    for row in rows[header_index + 1 :]:
        if not row or not row[0].strip() or set(row[0].strip()) == {"+"}:
            continue
        record = dict(zip(header, [cell.strip() for cell in row]))
        curations.setdefault(record["GENE SYMBOL"], []).append(
            {
                "disease": record.get("DISEASE LABEL"),
                "mondo": record.get("DISEASE ID (MONDO)"),
                "mode_of_inheritance": record.get("MOI"),
                "classification": record.get("CLASSIFICATION"),
                "sop": record.get("SOP"),
                "expert_panel": record.get("GCEP"),
                "report": record.get("ONLINE REPORT"),
                "classified_at": record.get("CLASSIFICATION DATE"),
            }
        )
    file_date = next(
        (row[0].split(":", 1)[1].strip() for row in rows[:header_index] if row and "FILE CREATED" in row[0]),
        UNAVAILABLE,
    )
    return {"file_created": file_date, "genes": curations, "curation_count": sum(len(v) for v in curations.values())}


def fetch_gencc_validity() -> dict[str, Any]:
    """Read the GenCC submissions export into per-gene, per-disease submitter groups.

    GenCC is an aggregate, so the unit that matters is *which submitters said what*, not the
    row count: five rows from one laboratory are one opinion. Submissions are therefore
    grouped by (disease, mode of inheritance) with the submitters named, and the established
    set is the groups meeting `MIN_GENCC_SUBMITTERS` at Definitive or Strong.
    """
    raw = _fetch(GENCC_TSV, accept="text/tab-separated-values").decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw), delimiter="\t")
    genes: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for row in reader:
        symbol = (row.get("gene_symbol") or "").strip()
        if not symbol:
            continue
        total += 1
        genes.setdefault(symbol, []).append(
            {
                "disease": (row.get("disease_title") or "").strip(),
                "disease_curie": (row.get("disease_curie") or "").strip(),
                "mode_of_inheritance": (row.get("moi_title") or "").strip(),
                "classification": (row.get("classification_title") or "").strip(),
                "submitter": (row.get("submitter_title") or "").strip(),
                "submitted_at": (row.get("submitted_as_date") or "").strip(),
                "report": (row.get("submitted_as_public_report_url") or "").strip(),
                "pmids": [p for p in (row.get("submitted_as_pmids") or "").split(",") if p.strip()],
            }
        )
    return {"genes": genes, "submission_count": total}


def _gencc_summary(submissions: list[dict[str, Any]]) -> dict[str, Any]:
    """Group one gene's GenCC submissions and say which groups are established."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in submissions:
        # Normalised before grouping, so `Autosomal recessive` and ClinGen's `AR` land in the
        # same bucket instead of reading as two modes for one disease.
        mode = normalised_moi(item["mode_of_inheritance"])
        key = (item["disease"], mode)
        entry = grouped.setdefault(
            key,
            {
                "disease": item["disease"],
                "disease_curie": item["disease_curie"],
                "mode_of_inheritance": mode,
                "mode_of_inheritance_reported": item["mode_of_inheritance"],
                "submitters": set(),
                "classifications": set(),
                "established_submitters": set(),
                "pmids": set(),
            },
        )
        entry["submitters"].add(item["submitter"])
        entry["classifications"].add(item["classification"])
        entry["pmids"].update(item["pmids"])
        if item["classification"] in ESTABLISHED_VALIDITY:
            entry["established_submitters"].add(item["submitter"])

    groups = []
    for entry in grouped.values():
        established = len(entry["established_submitters"]) >= MIN_GENCC_SUBMITTERS
        groups.append(
            {
                "disease": entry["disease"],
                "disease_curie": entry["disease_curie"],
                "mode_of_inheritance": entry["mode_of_inheritance"],
                "mode_of_inheritance_reported": entry["mode_of_inheritance_reported"],
                "submitters": sorted(entry["submitters"]),
                "classifications": sorted(entry["classifications"]),
                "established_submitters": sorted(entry["established_submitters"]),
                "established": established,
                "pmids": sorted(entry["pmids"]),
            }
        )
    groups.sort(key=lambda g: (not g["established"], g["disease"], g["mode_of_inheritance"]))

    established_groups = [g for g in groups if g["established"]]
    # A disease established under two different modes of inheritance is a real disagreement
    # between submitters, not a rounding error. It is recorded and never resolved here:
    # sections 4 and 7 forbid arbitrating a conflict, and picking one mode would decide
    # whether a heterozygote is a carrier or a patient.
    by_disease: dict[str, set[str]] = {}
    for group in established_groups:
        by_disease.setdefault(group["disease"], set()).add(group["mode_of_inheritance"])
    conflicts = [
        {"disease": disease, "modes": sorted(modes)}
        for disease, modes in sorted(by_disease.items())
        if len(modes) > 1
    ]
    return {
        # Without this key the caller's `block.get("established")` was always None and GenCC
        # could never establish anything — the aggregate was fetched, grouped and ignored.
        "established": bool(established_groups),
        "groups": groups,
        "established_groups": established_groups,
        "modes_of_inheritance": sorted({g["mode_of_inheritance"] for g in established_groups}),
        "diseases": sorted({g["disease"] for g in established_groups}),
        "mode_of_inheritance_conflicts": conflicts,
        "submitters": sorted({s for g in groups for s in g["submitters"]}),
    }


def _clinvar_for_locus(rsid: str) -> dict[str, Any]:
    """Fail one locus closed when dbSNP cannot substantiate its identity."""
    try:
        return fetch_clinvar_conditions(rsid)
    except (MarkerVerificationError, CurationError) as exc:
        source = "dbSNP" if isinstance(exc, MarkerVerificationError) else "ClinVar"
        return {
            "status": UNAVAILABLE,
            "reason": f"{source} não pôde verificar {rsid}: {exc}",
            "records": [],
        }


def fetch_clinvar_conditions(rsid: str) -> dict[str, Any]:
    """Return only ClinVar summaries proven to describe this rsid's GRCh38 locus.

    An rsid text search is discovery, not identity. Every returned summary is joined to the
    dbSNP GRCh38 placement by sequence accession, zero-based SPDI position, and reference
    allele before its classification or conditions may be marked verified.
    """
    refsnp = fetch_refsnp(rsid)
    grch38 = placements(refsnp).get("GRCh38")
    if (
        not isinstance(grch38, dict)
        or not str(grch38.get("seq_id") or "").strip()
        or not str(grch38.get("reference_allele") or "").strip()
    ):
        return {
            "status": UNAVAILABLE,
            "reason": f"dbSNP não retorna colocação GRCh38 utilizável para {rsid}",
            "records": [],
        }
    try:
        expected_position = int(grch38["position"]) - 1
    except (KeyError, TypeError, ValueError):
        return {
            "status": UNAVAILABLE,
            "reason": f"dbSNP não retorna posição GRCh38 utilizável para {rsid}",
            "records": [],
        }
    expected_sequence = str(grch38["seq_id"])
    expected_reference = str(grch38["reference_allele"]).upper()

    term = urllib.parse.quote(f"{rsid}[Variant ID]" if rsid.isdigit() else rsid)
    uids: list[str] = []
    retstart = 0
    count: int | None = None
    while count is None or retstart < count:
        search = _json(
            f"{EUTILS}/esearch.fcgi?db=clinvar&retmode=json&retmax=50"
            f"&retstart={retstart}&term={term}"
        )
        search_result = search.get("esearchresult") or {}
        page = [str(uid) for uid in (search_result.get("idlist") or []) if str(uid)]
        if count is None:
            try:
                count = int(search_result.get("count") or len(page))
            except (TypeError, ValueError) as exc:
                raise CurationError(
                    f"{rsid}: ClinVar esearch returned an invalid count"
                ) from exc
        uids.extend(page)
        retstart += len(page)
        if not page:
            break
        if retstart < count:
            time.sleep(REQUEST_INTERVAL_SECONDS)
    # Completeness is decided before anything is concluded about the content. With the order
    # reversed, an esearch reporting count > 0 whose first page came back with an empty
    # idlist — the partial response NCBI returns under load — broke the loop, left `uids`
    # empty, and returned "ClinVar não retorna registro". That sentence asserts absence; the
    # fact was an incomplete collection, and the locus entered the record as a verified gap.
    if count is not None and len(uids) < count:
        raise CurationError(
            f"{rsid}: ClinVar returned {len(uids)} of {count} record ids; "
            "refusing partial curation"
        )
    if not uids:
        return {
            "status": UNAVAILABLE,
            "reason": f"ClinVar não retorna registro para {rsid}",
            "records": [],
        }

    result: dict[str, Any] = {"uids": []}
    for start in range(0, len(uids), 50):
        time.sleep(REQUEST_INTERVAL_SECONDS)
        chunk = uids[start : start + 50]
        summary = _json(
            f"{EUTILS}/esummary.fcgi?db=clinvar&retmode=json&id="
            + ",".join(chunk)
        )
        page_result = summary.get("result") or {}
        for uid in page_result.get("uids", []):
            if uid in page_result:
                result["uids"].append(uid)
                result[uid] = page_result[uid]
    if len(result["uids"]) != len(uids):
        raise CurationError(
            f"{rsid}: ClinVar returned {len(result['uids'])} of {len(uids)} "
            "summaries; refusing partial curation"
        )

    records: list[dict[str, Any]] = []
    mismatched = 0
    for uid in result.get("uids", []):
        entry = result.get(uid) or {}
        spdi = _spdi(entry)
        if spdi is None:
            mismatched += 1
            continue
        sequence, position, deleted, inserted = spdi
        if (
            sequence != expected_sequence
            or position != expected_position
            or deleted != expected_reference
        ):
            mismatched += 1
            continue

        germline = entry.get("germline_classification") or {}
        traits = [
            {
                "name": trait.get("trait_name"),
                "xrefs": {
                    str(x.get("db_source")): str(x.get("db_id"))
                    for x in (trait.get("trait_xrefs") or [])
                    if x.get("db_source")
                },
            }
            for trait in (germline.get("trait_set") or [])
            if str(trait.get("trait_name") or "").strip().lower()
            not in ("not provided", "not specified", "")
        ]
        records.append(
            {
                "accession": entry.get("accession"),
                "title": entry.get("title"),
                "classification": germline.get("description") or UNAVAILABLE,
                "review_status": germline.get("review_status") or UNAVAILABLE,
                "last_evaluated": germline.get("last_evaluated") or UNAVAILABLE,
                # Preserve the variant identity established by the SPDI join. Coordinate
                # alone is ambiguous at multiallelic loci.
                "alternate_allele": inserted,
                "conditions": traits,
                "genes": sorted(
                    {str(g.get("symbol")) for g in (entry.get("genes") or []) if g.get("symbol")}
                ),
                "coordinate_check": {
                    "status": "VERIFICADO",
                    "assembly": "GRCh38",
                    "sequence": sequence,
                    "position": position + 1,
                    "reference_allele": deleted,
                    "alternate_allele": inserted,
                },
            }
        )
    return {
        "status": "VERIFICADO" if records else UNAVAILABLE,
        "records": records,
        "records_rejected_by_coordinate": mismatched,
        **(
            {}
            if records
            else {
                "reason": (
                    f"nenhum resumo ClinVar retornado para {rsid} corresponde à colocação "
                    "GRCh38 confirmada no dbSNP"
                )
            }
        ),
    }


def fetch_clinvar_gene_variant_counts(gene: str) -> dict[str, Any]:
    """How many variants ClinVar classifies P/LP in this gene, against how many in total.

    This is the denominator carrier screening needs. A panel that interrogates two SERPINA1
    variants out of the hundreds ClinVar classifies pathogenic has a detection rate well
    below one, and a negative result carries a residual risk the report has to state.

    It is a count of *variants*, not of allele frequency, and the difference matters: rare
    variants dominate the count while common ones dominate the frequency, so this bounds how
    much of the catalogue was interrogated and says nothing about how much of the risk was.
    Reporting it as a detection rate would be the overstatement it exists to prevent.
    """
    counts: dict[str, Any] = {"gene": gene}
    for label, term in (
        ("pathogenic", f'{gene}[gene] AND ("pathogenic"[Clinical significance] OR "likely pathogenic"[Clinical significance])'),
        ("total", f"{gene}[gene]"),
    ):
        try:
            result = _json(
                f"{EUTILS}/esearch.fcgi?db=clinvar&retmode=json&retmax=0&term="
                + urllib.parse.quote(term)
            )
            counts[label] = int((result.get("esearchresult") or {}).get("count", 0))
        except (CurationError, ValueError) as exc:
            # A failed count must not become zero: zero would read as "no pathogenic variants
            # in this gene", which is the most reassuring possible wrong answer.
            counts[label] = None
            counts.setdefault("errors", []).append(f"{label}: {exc}")
        time.sleep(REQUEST_INTERVAL_SECONDS)
    counts["status"] = "VERIFICADO" if counts.get("pathogenic") is not None else UNAVAILABLE
    return counts


def _ancestry_of(study: dict[str, Any]) -> dict[str, Any]:
    """The ancestry composition of a GWAS study, by participant count.

    Carried because a polygenic result is only transferable to the extent its cohort
    resembles the person: publishing the association without the composition would hide the
    dominant source of error for an admixed genome.
    """
    groups: dict[str, int] = {}
    for block in study.get("ancestries") or []:
        count = block.get("numberOfIndividuals") or 0
        for group in block.get("ancestralGroups") or []:
            name = str(group.get("ancestralGroup") or UNAVAILABLE)
            groups[name] = groups.get(name, 0) + int(count)
    return {
        "by_group": dict(sorted(groups.items(), key=lambda kv: -kv[1])),
        "initial_sample": study.get("initialSampleSize") or UNAVAILABLE,
        "replication_sample": study.get("replicationSampleSize") or UNAVAILABLE,
        "accession": study.get("accessionId") or UNAVAILABLE,
    }


def _is_authorized_gwas_link(url: str) -> bool:
    """Accept only HTTPS study links on the configured GWAS Catalog authority."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme.lower() == "https" and parsed.netloc.lower() == GWAS_AUTHORITY


def fetch_gwas_associations(rsid: str) -> dict[str, Any]:
    """Associations for one locus, grouped by EFO trait and priced by strength and ancestry."""
    try:
        payload = _json(
            f"{GWAS}/singleNucleotidePolymorphisms/{rsid}/associations?projection=associationBySnp"
        )
    except CurationError as exc:
        return {"status": UNAVAILABLE, "reason": str(exc), "traits": []}
    associations = (payload.get("_embedded") or {}).get("associations") or []
    if not associations:
        return {
            "status": "VERIFICADO",
            "reason": "GWAS Catalog não lista associação para este locus",
            "traits": [],
            "associations_considered": 0,
        }

    by_trait: dict[str, dict[str, Any]] = {}
    for association in associations:
        pvalue = association.get("pvalue")
        risk_alleles = sorted(
            {
                str(item.get("riskAlleleName"))
                for locus in association.get("loci") or []
                for item in locus.get("strongestRiskAlleles") or []
                if item.get("riskAlleleName")
            }
        )
        for trait in association.get("efoTraits") or []:
            name = str(trait.get("trait") or "").strip()
            if not name:
                continue
            entry = by_trait.setdefault(
                name,
                {
                    "trait": name,
                    "efo": trait.get("shortForm"),
                    "associations": 0,
                    "genome_wide_significant": 0,
                    "best_pvalue": None,
                    "risk_alleles": set(),
                    "_best_link": None,
                    "effect": None,
                },
            )
            entry["associations"] += 1
            entry["risk_alleles"].update(risk_alleles)
            if isinstance(pvalue, (int, float)) and pvalue <= GENOME_WIDE_SIGNIFICANCE:
                entry["genome_wide_significant"] += 1
            if isinstance(pvalue, (int, float)) and (
                entry["best_pvalue"] is None or pvalue < entry["best_pvalue"]
            ):
                entry["best_pvalue"] = pvalue
                entry["_best_link"] = ((association.get("_links") or {}).get("study") or {}).get("href")
                entry["effect"] = {
                    "odds_ratio": association.get("orPerCopyNum"),
                    "beta": association.get("betaNum"),
                    "beta_unit": association.get("betaUnit"),
                    "beta_direction": association.get("betaDirection"),
                    "range": association.get("range"),
                    "risk_frequency": association.get("riskFrequency"),
                }

    ranked = sorted(
        by_trait.values(),
        key=lambda e: (e["best_pvalue"] if e["best_pvalue"] is not None else 1.0, e["trait"]),
    )
    kept = ranked[:MAX_TRAITS_PER_LOCUS]
    for entry in kept:
        link = entry.pop("_best_link", None)
        entry["risk_alleles"] = sorted(entry["risk_alleles"])
        entry["ancestry"] = {"status": UNAVAILABLE, "reason": "estudo não recuperado"}
        if link:
            time.sleep(REQUEST_INTERVAL_SECONDS)
            try:
                if not _is_authorized_gwas_link(str(link)):
                    raise CurationError(
                        "GWAS Catalog retornou link de estudo fora da autoridade autorizada"
                    )
                entry["ancestry"] = _ancestry_of(_json(link))
                entry["ancestry"]["status"] = "VERIFICADO"
            except CurationError as exc:
                entry["ancestry"] = {"status": UNAVAILABLE, "reason": str(exc)}
    for entry in ranked[MAX_TRAITS_PER_LOCUS:]:
        entry.pop("_best_link", None)
        entry["risk_alleles"] = sorted(entry["risk_alleles"])

    return {
        "status": "VERIFICADO",
        "associations_considered": len(associations),
        "traits_total": len(ranked),
        "traits_detailed": len(kept),
        "traits": kept,
        # Named, not silently dropped: a reader must be able to tell a locus with three
        # associations from one with three hundred, of which twelve were detailed.
        "traits_not_detailed": [e["trait"] for e in ranked[MAX_TRAITS_PER_LOCUS:]],
        "significance_threshold": GENOME_WIDE_SIGNIFICANCE,
    }


def curate(targets_path: Path, *, with_gwas: bool = True) -> dict[str, Any]:
    """Assemble gene-disease validity for the target panel, recording which registry said so.

    `established_by` names the curators rather than collapsing to a boolean: "Definitive by a
    ClinGen expert panel" and "green on one NHS panel" are assertions of different weight,
    and a flattened flag makes them indistinguishable to everything downstream.
    """
    manifest = load_target_manifest(targets_path)
    clingen = fetch_clingen_validity()
    gencc = fetch_gencc_validity()

    genes = sorted({str(t["gene"]) for t in manifest["targets"] if t.get("gene")})
    gene_validity: dict[str, Any] = {}
    for gene in genes:
        curations = clingen["genes"].get(gene) or []
        gencc_summary = _gencc_summary(gencc["genes"].get(gene) or [])
        clingen_established = [
            c for c in curations if str(c.get("classification")) in ESTABLISHED_VALIDITY
        ]
        record: dict[str, Any] = {
            "clingen": {
                "status": "VERIFICADO" if curations else UNAVAILABLE,
                "source": "ClinGen Gene-Disease Validity",
                "curations": curations,
                # A gene can be Definitive for one disease and Limited for another; every
                # classification is listed, never just the strongest.
                "classifications": sorted(
                    {c["classification"] for c in curations if c.get("classification")}
                ),
                "modes_of_inheritance": sorted(
                    {
                        normalised_moi(c["mode_of_inheritance"])
                        for c in clingen_established
                        if c.get("mode_of_inheritance")
                    }
                ),
                "established": bool(clingen_established),
                **(
                    {}
                    if curations
                    else {
                        "reason": (
                            f"{gene} não consta no download de validade gene-doença do ClinGen: "
                            "nenhum painel de especialistas o curou nesse arcabouço. Isso não "
                            "torna a relação falsa nem verdadeira."
                        )
                    }
                ),
            },
            "gencc": {
                "status": "VERIFICADO" if gencc_summary["groups"] else UNAVAILABLE,
                "source": f"GenCC submissions export ({MIN_GENCC_SUBMITTERS}+ submetentes independentes para 'established')",
                **gencc_summary,
                **(
                    {}
                    if gencc_summary["groups"]
                    else {"reason": f"{gene} não consta no export de submissões do GenCC"}
                ),
            },
        }
        # `established` is true when either registry establishes the relationship, and which
        # one did is always recorded. Collapsing the two into a single boolean would hide
        # that SERPINA1 rests on three laboratory submitters while HFE rests on a ClinGen
        # expert panel — the same word, very different weight.
        established_by = [
            name
            for name, block in (("ClinGen", record["clingen"]), ("GenCC", record["gencc"]))
            if block.get("established")
        ]
        modes = sorted(
            set(record["clingen"]["modes_of_inheritance"])
            | set(record["gencc"]["modes_of_inheritance"])
        )
        # Modes are collected *per disease* across both registries. One gene carrying a
        # dominant condition and a recessive one is not a conflict — F5 is dominant for
        # thrombophilia and recessive for factor V deficiency — and counting it as one
        # would refuse every interpretation in such a gene. A conflict is two modes for the
        # *same* disease.
        modes_by_disease: dict[str, set[str]] = {}
        for curation in clingen_established:
            if curation.get("disease") and curation.get("mode_of_inheritance"):
                modes_by_disease.setdefault(str(curation["disease"]).lower(), set()).add(
                    normalised_moi(curation["mode_of_inheritance"])
                )
        for group in record["gencc"]["established_groups"]:
            if group.get("disease") and group.get("mode_of_inheritance"):
                modes_by_disease.setdefault(str(group["disease"]).lower(), set()).add(
                    str(group["mode_of_inheritance"])
                )
        conflicting = sorted(d for d, m in modes_by_disease.items() if len(m) > 1)
        record.update(
            {
                "status": "VERIFICADO" if established_by else UNAVAILABLE,
                "established": bool(established_by),
                "established_by": established_by,
                "modes_of_inheritance": modes,
                "modes_by_disease": {
                    disease: sorted(found) for disease, found in sorted(modes_by_disease.items())
                },
                "mode_of_inheritance_conflict": bool(conflicting),
                "conflicting_diseases": conflicting,
                "diseases": sorted(
                    {c["disease"] for c in clingen_established if c.get("disease")}
                    | set(record["gencc"]["diseases"])
                ),
            }
        )
        # The carrier-screening denominator: how much of ClinVar's catalogue for this gene a
        # panel of one or two positions can possibly have interrogated.
        record["clinvar_variant_counts"] = fetch_clinvar_gene_variant_counts(gene)
        if not established_by:
            record["reason"] = (
                f"nem o ClinGen nem o GenCC estabelecem relação gene-doença para {gene} em "
                "nível Definitivo ou Forte com submetentes independentes suficientes; sem isso "
                "este sistema não converte variante em achado clínico"
            )
        gene_validity[gene] = record

    loci: list[dict[str, Any]] = []
    for target in sorted(manifest["targets"], key=lambda t: str(t["rsid"])):
        rsid = str(target["rsid"]).lower()
        clinvar = _clinvar_for_locus(rsid)
        time.sleep(REQUEST_INTERVAL_SECONDS)
        gwas = (
            fetch_gwas_associations(rsid)
            if with_gwas
            else {"status": UNAVAILABLE, "reason": "busca GWAS desativada nesta execução", "traits": []}
        )
        time.sleep(REQUEST_INTERVAL_SECONDS)
        loci.append(
            {
                "rsid": rsid,
                "gene": target.get("gene"),
                "scope": target.get("scope"),
                "assessed_allele": target.get("assessed_allele"),
                "clinvar": clinvar,
                "gwas": gwas,
            }
        )
        print(
            f"  {rsid:<14} {str(target.get('gene') or '-'):<9} "
            f"clinvar={len(clinvar.get('records', []))} "
            f"gwas={gwas.get('traits_total', 0)} traços",
            flush=True,
        )

    curated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "schema": "genoma-gene-disease-validity-v1",
        "curated_at": curated_at,
        "target_manifest": {"id": manifest.get("id"), "version": manifest.get("version")},
        "sources": [
            f"ClinGen Gene-Disease Validity, {CLINGEN_CSV}, arquivo de {clingen['file_created']}, "
            f"{clingen['curation_count']} curadorias",
            f"GenCC (Gene Curation Coalition) submissions export, {GENCC_TSV}, "
            f"{gencc['submission_count']} submissões, recuperado em {datetime.now(timezone.utc).date().isoformat()}. "
            "Agrega ClinGen, Genomics England PanelApp, PanelApp Australia, Orphanet, G2P, "
            "Ambry, Labcorp e Laboratory for Molecular Medicine",
            "NCBI ClinVar via E-utilities (db=clinvar) — classificação da variante, status de "
            "revisão e conjunto de condições (germline_classification.trait_set)",
            "EBI GWAS Catalog REST (www.ebi.ac.uk/gwas/rest/api) — associações por traço EFO, "
            "com p-valor, tamanho de efeito e ancestralidade da coorte de descoberta",
        ],
        "method": (
            "Validade gene-doença e modo de herança vêm do ClinGen e, para os genes que o "
            f"ClinGen ainda não curou, do GenCC com no mínimo {MIN_GENCC_SUBMITTERS} submetentes "
            "independentes em nível Definitivo ou Forte. As duas fontes são registradas "
            "separadamente e `established_by` diz qual sustentou cada gene. Modos de herança "
            "divergentes entre submetentes são registrados como conflito e nunca arbitrados. "
            "Classificação de variante e condição vêm do ClinVar. Associações de traço vêm do "
            "GWAS Catalog, com a ancestralidade da coorte de descoberta buscada no registro do "
            "estudo da associação mais forte de cada traço. As três fontes são mantidas "
            "separadas: respondem perguntas diferentes com forças diferentes, e achatá-las "
            "faria uma associação de GWAS ler como uma curadoria Definitiva do ClinGen."
        ),
        "clingen_file_created": clingen["file_created"],
        "gencc_submission_count": gencc["submission_count"],
        "min_gencc_submitters": MIN_GENCC_SUBMITTERS,
        "established_validity_classifications": sorted(ESTABLISHED_VALIDITY),
        "genome_wide_significance": GENOME_WIDE_SIGNIFICANCE,
        "gene_validity": gene_validity,
        "loci": loci,
        "totals": {
            "genes": len(gene_validity),
            "genes_with_established_validity": sum(
                1 for v in gene_validity.values() if v["established"]
            ),
            "genes_curated_by_clingen": sum(
                1 for v in gene_validity.values() if v["clingen"]["status"] == "VERIFICADO"
            ),
            "genes_established_by_gencc_only": sum(
                1 for v in gene_validity.values() if v["established_by"] == ["GenCC"]
            ),
            "genes_with_mode_of_inheritance_conflict": sum(
                1 for v in gene_validity.values() if v["mode_of_inheritance_conflict"]
            ),
            "loci": len(loci),
            "loci_with_clinvar_record": sum(1 for x in loci if x["clinvar"].get("records")),
            "loci_with_gwas_association": sum(1 for x in loci if x["gwas"].get("traits_total")),
        },
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def main() -> int:
    """Curate gene-disease validity for the target panel and write the evidence artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", default=str(DEFAULT_TARGETS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--no-gwas", action="store_true", help="skip the GWAS Catalog lookups")
    args = parser.parse_args()

    payload = curate(Path(args.targets), with_gwas=not args.no_gwas)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(out), **payload["totals"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
