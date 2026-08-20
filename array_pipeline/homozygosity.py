"""Runs of homozygosity, and the inbreeding coefficient report 03 needs to price them.

Carrier screening answers "is this person a carrier"; it does not answer "how likely are two
carriers to be the same variant in the same family". Consanguinity changes that, and it
changes it by a large factor: the risk of an autosomal-recessive condition in the child of
first cousins is several times the population risk, and for a rare condition most of the
increase comes from identity by descent rather than from two independent carrier events.

That is measurable from a SNP array without any extra assay, because recent shared ancestry
leaves long homozygous tracts. ``F_ROH`` — the fraction of the autosomal genome inside runs of
homozygosity — is the standard estimator (McQuillan et al., *Am J Hum Genet* 83:359-372, 2008)
and behaves better on array data than the allele-frequency estimators, which need a matched
reference population that an admixed Brazilian genome does not have.

**What is deliberately not claimed.** F_ROH is not a pedigree and does not identify a
relationship. Long tracts also arise from population isolation and from founder history, so a
high value in a person from an endogamous community is not evidence of close parental kinship.
The output states the measured fraction and the tract inventory, names the expected value for
a few textbook relationships so the number can be placed, and stops there — the inference from
tract burden to family structure belongs to a genetic counsellor with a family history in
front of them, not to this module.

**Why the guards matter more than the algorithm.** The estimator is a sliding window over
called genotypes, and every way it can lie is a way of having too little data: a sparse array
makes short tracts undetectable and long ones look longer, a low call rate turns missing
genotypes into apparent homozygosity, and a chromosome with a handful of markers produces a
"run" that is really an absence of evidence. Each of those is refused rather than reported.
"""
from __future__ import annotations

from typing import Any, Iterable

from array_pipeline import assembly

UNAVAILABLE = "NÃO DISPONÍVEL"

#: Minimum tract length in kilobases. Shorter homozygous stretches are ordinary — every genome
#: carries many — and counting them inflates F_ROH with signal that is not recent ancestry.
MIN_TRACT_KB = 1500.0
#: Minimum number of called markers inside a tract. Length alone is not evidence on an array
#: whose density varies: a 2 Mb gap with four markers in it is not a measured run.
MIN_TRACT_MARKERS = 50
#: Heterozygous calls tolerated inside a tract, absorbing genotyping error without letting a
#: genuinely heterozygous region be merged into one long false run.
MAX_HETEROZYGOTES_PER_TRACT = 1
#: Largest gap between consecutive markers that a tract may span. Beyond this the run is
#: crossing a region the array did not interrogate, and its homozygosity is unmeasured.
MAX_GAP_KB = 1000.0

#: Below this many called autosomal markers the estimate is refused outright. Array-based
#: F_ROH is stable in the hundreds of thousands of markers; at low density the windows cannot
#: resolve tract boundaries and the fraction is dominated by where the markers happen to be.
MIN_CALLED_MARKERS = 100_000
#: Below this call rate the missing genotypes, not the person, decide where tracts fall.
MIN_CALL_RATE = 0.95

#: Per-chromosome autosomal lengths in kilobases (GRCh37/GRCh38 primary assembly; the two
#: differ by less than a tenth of a percent, far below anything this check discriminates).
#: Used as a bounds check, because a coordinate past the end of its chromosome means the file
#: is not on the assembly assumed here, and every tract length computed from it is fiction.
#:
#: Read from `array_pipeline.assembly` rather than restated: array QC applies the same bound
#: at the gate, and when the two carried separate copies they were free to disagree about
#: which files are physically possible.
CHROMOSOME_KB = dict(assembly.AUTOSOME_KB_BY_CHROMOSOME)

#: Autosomal length in kilobases, chromosomes 1-22. The denominator of F_ROH; summed from the
#: table above so the fraction and its bounds check can never be scaled against different
#: genomes.
AUTOSOME_KB = assembly.AUTOSOME_TOTAL_KB

