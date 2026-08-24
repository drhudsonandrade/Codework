#!/usr/bin/env python3
"""Build the PGx allele-definition registry from CPIC, with citation.

`array_pipeline/pharmacogenomics.py` refuses to name a star allele unless a curated registry
supplies the definitions and cites their source, because an uncited definition table is an
invented clinical assertion wearing a schema. No such registry shipped, so every diplotype
was NÃO DISPONÍVEL and the anaesthesia card was never emitted.

This script produces that registry from the CPIC API, which is the authoritative source for
clinical pharmacogenetic allele definitions. It joins four CPIC tables:

    allele            -> allele names, clinical function, PharmVar id, definition id
    allele_definition -> reference-sequence flag, structural-variation flag
    allele_location_value -> which variant base defines the allele at each location
    sequence_location -> the rsid and position of each location

and, separately, the `diplotype` table, which is CPIC's own diplotype -> phenotype mapping.
Nothing here is authored: every allele, every defining position and every phenotype label is
whatever CPIC returned, recorded with the retrieval date and CPIC's own version numbers.

Two further CPIC columns are carried because `array_pipeline/allele_discrimination.py`
cannot work without them. `allele.frequency` gives each allele's frequency per biogeographic
group, which is what turns "this allele was not interrogated" into a *quantified* residual
rather than an open-ended caveat; and `sequence_location.position` plus the gene's GRCh38
chromosome accession give each defining position a coordinate, which is what turns "targeted
sequencing is required" into a requisition an external laboratory can actually execute.

**`complete_panel` means complete with respect to CPIC**, not biologically exhaustive. An
allele CPIC has not catalogued stays indistinguishable from the reference haplotype, and the
passport says so. Alleles CPIC flags as structural variation are excluded from definitions —
an array cannot genotype them — and recorded separately so their absence is visible.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CPIC_BASE = "https://api.cpicpgx.org/v1"
DEFAULT_OUTPUT = ROOT / "config/pgx_allele_definitions.json"
REQUEST_INTERVAL_SECONDS = 0.3

#: Genes worth fetching: those the target registry routes to a PGx knowledge base.
DEFAULT_GENES = (
    "BCHE", "CYP2C19", "CYP2C9", "CYP3A5", "DPYD",
    "NAT2", "NUDT15", "SLCO1B1", "TPMT", "VKORC1",
)

#: CPIC marks the reference haplotype with `matchesreferencesequence`. Genes whose
#: clinically relevant variation is structural are never diplotyped from an array, so the
#: passport blocks them regardless of what this registry says.
ANAESTHESIA_RELEVANT = {
    "BCHE": (
        "Atividade reduzida de butirilcolinesterase prolonga o bloqueio por succinilcolina e "
        "mivacúrio. Genótipo não substitui dosagem de atividade enzimática nem número de dibucaína."
    ),
}

#: The CPIC guideline that defines what an anaesthesia-facing card is *for*. Its two genes
#: carry CPIC level A — the highest evidence level CPIC assigns — while BCHE, the only
#: anaesthesia gene this registry holds definitions for, is level B/C.
#:
#: Naming the guideline here is what lets the card state the gap instead of being silent
#: about it. Before this, `anesthesia_card` reported VERIFICADO whenever a single BCHE locus
#: was interpretable, and the one-page summary printed that word alone — with nothing
#: anywhere saying that susceptibility to malignant hyperthermia had never been interrogated
#: and is not in the knowledge base at all. Succinylcholine and every volatile agent are
#: precisely the drugs that decision concerns.
ANAESTHESIA_GUIDELINE_ID = 100427
ANAESTHESIA_GUIDELINE_NAME = "RYR1, CACNA1S and Volatile anesthetic agents and Succinylcholine"


class CpicError(RuntimeError):
    pass


def _get(path: str, *, attempts: int = 4, **params: str) -> list[dict[str, Any]]:
    """Fetch one CPIC table, retrying transient network faults.

    A dropped connection partway through must not silently yield a shorter allele list: an
    allele missing from the registry would make an untested haplotype look catalogued, so
    this raises rather than returning what it managed to collect.
    """
    query = urllib.parse.urlencode(params)
    url = f"{CPIC_BASE}/{path}" + (f"?{query}" if query else "")
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "genoma-pgx-registry/1.0"}
    )
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                raise CpicError(f"CPIC returned a non-list payload for {url}")
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code != 429 && not 500 <= exc.code < 600:
                raise CpicError(
                    f"CPIC fetch failed for {url} with non-retriable HTTP status {exc.code}"
                ) from exc
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise CpicError(f"CPIC fetch failed for {url} after {attempts} attempts: {last}")


def _frequency_object(value: Any) -> dict[str, float]:
    """Keep only real per-population frequency tables.

    A frequency of `null` for a group means CPIC published no number for it, which is not a
    frequency of zero; those keys are dropped rather than zero-filled so that a consumer
    counting how many groups are covered gets the honest count.
    """
    if not isinstance(value, dict):
        return {}
    return {
        str(group): float(freq)
        for group, freq in value.items()
        if isinstance(freq, (int, float)) and not isinstance(freq, bool)
    }


def _allele_label(symbol: str, name: str) -> str:
    """`*2` -> `CYP2C19*2`, but CPIC also uses descriptive names.

    VKORC1's alleles are named `rs9923231 variant (T)`; blindly prefixing the symbol
    produced `VKORC1rs9923231 variant (T)`, which reads as a star allele that does not
    exist.
    """
    return f"{symbol}{name}" if name.startswith("*") else f"{symbol} {name}"


#: Genes CPIC lists without publishing an allele table, and the rsids whose ClinVar records
#: define their clinically relevant variants. Naming here is deliberately HGVS/ClinVar, not
#: star nomenclature: BCHE's star names are not in a machine-readable public registry this
#: project can verify, and inventing `BCHE*2` from memory is the assertion the whole design
#: refuses. The variants are real and cited; only the shorthand is withheld.
CLINVAR_FALLBACK_GENES: dict[str, tuple[str, ...]] = {
    "BCHE": ("rs1799807", "rs1803274"),
}


def _clinvar_fallback(symbol: str) -> dict[str, Any]:
    """Build a gene's definitions from ClinVar when CPIC publishes no allele table."""
    from scripts.curate_assessed_alleles import curate_target

    alleles: dict[str, Any] = {}
    unresolved: list[str] = []
    for rsid in CLINVAR_FALLBACK_GENES[symbol]:
        record = curate_target(rsid, None)
        if not record.get("assessed_allele"):
            unresolved.append(f"{rsid}: {record.get('reason', 'no assertion')}")
            continue
        asserted = [
            m
            for m in record.get("clinvar_records_at_this_coordinate", [])
            if m["alternate"] == record["assessed_allele"]
        ]
        name = next((str(m.get("title")) for m in asserted if m.get("title")), rsid)
        # The GRCh38 coordinate travels with the definition here for the same reason it does
        # on the CPIC path: without it the sequencing requisition for this gene would list
        # rsids a laboratory still has to look up before it can design anything.
        grch38 = record.get("grch38") or {}
        chromosome = str(grch38.get("chromosome") or "").strip()
        alleles[f"{symbol} {name}"] = {
            "defining": [
                {
                    "rsid": rsid,
                    "allele": record["assessed_allele"],
                    "position": grch38.get("position"),
                    "chromosome": f"chr{chromosome}" if chromosome else None,
                }
            ],
            "clinvar_accessions": sorted({str(m.get("accession")) for m in asserted if m.get("accession")}),
            "clinvar_classification": next((m["classification"] for m in asserted), None),
            "reference_allele_dbsnp": record.get("reference_allele"),
            "population_frequency_dbsnp": (record.get("dbsnp_frequencies") or {}).get(
                record["assessed_allele"]
            ),
        }
    return {
        # ClinVar catalogues variants, not haplotypes: it cannot say the panel is complete,
        # so no diplotype will be established for this gene and the passport says why.
        "complete_panel": False,
        "complete_panel_scope": "ClinVar (variant catalogue, not an allele-definition registry)",
        "definitions_unavailable": (
            "CPIC não publica tabela de definição de alelos para este gene e o PharmVar exige "
            "credenciais que este projeto não possui. As variantes abaixo vêm do ClinVar, com "
            "acesso citado, e são nomeadas pela designação HGVS do próprio ClinVar — a "
            "nomenclatura estrela deste gene não está em registro público verificável, e "
            "inventá-la seria asserção clínica sem fonte. Nenhum diplótipo é estabelecido."
        ),
        "reference_allele": None,
        "alleles": alleles,
        "structural_alleles_excluded": [],
        "alleles_without_usable_snp_definition": unresolved,
        "phenotype_map": {},
        "phenotype_map_source": "NÃO DISPONÍVEL",
        "variant_source": "NCBI ClinVar via E-utilities, joined to dbSNP by GRCh38 coordinate",
        **(
            {"anesthesia_relevant": True, "anesthesia_note": ANAESTHESIA_RELEVANT[symbol]}
            if symbol in ANAESTHESIA_RELEVANT
            else {}
        ),
    }


