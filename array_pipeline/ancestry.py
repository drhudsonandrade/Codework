"""Project a case onto the population reference panel, or refuse and say why.

Report 02 could not estimate ancestry because no panel of genotypes existed. With one built
(`scripts/build_ancestry_panel.py`) the estimate becomes possible — and immediately acquires
three ways to be quietly wrong, each of which is closed here rather than footnoted.

**Shrinkage.** An individual projected onto components computed from a reference is pulled
toward the origin relative to the reference samples, and the fewer markers they share with
the panel the harder the pull. Proportions read off a shrunken point understate the extreme
components and overstate the middle. So proportions are emitted only above a declared marker
overlap, and below it the report gives population affinity without proportions.

**Strand.** The panel excludes palindromic markers, so a case allele pair that matches neither
the panel's alleles nor their complement is a real disagreement and the marker is dropped.
Both counts are reported: a case needing many complement flips is on the opposite strand, and
that is worth seeing rather than absorbing.

**Build.** The panel is annotated on GRCh37. A case on GRCh38 has the same rsids at different
coordinates; since the join here is by rsid the projection would still run and be subtly
wrong wherever an rsid moved. The build is checked and a mismatch refuses.

What this module does **not** claim: these are not ADMIXTURE proportions. They are a
constrained least-squares fit of the case's projected position onto the reference population
centroids, which is a geometric statement about principal components, and the report names it
as such.
"""
from __future__ import annotations

import json
import math
from contextlib import closing
from pathlib import Path
from typing import Any

try:  # NumPy is an optional adapter here, never a core runtime dependency.
    import numpy as np
except ImportError:  # pragma: no cover - the absence is what the regression exercises
    np = None

from array_pipeline import assembly

SCHEMA = "genoma-ancestry-reference-panel-v1"
UNAVAILABLE = "NÃO DISPONÍVEL"

COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}

#: Below this many usable markers nothing is emitted at all — a projection from a handful of
#: markers lands wherever noise puts it.
MIN_MARKERS = 2000
#: Proportions additionally require this share of the panel, because shrinkage grows as the
#: overlap falls and there is no correction applied here.
MIN_OVERLAP_FOR_PROPORTIONS = 0.60
#: ...but never more than this many markers in absolute terms.
#:
#: A fraction alone makes a *better* panel harder to use. Rebuilding the reference from
#: 12,914 markers to 60,000 raised the 60% bar from 7,748 markers to 36,000, so an array that
#: earned proportions against the small panel could be refused by the large one while
#: carrying strictly more information. Shrinkage depends on how many markers were actually
#: used, not on how many the panel happens to contain, so the absolute count is the quantity
#: that means something and the fraction is a secondary floor.
#:
#: 7,500 is set at or below what the 12,914-marker panel already demanded (7,748), because
#: that configuration is the one whose projections were validated. Published
#: ancestry-informative panels place individuals at continental level on hundreds to a few
#: thousand markers, so this is not a thin requirement — it is the old one, kept from
#: tightening as a side effect of a better reference.
MAX_MARKERS_FOR_PROPORTIONS = 7500
#: Bootstrap resamples used for the interval around each proportion.
BOOTSTRAP_SAMPLES = 200

#: Reference populations that are themselves admixed, and so cannot serve as basis vectors
#: for a proportion fit. 1000 Genomes AMR (MXL, PEL, CLM, PUR) is a *mixture* of European,
#: African and Native American ancestry; using it as a basis makes the basis linearly
#: dependent, and the fit then distributes weight across redundant directions. It showed up
#: as a Yoruba individual scoring 17.5% Native American. They stay in the affinity list —
#: "closest to AMR" is a true and useful statement — and out of the proportions.
ADMIXED_REFERENCES = frozenset({"AMR"})


class AncestryPanelError(ValueError):
    """The panel is unusable, or the case cannot be projected onto it."""


