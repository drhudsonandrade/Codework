#!/usr/bin/env python3
"""Build the population reference panel report 02 needs, from public genotype releases.

Report 02 refused to estimate ancestry, and the refusal was correct: allele frequencies do
not let you place an individual, and every consumer pie chart of origins comes from a
proprietary panel whose composition the reader never sees. What was missing was a panel of
*genotypes*, with named populations, that can be cited.

Two public releases supply it, and the second is the one that makes the result meaningful for
a Brazilian genome:

``1000 Genomes Affymetrix 6.0 chip``
    3,450 samples across five super-populations, genotyped on an array rather than sequenced,
    which is exactly the data type a consumer array must be projected against. The Affy 6.0
    release is chosen over the Omni 2.5M one for a concrete reason: the Native American panel
    below was also genotyped on Affy 6.0, and the two overlap at 51,263 coordinates against
    23,377 for Omni. Same platform, twice the panel.

``Native American reference panel (Mao et al. 2007, QC'd at Stanford/UCSF)``
    43 individuals — Nahua, Maya, Quechua, Aymara — retained because ADMIXTURE at K=3 put
    them at 99% or more Native American ancestry. This is the panel the 1000 Genomes project
    itself used to deconvolute its admixed American populations. Without it the only Native
    American reference available is 1000 Genomes AMR, which is *itself admixed*: estimating a
    Brazilian's indigenous component against PEL would measure it against a yardstick made
    partly of the thing being measured.

Brazilian ancestry is typically tri-hybrid — European, African and Native American in
varying proportions — so a panel missing any of the three cannot resolve it. It would project
onto the axes it happens to have and fall silent about the rest, which looks like an answer.

**Palindromic SNPs are excluded.** An A/T or C/G variant carries no strand information: a flip
maps A↔T and C↔G, so a strand error is undetectable and silently inverts the genotype. The
Native American panel's authors removed them for the same reason; this script removes them
again from the intersection rather than trusting that.

**The projection is by PCA loadings, not by re-running PCA per case.** Adding one individual
to the reference and recomputing would let that individual influence the axes they are then
measured against. The loadings are computed once, from the reference alone, and a case is
projected onto them.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.targets import sha256_json

SCHEMA = "genoma-ancestry-reference-panel-v1"
DEFAULT_OUTPUT = ROOT / "config/ancestry_reference_panel.json.gz"

#: A/T and C/G variants carry no strand information and are dropped on sight.
PALINDROMIC = frozenset({frozenset("AT"), frozenset("CG")})

#: Minor allele frequency floor. Rare markers contribute noise to a projection and are the
#: ones most likely to differ in strand or annotation between two array platforms.
MIN_MAF = 0.05
#: Maximum missingness per marker across the reference.
MAX_MISSING = 0.02
#: LD pruning, PLINK's parameters: a sliding window of `WINDOW` markers advanced `STEP` at a
#: time, dropping one of any pair correlated above `MAX_R2`. Without it the top components
#: describe a handful of long haplotype blocks rather than population structure.
LD_WINDOW = 50
LD_STEP = 5
LD_MAX_R2 = 0.2
#: Components retained. Population structure in a global panel is carried by the first
#: several; beyond that the axes describe families and batch effects.
N_COMPONENTS = 10

UNAVAILABLE = "NÃO DISPONÍVEL"


def _sha256(path: Path) -> str:
    """Hash the release actually read, so the citation cannot drift from the input.

    An earlier build cited the Omni chip in its sources while having been run against the
    Affy 6.0 file — a provenance error in a shipped artifact, produced by a hand-written
    citation that nothing checked against the argument.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_plink(prefix: Path) -> tuple[list[str], np.ndarray, list[dict[str, Any]], list[str]]:
    """Read a PLINK binary trio into (rsids, dosage[variants, samples], variant info, samples).

    Dosage counts the `a2` allele, with -1 for missing, which matches how the .bed encodes
    genotypes: 00 = homozygous a1, 01 = missing, 10 = heterozygous, 11 = homozygous a2.
    """
    fam = [line.split() for line in (prefix.with_suffix(".fam")).read_text().split("\n") if line.strip()]
    samples = [f"{row[0]}:{row[1]}" for row in fam]

    variants: list[dict[str, Any]] = []
    rsids: list[str] = []
    for line in (prefix.with_suffix(".bim")).read_text().split("\n"):
        if not line.strip():
            continue
        chromosome, rsid, _cm, position, a1, a2 = line.split("\t")[:6]
        rsids.append(rsid)
        variants.append(
            {"chromosome": chromosome, "rsid": rsid, "position": int(position), "a1": a1, "a2": a2}
        )

    raw = (prefix.with_suffix(".bed")).read_bytes()
    if raw[:3] != bytes([0x6C, 0x1B, 0x01]):
        raise ValueError("PLINK .bed is not in SNP-major v1 format")
    per_variant = (len(samples) + 3) // 4
    packed = np.frombuffer(raw[3:], dtype=np.uint8).reshape(len(variants), per_variant)
    bits = np.unpackbits(packed, axis=1, bitorder="little").reshape(len(variants), -1, 2)
    bits = bits[:, : len(samples), :]
    code = bits[:, :, 0].astype(np.int8) + 2 * bits[:, :, 1].astype(np.int8)
    dosage = np.select(
        [code == 0, code == 1, code == 2, code == 3], [0, -1, 1, 2]
    ).astype(np.int8)
    return rsids, dosage, variants, samples


