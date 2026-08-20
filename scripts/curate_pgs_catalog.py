#!/usr/bin/env python3
"""Curate the PGS Catalog score registry, with the two facts that decide whether a score may be used.

The PGS Catalog publishes 6,972 polygenic scores across 807 mapped traits — far more traits
than the GWAS Catalog route reaches, and each with a publication, a variant count and a
licence. What it does *not* publish is permission to apply any of them to a given person, and
two fields decide that.

**The ancestry of the cohorts the score was built in.** A polygenic score is a set of weights
fitted in one population, and its predictive accuracy falls — often by half or more — when
carried to a population with different allele frequencies and linkage structure. Most of this
catalogue was developed in European cohorts. For an admixed Brazilian genome that is not a
footnote, it is the dominant source of error, so every score carries its development-cohort
ancestry and a computed transferability class rather than a number that looks the same
whoever it is applied to.

**The number of variants, against how many an array can actually read.** The median score
here has 123,613 variants and the largest has 10.3 million; a consumer array carries about
700,000 positions genome-wide. Summing weights over the variants that happen to be present
and treating absent ones as zero dosage is the vacuous-truth failure in its purest form: it
produces a finite, plausible, wrong number, and nothing in the output says most of the score
was missing. This module therefore registers scores and measures coverage; it does not emit a
polygenic score, and `evaluate_coverage` refuses one whose variants the array cannot read.

Weights themselves are not vendored. Each score's harmonised file is cited by URL and licence
so it can be fetched when a specific score is actually to be used.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.targets import sha256_json

SCORES_CSV = "https://ftp.ebi.ac.uk/pub/databases/spot/pgs/metadata/pgs_all_metadata_scores.csv"
PGS_CITATION = (
    "PGS Catalog (Lambert SA et al., Nature Genetics 2021), "
    "https://www.pgscatalog.org — metadados de escore recuperados de "
    "pgs_all_metadata_scores.csv."
)

UNAVAILABLE = "NÃO DISPONÍVEL"

#: Ancestry labels the catalogue uses whose presence makes a score more transferable to an
#: admixed Latin American genome. "Hispanic or Latin American" is the catalogue's own term for
#: the cohorts closest to a Brazilian sample; African and Native American components of a
#: Brazilian genome are covered by the first two.
RELEVANT_ANCESTRIES = ("Hispanic or Latin American", "African", "Native American")

#: Coverage below this fraction of a score's variants is refused outright. It is not a
#: threshold below which the score is merely weaker: below it the sum is dominated by the
#: variants that are absent, and an absent variant contributes zero, which is a genotype claim
#: nobody measured.
MIN_VARIANT_COVERAGE = 0.95


class PgsError(RuntimeError):
    pass


def _fetch(url: str, *, attempts: int = 4) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "genoma-pgs/1.0"})
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt < attempts - 1:
                import time

                time.sleep(2**attempt)
    raise PgsError(f"falha ao ler {url}: {last}")


def parse_ancestry(text: str) -> dict[str, float]:
    """`European:72.7|Not Reported:18.2|East Asian:9.1` -> mapping.

    A label the catalogue writes without a percentage, or a percentage that will not parse, is
    dropped rather than guessed — and because the transferability class is computed from what
    parsed, an unparsed field yields `NÃO DISPONÍVEL`, never `European:100` by default.
    """
    out: dict[str, float] = {}
    for chunk in str(text or "").split("|"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        label, _, value = chunk.rpartition(":")
        label = label.strip()
        try:
            percent = float(value)
        except ValueError:
            continue
        if label:
            out[label] = out.get(label, 0.0) + percent
    return out


def transferability(gwas: dict[str, float], training: dict[str, float]) -> dict[str, Any]:
    """How far this score travels to an admixed Latin American genome.

    Deliberately coarse. A finer scale would imply a calibration nobody has published for this
    person's ancestry, and the honest statement is which cohorts the weights came from — not a
    correction factor.
    """
    combined: dict[str, float] = dict(gwas)
    for label, percent in training.items():
        combined[label] = max(combined.get(label, 0.0), percent)
    if not combined:
        return {
            "class": UNAVAILABLE,
            "relevant_ancestry_percent": None,
            "basis": (
                "o catálogo não declara a ancestralidade das coortes deste escore; sem isso "
                "não há como afirmar nem negar transferibilidade"
            ),
        }
    relevant = sum(combined.get(label, 0.0) for label in RELEVANT_ANCESTRIES)
    european = combined.get("European", 0.0)
    if relevant >= 20.0:
        label = "PARCIALMENTE TRANSFERÍVEL"
        basis = (
            f"{relevant:.0f}% das coortes são hispânicas/latino-americanas, africanas ou "
            "nativas americanas; ainda assim os pesos não foram ajustados para um genoma "
            "brasileiro miscigenado em particular"
        )
    elif european >= 90.0:
        label = "NÃO TRANSFERÍVEL SEM CALIBRAÇÃO"
        basis = (
            f"{european:.0f}% das coortes são europeias. A acurácia de um escore poligênico "
            "cai substancialmente fora da população em que foi ajustado, e a queda não é "
            "corrigível por reescala simples"
        )
    else:
        label = "TRANSFERIBILIDADE INCERTA"
        basis = (
            "as coortes não são predominantemente europeias nem incluem proporção relevante "
            "de populações próximas a um genoma brasileiro"
        )
    return {
        "class": label,
        "relevant_ancestry_percent": round(relevant, 1),
        "european_percent": round(european, 1),
        "basis": basis,
    }


def _int(text: str) -> int | None:
    text = str(text or "").strip()
    return int(text) if text.isdigit() else None


def _harmonised_urls(ftp_link: str, pgs_id: str) -> dict[str, str]:
    """The GRCh37/GRCh38 harmonised scoring files derived from the catalogue's FTP link."""
    base = str(ftp_link or "").strip()
    if not base or pgs_id not in base:
        return {}
    root = base.rsplit("/", 1)[0]
    return {
        build: f"{root}/Harmonized/{pgs_id}_hmPOS_{build}.txt.gz"
        for build in ("GRCh37", "GRCh38")
    }