def read_case_genotypes(input_path: Path, rsids: set[str]) -> tuple[dict[str, str], dict[str, int]]:
    """Read the case's called genotypes at the panel's markers.

    Unresolved cross-platform records and duplicated rsids with disagreeing genotypes are
    dropped rather than arbitrated, exactly as the completeness matrix drops them — a
    projection is a weighted sum, so one silently arbitrated genotype does not announce
    itself anywhere downstream.
    """
    from array_pipeline.completeness import _row_reader
    from array_pipeline.qc import UNRESOLVED_OVERLAP_STATUSES, _canonical_gt, _is_valid_consensus

    collected: dict[str, set[str]] = {}
    stats: dict[str, int] = {"rows": 0, "matched": 0, "unresolved": 0, "no_call": 0, "conflicting": 0}
    iterator = _row_reader(Path(input_path))
    with closing(iterator):
        for schema, row in iterator:
            stats["rows"] += 1
            rsid = (row.get("RSID") or "").strip().lower()
            if rsid not in rsids:
                continue
            stats["matched"] += 1
            if schema and schema.startswith("harmonized"):
                raw = row.get("CONSENSUS_RESULT")
                status = (row.get("STATUS") or "").strip().lower()
            else:
                raw = row.get("RESULT")
                status = ""
            if status in UNRESOLVED_OVERLAP_STATUSES:
                stats["unresolved"] += 1
                continue
            if not _is_valid_consensus(raw):
                stats["no_call"] += 1
                continue
            genotype = _canonical_gt(raw)
            if genotype:
                collected.setdefault(rsid, set()).add(genotype)

    genotypes: dict[str, str] = {}
    for rsid, values in collected.items():
        if len(values) > 1:
            stats["conflicting"] += 1
            continue
        genotypes[rsid] = next(iter(values))
    return genotypes, stats


def load_panel(path: Path) -> dict[str, Any]:
    """Read and validate a reference panel, using nothing NumPy provides.

    Every check here is on a scalar the JSON already decoded, so `math.isfinite` does the
    whole job. It used to be `np.isfinite`, which made the *validator* require the optional
    adapter: with `np = None` this raised `AttributeError` on the first marker, before
    `project_case` could return its NÃO DISPONÍVEL refusal — the import-time failure moved
    one function along rather than removed. The tests exercising the validator did not see
    it because their helper installs a stub `numpy` carrying `isfinite`; the real absence is
    covered by `test_the_whole_load_then_project_path_runs_with_numpy_absent`.

    NumPy stays required for the projection itself, which is linear algebra and is guarded
    inside `project_case`.
    """
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = assembly.bounded_gunzip(raw, name=str(path))
    panel = json.loads(raw.decode("utf-8"))
    if panel.get("schema") != SCHEMA:
        raise AncestryPanelError(f"unsupported ancestry panel schema: {panel.get('schema')!r}")
    if not panel.get("sources"):
        raise AncestryPanelError("ancestry panel must cite its sources")
    markers = panel.get("markers")
    if not isinstance(markers, list) or not markers:
        raise AncestryPanelError("ancestry panel carries no markers")
    loading_lengths: set[int] = set()
    # `project_case` walks the markers as a list and looks each rsid up in the case, so a locus
    # listed twice contributes its genotype to the projection twice and is counted twice in
    # overlap_fraction. That silently double-weights one position against every other marker in
    # the panel, which is a distorted ancestry projection rather than a rejected one.
    seen_rsids: set[str] = set()
    for marker in markers:
        if not isinstance(marker, dict):
            raise AncestryPanelError("ancestry panel marker entries must be objects")
        rsid = str(marker.get("rsid") or "").strip()
        if not rsid:
            raise AncestryPanelError("ancestry panel marker must carry a non-empty rsid")
        normalized_rsid = rsid.lower()
        if normalized_rsid in seen_rsids:
            raise AncestryPanelError(
                f"ancestry panel lists {rsid!r} more than once; a repeated marker would weight "
                "one locus twice in the projection"
            )
        seen_rsids.add(normalized_rsid)
        reference = str(marker.get("reference_allele") or "").strip().upper()
        effect = str(marker.get("effect_allele") or "").strip().upper()
        if reference not in COMPLEMENT or effect not in COMPLEMENT or reference == effect:
            raise AncestryPanelError(
                f"ancestry panel marker {rsid!r} must carry two distinct A/C/G/T alleles"
            )
        marker["rsid"] = rsid
        marker["reference_allele"] = reference
        marker["effect_allele"] = effect
        frequency = marker.get("effect_allele_frequency")
        if (
            isinstance(frequency, bool)
            or not isinstance(frequency, (int, float))
            or not math.isfinite(frequency)
            or not 0.0 <= float(frequency) <= 1.0
        ):
            raise AncestryPanelError(
                f"ancestry panel marker {rsid!r} has invalid effect_allele_frequency"
            )
        loadings = marker.get("loadings")
        if (
            not isinstance(loadings, list)
            or not loadings
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in loadings
            )
        ):
            raise AncestryPanelError(
                f"ancestry panel marker {rsid!r} must carry finite numeric loadings"
            )
        loading_lengths.add(len(loadings))
    if len(loading_lengths) != 1:
        raise AncestryPanelError(
            "ancestry panel marker loadings must all have the same length; "
            f"found dimensions {sorted(loading_lengths)}"
        )
    components = next(iter(loading_lengths))
    centroids = panel.get("population_centroids")
    if not isinstance(centroids, dict) or not centroids:
        raise AncestryPanelError("ancestry panel must carry population centroids")
    for population, centroid in centroids.items():
        if (
            not isinstance(centroid, list)
            or len(centroid) != components
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in centroid
            )
        ):
            raise AncestryPanelError(
                f"ancestry panel centroid {population!r} must carry {components} finite components"
            )
    if not any(name not in ADMIXED_REFERENCES for name in centroids):
        raise AncestryPanelError(
            "ancestry panel must carry at least one non-admixed reference centroid"
        )
    return panel