def read_vcf_genotypes(
    path: Path, wanted: set[tuple[str, int]]
) -> tuple[list[tuple[str, int]], np.ndarray, dict[tuple[str, int], dict[str, Any]], dict[str, int]]:
    """Stream a VCF, keeping the wanted coordinates as an allele-count matrix.

    **The join is by coordinate, not by the ID column.** Only 29% of this release's IDs are
    rsids; the rest are probe identifiers like `SNP1-524110`, so an rsid join would silently
    discard seven markers in ten and call the remainder a panel. Both releases are annotated
    on GRCh37, which is what makes the coordinate join sound.

    The coordinate is checked before the genotype block is touched, so the skip path costs one
    split — on a 1.3 GB file that is the difference between minutes and an hour.
    """
    samples: list[str] = []
    rows: list[np.ndarray] = []
    kept: list[tuple[str, int]] = []
    info: dict[tuple[str, int], dict[str, Any]] = {}
    stats: dict[str, int] = {"lines": 0, "matched": 0, "not_biallelic": 0, "duplicate": 0}

    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        for raw in handle:
            if raw.startswith(b"##"):
                continue
            if raw.startswith(b"#CHROM"):
                samples = raw.decode("utf-8").rstrip("\n").split("\t")[9:]
                continue
            stats["lines"] += 1
            head = raw.split(b"\t", 5)
            if len(head) < 5:
                continue
            try:
                key = (head[0].decode("ascii"), int(head[1]))
            except ValueError:
                continue
            if key not in wanted:
                continue
            reference = head[3].decode("ascii").upper()
            alternate = head[4].decode("ascii").upper()
            if len(reference) != 1 or len(alternate) != 1 or reference not in "ACGT" or alternate not in "ACGT":
                stats["not_biallelic"] += 1
                continue
            if key in info:
                # Two records at one coordinate cannot be resolved by choosing a row.
                stats["duplicate"] += 1
                continue
            fields = raw.rstrip(b"\n").split(b"\t")
            block = fields[9:]
            if len(block) != len(samples):
                continue
            # GT is the first colon-separated subfield; the first and third characters are
            # the two alleles for both `0|0` and `0/1`.
            first = np.frombuffer(b"".join(g[0:1] for g in block), dtype=np.uint8)
            second = np.frombuffer(b"".join(g[2:3] for g in block), dtype=np.uint8)
            missing = (first == ord(".")) | (second == ord("."))
            dosage = (first - ord("0")).astype(np.int8) + (second - ord("0")).astype(np.int8)
            dosage[missing] = -1
            rows.append(dosage)
            kept.append(key)
            info[key] = {
                "id": head[2].decode("ascii"),
                "chromosome": key[0],
                "position": key[1],
                "reference": reference,
                "alternate": alternate,
            }
            stats["matched"] += 1
    matrix = np.vstack(rows) if rows else np.zeros((0, len(samples)), dtype=np.int8)
    return kept, matrix, info, stats