#: Expected F_ROH for offspring of a few standard relationships, for placing a measurement.
#: These are expectations under a simple model, not thresholds, and the report says so.
REFERENCE_EXPECTATIONS = (
    {"relationship": "primos de segundo grau", "expected_f_roh": 0.0156},
    {"relationship": "primos de primeiro grau", "expected_f_roh": 0.0625},
    {"relationship": "tio-sobrinha ou meio-irmãos", "expected_f_roh": 0.125},
    {"relationship": "irmãos completos ou pai-filha", "expected_f_roh": 0.25},
)


class HomozygosityError(ValueError):
    """The genotypes cannot support a runs-of-homozygosity estimate."""


def _zygosity(genotype: Any) -> str | None:
    text = str(genotype or "").strip().upper()
    if len(text) != 2 or not set(text) <= set("ACGT"):
        return None
    return "HOM" if text[0] == text[1] else "HET"


def find_tracts(markers: Iterable[tuple[str, int, str]]) -> list[dict[str, Any]]:
    """Homozygous tracts from (chromosome, position, genotype), one chromosome at a time.

    Markers are sorted here rather than assumed sorted: an unsorted input would produce tracts
    that span the whole chromosome and an F_ROH near one, which looks like a dramatic finding
    instead of a bug.
    """
    by_chromosome: dict[str, list[tuple[int, str]]] = {}
    for chromosome, position, genotype in markers:
        state = _zygosity(genotype)
        if state is None:
            continue
        by_chromosome.setdefault(str(chromosome), []).append((int(position), state))

    tracts: list[dict[str, Any]] = []
    for chromosome, entries in by_chromosome.items():
        entries.sort()
        start = 0
        while start < len(entries):
            if entries[start][1] != "HOM":
                start += 1
                continue
            end = start
            heterozygotes = 0
            last_position = entries[start][0]
            index = start + 1
            while index < len(entries):
                position, state = entries[index]
                if (position - last_position) / 1000.0 > MAX_GAP_KB:
                    break
                if state == "HET":
                    if heterozygotes >= MAX_HETEROZYGOTES_PER_TRACT:
                        break
                    heterozygotes += 1
                last_position = position
                end = index
                index += 1
            # Trim a trailing heterozygote: a tract must begin and end on homozygous calls,
            # or its measured length includes a stretch it does not describe.
            while end > start and entries[end][1] != "HOM":
                end -= 1
            span_kb = (entries[end][0] - entries[start][0]) / 1000.0
            called = end - start + 1
            if span_kb >= MIN_TRACT_KB and called >= MIN_TRACT_MARKERS:
                tracts.append(
                    {
                        "chromosome": chromosome,
                        "start": entries[start][0],
                        "end": entries[end][0],
                        "length_kb": round(span_kb, 1),
                        "markers": called,
                        "heterozygotes_tolerated": heterozygotes,
                    }
                )
            start = max(end + 1, start + 1)
    tracts.sort(key=lambda t: (-t["length_kb"], t["chromosome"], t["start"]))
    return tracts