def _dosage(genotype: str, reference: str, effect: str) -> tuple[int | None, bool]:
    """Count the effect allele in a two-character genotype. Returns (dosage, flipped)."""
    text = str(genotype or "").strip().upper()
    if len(text) != 2 or not set(text) <= set("ACGT"):
        return None, False
    expected = {reference, effect}
    observed = set(text)
    if observed <= expected:
        return sum(1 for base in text if base == effect), False
    complemented = {COMPLEMENT[base] for base in observed}
    if complemented <= expected:
        flipped_effect = COMPLEMENT[effect]
        return sum(1 for base in text if base == flipped_effect), True
    return None, False


def _project_simplex(vector: np.ndarray) -> np.ndarray:
    """Euclidean projection onto {x : x >= 0, sum(x) = 1}."""
    sorted_desc = np.sort(vector)[::-1]
    cumulative = np.cumsum(sorted_desc) - 1
    indices = np.arange(1, len(vector) + 1)
    condition = sorted_desc - cumulative / indices > 0
    rho = indices[condition][-1]
    theta = cumulative[condition][-1] / rho
    return np.maximum(vector - theta, 0)


def _fit_proportions(centroids: np.ndarray, point: np.ndarray, iterations: int = 4000) -> np.ndarray:
    """Least squares of `point` onto the centroid simplex, by projected gradient.

    Constrained to non-negative weights summing to one because a "proportion" that is
    negative, or that sums to 1.4, is not a proportion — an unconstrained fit produces both
    and they read as ancestry all the same.
    """
    n = centroids.shape[0]
    weights = np.full(n, 1.0 / n)
    matrix = centroids @ centroids.T
    target = centroids @ point
    step = 1.0 / (np.linalg.norm(matrix, 2) + 1e-9)
    for _ in range(iterations):
        gradient = matrix @ weights - target
        weights = _project_simplex(weights - step * gradient)
    return weights