def harmonise(
    native_dosage: np.ndarray,
    native_info: list[dict[str, Any]],
    thousand_keys: list[tuple[str, int]],
    thousand_dosage: np.ndarray,
    thousand_info: dict[tuple[str, int], dict[str, Any]],
) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray, dict[str, int]]:
    """Intersect the two panels on GRCh37 coordinate, aligning to the 1000 Genomes alternate.

    Alignment is by allele *set*, which is only unambiguous because palindromic markers are
    excluded first — for an A/T marker both panels report {A, T} whichever strand they used,
    so the sets match while the genotypes may be inverted.

    The marker keeps the Native American panel's rsid, because that panel does carry real
    rsids and a case's array file is keyed by them.
    """
    by_coordinate: dict[tuple[str, int], int] = {}
    for index, variant in enumerate(native_info):
        by_coordinate.setdefault((variant["chromosome"], variant["position"]), index)

    stats: dict[str, int] = {
        "intersecting": 0, "palindromic": 0, "allele_mismatch": 0, "aligned": 0, "flipped": 0
    }
    markers: list[dict[str, Any]] = []
    native_rows: list[np.ndarray] = []
    thousand_rows: list[np.ndarray] = []

    for row, key in enumerate(thousand_keys):
        index = by_coordinate.get(key)
        if index is None:
            continue
        stats["intersecting"] += 1
        meta = thousand_info[key]
        alleles = frozenset({meta["reference"], meta["alternate"]})
        if alleles in PALINDROMIC:
            stats["palindromic"] += 1
            continue
        native = native_info[index]
        native_alleles = {native["a1"].upper(), native["a2"].upper()} - {"0"}
        if not native_alleles <= alleles:
            # The two releases disagree on which bases exist here. Aligning would mean
            # deciding which one is wrong.
            stats["allele_mismatch"] += 1
            continue

        # Native dosage counts a2; the panel is expressed in counts of the 1000 Genomes
        # alternate allele, so a marker whose a2 is the reference base is flipped.
        native_row = native_dosage[index].astype(np.int16)
        if native["a2"].upper() == meta["alternate"]:
            aligned = native_row
        else:
            flipped = 2 - native_row
            flipped[native_row < 0] = -1
            aligned = flipped
            stats["flipped"] += 1

        markers.append(
            {
                "rsid": native["rsid"],
                "chromosome": meta["chromosome"],
                "position": meta["position"],
                "reference_allele": meta["reference"],
                "effect_allele": meta["alternate"],
            }
        )
        native_rows.append(aligned.astype(np.int8))
        thousand_rows.append(thousand_dosage[row])
        stats["aligned"] += 1

    return (
        markers,
        np.vstack(native_rows) if native_rows else np.zeros((0, native_dosage.shape[1]), np.int8),
        np.vstack(thousand_rows) if thousand_rows else np.zeros((0, thousand_dosage.shape[1]), np.int8),
        stats,
    )


def ld_prune(dosage: np.ndarray, window: int, step: int, max_r2: float) -> np.ndarray:
    """Greedy sliding-window pruning, PLINK's `--indep-pairwise` in spirit.

    Returns the indices kept. Without this the leading components describe long haplotype
    blocks — a few megabases of chromosome 6 or 8 — rather than population structure.
    """
    n_markers = dosage.shape[0]
    keep = np.ones(n_markers, dtype=bool)
    filled = dosage.astype(np.float32)
    missing = filled < 0
    if missing.any():
        means = np.array(
            [row[row >= 0].mean() if (row >= 0).any() else 0.0 for row in dosage.astype(np.float32)],
            dtype=np.float32,
        )
        filled[missing] = np.take(means, np.where(missing)[0])
    centred = filled - filled.mean(axis=1, keepdims=True)
    norms = np.linalg.norm(centred, axis=1)
    norms[norms == 0] = 1.0

    start = 0
    while start < n_markers:
        stop = min(start + window, n_markers)
        block = [i for i in range(start, stop) if keep[i]]
        if len(block) > 1:
            sub = centred[block] / norms[block][:, None]
            correlation = sub @ sub.T
            np.fill_diagonal(correlation, 0.0)
            for a in range(len(block)):
                if not keep[block[a]]:
                    continue
                for b in range(a + 1, len(block)):
                    if keep[block[b]] and correlation[a, b] ** 2 > max_r2:
                        keep[block[b]] = False
        start += step
    return np.where(keep)[0]