def analyse(
    markers: list[tuple[str, int, str]],
    *,
    total_autosomal_markers: int | None = None,
) -> dict[str, Any]:
    """F_ROH and the tract inventory, or a refusal that says which guard stopped it."""
    called = [m for m in markers if _zygosity(m[2]) is not None]
    considered = total_autosomal_markers if total_autosomal_markers is not None else len(markers)
    call_rate = (len(called) / considered) if considered else 0.0

    refusals: list[str] = []
    # Coordinates are checked against the assembly before anything is measured from them. A
    # position past the end of its chromosome is not a marker to skip, it is proof the file is
    # on a different assembly or is corrupt, and every length derived from it would be wrong.
    out_of_bounds = [
        (chromosome, position)
        for chromosome, position, _genotype in called
        if chromosome in CHROMOSOME_KB and position > CHROMOSOME_KB[chromosome] * 1000
    ]
    unknown_chromosomes = sorted(
        {chromosome for chromosome, _p, _g in called if chromosome not in CHROMOSOME_KB}
    )
    if out_of_bounds:
        first = out_of_bounds[0]
        refusals.append(
            f"{len(out_of_bounds):,} marcadores estão além do fim do próprio cromossomo "
            f"(por exemplo chr{first[0]}:{first[1]:,}, que excede "
            f"{CHROMOSOME_KB[first[0]]:,} kb). O arquivo não está na montagem assumida aqui, "
            "ou está corrompido; comprimentos de trato calculados sobre essas coordenadas "
            "não descrevem nada."
        )
    if unknown_chromosomes:
        refusals.append(
            f"cromossomos autossômicos não reconhecidos: {unknown_chromosomes[:5]}"
        )
    if len(called) < MIN_CALLED_MARKERS:
        refusals.append(
            f"{len(called):,} marcadores autossômicos chamados, abaixo dos "
            f"{MIN_CALLED_MARKERS:,} exigidos. Em densidade baixa as janelas não resolvem as "
            "bordas dos tratos e a fração passa a descrever onde os marcadores caíram, não o "
            "genoma da pessoa."
        )
    if considered and call_rate < MIN_CALL_RATE:
        refusals.append(
            f"taxa de chamada de {call_rate:.1%}, abaixo de {MIN_CALL_RATE:.0%}. Genótipos "
            "ausentes não interrompem um trato e por isso são lidos como homozigose: com "
            "muitas faltas, quem decide onde os tratos caem é a ausência de dado."
        )
    if refusals:
        return {
            "status": UNAVAILABLE,
            "f_roh": None,
            "tracts": [],
            "called_markers": len(called),
            "call_rate": round(call_rate, 4) if considered else None,
            "refusals": refusals,
            "method": _METHOD,
        }

    tracts = find_tracts(called)
    total_kb = sum(t["length_kb"] for t in tracts)
    f_roh = total_kb / AUTOSOME_KB
    if f_roh > 1.0:
        # A fraction of the genome cannot exceed the genome. Reaching here means the tracts
        # overlap or the coordinates span more than an autosome, and the only honest output
        # is a refusal: 1.9 printed as an inbreeding coefficient is confident nonsense, and
        # clamping it to 1.0 would hide the same fault behind a plausible number.
        return {
            "status": UNAVAILABLE,
            "f_roh": None,
            "tracts": [],
            "called_markers": len(called),
            "call_rate": round(call_rate, 4) if considered else None,
            "refusals": [
                f"os tratos somam {total_kb:,.0f} kb, mais do que os "
                f"{AUTOSOME_KB:,.0f} kb de autossomos. Uma fração do genoma não pode exceder "
                "o genoma: as coordenadas de entrada não são consistentes com a montagem, e "
                "nenhum valor de F_ROH é emitido."
            ],
            "method": _METHOD,
        }
    return {
        "status": "INFERIDO",
        "f_roh": round(f_roh, 5),
        "total_roh_kb": round(total_kb, 1),
        "autosome_kb": AUTOSOME_KB,
        "tract_count": len(tracts),
        "longest_tract_kb": tracts[0]["length_kb"] if tracts else 0.0,
        "tracts": tracts[:50],
        "tracts_omitted": max(0, len(tracts) - 50),
        "called_markers": len(called),
        "call_rate": round(call_rate, 4),
        "parameters": {
            "min_tract_kb": MIN_TRACT_KB,
            "min_tract_markers": MIN_TRACT_MARKERS,
            "max_heterozygotes_per_tract": MAX_HETEROZYGOTES_PER_TRACT,
            "max_gap_kb": MAX_GAP_KB,
        },
        "reference_expectations": list(REFERENCE_EXPECTATIONS),
        "interpretation": _interpretation(f_roh, len(tracts)),
        "method": _METHOD,
    }