def fetch_gene(symbol: str) -> dict[str, Any]:
    """Assemble one gene's allele definitions and CPIC's diplotype->phenotype table."""
    alleles = _get("allele", genesymbol=f"eq.{symbol}")
    if not alleles and symbol in CLINVAR_FALLBACK_GENES:
        return _clinvar_fallback(symbol)
    if not alleles:
        # CPIC lists some gene symbols without publishing an allele definition table.
        # BCHE is one of them, and PharmVar's API requires credentials this project does
        # not hold. Recording the gap is the whole point: without definitions no star
        # allele may be named, and the passport must say why rather than fall silent.
        return {
            "complete_panel": False,
            "complete_panel_scope": "CPIC",
            "definitions_unavailable": (
                "CPIC não publica tabela de definição de alelos para este gene "
                "(allele, allele_definition e sequence_location retornam vazio). "
                "PharmVar exige credenciais que este projeto não possui. "
                "Nenhum alelo estrela pode ser nomeado; apenas genótipos observados."
            ),
            "reference_allele": None,
            "alleles": {},
            "structural_alleles_excluded": [],
            "alleles_without_usable_snp_definition": [],
            "phenotype_map": {},
            "phenotype_map_source": "NÃO DISPONÍVEL",
            **(
                {"anesthesia_relevant": True, "anesthesia_note": ANAESTHESIA_RELEVANT[symbol]}
                if symbol in ANAESTHESIA_RELEVANT
                else {}
            ),
        }
    time.sleep(REQUEST_INTERVAL_SECONDS)
    definitions = _get("allele_definition", genesymbol=f"eq.{symbol}")
    time.sleep(REQUEST_INTERVAL_SECONDS)
    locations = _get("sequence_location", genesymbol=f"eq.{symbol}")
    time.sleep(REQUEST_INTERVAL_SECONDS)
    gene_rows = _get("gene", symbol=f"eq.{symbol}")
    time.sleep(REQUEST_INTERVAL_SECONDS)
    gene_row = gene_rows[0] if gene_rows else {}

    definition_by_id = {d["id"]: d for d in definitions}
    location_by_id = {loc["id"]: loc for loc in locations}

    values: list[dict[str, Any]] = []
    definition_ids = [str(d["id"]) for d in definitions]
    for chunk_start in range(0, len(definition_ids), 40):
        chunk = definition_ids[chunk_start : chunk_start + 40]
        values.extend(
            _get("allele_location_value", alleledefinitionid=f"in.({','.join(chunk)})")
        )
        time.sleep(REQUEST_INTERVAL_SECONDS)

    by_definition: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for value in values:
        by_definition[value["alleledefinitionid"]].append(value)

    built: dict[str, Any] = {}
    structural: list[str] = []
    reference_allele: str | None = None
    skipped_no_rsid: list[str] = []

    for allele in sorted(alleles, key=lambda a: str(a.get("name") or "")):
        name = str(allele.get("name") or "").strip()
        definition = definition_by_id.get(allele.get("definitionid"))
        if not name or definition is None:
            continue
        if definition.get("matchesreferencesequence"):
            reference_allele = _allele_label(symbol, name)
        if definition.get("structuralvariation"):
            # A duplication or hybrid is not a base substitution; no SNP set defines it.
            structural.append(_allele_label(symbol, name))
            continue

        defining: list[dict[str, Any]] = []
        missing_rsid = False
        for value in by_definition.get(definition["id"], []):
            location = location_by_id.get(value["locationid"])
            if location is None:
                continue
            rsid = (location.get("dbsnpid") or "").strip()
            variant = (value.get("variantallele") or "").strip().upper()
            if not variant or len(variant) != 1 or variant not in "ACGT":
                # Indels and multi-base variants are outside what the array probe reads.
                continue
            if not rsid:
                missing_rsid = True
                continue
            defining.append(
                {
                    "rsid": rsid.lower(),
                    "allele": variant,
                    "cpic_location": location.get("name"),
                    "chromosome_location": location.get("chromosomelocation"),
                    # Coordinate and accession are what a sequencing requisition is written
                    # in; without them the "order targeted sequencing" conclusion stays a
                    # sentence instead of becoming an executable panel design.
                    "position": location.get("position"),
                    "chromosome": gene_row.get("chr"),
                    "reference_accession": gene_row.get("chromosequenceid"),
                }
            )

        if definition.get("matchesreferencesequence"):
            # The reference haplotype is defined by the absence of the others, not by a
            # variant of its own; it is named in `reference_allele`, not as a definition.
            continue
        if not defining:
            skipped_no_rsid.append(_allele_label(symbol, name))
            continue
        if missing_rsid:
            skipped_no_rsid.append(f"{_allele_label(symbol, name)} (parcial)")

        built[_allele_label(symbol, name)] = {
            "definition_complete": not missing_rsid,
            "defining": sorted(defining, key=lambda d: d["rsid"]),
            "cpic_clinical_function": allele.get("clinicalfunctionalstatus"),
            "cpic_activity_value": allele.get("activityvalue"),
            "cpic_strength": allele.get("strength"),
            "pharmvar_id": definition.get("pharmvarid"),
            "citations": allele.get("citations") or [],
            # Per-biogeographic-group frequency, exactly as CPIC publishes it. `frequency`
            # is CPIC's observed table and `inferredfrequency` its imputed one; they are kept
            # apart so a residual computed from inferred numbers can never be presented as an
            # observed one. A null inside either object means CPIC published no number for
            # that group — not a frequency of zero, and the discrimination module must not
            # read it as one.
            # CPIC returns `inferredfrequency` as a boolean flag on some alleles and as a
            # frequency object on others. Coercing whatever arrives into a dict would turn
            # `true` into an empty frequency table that reads as "no frequencies published";
            # keeping only real objects, and recording the flag separately, keeps the two
            # meanings apart.
            "cpic_frequency": _frequency_object(allele.get("frequency")),
            "cpic_inferred_frequency": _frequency_object(allele.get("inferredfrequency")),
            "cpic_frequency_is_inferred": allele.get("inferredfrequency") is True,
        }

    diplotypes = _get("diplotype", genesymbol=f"eq.{symbol}")
    time.sleep(REQUEST_INTERVAL_SECONDS)
    phenotype_map = {
        str(d["diplotype"]): {
            "phenotype": d.get("generesult"),
            "activity_score": d.get("totalactivityscore"),
            "description": d.get("description"),
        }
        for d in diplotypes
        if d.get("diplotype")
    }

    record: dict[str, Any] = {
        # Complete with respect to CPIC's catalogue, which is what the citation covers.
        "complete_panel": bool(built) and all(
            definition.get("definition_complete", True) for definition in built.values()
        ),
        "complete_panel_scope": "CPIC",
        "chromosome": gene_row.get("chr"),
        "reference_accession": gene_row.get("chromosequenceid"),
        "gene_reference_sequence": gene_row.get("genesequenceid"),
        "reference_allele": reference_allele,
        "alleles": built,
        "structural_alleles_excluded": sorted(structural),
        "alleles_without_usable_snp_definition": sorted(skipped_no_rsid),
        "phenotype_map": phenotype_map,
        "phenotype_map_source": "CPIC diplotype table",
    }
    if symbol in ANAESTHESIA_RELEVANT:
        record["anesthesia_relevant"] = True
        record["anesthesia_note"] = ANAESTHESIA_RELEVANT[symbol]
    return record