def principal_components(dosage: np.ndarray, n_components: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """PCA on the reference, standardised as in Patterson/Price.

    Each marker is centred on twice its allele frequency and scaled by sqrt(2p(1-p)), the
    binomial standard deviation, so a common marker does not dominate a rare one purely by
    variance. Returns (loadings, coordinates, explained variance ratio, allele frequencies).
    """
    filled = dosage.astype(np.float32)
    missing = filled < 0
    frequencies = np.zeros(dosage.shape[0], dtype=np.float32)
    for i in range(dosage.shape[0]):
        row = dosage[i]
        observed = row[row >= 0]
        frequencies[i] = observed.mean() / 2.0 if observed.size else 0.0
    if missing.any():
        filled[missing] = np.repeat(2 * frequencies, dosage.shape[1]).reshape(dosage.shape)[missing]

    scale = np.sqrt(2 * frequencies * (1 - frequencies))
    scale[scale == 0] = 1.0
    standardised = (filled - 2 * frequencies[:, None]) / scale[:, None]

    # Samples-by-markers for the SVD; components come out as marker loadings.
    matrix = standardised.T
    _u, singular, vt = np.linalg.svd(matrix, full_matrices=False)
    k = min(n_components, vt.shape[0])
    loadings = vt[:k]
    coordinates = matrix @ loadings.T
    variance = singular**2
    return loadings, coordinates, (variance[:k] / variance.sum()), frequencies


def build(
    vcf_path: Path,
    panel_path: Path,
    native_prefix: Path,
    *,
    max_markers: int | None = None,
) -> dict[str, Any]:
    native_rsids, native_dosage, native_info, native_samples = read_plink(native_prefix)
    print(f"  painel ameríndio: {len(native_rsids):,} marcadores, {len(native_samples)} amostras", flush=True)

    # Autosomes only. The sex chromosomes have a different effective population size and a
    # different missingness pattern between sexes, both of which distort the components.
    autosomes = {str(c) for c in range(1, 23)}
    keep_rows = [i for i, v in enumerate(native_info) if v["chromosome"] in autosomes]
    native_dosage = native_dosage[keep_rows]
    native_info = [native_info[i] for i in keep_rows]
    print(f"  autossomos: {len(native_info):,} marcadores", flush=True)

    wanted = {(v["chromosome"], v["position"]) for v in native_info}
    kept, thousand_dosage, thousand_info, vcf_stats = read_vcf_genotypes(vcf_path, wanted)
    print(f"  1000 Genomes: {len(kept):,} coordenadas em comum, {thousand_dosage.shape[1]} amostras", flush=True)

    markers, native_aligned, thousand_aligned, harmony = harmonise(
        native_dosage, native_info, kept, thousand_dosage, thousand_info
    )
    print(f"  harmonizados: {harmony['aligned']:,} "
          f"(palindrômicos {harmony['palindromic']:,}, alelos divergentes {harmony['allele_mismatch']:,})",
          flush=True)

    combined = np.hstack([thousand_aligned, native_aligned])

    # Population labels. The Native American panel's samples are labelled from its README;
    # the 1000 Genomes samples from the release's own panel file.
    labels: dict[str, dict[str, str]] = {}
    with panel_path.open("r", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        for line in handle:
            row = line.rstrip("\n").split("\t")
            if len(row) < 3:
                continue
            record = dict(zip(header, row))
            labels[record["sample"]] = {
                "population": record["pop"],
                "super_population": record["super_pop"],
            }

    vcf_samples = _vcf_samples(vcf_path)
    sample_ids = list(vcf_samples) + list(native_samples)
    populations: list[dict[str, str]] = []
    unlabelled = 0
    for sample in vcf_samples:
        found = labels.get(sample)
        if found is None:
            unlabelled += 1
            populations.append({"sample": sample, "population": UNAVAILABLE, "super_population": UNAVAILABLE})
        else:
            populations.append({"sample": sample, **found})
    for sample in native_samples:
        populations.append(
            {"sample": sample, "population": "NativeAmerican_Mao2007", "super_population": "AMR-NAT"}
        )

    # Quality filters, then pruning, then PCA — in that order, because pruning correlations
    # computed over rare or missing-heavy markers are not worth acting on.
    missing_rate = (combined < 0).mean(axis=1)
    frequency = np.array(
        [row[row >= 0].mean() / 2.0 if (row >= 0).any() else 0.0 for row in combined], dtype=np.float32
    )
    maf = np.minimum(frequency, 1 - frequency)
    usable = (missing_rate <= MAX_MISSING) & (maf >= MIN_MAF)
    print(f"  após MAF>={MIN_MAF} e faltantes<={MAX_MISSING}: {int(usable.sum()):,}", flush=True)

    indices = np.where(usable)[0]
    filtered = combined[indices]
    pruned_local = ld_prune(filtered, LD_WINDOW, LD_STEP, LD_MAX_R2)
    selected = indices[pruned_local]
    print(f"  após poda de LD (r2<{LD_MAX_R2}): {len(selected):,}", flush=True)

    if max_markers is not None and len(selected) > max_markers:
        # Deterministic thinning, evenly across the genome rather than by taking a prefix,
        # so no chromosome is over-represented in the retained set.
        selected = selected[np.linspace(0, len(selected) - 1, max_markers).astype(int)]
        print(f"  afinado para {len(selected):,} marcadores", flush=True)

    final = combined[selected]
    loadings, coordinates, explained, frequencies = principal_components(final, N_COMPONENTS)
    print(f"  PCA: {loadings.shape[0]} componentes, "
          f"variância explicada {', '.join(f'{v:.1%}' for v in explained[:4])}", flush=True)

    by_population: dict[str, list[int]] = {}
    for index, record in enumerate(populations):
        by_population.setdefault(record["super_population"], []).append(index)
    centroids = {
        population: coordinates[members].mean(axis=0).tolist()
        for population, members in sorted(by_population.items())
        if population != UNAVAILABLE
    }

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "id": "GENOMA-ANCESTRY-1KG-OMNI-PLUS-NATIVE",
        "version": generated[:10].replace("-", "") + ".1",
        "generated_at": generated,
        "build": "GRCh37",
        "inputs": {
            "genotype_release": vcf_path.name,
            "genotype_release_sha256": _sha256(vcf_path),
            "population_labels": panel_path.name,
            "native_american_panel": native_prefix.name,
        },
        "sources": [
            "1000 Genomes Project, release de genótipos de chip "
            f"({vcf_path.name}, SHA-256 {_sha256(vcf_path)}), com rótulos de população de "
            f"{panel_path.name}",
            "Native American reference panel, Mao et al. 2007 (Am J Hum Genet 80:1171-78), "
            "genotipado em Affymetrix 6.0, filtrado e controlado por Kenny, Moreno, Maples e "
            "Gignoux (Stanford/UCSF) e distribuído pelo 1000 Genomes em "
            "technical/working/20130711_native_american_admix_train. 43 indivíduos (Nahua, "
            "Maya, Quechua, Aymara) retidos por terem 99% ou mais de ancestralidade nativa "
            "segundo ADMIXTURE em K=3.",
        ],
        "method": (
            "Interseção por rsid dos dois painéis, com marcadores palindrômicos (A/T, C/G) "
            f"excluídos porque um flip de fita neles é indetectável. Filtro MAF >= {MIN_MAF} e "
            f"faltantes <= {MAX_MISSING}. Poda de LD em janela deslizante de {LD_WINDOW} "
            f"marcadores, passo {LD_STEP}, r2 < {LD_MAX_R2}. PCA sobre genótipos padronizados "
            "por marcador (centrados em 2p, escalados por sqrt(2p(1-p))). Os loadings são "
            "calculados uma vez, só a partir da referência: projetar um caso recalculando o "
            "PCA deixaria o indivíduo influenciar os eixos contra os quais é medido."
        ),
        "parameters": {
            "min_maf": MIN_MAF,
            "max_missing": MAX_MISSING,
            "ld_window": LD_WINDOW,
            "ld_step": LD_STEP,
            "ld_max_r2": LD_MAX_R2,
            "components": int(loadings.shape[0]),
        },
        "statistics": {
            "native_markers": len(native_rsids),
            "vcf": vcf_stats,
            "harmonisation": harmony,
            "markers_after_quality": int(usable.sum()),
            "markers_after_pruning": int(len(selected)),
            "samples": len(sample_ids),
            "samples_unlabelled": unlabelled,
        },
        "markers": [
            {
                **markers[int(i)],
                "effect_allele_frequency": round(float(frequencies[j]), 6),
                "loadings": [round(float(v), 6) for v in loadings[:, j]],
            }
            for j, i in enumerate(selected)
        ],
        "explained_variance_ratio": [round(float(v), 6) for v in explained],
        "reference_samples": [
            {**populations[i], "coordinates": [round(float(v), 4) for v in coordinates[i]]}
            for i in range(len(sample_ids))
        ],
        "population_centroids": {
            population: [round(float(v), 4) for v in centre]
            for population, centre in centroids.items()
        },
        "population_counts": {
            population: len(members) for population, members in sorted(by_population.items())
        },
        "limitations": [
            "O painel é de arrays: marcadores fora dele não são projetáveis, e a cobertura do "
            "array do caso decide quantos entram na projeção.",
            "As populações do 1000 Genomes rotuladas AMR (MXL, PEL, CLM, PUR) são elas mesmas "
            "miscigenadas e não servem de referência ameríndia; por isso o painel Mao et al. "
            "entra como AMR-NAT separado.",
            "Nahua, Maya, Quechua e Aymara são populações mesoamericanas e andinas. Não há "
            "referência amazônica ou de povos originários do Brasil neste painel, então o "
            "componente ameríndio de um genoma brasileiro é estimado contra populações "
            "aparentadas mas não locais.",
            "O grupo AFR do 1000 Genomes mistura africanos continentais (YRI, LWK, GWD, MSL, ESN) "
            "com afro-americanos e afro-caribenhos (ASW, ACB), que são miscigenados. O centróide "
            "AFR portanto não é uma âncora africana pura, e um africano continental cai além dele "
            "em vez de sobre ele.",
            "Coordenadas em GRCh37. Um caso em GRCh38 precisa ser convertido antes da projeção.",
            "Ancestralidade genética não é identidade, cultura, nacionalidade nem história "
            "familiar.",
        ],
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def _vcf_samples(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        for raw in handle:
            if raw.startswith(b"#CHROM"):
                return raw.decode("utf-8").rstrip("\n").split("\t")[9:]
            if not raw.startswith(b"#"):
                break
    raise ValueError("VCF has no #CHROM header line")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vcf", required=True, help="1000 Genomes chip genotypes VCF")
    parser.add_argument("--panel", required=True, help="1000 Genomes sample population panel")
    parser.add_argument("--native", required=True, help="PLINK prefix of the Native American panel")
    parser.add_argument("--max-markers", type=int, default=60000)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    payload = build(
        Path(args.vcf),
        Path(args.panel),
        Path(args.native),
        max_markers=args.max_markers,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    if out.suffix == ".gz":
        out.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        out.write_text(text, encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(out),
                "bytes": out.stat().st_size,
                "markers": len(payload["markers"]),
                "samples": len(payload["reference_samples"]),
                "populations": payload["population_counts"],
                "explained_variance": payload["explained_variance_ratio"][:5],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
