#!/usr/bin/env python3
"""Annotate interrogated loci with gnomAD allele frequencies, by population.

Report 03 can now say how much of a gene's pathogenic catalogue was interrogated, as a count
of variants. It still cannot say how much of the *risk* that covers, and the two differ
sharply: rare variants dominate the count while common ones dominate the frequency, so a
panel covering 2% of a gene's catalogue may cover most of its carrier burden, or almost none.

gnomAD is what closes that gap. It publishes allele counts by genetic ancestry group over
~800,000 exomes and genomes, which turns "2 of 134 variants" into a carrier frequency.

**Why per case and not for the whole registry.** The registry holds 55,916 loci; annotating
all of them is hundreds of thousands of API calls for numbers most cases will never use.
This runs over the loci a case actually interrogated — a few thousand — so the cost is
bounded by coverage rather than by catalogue size.

**A missing answer is never a zero.** A variant gnomAD does not carry, or a query that fails,
is recorded as NÃO DISPONÍVEL. Reading either as a frequency of zero would say the variant is
absent from every population, which is the most reassuring possible wrong answer.
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

from array_pipeline.targets import sha256_json

GNOMAD_API = "https://gnomad.broadinstitute.org/api"
DATASET = "gnomad_r4"
REQUEST_INTERVAL_SECONDS = 0.25

#: gnomAD reports each group and its sex-stratified subsets; the subsets are the same
#: chromosomes counted again, so summing them would double every frequency.
SEX_SUFFIXES = ("_XX", "_XY")
#: The whole-cohort sex strata arrive as bare `XX` and `XY`, which the suffix test above does
#: not catch. They are every chromosome counted again, split by sex, so leaving them in the
#: ancestry list lets a sex stratum win "highest frequency population" — a category error.
SEX_STRATA = frozenset({"XX", "XY"})

#: gnomAD v4 also exposes the HGDP and 1000 Genomes cohorts as populations named
#: `hgdp:french`, `1kg:gbr` and so on. Those have tens to hundreds of chromosomes against
#: tens of thousands in the main groups, so letting them compete for "highest frequency"
#: hands the headline to whichever small cohort happened to sample a carrier — HFE C282Y
#: reported 9.3% in `hgdp:french` before this filter. They are kept, separately, because a
#: cohort-level frequency is still evidence; they just do not set the headline.
COHORT_PREFIXES = ("hgdp:", "1kg:")

QUERY = """
query Variant($variantId: String!, $dataset: DatasetId!) {
  variant(variantId: $variantId, dataset: $dataset) {
    variant_id
    rsids
    genome { ac an populations { id ac an } }
    exome { ac an populations { id ac an } }
  }
}
"""

UNAVAILABLE = "NÃO DISPONÍVEL"


def _post(payload: dict[str, Any], *, attempts: int = 3) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        GNOMAD_API,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "genoma-gnomad/1.0"},
    )
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"gnomAD query failed after {attempts} attempts: {last}")


def _frequencies(block: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split gnomAD's population list into main ancestry groups and cohort subsets."""
    if not block:
        return {}, {}
    groups: dict[str, Any] = {}
    cohorts: dict[str, Any] = {}
    for population in block.get("populations") or []:
        identifier = str(population.get("id") or "")
        if identifier.endswith(SEX_SUFFIXES) or identifier in SEX_STRATA:
            continue
        allele_number = population.get("an") or 0
        if not allele_number:
            continue
        record = {
            "ac": population.get("ac"),
            "an": allele_number,
            "af": round((population.get("ac") or 0) / allele_number, 8),
        }
        if identifier.startswith(COHORT_PREFIXES):
            cohorts[identifier] = record
        else:
            groups[identifier] = record
    return groups, cohorts


