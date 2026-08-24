#!/usr/bin/env python3
"""Derive trait and nutrition targets from the GWAS Catalog release, by declared ontology term.

Reports 04 and 08 came out nearly empty, and the reason was never the code: the target
registry held no locus scoped for nutrition and none scoped CURIOSIDADE. This fills both from
the GWAS Catalog's own release file.

**Why a declared term list is not an invention.** The catalogue labels every association with
an ontology term (EFO, MONDO, OBA, GO, HP) but publishes no thematic categorisation — nothing
in it says "lactose intolerance is nutritional". Deciding that is editorial, so it lives in
`config/trait_scopes.json` as a list of ontology identifiers with a written rationale, not as
a hidden constant. Everything downstream of the list — which loci, which risk allele, which
effect size, which discovery cohort — comes from the catalogue. And a declared term that
matches nothing in the release is a hard error, so the list cannot rot quietly into a scope
that silently covers less than it claims.

**Three refusals are built in.**

*Genome-wide significance only.* p ≤ 5×10⁻⁸. The nutrigenomics literature is full of
candidate-SNP findings at p < 0.05 that never replicated; admitting them would be the whole
failure mode of the genre.

*No risk allele where studies disagree.* The catalogue records `rs738409-C` in one study and
`rs738409-G` in another for the same locus. Picking one would arbitrate a conflict, so the
target gets no assessed allele and can only ever reach OBSERVADO — never NÃO DETECTADO.

*The discovery cohort travels with the association.* Ancestry is joined from the release's own
ancestry table by study accession. An effect estimated in a European cohort does not transfer
to an admixed Brazilian genome at the stated size, and a report that omits which cohort it
came from is making a claim it cannot support.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.targets import load_target_manifest, sha256_json

DEFAULT_SCOPES = ROOT / "config/trait_scopes.json"
DEFAULT_TARGETS_OUT = ROOT / "config/targets_gwas_traits.json"
DEFAULT_EVIDENCE_OUT = ROOT / "docs/evidence/TRAIT_ASSOCIATIONS_GWAS.json.gz"

GWAS_RELEASE = "https://ftp.ebi.ac.uk/pub/databases/gwas/releases/latest"
UNAVAILABLE = "NÃO DISPONÍVEL"


class TraitScopeError(ValueError):
    """The declared scope list does not match the catalogue."""


def _open_associations(path: Path) -> io.TextIOWrapper:
    if path.suffix == ".zip":
        archive = zipfile.ZipFile(path)
        name = next(n for n in archive.namelist() if n.endswith(".tsv"))
        return io.TextIOWrapper(archive.open(name), encoding="utf-8", errors="replace")
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def read_ancestries(path: Path) -> dict[str, dict[str, Any]]:
    """Discovery-cohort ancestry per study accession, from the release's ancestry table."""
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"initial": defaultdict(int), "replication": defaultdict(int), "descriptions": set()}
    )
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            accession = (row.get("STUDY ACCESSION") or "").strip()
            if not accession:
                continue
            group = (row.get("BROAD ANCESTRAL CATEGORY") or "").strip() or UNAVAILABLE
            stage = (row.get("STAGE") or "").strip().lower()
            try:
                count = int(row.get("NUMBER OF INDIVIDUALS") or 0)
            except ValueError:
                count = 0
            bucket = "replication" if stage.startswith("replication") else "initial"
            out[accession][bucket][group] += count
            description = (row.get("INITIAL SAMPLE DESCRIPTION") or "").strip()
            if description:
                out[accession]["descriptions"].add(description)
    return {
        accession: {
            "initial": dict(sorted(data["initial"].items(), key=lambda kv: -kv[1])),
            "replication": dict(sorted(data["replication"].items(), key=lambda kv: -kv[1])),
            "description": sorted(data["descriptions"])[:1],
        }
        for accession, data in out.items()
    }


def _risk_allele(field: str, rsid: str) -> str | None:
    """`rs738409-G` -> `G`. `rs738409-?` and anything unparseable -> None."""
    text = (field or "").strip()
    if "-" not in text:
        return None
    _, _, allele = text.rpartition("-")
    allele = allele.strip().upper()
    return allele if allele in ("A", "C", "G", "T") else None


