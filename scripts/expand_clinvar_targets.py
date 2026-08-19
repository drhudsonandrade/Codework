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

from array_pipeline.clinical_findings import normalised_moi
from array_pipeline.targets import load_target_manifest, sha256_json

CLINVAR_BULK_URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
CLINGEN_CSV = "https://search.clinicalgenome.org/kb/gene-validity/download"
GENCC_TSV = "https://search.thegencc.org/download/action/submissions-export-tsv"

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
#: ClinVar review statuses worth two stars or more.
TWO_STAR_OR_BETTER = frozenset(
    {
        "criteria provided, multiple submitters, no conflicts",
        "reviewed by expert panel",
        "practice guideline",
    }
)
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


def gene_validity(
    gene: str,
    clingen: dict[str, list[dict[str, Any]]],
    gencc: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """One gene's validity, from both registries, kept apart and never merged."""
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

    established_by = [
        name
        for name, present in (("ClinGen", established_clingen), ("GenCC", established_gencc))
        if present
    ]
    return {
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
        ),
        "mode_of_inheritance_conflict": bool(conflicting),
        "conflicting_diseases": conflicting,
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
        lambda: {"pathogenic_any": 0, "pathogenic_two_star": 0, "pathogenic_two_star_snv_rsid": 0}
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
            if review not in TWO_STAR_OR_BETTER:
                stats["below_two_star"] += 1
                continue
            stats["two_star"] += 1
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
            "clinvar_conditions": conditions[:6],
            "clinvar_submitters": max(r["submitters"] for r in records),
            "reference_allele": records[0]["reference_allele"],
        }
        if len(alternates) == 1:
            target["assessed_allele"] = alternates[0]
            target["assessed_allele_source"] = "ClinVar variant_summary (GRCh38, 2★+)"
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_rsid, scan_stats, gene_counts = scan_clinvar(clinvar_path)
    targets, target_stats = build_targets(by_rsid)

    clingen = read_clingen(_local_or_fetch(clingen_path, CLINGEN_CSV))
    gencc = read_gencc(_local_or_fetch(gencc_path, GENCC_TSV))

    genes = sorted({g for t in targets for g in t["genes"]})
    validity = {}
    for gene in genes:
        block = gene_validity(gene, clingen, gencc)
        counts = gene_counts.get(gene, {})
        # The carrier-screening denominator, from the same release the targets came from.
        block["clinvar_variant_counts"] = {
            "status": "VERIFICADO" if counts else UNAVAILABLE,
            "gene": gene,
            "pathogenic": counts.get("pathogenic_any"),
            "pathogenic_two_star": counts.get("pathogenic_two_star"),
            "representable_in_registry": counts.get("pathogenic_two_star_snv_rsid"),
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
        "de duas estrelas ou mais, rsid presente, alelos bialélicos ACGT.",
        f"ClinGen Gene-Disease Validity, {CLINGEN_CSV}",
        f"GenCC submissions export, {GENCC_TSV}",
    ]

    manifest = {
        "schema": "genoma-partial-genome-targets-v1",
        "id": "GENOMA-CLINVAR-PLP-2STAR",
        "version": generated[:10].replace("-", "") + ".1",
        "description": (
            "Toda variante de nucleotídeo único que o ClinVar classifica como patogênica ou "
            "provavelmente patogênica com revisão de duas estrelas ou mais, em GRCh38, com "
            "rsid e alelos bialélicos. Presença aqui autoriza apenas interrogação de "
            "cobertura: não estabelece significado clínico, diplótipo, fase nem completude. "
            "Reproduzir com scripts/expand_clinvar_targets.py."
        ),
        "sources": sources,
        "generated_at": generated,
        "selection": {
            "assembly": "GRCh38",
            "variant_type": "single nucleotide variant",
            "classifications": sorted(PATHOGENIC),
            "review_statuses": sorted(TWO_STAR_OR_BETTER),
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
            "Validade gene-doença do ClinGen e do GenCC, mantidas separadas, com "
            f"{MIN_GENCC_SUBMITTERS} submetentes independentes em nível Definitive ou Strong "
            "exigidos para o GenCC estabelecer. Registros de variante vêm do dump do ClinVar: "
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
    parser.add_argument("--targets-out", default=str(DEFAULT_TARGETS_OUT))
    parser.add_argument("--evidence-out", default=str(DEFAULT_EVIDENCE_OUT))
    args = parser.parse_args()

    manifest, evidence = build(
        Path(args.clinvar_bulk),
        clingen_path=Path(args.clingen) if args.clingen else None,
        gencc_path=Path(args.gencc) if args.gencc else None,
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
