#!/usr/bin/env python3
"""Expand the target registry from ClinVar's bulk release, GenCC and ClinGen.

The curated registry holds twenty-nine loci. That number was never a scientific boundary —
it was how many someone had time to curate by hand, and it made report 03 quote a
denominator ("2 of 134 SERPINA1 variants") without ever being able to interrogate the other
132. This script closes that gap from the authoritative sources rather than by loosening
what counts as evidence.

**Why the bulk file rather than the API.** Curating 3,137 genes through E-utilities is about
ten thousand requests, an hour of throttled traffic, and a rate limit away from a half-built
registry that looks complete. `variant_summary.txt.gz` is the same data as one versioned
download, and it removes the failure mode entirely: either the file is there or it is not.

**Why the coordinate join stops being a risk here.** The whole reason the curated path joins
ClinVar to dbSNP by coordinate is that an rsid *text search* returns unrelated variants. In
the bulk file the accession, the classification, the review status, the rsid and the GRCh38
coordinate are fields of one row — there is no cross-source join to get wrong, and each
target carries the coordinate so a consumer can check it rather than trust this script.

**What is filtered out, and why each filter is a refusal rather than a convenience.**

``Assembly = GRCh38``   the file carries both builds; mixing them silently puts a variant at
                        the wrong coordinate.
``single nucleotide``   an array probe reads a base substitution. Indels and structural
                        variants are not interrogable at all, so listing them as targets
                        would manufacture coverage that cannot exist.
``P/LP exactly``        matched against the full classification string, not by substring:
                        "Conflicting classifications of pathogenicity" contains the word and
                        asserts the opposite.
``two stars or better`` multiple submitters with no conflicts, an expert panel, or a
                        practice guideline. One submitter's opinion is not a curated
                        assertion, and 108,809 of ClinVar's P/LP SNVs are exactly that.
``has an rsid``         array files are keyed by rsid; a variant without one can never be
                        matched, and the count of those dropped is reported.
``biallelic ACGT``      a reference or alternate that is not a single base is not a SNV
                        whatever the Type column says.

Nothing here is authored. Every target's assessed allele is the alternate base ClinVar
asserts at that coordinate, and where ClinVar asserts more than one at the same position no
assessed allele is emitted — the locus can then only ever reach OBSERVADO, never
NÃO DETECTADO, because there would be no single allele it was tested against.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.clinical_findings import (
    AUTOSOMAL_DOMINANT as AUTOSOMAL_DOMINANT_ABBR,
    AUTOSOMAL_RECESSIVE as AUTOSOMAL_RECESSIVE_ABBR,
    X_LINKED as X_LINKED_ABBR,
    normalised_moi,
)
from array_pipeline.targets import load_target_manifest, sha256_json

CLINVAR_BULK_URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
CLINGEN_CSV = "https://search.clinicalgenome.org/kb/gene-validity/download"
GENCC_TSV = "https://search.thegencc.org/download/action/submissions-export-tsv"
CLINGEN_DOSAGE_TSV = "https://ftp.clinicalgenome.org/ClinGen_gene_curation_list_GRCh38.tsv"
GNOMAD_CONSTRAINT_TSV = (
    "https://storage.googleapis.com/gcp-public-data--gnomad/release/4.1/constraint/"
    "gnomad.v4.1.constraint_metrics.tsv"
)

DEFAULT_TARGETS_OUT = ROOT / "config/targets_clinvar_plp.json.gz"
DEFAULT_EVIDENCE_OUT = ROOT / "docs/evidence/GENE_DISEASE_VALIDITY_BULK.json.gz"

#: Classifications that assert pathogenicity. Matched in full — never by substring.
PATHOGENIC = frozenset(
    {
        "Pathogenic",
        "Likely pathogenic",
        "Pathogenic/Likely pathogenic",
        "Pathogenic/Likely pathogenic/Established risk allele",
        "Pathogenic/Likely pathogenic/Likely risk allele",
        "Pathogenic/Likely pathogenic/Pathogenic, low penetrance",
    }
)
#: ClinVar's review-status ladder, in stars. Anything not listed is zero: an unrecognised
#: status must not accidentally clear a threshold.
REVIEW_STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, single submitter": 1,
    "no assertion criteria provided": 0,
    "no classification provided": 0,
    "no classifications from unflagged records": 0,
    "no classification for the single variant": 0,
}
#: ClinVar review statuses worth two stars or more.
TWO_STAR_OR_BETTER = frozenset(
    {
        "criteria provided, multiple submitters, no conflicts",
        "reviewed by expert panel",
        "practice guideline",
    }
)


def review_stars(status: str) -> int:
    """Stars for a review status, defaulting to zero for anything unrecognised."""
    return REVIEW_STARS.get(str(status or "").strip().lower(), 0)
ESTABLISHED_VALIDITY = frozenset({"Definitive", "Strong"})
MIN_GENCC_SUBMITTERS = 2

UNAVAILABLE = "NÃO DISPONÍVEL"


def _fetch(url: str, *, attempts: int = 4) -> bytes:
    last: Exception | None = None
    request = urllib.request.Request(url, headers={"User-Agent": "genoma-target-expansion/1.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=1800) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt < attempts - 1:
                import time

                time.sleep(2**attempt)
    raise RuntimeError(f"download failed for {url}: {last}")


def _local_or_fetch(path: Path | None, url: str) -> bytes:
    if path is not None and path.is_file():
        return path.read_bytes()
    return _fetch(url)


# ---------------------------------------------------------------------------------
# Gene–disease validity, for every gene the expansion touches
# ---------------------------------------------------------------------------------


def read_clingen(raw: bytes) -> dict[str, list[dict[str, Any]]]:
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    header_index = next(
        (i for i, row in enumerate(rows) if row and row[0].strip() == "GENE SYMBOL"), None
    )
    if header_index is None:
        raise RuntimeError("ClinGen download has no 'GENE SYMBOL' header row")
    header = [cell.strip() for cell in rows[header_index]]
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows[header_index + 1 :]:
        if not row or not row[0].strip() or set(row[0].strip()) == {"+"}:
            continue
        record = dict(zip(header, [cell.strip() for cell in row]))
        out[record["GENE SYMBOL"]].append(
            {
                "disease": record.get("DISEASE LABEL"),
                "mondo": record.get("DISEASE ID (MONDO)"),
                "mode_of_inheritance": record.get("MOI"),
                "classification": record.get("CLASSIFICATION"),
                "expert_panel": record.get("GCEP"),
                "report": record.get("ONLINE REPORT"),
                "classified_at": record.get("CLASSIFICATION DATE"),
            }
        )
    return dict(out)


def read_gencc(raw: bytes) -> dict[str, list[dict[str, Any]]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")), delimiter="\t")
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in reader:
        symbol = (row.get("gene_symbol") or "").strip()
        if not symbol:
            continue
        out[symbol].append(
            {
                "disease": (row.get("disease_title") or "").strip(),
                "disease_curie": (row.get("disease_curie") or "").strip(),
                "mode_of_inheritance": normalised_moi(row.get("moi_title")),
                "mode_of_inheritance_reported": (row.get("moi_title") or "").strip(),
                "classification": (row.get("classification_title") or "").strip(),
                "submitter": (row.get("submitter_title") or "").strip(),
            }
        )
    return dict(out)


def read_panelapp(path: Path | None) -> dict[str, dict[str, Any]]:
    """Load the PanelApp curation artefact produced by ``scripts/curate_panelapp.py``.

    Absent is absent: an empty index makes every gene report `NÃO DISPONÍVEL` for PanelApp,
    which is true, rather than silently dropping the registry from `established_by` while the
    method text still claims three sources.
    """
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"PanelApp curation not found: {path}")
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema") != "genoma-panelapp-curation-v1":
        raise ValueError(f"unexpected PanelApp schema: {payload.get('schema')!r}")
    return payload.get("genes") or {}


#: ClinGen's dosage-sensitivity scale. 3 is the only score that asserts the mechanism; 30 and
#: 40 are not points on the same scale at all — they are notes the curators attach instead of
#: a score, and reading either as "higher than 3" would invert the meaning.
DOSAGE_SUFFICIENT = "3"
DOSAGE_AUTOSOMAL_RECESSIVE = "30"

#: Parses the chromosome out of the dosage file's own locus columns. `Genomic Location`
#: reads "chrX:153724856-153744755" and `cytoBand` reads "Xq28"; either answers the only
#: question asked of them, which is whether the gene is on a sex chromosome.
_DOSAGE_LOCATION = re.compile(r"^chr([0-9]{1,2}|X|Y|MT?)\b", re.IGNORECASE)
_DOSAGE_CYTOBAND = re.compile(r"^([0-9]{1,2}|X|Y)[pq]", re.IGNORECASE)


def _dosage_chromosome(row: dict[str, Any]) -> str | None:
    for column, pattern in (
        ("Genomic Location", _DOSAGE_LOCATION),
        ("cytoBand", _DOSAGE_CYTOBAND),
    ):
        match = pattern.match((row.get(column) or "").strip())
        if match:
            value = match.group(1).upper()
            return "MT" if value == "M" else value
    return None
DOSAGE_UNLIKELY = "40"
DOSAGE_LABELS = {
    "0": "sem evidência",
    "1": "evidência mínima",
    "2": "evidência emergente",
    "3": "evidência suficiente para patogenicidade por dosagem",
    "30": "gene associado a fenótipo autossômico recessivo",
    "40": "dosagem improvável de ser sensível",
}


def read_clingen_dosage(path: Path | None) -> dict[str, dict[str, Any]]:
    """ClinGen's haploinsufficiency and triplosensitivity curation, one row per gene.

    This is a second, independent ClinGen product and not a restatement of the gene–disease
    validity download: validity asks whether the relationship is real, dosage asks whether
    *losing or gaining a copy* is the mechanism. It matters here for one concrete reason —
    a haploinsufficiency score of 3 is an expert panel saying one broken copy is enough, and
    a score of 30 is an expert panel saying the gene's phenotype is recessive. Both are
    mode-of-inheritance statements with a citation, for genes the validity download often
    does not carry.

    The file's header is a comment line, and its scores are not ordinal: 30 and 40 are
    annotations, not "more than 3".
    """
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"ClinGen dosage list not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header: list[str] | None = None
    rows: list[str] = []
    for line in text:
        if line.startswith("#"):
            fields = line.lstrip("#").split("\t")
            if len(fields) > 5 and fields[0].strip() == "Gene Symbol":
                header = [f.strip() for f in fields]
            continue
        if line.strip():
            rows.append(line)
    if header is None:
        raise ValueError(f"ClinGen dosage list has no recognisable header: {path}")

    out: dict[str, dict[str, Any]] = {}
    for row in csv.DictReader(rows, fieldnames=header, delimiter="\t"):
        gene = (row.get("Gene Symbol") or "").strip()
        if not gene:
            continue
        haplo = (row.get("Haploinsufficiency Score") or "").strip()
        triplo = (row.get("Triplosensitivity Score") or "").strip()
        # Haploinsufficiency says one broken copy is enough. On an autosome that reads as
        # dominant inheritance; on the X it reads as a hemizygous male being affected, which
        # is not autosomal anything. Emitting AD regardless put a spurious AD on 107
        # established X-linked genes — ABCD1, BTK, ATP7A, AR among them — against ClinGen
        # validity, GenCC and PanelApp all saying XL for the same gene, and the disagreement
        # then knocked those genes out of the X-linked reading downstream.
        #
        # The file carries the locus, so the chromosome is read rather than assumed. A gene
        # whose location cannot be parsed contributes no mode at all: dosage is a statement
        # about mechanism, and turning it into an inheritance mode nobody curated is what
        # caused this.
        chromosome = _dosage_chromosome(row)
        modes: list[str] = []
        if chromosome == "X":
            if haplo in (DOSAGE_SUFFICIENT, DOSAGE_AUTOSOMAL_RECESSIVE):
                modes.append(X_LINKED_ABBR)
        elif chromosome and chromosome not in ("Y", "MT"):
            if haplo == DOSAGE_SUFFICIENT:
                modes.append(AUTOSOMAL_DOMINANT_ABBR)
            if haplo == DOSAGE_AUTOSOMAL_RECESSIVE:
                modes.append(AUTOSOMAL_RECESSIVE_ABBR)
        pmids = sorted(
            {
                (row.get(f"{prefix} PMID{n}") or "").strip()
                for prefix in ("Haploinsufficiency", "Triplosensitivity")
                for n in range(1, 7)
            }
            - {""}
        )
        established = DOSAGE_SUFFICIENT in (haplo, triplo)
        out[gene] = {
            "status": "VERIFICADO" if established else UNAVAILABLE,
            "source": "ClinGen Dosage Sensitivity curation",
            "established": established,
            "haploinsufficiency_score": haplo,
            "haploinsufficiency": DOSAGE_LABELS.get(haplo, haplo or UNAVAILABLE),
            "triplosensitivity_score": triplo,
            "triplosensitivity": DOSAGE_LABELS.get(triplo, triplo or UNAVAILABLE),
            "modes_of_inheritance": modes,
            "diseases": sorted(
                {
                    (row.get(f"{prefix} Disease ID") or "").strip()
                    for prefix in ("Haploinsufficiency", "Triplosensitivity")
                }
                - {""}
            ),
            "pmids": pmids,
            "last_evaluated": (row.get("Date Last Evaluated") or "").strip() or None,
            "genomic_location_grch38": (row.get("Genomic Location") or "").strip() or None,
        }
    return out


def _float(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value == value else None  # NaN is absence, not a number


def read_gnomad_constraint(path: Path | None) -> dict[str, dict[str, Any]]:
    """Per-gene loss-of-function and missense constraint from the gnomAD v4.1 release.

    Constraint is *not* gene–disease validity and is never allowed to establish a
    relationship: a gene can be exquisitely intolerant of loss of function and have no curated
    disease, and a gene can be Definitive and unconstrained (CFTR's pLI is ~0 because carriers
    are common and healthy). It is carried because it answers a different question — how
    tolerant the gene is of being broken in a population that was not ascertained for disease —
    and because a report that says "no established validity" is more useful when it can add
    whether the gene is nonetheless constrained.

    One row per gene: the MANE Select transcript where there is one, otherwise the canonical
    transcript. The release lists each transcript twice, keyed by Ensembl and by NCBI id, with
    identical metrics; the Ensembl row is taken so the transcript identifier is stable.
    """
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"gnomAD constraint table not found: {path}")
    opener = gzip.open if path.suffix == ".gz" else open
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    with opener(path, "rt", encoding="utf-8", newline="") as handle:  # type: ignore[operator]
        for row in csv.DictReader(handle, delimiter="\t"):
            gene = (row.get("gene") or "").strip()
            if not gene:
                continue
            mane = (row.get("mane_select") or "").strip().lower() == "true"
            canonical = (row.get("canonical") or "").strip().lower() == "true"
            if not (mane or canonical):
                continue
            ensembl = (row.get("gene_id") or "").startswith("ENSG")
            # Rank: MANE beats canonical, and within a tier the Ensembl-keyed row wins.
            rank = (2 if mane else 1) * 2 + (1 if ensembl else 0)
            if gene in best and best[gene][0] >= rank:
                continue
            best[gene] = (
                rank,
                {
                    "status": "VERIFICADO",
                    "source": "gnomAD v4.1 constraint metrics",
                    "transcript": (row.get("transcript") or "").strip() or None,
                    "transcript_basis": "MANE Select" if mane else "canônico",
                    "pli": _float(row.get("lof.pLI", "")),
                    "loeuf": _float(row.get("lof.oe_ci.upper", "")),
                    "lof_oe": _float(row.get("lof.oe", "")),
                    "missense_z": _float(row.get("mis.z_score", "")),
                    "flags": (row.get("constraint_flags") or "").strip() or None,
                },
            )
    return {gene: record for gene, (_, record) in best.items()}


def _panelapp_block(gene: str, panelapp: dict[str, dict[str, Any]]) -> dict[str, Any]:
    record = panelapp.get(gene)
    if not record:
        return {
            "status": UNAVAILABLE,
            "source": "Genomics England PanelApp e PanelApp Australia",
            "established": False,
            "established_by": [],
            "green_panel_count": 0,
            "modes_of_inheritance": [],
            "reason": (
                f"{gene} não aparece como gene verde em nenhum painel diagnóstico das duas "
                "instâncias do PanelApp"
                if panelapp
                else "curadoria PanelApp não fornecida a esta execução"
            ),
        }
    return {
        "status": "VERIFICADO" if record.get("established") else UNAVAILABLE,
        "source": "Genomics England PanelApp e PanelApp Australia",
        "established": bool(record.get("established")),
        "established_by": list(record.get("established_by") or []),
        "green_panel_count": int(record.get("green_panel_count") or 0),
        "modes_of_inheritance": list(record.get("modes_of_inheritance") or []),
        "mode_of_inheritance_conflict": bool(record.get("mode_of_inheritance_conflict")),
        "phenotypes": list(record.get("phenotypes") or []),
        "publications": list(record.get("publications") or []),
    }


def _dosage_block(gene: str, dosage: dict[str, dict[str, Any]]) -> dict[str, Any]:
    record = dosage.get(gene)
    if record:
        return record
    return {
        "status": UNAVAILABLE,
        "source": "ClinGen Dosage Sensitivity curation",
        "established": False,
        "modes_of_inheritance": [],
        "reason": (
            f"{gene} não consta na lista de curadoria de dosagem do ClinGen"
            if dosage
            else "curadoria de dosagem do ClinGen não fornecida a esta execução"
        ),
    }


def gene_validity(
    gene: str,
    clingen: dict[str, list[dict[str, Any]]],
    gencc: dict[str, list[dict[str, Any]]],
    panelapp: dict[str, dict[str, Any]] | None = None,
    dosage: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One gene's validity, from every registry, kept apart and never merged."""
    curations = clingen.get(gene, [])
    established_clingen = [
        c for c in curations if str(c.get("classification")) in ESTABLISHED_VALIDITY
    ]

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in gencc.get(gene, []):
        key = (item["disease"], item["mode_of_inheritance"])
        entry = grouped.setdefault(
            key,
            {
                "disease": item["disease"],
                "disease_curie": item["disease_curie"],
                "mode_of_inheritance": item["mode_of_inheritance"],
                "submitters": set(),
                "classifications": set(),
                "established_submitters": set(),
            },
        )
        entry["submitters"].add(item["submitter"])
        entry["classifications"].add(item["classification"])
        if item["classification"] in ESTABLISHED_VALIDITY:
            entry["established_submitters"].add(item["submitter"])

    groups = []
    for entry in grouped.values():
        groups.append(
            {
                "disease": entry["disease"],
                "disease_curie": entry["disease_curie"],
                "mode_of_inheritance": entry["mode_of_inheritance"],
                "submitters": sorted(entry["submitters"]),
                "classifications": sorted(entry["classifications"]),
                "established_submitters": sorted(entry["established_submitters"]),
                "established": len(entry["established_submitters"]) >= MIN_GENCC_SUBMITTERS,
            }
        )
    groups.sort(key=lambda g: (not g["established"], g["disease"], g["mode_of_inheritance"]))
    established_gencc = [g for g in groups if g["established"]]

    # A mode conflict is two modes for the *same* disease. One gene carrying a dominant
    # condition and a recessive one is two relationships, not a disagreement.
    modes_by_disease: dict[str, set[str]] = defaultdict(set)
    for curation in established_clingen:
        if curation.get("disease") and curation.get("mode_of_inheritance"):
            modes_by_disease[str(curation["disease"]).lower()].add(
                normalised_moi(curation["mode_of_inheritance"])
            )
    for group in established_gencc:
        if group.get("disease") and group.get("mode_of_inheritance"):
            modes_by_disease[str(group["disease"]).lower()].add(group["mode_of_inheritance"])
    conflicting = sorted(d for d, modes in modes_by_disease.items() if len(modes) > 1)

    panel = _panelapp_block(gene, panelapp or {})
    dose = _dosage_block(gene, dosage or {})
    established_by = [
        name
        for name, present in (
            ("ClinGen", established_clingen),
            ("GenCC", established_gencc),
            ("PanelApp", [panel] if panel["established"] else []),
            ("ClinGen Dosage", [dose] if dose["established"] else []),
        )
        if present
    ]
    return {
        "panelapp": panel,
        "clingen_dosage": dose,
        # PanelApp is not independent of GenCC: GenCC's export includes submissions from both
        # PanelApp instances. Where both establish a gene, that is one body of curation
        # counted twice, and the flag says so rather than letting a reader read two
        # registries agreeing.
        "panelapp_overlaps_gencc": bool(panel["established"] and established_gencc),
        "clingen": {
            "status": "VERIFICADO" if curations else UNAVAILABLE,
            "source": "ClinGen Gene-Disease Validity",
            "curations": curations,
            "classifications": sorted({c["classification"] for c in curations if c.get("classification")}),
            "modes_of_inheritance": sorted(
                {
                    normalised_moi(c["mode_of_inheritance"])
                    for c in established_clingen
                    if c.get("mode_of_inheritance")
                }
            ),
            "established": bool(established_clingen),
        },
        "gencc": {
            "status": "VERIFICADO" if groups else UNAVAILABLE,
            "source": f"GenCC submissions export ({MIN_GENCC_SUBMITTERS}+ submetentes independentes)",
            "groups": groups,
            "established_groups": established_gencc,
            "modes_of_inheritance": sorted({g["mode_of_inheritance"] for g in established_gencc}),
            "diseases": sorted({g["disease"] for g in established_gencc}),
            "established": bool(established_gencc),
            "mode_of_inheritance_conflicts": [],
        },
        "status": "VERIFICADO" if established_by else UNAVAILABLE,
        "established": bool(established_by),
        "established_by": established_by,
        "modes_of_inheritance": sorted(
            {
                normalised_moi(c["mode_of_inheritance"])
                for c in established_clingen
                if c.get("mode_of_inheritance")
            }
            | {g["mode_of_inheritance"] for g in established_gencc}
            | set(panel["modes_of_inheritance"])
            # Dosage contributes a mode whenever the curators scored the gene, even at a
            # score that does not establish: 30 means "this gene's phenotype is autosomal
            # recessive", which is a curated statement about inheritance regardless of
            # whether haploinsufficiency was demonstrated.
            | set(dose["modes_of_inheritance"])
        ),
        "mode_of_inheritance_conflict": bool(conflicting),
        "conflicting_diseases": conflicting,
        # PanelApp states a mode per panel, not per MONDO disease, so a mode it contributes
        # cannot be checked against the condition ClinVar names for a given variant. Those
        # modes are listed here so the gap is visible instead of being inferred from the
        # absence of a per-disease entry.
        "modes_without_disease_anchor": sorted(
            (set(panel["modes_of_inheritance"]) | set(dose["modes_of_inheritance"]))
            - {mode for modes in modes_by_disease.values() for mode in modes}
        ),
        "diseases": sorted(
            {str(c["disease"]) for c in established_clingen if c.get("disease")}
            | {str(g["disease"]) for g in established_gencc if g.get("disease")}
        ),
    }