def scan(
    associations_path: Path,
    wanted: dict[str, tuple[str, str]],
    threshold: float,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Every genome-wide-significant single-SNP association for the declared terms."""
    by_rsid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stats: dict[str, int] = defaultdict(int)
    with _open_associations(associations_path) as txt:
        header = txt.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in txt:
            stats["rows"] += 1
            row = line.rstrip("\n").split("\t")
            if len(row) < len(header):
                continue
            snps = row[idx["SNPS"]].strip()
            # Haplotypes (`rs1; rs2`) and SNP-SNP interactions (`rs1 x rs2`) are not a single
            # interrogable locus, so they are dropped rather than split.
            if not snps.startswith("rs") or any(sep in snps for sep in (";", " x ", ",")):
                continue
            try:
                pvalue = float(row[idx["P-VALUE"]])
            except ValueError:
                continue
            if pvalue > threshold:
                continue
            stats["significant"] += 1
            terms = [t.strip() for t in row[idx["MAPPED_TRAIT_URI"]].split(",")]
            labels = [t.strip() for t in row[idx["MAPPED_TRAIT"]].split(",")]
            # The two columns are comma-separated and positionally aligned, and a trait label
            # containing a comma breaks that alignment. Zipping them regardless does two
            # things silently: it puts another trait's name on this locus, and — when the
            # label list ends up shorter — it truncates, so trailing URIs are never checked
            # against the declared scope and their targets vanish. Where the lengths disagree
            # the URIs are kept, because they drive the lookup, and the labels are dropped in
            # favour of the one declared in config/trait_scopes.json.
            if len(labels) != len(terms):
                stats["misaligned_trait_columns"] += 1
                labels = [""] * len(terms)
            for uri, label in zip(terms, labels):
                term_id = uri.rsplit("/", 1)[-1].strip()
                if term_id not in wanted:
                    continue
                stats["matched"] += 1
                scope, declared_label = wanted[term_id]
                position = row[idx["CHR_POS"]].strip()
                by_rsid[snps].append(
                    {
                        "term_id": term_id,
                        "term_label": label or declared_label,
                        "scope": scope,
                        "pvalue": pvalue,
                        "risk_allele": _risk_allele(row[idx["STRONGEST SNP-RISK ALLELE"]], snps),
                        "risk_allele_frequency": row[idx["RISK ALLELE FREQUENCY"]].strip(),
                        "effect": row[idx["OR or BETA"]].strip(),
                        "confidence_interval": row[idx["95% CI (TEXT)"]].strip(),
                        "study": row[idx["STUDY ACCESSION"]].strip(),
                        "pubmed": row[idx["PUBMEDID"]].strip(),
                        "mapped_gene": row[idx["MAPPED_GENE"]].strip(),
                        "reported_genes": row[idx["REPORTED GENE(S)"]].strip(),
                        "initial_sample": row[idx["INITIAL SAMPLE SIZE"]].strip(),
                        "grch38": {
                            "chromosome": row[idx["CHR_ID"]].strip(),
                            "position": int(position) if position.isdigit() else None,
                        },
                    }
                )
    return dict(by_rsid), dict(stats)


def build(
    associations_path: Path,
    ancestry_path: Path,
    scopes_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = json.loads(Path(scopes_path).read_text(encoding="utf-8"))
    if config.get("schema") != "genoma-trait-scopes-v1":
        raise TraitScopeError(f"unsupported trait scope schema: {config.get('schema')!r}")
    threshold = float(config.get("significance_threshold", 5e-8))
    per_term = int(config.get("max_loci_per_term", 40))

    wanted: dict[str, tuple[str, str]] = {}
    for scope, block in config["scopes"].items():
        for term in block["terms"]:
            wanted[str(term["id"])] = (scope, str(term["label"]))

    by_rsid, stats = scan(associations_path, wanted, threshold)
    ancestries = read_ancestries(ancestry_path)

    # A declared term that matched nothing is a hard error, not a quiet gap: the scope would
    # claim coverage the registry does not have.
    matched_terms = {a["term_id"] for records in by_rsid.values() for a in records}
    missing = sorted(set(wanted) - matched_terms)
    if missing:
        raise TraitScopeError(
            "termos declarados sem nenhuma associação de significância genômica no catálogo: "
            + ", ".join(f"{t} ({wanted[t][1]})" for t in missing)
        )

    # Keep the strongest loci per term so one heavily-studied trait cannot swamp the registry.
    keep: set[str] = set()
    by_term: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for rsid, records in by_rsid.items():
        for record in records:
            by_term[record["term_id"]].append((record["pvalue"], rsid))
    for term_id, entries in by_term.items():
        for _pvalue, rsid in sorted(set(entries))[:per_term]:
            keep.add(rsid)

    targets: list[dict[str, Any]] = []
    loci: list[dict[str, Any]] = []
    target_stats: dict[str, int] = defaultdict(int)

    for rsid in sorted(keep, key=lambda r: int(r[2:]) if r[2:].isdigit() else 0):
        records = [r for r in by_rsid[rsid] if r["term_id"] in wanted]
        positions = {
            (r["grch38"]["chromosome"], r["grch38"]["position"])
            for r in records
            if r["grch38"]["position"]
        }
        if len(positions) != 1:
            target_stats["ambiguous_position"] += 1
            continue
        chromosome, position = next(iter(positions))

        # CURIOSIDADE wins a tie only if the locus has no PREDISPOSICAO association; a locus
        # that is both is clinical-adjacent and belongs in the stronger scope.
        scopes = {r["scope"] for r in records}
        scope = "PREDISPOSICAO" if "PREDISPOSICAO" in scopes else sorted(scopes)[0]
        alleles = {r["risk_allele"] for r in records if r["risk_allele"]}
        genes = sorted(
            {
                g.strip()
                for r in records
                for g in r["mapped_gene"].replace("-", ",").split(",")
                if g.strip() and g.strip() not in ("", "NR")
            }
        )
        terms = sorted({(r["term_id"], r["term_label"]) for r in records})
        best = min(records, key=lambda r: r["pvalue"])

        target: dict[str, Any] = {
            "rsid": rsid,
            "gene": genes[0] if genes else None,
            "genes": genes[:6],
            "scope": scope,
            "label": (
                f"{genes[0] if genes else 'sem gene mapeado'} {rsid}: "
                + "; ".join(label for _id, label in terms[:3])
            ),
            "queries": {"clinvar": {"term": rsid, "retmax": 5}},
            "grch38": {"chromosome": chromosome, "position": position},
            "gwas_terms": [{"id": i, "label": label} for i, label in terms],
            "gwas_best_pvalue": best["pvalue"],
            "gwas_studies": sorted({r["study"] for r in records})[:8],
            "gwas_association_count": len(records),
        }
        if len(alleles) == 1:
            target["assessed_allele"] = next(iter(alleles))
            target["assessed_allele_source"] = "GWAS Catalog STRONGEST SNP-RISK ALLELE"
            target["assessed_allele_status"] = "VERIFICADO"
            target["assessed_allele_reason"] = (
                f"único alelo de risco que o catálogo atribui a este locus em "
                f"{len(records)} associação(ões) de significância genômica"
            )
            target_stats["with_assessed_allele"] += 1
        else:
            target["gwas_risk_alleles"] = sorted(alleles)
            target["assessed_allele_reason"] = (
                "estudos divergem sobre o alelo de risco deste locus "
                f"({', '.join(sorted(alleles)) or 'nenhum alelo legível'}); escolher um seria "
                "arbitrar um conflito, e o locus não admite NÃO DETECTADO"
            )
            target_stats["conflicting_risk_allele" if alleles else "no_readable_risk_allele"] += 1
        targets.append(target)

        traits: dict[str, dict[str, Any]] = {}
        for record in sorted(records, key=lambda r: r["pvalue"]):
            entry = traits.setdefault(
                record["term_label"],
                {
                    "trait": record["term_label"],
                    "efo": record["term_id"],
                    "associations": 0,
                    "genome_wide_significant": 0,
                    "best_pvalue": record["pvalue"],
                    "risk_alleles": set(),
                    "effect": {
                        "odds_ratio": None,
                        "beta": record["effect"] or None,
                        "beta_unit": None,
                        "beta_direction": None,
                        "range": record["confidence_interval"] or None,
                        "risk_frequency": record["risk_allele_frequency"] or None,
                    },
                    "ancestry": {"status": UNAVAILABLE, "reason": "estudo sem tabela de ancestralidade"},
                },
            )
            entry["associations"] += 1
            entry["genome_wide_significant"] += 1
            if record["risk_allele"]:
                entry["risk_alleles"].add(record["risk_allele"])
            if entry["ancestry"]["status"] != "VERIFICADO":
                found = ancestries.get(record["study"])
                if found:
                    entry["ancestry"] = {
                        "status": "VERIFICADO",
                        "accession": record["study"],
                        "by_group": found["initial"],
                        "initial_sample": record["initial_sample"] or UNAVAILABLE,
                        "replication_sample": found["replication"] or UNAVAILABLE,
                    }
        for entry in traits.values():
            entry["risk_alleles"] = sorted(entry["risk_alleles"])
        loci.append(
            {
                "rsid": rsid,
                "gene": target["gene"],
                "grch38": target["grch38"],
                "clinvar": {"status": UNAVAILABLE, "records": [], "reason": "rota de traços; não consultado"},
                "gwas": {
                    "status": "VERIFICADO",
                    "associations_considered": len(records),
                    "traits_total": len(traits),
                    "traits_detailed": len(traits),
                    "traits": sorted(traits.values(), key=lambda t: t["best_pvalue"]),
                    "traits_not_detailed": [],
                    "significance_threshold": threshold,
                },
            }
        )

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sources = [
        f"EBI GWAS Catalog release, {GWAS_RELEASE}/gwas-catalog-associations_ontology-annotated-full.zip, "
        f"lido em {generated}. Coordenadas em GRCh38. Apenas associações de SNP único com "
        f"p <= {threshold}.",
        f"EBI GWAS Catalog ancestries, {GWAS_RELEASE}/gwas-catalog-download-ancestries-v1.0.3.1.txt",
        f"Escopo declarado pelo operador em config/trait_scopes.json ({config['version']})",
    ]

    manifest = {
        "schema": "genoma-partial-genome-targets-v1",
        "id": "GENOMA-GWAS-TRAITS",
        "version": generated[:10].replace("-", "") + ".1",
        "description": (
            "Loci associados aos termos de ontologia declarados em config/trait_scopes.json, "
            "com significância genômica no GWAS Catalog. Presença aqui autoriza apenas "
            "interrogação de cobertura: associação não é causalidade, o efeito é médio de "
            "coorte e não resposta individual, e a transferibilidade entre ancestralidades não "
            "está estabelecida. Reproduzir com scripts/build_trait_targets.py."
        ),
        "sources": sources,
        "generated_at": generated,
        "selection": {
            "significance_threshold": threshold,
            "max_loci_per_term": per_term,
            "single_snp_only": True,
            "scopes": {scope: len(block["terms"]) for scope, block in config["scopes"].items()},
        },
        "scan_statistics": stats,
        "target_statistics": dict(target_stats),
        "targets": targets,
    }
    manifest["sha256"] = sha256_json({k: v for k, v in manifest.items() if k != "sha256"})

    evidence = {
        "schema": "genoma-gene-disease-validity-v1",
        "curated_at": generated,
        "sources": sources,
        "method": (
            "Associações de traço do release do GWAS Catalog, filtradas pelos termos de "
            "ontologia declarados e por significância genômica, com a ancestralidade da coorte "
            "de descoberta unida pelo acesso do estudo. Não há validade gene-doença aqui: "
            "associação de GWAS é um nível de evidência abaixo, e este arquivo não estabelece "
            "relação gene-doença para nenhum gene."
        ),
        "gene_validity": {},
        "loci": loci,
        "totals": {"loci": len(loci), "genes": len({t["gene"] for t in targets if t["gene"]})},
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
    parser.add_argument("--associations", required=True, help="GWAS Catalog associations zip/tsv")
    parser.add_argument("--ancestries", required=True, help="GWAS Catalog ancestries TSV")
    parser.add_argument("--scopes", default=str(DEFAULT_SCOPES))
    parser.add_argument("--targets-out", default=str(DEFAULT_TARGETS_OUT))
    parser.add_argument("--evidence-out", default=str(DEFAULT_EVIDENCE_OUT))
    args = parser.parse_args()

    manifest, evidence = build(
        Path(args.associations), Path(args.ancestries), Path(args.scopes)
    )
    targets_out = _write(manifest, Path(args.targets_out))
    evidence_out = _write(evidence, Path(args.evidence_out))
    load_target_manifest(targets_out)

    by_scope: dict[str, int] = defaultdict(int)
    for target in manifest["targets"]:
        by_scope[target["scope"]] += 1
    print(
        json.dumps(
            {
                "targets": str(targets_out),
                "evidence": str(evidence_out),
                "target_count": len(manifest["targets"]),
                "by_scope": dict(by_scope),
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