def _interpretation(f_roh: float, tract_count: int) -> dict[str, Any]:
    """What the number supports, and — mostly — what it does not."""
    if tract_count == 0:
        band = "sem tratos longos detectados"
        reading = (
            "Nenhum trato homozigoto longo o bastante para ser medido. Isso é compatível com "
            "ausência de parentesco recente entre os pais, e não é prova dela: tratos curtos "
            "não são contados e um array não vê o que não interroga."
        )
    elif f_roh < 0.0156:
        band = "abaixo do esperado para primos de segundo grau"
        reading = (
            "Carga de homozigose dentro da faixa comum em populações não isoladas. Não "
            "sustenta afirmação de consanguinidade."
        )
    elif f_roh < 0.0625:
        band = "entre primos de segundo e de primeiro grau"
        reading = (
            "Carga compatível com parentesco distante entre os pais **ou** com origem em "
            "população endogâmica ou fundadora. As duas produzem tratos longos e este exame "
            "não as distingue."
        )
    else:
        band = "igual ou acima do esperado para primos de primeiro grau"
        reading = (
            "Carga alta de homozigose. Em triagem reprodutiva isso eleva materialmente o "
            "risco de condição autossômica recessiva, porque a maior parte do aumento vem de "
            "identidade por descendência e não de dois eventos independentes de portador. "
            "Exige aconselhamento genético com história familiar; este exame não estabelece "
            "grau de parentesco."
        )
    return {
        "band": band,
        "reading": reading,
        "not_established": (
            "F_ROH não é pedigree e não identifica relação de parentesco. Isolamento "
            "populacional e efeito fundador produzem tratos longos sem parentesco próximo "
            "entre os pais, e nenhuma dessas causas é distinguível por este dado."
        ),
    }


_METHOD = (
    "Tratos homozigotos por varredura de janela deslizante sobre genótipos chamados, "
    f"exigindo comprimento >= {MIN_TRACT_KB:.0f} kb, >= {MIN_TRACT_MARKERS} marcadores "
    f"chamados, no máximo {MAX_HETEROZYGOTES_PER_TRACT} heterozigoto tolerado e nenhum vão "
    f"acima de {MAX_GAP_KB:.0f} kb. F_ROH é a soma dos tratos dividida por "
    f"{AUTOSOME_KB:,.0f} kb de autossomos. Estimador de McQuillan et al., Am J Hum Genet "
    "83:359-372 (2008), preferido aos estimadores por frequência alélica porque estes exigem "
    "uma população de referência pareada que um genoma brasileiro miscigenado não tem."
)


def read_autosomal_genotypes(input_path: Any) -> tuple[list[tuple[str, int, str]], int]:
    """Every autosomal marker in the array, as (chromosome, position, genotype).

    Unlike the target-driven readers elsewhere, this one takes the whole autosome: runs of
    homozygosity are a property of the genome between the targets, and reading only the
    registry's loci would measure the registry's spacing instead of the person's tracts.
    """
    from pathlib import Path

    from array_pipeline.completeness import _row_reader
    from array_pipeline.qc import UNRESOLVED_OVERLAP_STATUSES, _canonical_gt, _is_valid_consensus

    autosomes = {str(c) for c in range(1, 23)}
    markers: list[tuple[str, int, str]] = []
    total = 0
    for schema, row in _row_reader(Path(input_path)):
        chromosome = (row.get("CHROMOSOME") or "").strip()
        if chromosome not in autosomes:
            continue
        total += 1
        position = (row.get("POSITION") or "").strip()
        if not position.isdigit():
            continue
        if schema and schema.startswith("harmonized"):
            raw = row.get("CONSENSUS_RESULT")
            status = (row.get("STATUS") or "").strip().lower()
        else:
            raw = row.get("RESULT")
            status = ""
        # An unresolved cross-platform record is not a genotype. Letting it through would
        # count a disagreement between platforms as evidence about this person's zygosity.
        if status in UNRESOLVED_OVERLAP_STATUSES or not _is_valid_consensus(raw):
            continue
        genotype = _canonical_gt(raw)
        if genotype:
            markers.append((chromosome, int(position), genotype))
    return markers, total


def analyse_array(input_path: Any) -> dict[str, Any]:
    """Runs of homozygosity for one array file."""
    markers, total = read_autosomal_genotypes(input_path)
    result = analyse(markers, total_autosomal_markers=total)
    result["autosomal_rows"] = total
    return result