# ---------------------------------------------------------------------------------
# ClinVar bulk scan
# ---------------------------------------------------------------------------------


def _conditions(phenotype_list: str, phenotype_ids: str) -> list[dict[str, Any]]:
    """Pair ClinVar's parallel phenotype name and cross-reference columns.

    `PhenotypeList` and `PhenotypeIDS` are pipe-separated and positionally aligned. Where the
    two disagree in length the names are kept and the cross-references dropped, because a
    condition matched to the wrong MONDO id is worse than a condition with no id at all.
    """
    names = [n.strip() for n in (phenotype_list or "").split("|") if n.strip() and n != "-"]
    id_groups = [g.strip() for g in (phenotype_ids or "").split("|")]
    aligned = len(names) == len(id_groups)
    out: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        if name.lower() in ("not provided", "not specified"):
            continue
        xrefs: dict[str, str] = {}
        if aligned:
            for token in id_groups[index].split(","):
                if ":" not in token:
                    continue
                source, _, value = token.partition(":")
                source = source.strip()
                value = value.strip()
                if source and value:
                    # ClinVar writes MONDO ids as `MONDO:MONDO:0013342`.
                    xrefs[source] = value if value.upper().startswith(source.upper()) else f"{source}:{value}"
        out.append({"name": name, "xrefs": xrefs})
    return out