def fetch_anaesthesia_scope(built: dict[str, Any]) -> dict[str, Any]:
    """What CPIC says an anaesthesia card must cover, and which of it this registry holds.

    Read from the CPIC pair table rather than written here, so the scope cannot drift away
    from the guideline it claims to follow. A gene CPIC lists that this registry carries no
    definitions for is recorded with `definitions_available: false` — the card then names it
    as NÃO INTERROGADO instead of leaving the reader to notice the absence.
    """
    pairs = _get("pair", guidelineid=f"eq.{ANAESTHESIA_GUIDELINE_ID}")
    time.sleep(REQUEST_INTERVAL_SECONDS)
    drugs: dict[str, str] = {}
    genes: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        symbol = str(pair.get("genesymbol") or "").strip()
        if not symbol:
            continue
        entry = genes.setdefault(symbol, {"gene": symbol, "cpic_level": pair.get("cpiclevel"), "drugs": set()})
        drug_id = pair.get("drugid")
        if drug_id and drug_id not in drugs:
            found = _get("drug", drugid=f"eq.{drug_id}")
            time.sleep(REQUEST_INTERVAL_SECONDS)
            drugs[drug_id] = str(found[0]["name"]) if found else str(drug_id)
        if drug_id:
            entry["drugs"].add(drugs[drug_id])

    return {
        "guideline_id": ANAESTHESIA_GUIDELINE_ID,
        "guideline_name": ANAESTHESIA_GUIDELINE_NAME,
        "source": f"CPIC pair table, guidelineid={ANAESTHESIA_GUIDELINE_ID}",
        "genes": sorted(
            (
                {
                    "gene": entry["gene"],
                    "cpic_level": entry["cpic_level"],
                    "drugs": sorted(entry["drugs"]),
                    # The whole point of the record: this registry holds no allele
                    # definitions for RYR1 or CACNA1S, and an array does not resolve them.
                    "definitions_available": bool((built.get(entry["gene"]) or {}).get("alleles")),
                }
                for entry in genes.values()
            ),
            key=lambda item: item["gene"],
        ),
    }