def project_case(
    panel: dict[str, Any],
    genotypes: dict[str, str],
    *,
    case_build: str,
    bootstrap: int = BOOTSTRAP_SAMPLES,
    seed: int = 20260819,
) -> dict[str, Any]:
    """Place a case in the panel's principal-component space and describe where it landed."""
    panel_build = str(panel.get("build") or UNAVAILABLE)
    if str(case_build).strip().upper() != panel_build.strip().upper():
        raise AncestryPanelError(
            f"case is annotated on {case_build} and the panel on {panel_build}; the projection "
            "joins by rsid and would run silently on markers whose coordinates moved between "
            "builds. Convert the case before projecting."
        )

    markers = panel["markers"]
    used: list[int] = []
    dosages: list[int] = []
    flipped = 0
    mismatched = 0
    absent = 0
    for index, marker in enumerate(markers):
        genotype = genotypes.get(str(marker["rsid"]).lower())
        if genotype is None:
            absent += 1
            continue
        dose, was_flipped = _dosage(genotype, marker["reference_allele"], marker["effect_allele"])
        if dose is None:
            mismatched += 1
            continue
        used.append(index)
        dosages.append(dose)
        flipped += int(was_flipped)

    overlap = len(used) / len(markers) if markers else 0.0
    base = {
        "panel": {
            "id": panel.get("id"),
            "version": panel.get("version"),
            "sha256": panel.get("sha256"),
            "build": panel_build,
            "markers": len(markers),
            "populations": panel.get("population_counts", {}),
            "sources": panel.get("sources", []),
        },
        "markers_used": len(used),
        "markers_absent_from_case": absent,
        "markers_allele_mismatch": mismatched,
        "markers_strand_flipped": flipped,
        "overlap_fraction": round(overlap, 4),
        "limitations": panel.get("limitations", []),
    }

    if np is None:
        # The projection is linear algebra and there is no honest way to do it without the
        # library. Importing NumPy at module scope made it a *core* runtime dependency —
        # unpinned, absent from environment.yml, requirements.txt and the runtime lock — so
        # merely importing `array_pipeline.ancestry` failed wherever it was missing, and any
        # caller died at import time rather than reading a status. It is an optional adapter:
        # absent, this refuses in the same shape as every other refusal here, and the rest of
        # the pipeline keeps working without ancestry.
        return {
            **base,
            "status": UNAVAILABLE,
            "coordinates": None,
            "affinity": [],
            "proportions": None,
            "reason": (
                "NumPy não está disponível neste runtime e a projeção em componentes "
                "principais não pode ser calculada sem ela. Ancestralidade é um adaptador "
                "opcional: sua ausência não é estimada por aproximação nem silenciada."
            ),
        }

    if len(used) < MIN_MARKERS:
        return {
            **base,
            "status": UNAVAILABLE,
            "coordinates": None,
            "affinity": [],
            "proportions": None,
            "reason": (
                f"apenas {len(used)} marcadores do painel puderam ser usados, abaixo do mínimo "
                f"de {MIN_MARKERS}. Uma projeção a partir de poucos marcadores cai onde o ruído "
                "a colocar, e a posição resultante não distingue populações."
            ),
        }

    loadings = np.array([[markers[i]["loadings"][k] for i in used]
                         for k in range(len(markers[0]["loadings"]))], dtype=np.float64)
    frequency = np.array([markers[i]["effect_allele_frequency"] for i in used], dtype=np.float64)
    scale = np.sqrt(2 * frequency * (1 - frequency))
    scale[scale == 0] = 1.0
    standardised = (np.array(dosages, dtype=np.float64) - 2 * frequency) / scale
    point = loadings @ standardised

    all_names = sorted(panel.get("population_centroids", {}))
    all_centroids = np.array(
        [panel["population_centroids"][name] for name in all_names], dtype=np.float64
    )
    distances = np.linalg.norm(all_centroids - point, axis=1)
    affinity = [
        {
            "population": name,
            "distance": round(float(distance), 4),
            "samples": panel.get("population_counts", {}).get(name),
            "admixed_reference": name in ADMIXED_REFERENCES,
        }
        for name, distance in sorted(zip(all_names, distances), key=lambda x: x[1])
    ]
    # Proportions are fitted only over reference populations that are not themselves
    # mixtures of the others.
    centroid_names = [n for n in all_names if n not in ADMIXED_REFERENCES]
    centroids = np.array(
        [panel["population_centroids"][name] for name in centroid_names], dtype=np.float64
    )

    result = {
        **base,
        "status": "INFERIDO",
        "coordinates": [round(float(v), 4) for v in point],
        "explained_variance_ratio": panel.get("explained_variance_ratio", []),
        "affinity": affinity,
        "nearest_population": affinity[0]["population"] if affinity else UNAVAILABLE,
        "method": (
            "Projeção nos componentes principais do painel de referência, usando loadings "
            "calculados só a partir da referência. Afinidade é distância euclidiana aos "
            "centróides das populações no mesmo espaço."
        ),
    }

    required = min(MAX_MARKERS_FOR_PROPORTIONS, int(MIN_OVERLAP_FOR_PROPORTIONS * len(markers)))
    if len(used) < required:
        result["proportions"] = None
        result["proportions_reason"] = (
            f"{len(used):,} marcadores em comum com o painel ({overlap:.1%} dele), abaixo dos "
            f"{required:,} exigidos. A projeção de um indivíduo encolhe em direção à origem "
            "quanto menos marcadores compartilha com a referência, e proporções lidas de um "
            "ponto encolhido subestimam os componentes extremos. A afinidade acima não "
            "depende dessa escala e permanece válida."
        )
        return result

    weights = _fit_proportions(centroids, point)
    # How far the projected point sits from the mixture the weights describe. A large
    # residual means the individual is not well represented by any combination of the
    # reference populations, and the proportions are then a nearest-fit rather than a
    # decomposition — worth seeing, since the fit always returns something.
    residual = float(np.linalg.norm(centroids.T @ weights - point))
    spread = float(np.linalg.norm(point)) or 1.0
    rng = np.random.default_rng(seed)
    draws = np.zeros((bootstrap, len(centroid_names)))
    count = len(used)
    for i in range(bootstrap):
        pick = rng.integers(0, count, count)
        resampled = loadings[:, pick] @ standardised[pick]
        draws[i] = _fit_proportions(centroids, resampled, iterations=600)
    lower = np.percentile(draws, 2.5, axis=0)
    upper = np.percentile(draws, 97.5, axis=0)

    result["proportions"] = [
        {
            "population": name,
            "proportion": round(float(weights[i]), 4),
            "interval_95": [round(float(lower[i]), 4), round(float(upper[i]), 4)],
        }
        for i, name in enumerate(centroid_names)
    ]
    result["fit_residual"] = round(residual, 4)
    result["fit_residual_relative"] = round(residual / spread, 4)
    # Calibrated against observed behaviour rather than chosen round numbers. A Yoruba
    # reference individual fits at 28% residual and picks up a spurious 17.5% Native American
    # component; a CEU fits at 11% and a Han at 5%, both clean. So 15% is where the artifacts
    # start and 30% is where they dominate.
    ratio = residual / spread
    result["fit_quality"] = "boa" if ratio < 0.15 else ("moderada" if ratio < 0.30 else "ruim")
    if ratio >= 0.15:
        result["fit_quality_warning"] = (
            f"resíduo de {ratio:.0%} da distância à origem: a pessoa não é bem representada "
            "por nenhuma combinação das populações de referência, e as proporções abaixo são "
            "o ajuste mais próximo, não uma decomposição."
        )

    measured = (panel.get("validation_summary") or {}).get("largest_spurious_component")
    result["minor_component_floor"] = (
        round(float(measured), 4) if isinstance(measured, (int, float)) and measured > 0 else None
    )
    if isinstance(measured, (int, float)) and measured > 0:
        result["minor_component_caveat"] = (
            f"Componentes abaixo de {measured:.0%} não são estabelecidos por esta projeção. "
            "Esse número é medido, não estipulado: é o maior componente espúrio observado ao "
            "projetar indivíduos de origem conhecida por este mesmo painel "
            f"({(panel.get('validation_summary') or {}).get('largest_spurious_example', '')}). "
            "Leia o componente majoritário e a afinidade."
        )
    else:
        result["minor_component_caveat"] = (
            "Este painel não traz artefato de validação, então o tamanho típico de um "
            "componente espúrio não foi medido. Componentes minoritários não são "
            "estabelecidos e nenhum limiar pode ser citado para eles."
        )
    result["proportions_method"] = (
        "Mínimos quadrados restritos da posição projetada sobre os centróides das populações "
        "de referência, com pesos não negativos somando 1. **Isto não é ADMIXTURE**: é uma "
        "afirmação geométrica sobre componentes principais, não uma estimativa de "
        "verossimilhança de mistura, e não decompõe o genoma em segmentos de ancestralidade. "
        f"O intervalo de 95% vem de {bootstrap} reamostragens bootstrap dos marcadores. "
        f"Resíduo do ajuste: {residual:.2f} ({residual / spread:.0%} da distância à origem, "
        f"qualidade {result['fit_quality']}). Um resíduo alto significa que a pessoa não é bem "
        "representada por nenhuma combinação das populações de referência, e as proporções "
        "são então o ajuste mais próximo, não uma decomposição."
    )
    return result