def scan_clinvar(
    raw_path: Path,
    *,
    min_review_stars: int = 2,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], dict[str, dict[str, int]]]:
    """Group every qualifying ClinVar record by rsid, and count each gene's whole catalogue.

    The per-gene counts are the denominator carrier screening needs and the reason report 03
    could only quote one before: a negative screen is interpretable only against how much of
    the gene's pathogenic catalogue was interrogable at all. Counting here costs one extra
    pass over rows already being read, and it is a count of *variants* — rare variants
    dominate the count while common ones dominate the frequency, so it bounds how much of the
    catalogue was covered and says nothing about how much of the risk was.
    """
    by_rsid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stats: dict[str, int] = defaultdict(int)
    gene_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "pathogenic_any": 0,
            "pathogenic_two_star": 0,
            "pathogenic_two_star_snv_rsid": 0,
            "pathogenic_at_threshold_snv_rsid": 0,
        }
    )
    with gzip.open(raw_path, "rt", encoding="utf-8", errors="replace") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in fh:
            stats["rows"] += 1
            row = line.rstrip("\n").split("\t")
            if len(row) < len(header):
                stats["short_rows"] += 1
                continue
            if row[idx["Assembly"]] != "GRCh38":
                continue
            stats["grch38"] += 1
            classification = row[idx["ClinicalSignificance"]].split(";")[0].strip()
            review = row[idx["ReviewStatus"]].strip()
            row_genes = [
                g.strip()
                for g in row[idx["GeneSymbol"]].replace("|", ";").split(";")
                if g.strip() and g.strip() != "-"
            ]
            # The denominator counts the gene's whole pathogenic catalogue, before any of the
            # filters that decide what this registry can represent — that is the point of it.
            if classification in PATHOGENIC:
                for symbol in row_genes:
                    gene_counts[symbol]["pathogenic_any"] += 1
                    if review in TWO_STAR_OR_BETTER:
                        gene_counts[symbol]["pathogenic_two_star"] += 1

            if row[idx["Type"]] != "single nucleotide variant":
                continue
            stats["snv"] += 1
            if classification not in PATHOGENIC:
                continue
            stats["pathogenic"] += 1
            stars = review_stars(review)
            if stars < min_review_stars:
                stats["below_review_threshold"] += 1
                continue
            stats["at_or_above_review_threshold"] += 1
            stats[f"stars_{stars}"] += 1
            rs = row[idx["RS# (dbSNP)"]].strip()
            if rs in ("", "-"):
                stats["no_rsid"] += 1
                continue
            reference = row[idx["ReferenceAlleleVCF"]].strip().upper()
            alternate = row[idx["AlternateAlleleVCF"]].strip().upper()
            if len(reference) != 1 or len(alternate) != 1 or reference not in "ACGT" or alternate not in "ACGT":
                stats["not_biallelic"] += 1
                continue
            stats["kept"] += 1
            for symbol in row_genes:
                gene_counts[symbol]["pathogenic_at_threshold_snv_rsid"] += 1
                if stars >= 2:
                    gene_counts[symbol]["pathogenic_two_star_snv_rsid"] += 1

            variation_id = row[idx["VariationID"]].strip()
            genes = sorted(set(row_genes))
            by_rsid[f"rs{rs}"].append(
                {
                    "variation_id": variation_id,
                    "accession": f"VCV{int(variation_id):09d}" if variation_id.isdigit() else variation_id,
                    "name": row[idx["Name"]].strip(),
                    "classification": classification,
                    "review_status": review,
                    "review_stars": stars,
                    "submitters": int(row[idx["NumberSubmitters"]] or 0),
                    "last_evaluated": row[idx["LastEvaluated"]].strip(),
                    "genes": genes,
                    "reference_allele": reference,
                    "alternate_allele": alternate,
                    "grch38": {
                        "chromosome": row[idx["Chromosome"]].strip(),
                        "position": int(row[idx["PositionVCF"]] or 0) or None,
                        "reference_accession": row[idx["ChromosomeAccession"]].strip(),
                    },
                    "conditions": _conditions(row[idx["PhenotypeList"]], row[idx["PhenotypeIDS"]]),
                }
            )
    return dict(by_rsid), dict(stats), {g: dict(c) for g, c in gene_counts.items()}