def curate(csv_bytes: bytes) -> dict[str, Any]:
    text = csv_bytes.decode("utf-8", errors="replace")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise PgsError("o export de escores do PGS Catalog veio vazio")

    scores: dict[str, Any] = {}
    traits: dict[str, dict[str, Any]] = {}
    licences: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    for row in rows:
        pgs_id = str(row.get("Polygenic Score (PGS) ID") or "").strip()
        if not pgs_id:
            continue
        gwas = parse_ancestry(row.get("Ancestry Distribution (%) - Source of Variant Associations (GWAS)", ""))
        training = parse_ancestry(row.get("Ancestry Distribution (%) - Score Development/Training", ""))
        transfer = transferability(gwas, training)
        licence = str(row.get("License/Terms of Use") or "").strip() or UNAVAILABLE
        efo_ids = [t.strip() for t in str(row.get("Mapped Trait(s) (EFO ID)") or "").split("|") if t.strip()]
        efo_labels = [t.strip() for t in str(row.get("Mapped Trait(s) (EFO label)") or "").split("|") if t.strip()]
        variants = _int(row.get("Number of Variants", ""))
        build = str(row.get("Original Genome Build") or "").strip() or UNAVAILABLE

        licences[licence[:80]] += 1
        classes[transfer["class"]] += 1
        scores[pgs_id] = {
            "id": pgs_id,
            "name": str(row.get("PGS Name") or "").strip(),
            "trait_reported": str(row.get("Reported Trait") or "").strip(),
            "trait_efo_ids": efo_ids,
            "trait_efo_labels": efo_labels,
            "variants": variants,
            "genome_build": build,
            "development_method": str(row.get("PGS Development Method") or "").strip(),
            "weight_type": str(row.get("Type of Variant Weight") or "").strip(),
            "publication": {
                "pgp_id": str(row.get("PGS Publication (PGP) ID") or "").strip(),
                "pmid": _int(row.get("Publication (PMID)", "")),
                "doi": str(row.get("Publication (doi)") or "").strip(),
            },
            "matches_publication": str(row.get("Score and results match the original publication") or "").strip(),
            "ancestry_gwas": gwas,
            "ancestry_training": training,
            "ancestry_evaluation": parse_ancestry(
                row.get("Ancestry Distribution (%) - PGS Evaluation", "")
            ),
            "transferability": transfer,
            "license": licence,
            # The licence travels with the score because it is not uniform: most of the
            # catalogue is citation-only, but some scores are non-commercial or research-only,
            # and a registry that flattened that would authorise a use the author forbade.
            "license_is_restrictive": bool(
                re.search(r"NonCommercial|NoDerivativ|research purposes only|academic",
                          licence, re.IGNORECASE)
            ),
            "ftp_link": str(row.get("FTP link") or "").strip(),
            "harmonised_files": _harmonised_urls(row.get("FTP link", ""), pgs_id),
            "release_date": str(row.get("Release Date") or "").strip(),
        }
        for efo_id, label in zip(efo_ids, efo_labels + [""] * len(efo_ids)):
            entry = traits.setdefault(efo_id, {"efo_id": efo_id, "label": label, "scores": []})
            entry["scores"].append(pgs_id)

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with_variants = [s["variants"] for s in scores.values() if s["variants"]]
    payload = {
        "schema": "genoma-pgs-catalog-registry-v1",
        "curated_at": generated,
        "sources": [f"{PGS_CITATION} {SCORES_CSV}, recuperado em {generated}."],
        "method": (
            "Todo escore publicado do PGS Catalog, com a ancestralidade das coortes de "
            "descoberta e de treino, o número de variantes, a licença e o arquivo harmonizado "
            "citado por URL. Nenhum peso é copiado para este repositório. A classe de "
            "transferibilidade é derivada da distribuição de ancestralidade declarada e é "
            "deliberadamente grosseira: uma escala fina sugeriria uma calibração que ninguém "
            "publicou para a ancestralidade desta pessoa."
        ),
        "usage_policy": (
            "Este registro autoriza consulta e medição de cobertura. Não autoriza emitir um "
            f"escore poligênico: abaixo de {MIN_VARIANT_COVERAGE:.0%} das variantes do escore "
            "lidas no array, a soma é dominada pelas variantes ausentes, e uma variante "
            "ausente contribui zero — que é uma afirmação de genótipo que ninguém mediu."
        ),
        "min_variant_coverage": MIN_VARIANT_COVERAGE,
        "relevant_ancestries": list(RELEVANT_ANCESTRIES),
        "totals": {
            "scores": len(scores),
            "traits": len(traits),
            "variant_weights_total": sum(with_variants),
            "variants_median": sorted(with_variants)[len(with_variants) // 2] if with_variants else None,
            "variants_max": max(with_variants) if with_variants else None,
            "scores_with_restrictive_license": sum(
                1 for s in scores.values() if s["license_is_restrictive"]
            ),
            "transferability": dict(classes),
            "licenses": dict(licences.most_common(12)),
        },
        "traits": traits,
        "scores": scores,
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def evaluate_coverage(
    registry: dict[str, Any],
    pgs_id: str,
    observed_rsids: set[str],
    *,
    harmonised_bytes: bytes,
    build: str = "GRCh37",
) -> dict[str, Any]:
    """How much of one score's variant set an array actually reads.

    Returns a refusal, not a score. Whether the weights should ever be summed is a separate
    decision that depends on this number and on the transferability class beside it.
    """
    score = (registry.get("scores") or {}).get(pgs_id)
    if not score:
        raise PgsError(f"{pgs_id} não consta do registro do PGS Catalog")
    declared = score.get("variants")

    covered = 0
    total = 0
    without_rsid = 0
    header: dict[str, int] = {}
    raw = gzip.decompress(harmonised_bytes) if harmonised_bytes[:2] == b"\x1f\x8b" else harmonised_bytes
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if not header:
            # The first non-comment line is the column header. Reading it as a weight row
            # would add one uncoverable variant to every score in the catalogue.
            header = {name.strip(): i for i, name in enumerate(fields)}
            continue
        total += 1
        rsid = None
        for column in ("hm_rsID", "rsID"):
            index = header.get(column)
            if index is not None and index < len(fields):
                candidate = fields[index].strip().lower()
                if candidate.startswith("rs"):
                    rsid = candidate
                    break
        if rsid is None:
            # A weight with no rsid cannot be matched against an array keyed by rsid. It
            # counts against coverage rather than being quietly excluded from the
            # denominator, because it is a variant of the score this array cannot read.
            without_rsid += 1
            continue
        if rsid in observed_rsids:
            covered += 1

    fraction = covered / total if total else 0.0
    # An empty weight file is not full coverage. Without this the fraction is 0/0, and every
    # branch that reads "coverage is fine" would read it as fine.
    computable = total > 0
    return {
        "pgs_id": pgs_id,
        "status": "VERIFICADO" if computable else UNAVAILABLE,
        "build": build,
        "variants_declared": declared,
        "variants_in_file": total,
        "variants_covered": covered,
        "variants_without_rsid": without_rsid,
        "coverage": round(fraction, 4) if computable else None,
        "meets_threshold": bool(computable and fraction >= MIN_VARIANT_COVERAGE),
        "transferability": score["transferability"],
        "license": score["license"],
        "refusal": None
        if computable and fraction >= MIN_VARIANT_COVERAGE
        else (
            "arquivo de pesos vazio ou ilegível; nenhuma cobertura pode ser afirmada"
            if not computable
            else (
                f"o array lê {covered} de {total} variantes ({fraction:.1%}), abaixo do "
                f"mínimo de {MIN_VARIANT_COVERAGE:.0%}. Somar os pesos presentes trataria as "
                "variantes ausentes como dose zero, o que é uma afirmação de genótipo que "
                "ninguém mediu"
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores-csv", help="local copy of pgs_all_metadata_scores.csv")
    parser.add_argument("--output", default=str(ROOT / "docs/evidence/PGS_CATALOG_REGISTRY.json.gz"))
    args = parser.parse_args()

    raw = (
        Path(args.scores_csv).read_bytes()
        if args.scores_csv and Path(args.scores_csv).is_file()
        else _fetch(SCORES_CSV)
    )
    payload = curate(raw)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if out.suffix == ".gz":
        out.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        out.write_text(text, encoding="utf-8")
    print(json.dumps({"output": str(out), "bytes": out.stat().st_size, **payload["totals"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