def build(genes: tuple[str, ...] = DEFAULT_GENES) -> dict[str, Any]:
    retrieved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    built = {symbol: fetch_gene(symbol) for symbol in genes}
    return {
        "schema": "genoma-pgx-registry-v1",
        "id": "GENOMA-PGX-CPIC",
        "version": retrieved[:10].replace("-", "") + ".1",
        "source": (
            "CPIC (Clinical Pharmacogenetics Implementation Consortium) API, api.cpicpgx.org/v1, "
            f"recuperado em {retrieved}. Definições de alelo obtidas do join allele + "
            "allele_definition + allele_location_value + sequence_location; mapeamento "
            "diplótipo->fenótipo da tabela diplotype do próprio CPIC. Identificadores PharmVar "
            "preservados por alelo quando o CPIC os fornece. Reproduzir com "
            "scripts/build_pgx_registry.py."
        ),
        "retrieved_at": retrieved,
        "scope_note": (
            "complete_panel significa completo em relação ao catálogo do CPIC, não "
            "biologicamente exaustivo: um alelo que o CPIC não cataloga permanece "
            "indistinguível do haplótipo de referência. Alelos marcados pelo CPIC como "
            "variação estrutural são excluídos das definições porque genotipagem em array "
            "não os resolve, e ficam listados em structural_alleles_excluded."
        ),
        "anesthesia_scope": fetch_anaesthesia_scope(built),
        "genes": built,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--genes", nargs="*", default=list(DEFAULT_GENES))
    args = parser.parse_args()

    registry = build(tuple(args.genes))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"registro escrito em {out}")
    for symbol, gene in sorted(registry["genes"].items()):
        print(
            f"  {symbol:<9} alelos={len(gene['alleles']):<3} "
            f"ref={gene['reference_allele'] or 'NÃO DISPONÍVEL':<12} "
            f"fenótipos={len(gene['phenotype_map']):<4} "
            f"estruturais_excluídos={len(gene['structural_alleles_excluded'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