def build_targets(by_rsid: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One target per rsid, refusing an assessed allele where ClinVar asserts more than one."""
    targets: list[dict[str, Any]] = []
    stats: dict[str, int] = defaultdict(int)
    for rsid in sorted(by_rsid, key=lambda r: int(r[2:])):
        records = by_rsid[rsid]
        positions = {
            (r["grch38"]["chromosome"], r["grch38"]["position"])
            for r in records
            if r["grch38"]["position"]
        }
        if len(positions) != 1:
            # One rsid mapping to two GRCh38 coordinates is a mapping ambiguity, not a
            # variant. Choosing one would put the genotype at the wrong place.
            stats["ambiguous_position"] += 1
            continue
        chromosome, position = next(iter(positions))
        alternates = sorted({r["alternate_allele"] for r in records})
        genes = sorted({g for r in records for g in r["genes"]})
        classifications = sorted({r["classification"] for r in records})
        reviews = sorted({r["review_status"] for r in records})
        conditions = sorted(
            {c["name"] for r in records for c in r["conditions"]}
        )
        accession = sorted({r["accession"] for r in records})

        target: dict[str, Any] = {
            "rsid": rsid,
            "gene": genes[0] if genes else None,
            "genes": genes,
            "scope": "CLINICO",
            "label": (
                f"{'/'.join(genes) or 'sem gene'} {rsid}: "
                f"{', '.join(classifications)} ({', '.join(reviews)})"
            ),
            "queries": {"clinvar": {"term": rsid, "retmax": 10}},
            "grch38": {
                "chromosome": chromosome,
                "position": position,
                "reference_accession": records[0]["grch38"]["reference_accession"],
            },
            "clinvar_accessions": accession,
            "clinvar_classifications": classifications,
            "clinvar_review_statuses": reviews,
            # The star level travels with the target rather than being implied by membership.
            # A registry that mixes tiers and does not say which is which turns a single
            # laboratory's opinion into the same object as a practice guideline; downstream,
            # `array_pipeline.clinical_findings` reads this back and a one-star locus can only
            # ever reach ACHADO PRELIMINAR.
            "clinvar_review_stars": max(r["review_stars"] for r in records),
            "clinvar_review_stars_min": min(r["review_stars"] for r in records),
            "clinvar_conditions": conditions[:6],
            "clinvar_submitters": max(r["submitters"] for r in records),
            "reference_allele": records[0]["reference_allele"],
        }
        stats[f"tier_{target['clinvar_review_stars']}_star"] += 1
        if len(alternates) == 1:
            target["assessed_allele"] = alternates[0]
            target["assessed_allele_source"] = (
                f"ClinVar variant_summary (GRCh38, {target['clinvar_review_stars']}★)"
            )
            target["assessed_allele_status"] = "VERIFICADO"
            target["assessed_allele_reason"] = (
                f"única base alternativa que o ClinVar assere como patogênica nesta coordenada "
                f"({chromosome}:{position}), em {', '.join(accession[:3])}"
            )
            stats["with_assessed_allele"] += 1
        else:
            target["clinvar_alternate_alleles"] = alternates
            target["assessed_allele_reason"] = (
                f"o ClinVar assere mais de uma base alternativa nesta coordenada "
                f"({', '.join(alternates)}); nenhum alelo avaliado único pode ser declarado e o "
                "locus não admite NÃO DETECTADO"
            )
            stats["multi_allelic"] += 1
        targets.append(target)
    return targets, dict(stats)


def build(
    clinvar_path: Path,
    *,
    clingen_path: Path | None = None,
    gencc_path: Path | None = None,
    panelapp_path: Path | None = None,
    gnomad_constraint_path: Path | None = None,
    clingen_dosage_path: Path | None = None,
    min_review_stars: int = 2,
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_rsid, scan_stats, gene_counts = scan_clinvar(
        clinvar_path, min_review_stars=min_review_stars
    )
    targets, target_stats = build_targets(by_rsid)

    clingen = read_clingen(_local_or_fetch(clingen_path, CLINGEN_CSV))
    gencc = read_gencc(_local_or_fetch(gencc_path, GENCC_TSV))
    panelapp = read_panelapp(panelapp_path)
    constraint = read_gnomad_constraint(gnomad_constraint_path)
    dosage = read_clingen_dosage(clingen_dosage_path)

    genes = sorted({g for t in targets for g in t["genes"]})
    validity = {}
    for gene in genes:
        block = gene_validity(gene, clingen, gencc, panelapp, dosage)
        block["gnomad_constraint"] = constraint.get(gene) or {
            "status": UNAVAILABLE,
            "source": "gnomAD v4.1 constraint metrics",
            "reason": (
                f"{gene} não tem transcrito MANE Select nem canônico na tabela de restrição"
                if constraint
                else "tabela de restrição do gnomAD não fornecida a esta execução"
            ),
        }
        counts = gene_counts.get(gene, {})
        # The carrier-screening denominator, from the same release the targets came from.
        block["clinvar_variant_counts"] = {
            "status": "VERIFICADO" if counts else UNAVAILABLE,
            "gene": gene,
            "pathogenic": counts.get("pathogenic_any"),
            "pathogenic_two_star": counts.get("pathogenic_two_star"),
            "representable_in_registry": counts.get("pathogenic_at_threshold_snv_rsid"),
            "representable_two_star": counts.get("pathogenic_two_star_snv_rsid"),
            "review_star_threshold": min_review_stars,
            "basis": (
                "contagem de variantes P/LP do gene no release do ClinVar; contagem de "
                "variantes, não de frequência alélica, portanto limita quanto do catálogo foi "
                "interrogado e nada diz sobre quanto do risco foi"
            ),
        }
        validity[gene] = block

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sources = [
        f"NCBI ClinVar variant_summary.txt.gz, {CLINVAR_BULK_URL}, lido em {generated}. "
        "Filtros: GRCh38, single nucleotide variant, classificação P/LP exata, review status "
        f"de {min_review_stars} estrela(s) ou mais, rsid presente, alelos bialélicos ACGT. "
        "Cada alvo carrega o próprio nível de estrelas.",
        f"ClinGen Gene-Disease Validity, {CLINGEN_CSV}",
        f"GenCC submissions export, {GENCC_TSV}",
    ]
    if panelapp:
        sources.append(
            "Genomics England PanelApp e PanelApp Australia, via "
            "scripts/curate_panelapp.py; apenas genes verdes (grau diagnóstico) contam como "
            f"estabelecidos. {len(panelapp)} genes indexados, "
            f"{sum(1 for g in panelapp.values() if g.get('established'))} verdes."
        )
    if dosage:
        sources.append(
            f"ClinGen Dosage Sensitivity, {CLINGEN_DOSAGE_TSV}, {len(dosage)} genes curados; "
            "escore 3 de haploinsuficiência ou triplossensibilidade estabelece, escore 30 "
            "registra fenótipo autossômico recessivo e não estabelece."
        )
    if constraint:
        sources.append(
            f"gnomAD v4.1 constraint metrics, {GNOMAD_CONSTRAINT_TSV}, transcrito MANE Select "
            f"quando existe e canônico caso contrário; {len(constraint)} genes. Restrição não "
            "estabelece relação gene-doença e nunca entra em `established_by`."
        )

    manifest = {
        "schema": "genoma-partial-genome-targets-v1",
        "id": f"GENOMA-CLINVAR-PLP-{min_review_stars}STAR",
        "version": generated[:10].replace("-", "") + ".1",
        "description": (
            "Toda variante de nucleotídeo único que o ClinVar classifica como patogênica ou "
            f"provavelmente patogênica com revisão de {min_review_stars} estrela(s) ou mais, "
            "em GRCh38, com rsid e alelos bialélicos. Cada alvo declara o próprio nível de "
            "revisão em `clinvar_review_stars`, e um alvo de uma estrela nunca sustenta achado "
            "acionável — a interpretação o rebaixa a ACHADO PRELIMINAR. Presença aqui autoriza "
            "apenas interrogação de cobertura: não estabelece significado clínico, diplótipo, "
            "fase nem completude. Reproduzir com scripts/expand_clinvar_targets.py."
        ),
        "sources": sources,
        "generated_at": generated,
        "selection": {
            "assembly": "GRCh38",
            "variant_type": "single nucleotide variant",
            "classifications": sorted(PATHOGENIC),
            "min_review_stars": min_review_stars,
            "review_statuses": sorted(
                status for status, stars in REVIEW_STARS.items() if stars >= min_review_stars
            ),
            "requires_rsid": True,
            "requires_biallelic_acgt": True,
        },
        "scan_statistics": scan_stats,
        "target_statistics": target_stats,
        "targets": targets,
    }
    manifest["sha256"] = sha256_json({k: v for k, v in manifest.items() if k != "sha256"})

    evidence = {
        "schema": "genoma-gene-disease-validity-v1",
        "curated_at": generated,
        "sources": sources,
        "method": (
            "Validade gene-doença do ClinGen, do GenCC e do PanelApp, mantidas separadas, com "
            f"{MIN_GENCC_SUBMITTERS} submetentes independentes em nível Definitive ou Strong "
            "exigidos para o GenCC estabelecer e apenas painéis verdes para o PanelApp. "
            "PanelApp responde uma pergunta diferente das outras duas — se um serviço de saúde "
            "testa o gene na prática, não se a relação é biologicamente estabelecida — e não é "
            "independente do GenCC, que já agrega as submissões das duas instâncias do "
            "PanelApp; `panelapp_overlaps_gencc` marca cada gene em que as duas coincidem, "
            "para que não sejam lidas como dois votos. A restrição populacional do gnomAD é "
            "anexada por gene e nunca estabelece relação: um gene pode ser intolerante a perda "
            "de função sem doença curada, e um gene Definitivo pode ser irrestrito. "
            "Registros de variante vêm do dump do ClinVar: "
            "acesso, classificação, status de revisão, condições e coordenada GRCh38 são "
            "campos da mesma linha, portanto não há junção entre fontes a errar e cada "
            "registro carrega a própria coordenada para conferência."
        ),
        "clinvar_join": "coordinate-native",
        "gene_validity": validity,
        "loci": [
            {
                "rsid": rsid,
                "gene": (by_rsid[rsid][0]["genes"] or [None])[0],
                "grch38": records[0]["grch38"],
                "clinvar": {
                    "status": "VERIFICADO",
                    "records": [
                        {
                            "accession": r["accession"],
                            "title": r["name"],
                            "classification": r["classification"],
                            "review_status": r["review_status"],
                            "review_stars": r["review_stars"],
                            "last_evaluated": r["last_evaluated"],
                            "conditions": r["conditions"],
                            "genes": r["genes"],
                            "grch38": r["grch38"],
                        }
                        for r in records
                    ],
                },
                "gwas": {"status": UNAVAILABLE, "traits": [], "reason": "não consultado nesta rota em massa"},
            }
            for rsid, records in ((t["rsid"], by_rsid[t["rsid"]]) for t in targets)
        ],
        "totals": {
            "genes": len(validity),
            "genes_with_established_validity": sum(1 for v in validity.values() if v["established"]),
            "genes_established_by_gencc_only": sum(
                1 for v in validity.values() if v["established_by"] == ["GenCC"]
            ),
            "genes_established_by_panelapp_only": sum(
                1 for v in validity.values() if v["established_by"] == ["PanelApp"]
            ),
            "genes_green_in_panelapp": sum(
                1 for v in validity.values() if v["panelapp"]["established"]
            ),
            "genes_where_panelapp_overlaps_gencc": sum(
                1 for v in validity.values() if v["panelapp_overlaps_gencc"]
            ),
            "genes_established_by_clingen_dosage_only": sum(
                1 for v in validity.values() if v["established_by"] == ["ClinGen Dosage"]
            ),
            "genes_with_dosage_curation": sum(
                1 for v in validity.values() if v["clingen_dosage"].get("haploinsufficiency_score")
            ),
            "genes_with_gnomad_constraint": sum(
                1 for v in validity.values() if v["gnomad_constraint"]["status"] == "VERIFICADO"
            ),
            "genes_lof_intolerant_pli_090": sum(
                1
                for v in validity.values()
                if (v["gnomad_constraint"].get("pli") or 0) >= 0.9
            ),
            "genes_with_mode_of_inheritance_conflict": sum(
                1 for v in validity.values() if v["mode_of_inheritance_conflict"]
            ),
            "loci": len(targets),
        },
    }
    evidence["sha256"] = sha256_json({k: v for k, v in evidence.items() if k != "sha256"})
    return manifest, evidence


def _write(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clinvar-bulk", required=True, help="variant_summary.txt.gz")
    parser.add_argument("--clingen", help="local copy of the ClinGen gene-validity CSV")
    parser.add_argument("--gencc", help="local copy of the GenCC submissions TSV")
    parser.add_argument("--panelapp", help="PanelApp curation from scripts/curate_panelapp.py")
    parser.add_argument("--gnomad-constraint", help="gnomAD v4.1 constraint metrics TSV")
    parser.add_argument("--clingen-dosage", help="ClinGen dosage-sensitivity curation TSV")
    parser.add_argument(
        "--min-review-stars",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        help=(
            "lowest ClinVar review level admitted. 2 is the curated-consensus registry; 1 adds "
            "single-submitter assertions, which the interpretation caps at ACHADO PRELIMINAR"
        ),
    )
    parser.add_argument("--targets-out", default=str(DEFAULT_TARGETS_OUT))
    parser.add_argument("--evidence-out", default=str(DEFAULT_EVIDENCE_OUT))
    args = parser.parse_args()

    manifest, evidence = build(
        Path(args.clinvar_bulk),
        clingen_path=Path(args.clingen) if args.clingen else None,
        gencc_path=Path(args.gencc) if args.gencc else None,
        panelapp_path=Path(args.panelapp) if args.panelapp else None,
        gnomad_constraint_path=(
            Path(args.gnomad_constraint) if args.gnomad_constraint else None
        ),
        clingen_dosage_path=Path(args.clingen_dosage) if args.clingen_dosage else None,
        min_review_stars=args.min_review_stars,
    )
    targets_out = _write(manifest, Path(args.targets_out))
    evidence_out = _write(evidence, Path(args.evidence_out))

    # Read it back through the real validator: a manifest this pipeline cannot load is not a
    # manifest, and finding that out here beats finding it out mid-run.
    load_target_manifest(targets_out)

    print(
        json.dumps(
            {
                "targets": str(targets_out),
                "targets_bytes": targets_out.stat().st_size,
                "evidence": str(evidence_out),
                "evidence_bytes": evidence_out.stat().st_size,
                "target_count": len(manifest["targets"]),
                "genes": evidence["totals"]["genes"],
                "genes_with_established_validity": evidence["totals"]["genes_with_established_validity"],
                "scan": manifest["scan_statistics"],
                "selection": manifest["target_statistics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
