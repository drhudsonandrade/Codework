#!/usr/bin/env python3
"""Derive the full CPIC defining-position panel from the allele-definition registry.

The passport reported that the array interrogated one to four of the forty to eighty
positions CPIC uses to define each gene's star alleles, and concluded that only targeted
sequencing could change that. The first half of that conclusion was an artefact of this
pipeline, not a property of the array.

`config/partial_genome_annotation_targets.json` lists twenty-nine hand-picked loci. The
completeness matrix classifies exactly those, and the passport then joins CPIC's defining
positions against that matrix — so **every CPIC position outside the twenty-nine came back
NÃO TESTADO by construction**, whether or not the chip carried it. A consumer array assays
several hundred thousand positions; how many of CPIC's it happens to include had never been
measured, only assumed.

This script derives a second target manifest containing *every* defining position CPIC
publishes for the registry's genes, so the question becomes a measurement. Running the
completeness matrix over it says how many of those positions this array actually carries,
which is the number the coverage claim should have rested on all along.

Nothing here is authored. Each position's assessed allele is the variant base CPIC's
`allele_location_value` assigns it. Where two alleles of the same gene are defined by
different bases at one position, no assessed allele is emitted: the locus stays OBSERVADO
rather than being scored against an arbitrarily chosen one of them.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.pharmacogenomics import load_pgx_registry
from array_pipeline.targets import load_target_manifest, sha256_json

DEFAULT_REGISTRY = ROOT / "config/pgx_allele_definitions.json"
DEFAULT_OUTPUT = ROOT / "config/pgx_panel_targets.json"

SCHEMA = "genoma-partial-genome-targets-v1"


def build_panel(registry: dict[str, Any]) -> dict[str, Any]:
    """One target per unique CPIC defining position, carrying its GRCh38 coordinate."""
    by_rsid: dict[str, dict[str, Any]] = {}
    alleles_at: dict[str, set[str]] = defaultdict(set)
    bases_at: dict[str, set[str]] = defaultdict(set)

    for gene in sorted(registry.get("genes", {})):
        spec = registry["genes"][gene] or {}
        for allele in sorted(spec.get("alleles", {})):
            for item in spec["alleles"][allele].get("defining", []):
                rsid = str(item.get("rsid") or "").strip().lower()
                if not rsid.startswith("rs") or not rsid[2:].isdigit():
                    continue
                base = str(item.get("allele") or "").strip().upper()
                alleles_at[rsid].add(allele)
                if base:
                    bases_at[rsid].add(base)
                position = item.get("position")
                chromosome = str(item.get("chromosome") or "").strip()
                accession = str(item.get("reference_accession") or "").strip()
                normalized_chromosome = chromosome.lower().removeprefix("chr").upper()
                if isinstance(position, bool) or not isinstance(position, int) or position <= 0:
                    raise ValueError(f"{rsid} has invalid GRCh38 position: {position!r}")
                if normalized_chromosome not in {
                    *(str(number) for number in range(1, 23)), "X", "Y", "M", "MT"
                }:
                    raise ValueError(f"{rsid} has invalid GRCh38 chromosome: {chromosome!r}")
                if not accession.startswith("NC_") or "." not in accession:
                    raise ValueError(
                        f"{rsid} has invalid GRCh38 reference_accession: {accession!r}"
                    )
                candidate_identity = {
                    "position": position,
                    "chromosome": chromosome,
                    "reference_accession": accession,
                    "cpic_location": item.get("cpic_location"),
                    "chromosome_location": item.get("chromosome_location"),
                }
                record = by_rsid.get(rsid)
                if record is None:
                    record = {
                        "rsid": rsid,
                        "gene": gene,
                        "genes": set(),
                        **candidate_identity,
                    }
                    by_rsid[rsid] = record
                else:
                    conflicts = sorted(
                        field
                        for field, value in candidate_identity.items()
                        if record.get(field) != value
                    )
                    if conflicts:
                        raise ValueError(
                            f"{rsid} has conflicting CPIC coordinate identity fields: "
                            f"{', '.join(conflicts)}"
                        )
                record["genes"].add(gene)

    targets: list[dict[str, Any]] = []
    for rsid in sorted(by_rsid, key=lambda r: int(r[2:])):
        record = by_rsid[rsid]
        genes = sorted(record.pop("genes"))
        defines = sorted(alleles_at[rsid])
        bases = sorted(bases_at[rsid])
        # A position that defines two alleles by two different bases has no single "allele
        # being looked for". Emitting one of them would make the completeness matrix score
        # the locus against a choice this script made, so none is emitted and the locus can
        # only ever reach OBSERVADO.
        assessed = bases[0] if len(bases) == 1 else None
        sample = ", ".join(defines[:4]) + (f" (+{len(defines) - 4})" if len(defines) > 4 else "")
        target: dict[str, Any] = {
            "rsid": rsid,
            "gene": record["gene"],
            "genes": genes,
            "scope": "CLINICO",
            "label": f"posição definidora CPIC de {'/'.join(genes)}: {sample}",
            "queries": {"cpic": {"path": "data/gene", "params": {"symbol": genes[0]}}},
            "defines_alleles": defines,
            "cpic_variant_alleles": bases,
            "grch38": {
                "chromosome": record["chromosome"],
                "position": record["position"],
                "reference_accession": record["reference_accession"],
            },
            "cpic_location": record["cpic_location"],
            "chromosome_location": record["chromosome_location"],
        }
        if assessed:
            target["assessed_allele"] = assessed
            target["assessed_allele_source"] = "CPIC allele_location_value"
            target["assessed_allele_status"] = "VERIFICADO"
            target["assessed_allele_reason"] = (
                f"única base variante que o CPIC atribui a esta posição, definindo {sample}"
            )
        else:
            target["assessed_allele_reason"] = (
                f"o CPIC atribui mais de uma base variante a esta posição ({', '.join(bases)}); "
                "nenhum alelo avaliado único pode ser declarado e o locus não admite NÃO DETECTADO"
            )
        targets.append(target)

    retrieved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "schema": SCHEMA,
        "id": "GENOMA-PGX-CPIC-PANEL",
        "version": (
            retrieved[:10].replace("-", "")
            + "."
            + sha256_json(
                {
                    "registry_sha256": sha256_json(registry),
                    "schema": SCHEMA,
                    "generator": "scripts/build_pgx_panel.py",
                }
            )[:12]
        ),
        "description": (
            "Toda posição definidora publicada pelo CPIC para os genes do registro "
            "farmacogenômico, derivada de config/pgx_allele_definitions.json. Presença aqui "
            "autoriza apenas interrogação de cobertura: não estabelece significado clínico, "
            "diplótipo, fase nem completude. Reproduzir com scripts/build_pgx_panel.py."
        ),
        "derived_from": {
            "registry_id": registry.get("id"),
            "registry_version": registry.get("version"),
            "registry_source": registry.get("source"),
            "registry_sha256": sha256_json(registry),
        },
        "generated_at": retrieved,
        "targets": targets,
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def main() -> int:
    """Build the PGx target panel from the curated registry's defining positions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    registry = load_pgx_registry(Path(args.registry))
    payload = build_panel(registry)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Load it back through the real validator: a manifest this pipeline cannot read is not a
    # manifest, and finding that out here beats finding it out mid-run.
    load_target_manifest(out)

    per_gene: dict[str, int] = defaultdict(int)
    for target in payload["targets"]:
        for gene in target["genes"]:
            per_gene[gene] += 1
    print(f"painel escrito em {out}")
    print(f"  posições definidoras únicas: {len(payload['targets'])}")
    print(f"  com alelo avaliado único:    {sum(1 for t in payload['targets'] if t.get('assessed_allele'))}")
    for gene in sorted(per_gene):
        print(f"  {gene:<9} {per_gene[gene]:>4} posições")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