def annotate(variant_id: str) -> dict[str, Any]:
    """One variant's frequencies, or a recorded reason there are none."""
    try:
        response = _post({"query": QUERY, "variables": {"variantId": variant_id, "dataset": DATASET}})
    except RuntimeError as exc:
        return {"status": UNAVAILABLE, "reason": str(exc), "variant_id": variant_id}
    variant = (response.get("data") or {}).get("variant")
    if not variant:
        errors = "; ".join(str(e.get("message")) for e in response.get("errors") or [])
        return {
            "status": UNAVAILABLE,
            "variant_id": variant_id,
            "reason": errors or f"gnomAD {DATASET} não carrega esta variante",
        }

    genome, genome_cohorts = _frequencies(variant.get("genome"))
    exome, exome_cohorts = _frequencies(variant.get("exome"))
    # Genome and exome are separate callsets over overlapping samples; they are reported
    # apart rather than pooled, because pooling would need the joint frequency gnomAD
    # publishes and this query does not request.
    combined = genome or exome
    highest = max(combined.items(), key=lambda kv: kv[1]["af"]) if combined else None
    return {
        "status": "VERIFICADO",
        "variant_id": variant["variant_id"],
        "rsids": variant.get("rsids") or [],
        "dataset": DATASET,
        "genome_populations": genome,
        "exome_populations": exome,
        "genome_cohorts": genome_cohorts,
        "exome_cohorts": exome_cohorts,
        "preferred_callset": "genome" if genome else ("exome" if exome else UNAVAILABLE),
        "highest_frequency_population": highest[0] if highest else UNAVAILABLE,
        "highest_frequency_scope": (
            "grupo de ancestralidade principal do gnomAD; subconjuntos de coorte "
            "(hgdp:, 1kg:) ficam em genome_cohorts e não disputam este máximo"
        ),
        "highest_frequency": highest[1]["af"] if highest else None,
        "carrier_frequency_estimate": (
            # 2pq under Hardy-Weinberg, the standard reading of a carrier rate from an allele
            # frequency. It assumes random mating and no selection, which is why it is named
            # as an estimate and reported beside the raw frequency rather than instead of it.
            round(2 * highest[1]["af"] * (1 - highest[1]["af"]), 8) if highest else None
        ),
    }


def variant_id_for(finding: dict[str, Any]) -> str | None:
    """gnomAD's `chrom-pos-ref-alt`, from a target that carries a GRCh38 coordinate."""
    coordinate = finding.get("grch38") or {}
    chromosome = str(coordinate.get("chromosome") or "").replace("chr", "")
    position = coordinate.get("position")
    reference = str(finding.get("reference_allele") or "").upper()
    alternate = str(finding.get("assessed_allele") or "").upper()
    if not chromosome or not position or reference not in "ACGT" or alternate not in "ACGT":
        return None
    if len(reference) != 1 or len(alternate) != 1:
        return None
    return f"{chromosome}-{position}-{reference}-{alternate}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", required=True, help="target manifest carrying GRCh38 coordinates")
    parser.add_argument("--matrix", help="completeness matrix; restricts to interrogated loci")
    parser.add_argument("--limit", type=int, default=500, help="maximum variants to query")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    from array_pipeline.targets import load_target_manifest

    manifest = load_target_manifest(Path(args.targets))
    targets = {str(t["rsid"]).lower(): t for t in manifest["targets"]}

    if args.matrix:
        matrix = json.loads(Path(args.matrix).read_text(encoding="utf-8"))
        interrogated = {
            str(e["rsid"]).lower()
            for e in matrix.get("entries", [])
            if e.get("classification") in ("OBSERVADO", "NÃO DETECTADO")
        }
        selected = [targets[r] for r in sorted(interrogated) if r in targets]
    else:
        selected = list(targets.values())

    results: list[dict[str, Any]] = []
    skipped = 0
    for target in selected[: args.limit]:
        variant_id = variant_id_for(target)
        if variant_id is None:
            skipped += 1
            continue
        record = annotate(variant_id)
        record["rsid"] = target["rsid"]
        record["gene"] = target.get("gene")
        results.append(record)
        time.sleep(REQUEST_INTERVAL_SECONDS)

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "schema": "genoma-gnomad-frequencies-v1",
        "curated_at": generated,
        "sources": [
            f"gnomAD {DATASET} via {GNOMAD_API} (GraphQL), consultado em {generated}. "
            "Frequências por grupo de ancestralidade genética, contagens alélicas brutas "
            "preservadas ao lado da frequência."
        ],
        "method": (
            "Uma consulta por variante, identificada por coordenada GRCh38 e par de alelos. "
            "Subconjuntos estratificados por sexo (_XX, _XY) são ignorados porque são os "
            "mesmos cromossomos contados de novo. Variante ausente do gnomAD ou consulta que "
            "falha ficam NÃO DISPONÍVEL: ler qualquer das duas como frequência zero afirmaria "
            "ausência em todas as populações."
        ),
        "dataset": DATASET,
        "totals": {
            "requested": len(results),
            "with_frequencies": sum(1 for r in results if r["status"] == "VERIFICADO"),
            "unavailable": sum(1 for r in results if r["status"] != "VERIFICADO"),
            "skipped_no_coordinate": skipped,
        },
        "variants": results,
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), **payload["totals"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
