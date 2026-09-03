"""Quantify what a partial pharmacogenomic panel can and cannot exclude.

`array_pipeline/pharmacogenomics.py` refuses a diplotype whenever any of CPIC's defining
positions for the gene is not interpretable. That refusal is sound — `*1` asserts the
reference base at *every* defining position, including the ones the chip never carried — but
it is also all-or-nothing, and on a consumer array it fires for every gene except VKORC1. The
report then says "diplótipo não estabelecido" for ten genes and stops, which is honest and
almost useless: it gives the reader no way to tell a gene missing one rare allele from a gene
missing forty common ones.

This module replaces the binary with a measurement. For each gene it partitions CPIC's
alleles into those the sample can *discriminate* — every defining position interpretable —
and those it cannot, then prices the second set from CPIC's own per-biogeographic-group
frequency table. What comes out is the quantity a clinician actually needs:

    residual = P(a chromosome carries a function-altering allele this panel cannot see)

With that number three things become possible that were not before.

* A **conditional diplotype** can be stated: not `*1/*2`, which claims the reference base
  everywhere, but `*2` plus a second chromosome carrying none of the alleles that *were*
  tested, with the residual attached and the closed-world assumption written out. It is
  emitted in its own field, never as `diplotype.value`, so nothing downstream that reads an
  established diplotype starts reading a conditional one instead.
* A **conditional phenotype** can be looked up in CPIC's table — but only when the residual
  is actually *bounded*, meaning CPIC publishes a frequency for every allele the panel could
  not exclude. An allele with no published frequency makes the residual a lower bound, and a
  lower bound cannot license a metabolizer status.
* A **sequencing requisition** can be written. Greedy selection over the uncovered positions
  answers the question the previous refusal left hanging: not "sequence forty to eighty
  positions" but "these eleven positions, in this order, take the unexcluded function-altering
  frequency from 0.31 to 0.00".

The failure this module is built to avoid is the one the rest of the project keeps finding:
a residual of zero that means "nothing left to exclude" is right, and a residual of zero that
means "we could not price anything" is a lie. They are kept apart by `computable` and
`bounded`, both computed from the data rather than assumed, and an allele whose CPIC function
label this module does not recognise is counted as uncertain — never as normal.
"""
from __future__ import annotations

import math
from typing import Any

from array_pipeline.completeness import INTERPRETABLE

UNAVAILABLE = "NÃO DISPONÍVEL"

#: CPIC's clinical function vocabulary, split by what it means for residual risk.
NORMAL_FUNCTION = "Normal function"
ALTERED_FUNCTIONS = frozenset({"No function", "Decreased function", "Increased function"})
UNCERTAIN_FUNCTIONS = frozenset({"Uncertain function", "Unknown function"})

#: Buckets this module reports. `UNCERTAIN` is deliberately its own bucket: folding it into
#: `NORMAL` would understate residual risk, folding it into `ALTERED` would overstate it, and
#: both would hide how much of the gene CPIC itself has not resolved.
NORMAL = "NORMAL"
ALTERED = "ALTERADA"
UNCERTAIN = "INCERTA"

#: The placeholder that stands in for a chromosome carrying none of the *tested* alleles.
#: It deliberately reuses report 09's vocabulary rather than CPIC's `*1`: NÃO DETECTADO means
#: "interrogated and absent", which is exactly the claim, whereas `*1` would additionally
#: claim the reference base at every position the panel never read.
NOT_DETECTED_ELEMENT = "NÃO DETECTADO"


def function_bucket(label: Any) -> str:
    """Map a CPIC clinical-function label to a residual-risk bucket.

    Anything outside CPIC's published vocabulary — including a null, which CPIC uses for
    alleles it has not functionally classified — becomes `UNCERTAIN`. Defaulting to `NORMAL`
    would make a CPIC vocabulary change silently shrink the residual, which is the direction
    that produces a false reassurance rather than a false alarm.
    """
    text = str(label or "").strip()
    if text == NORMAL_FUNCTION:
        return NORMAL
    if text in ALTERED_FUNCTIONS:
        return ALTERED
    return UNCERTAIN


def _is_recognised(label: Any) -> bool:
    """Whether a CPIC function label is one this module knows how to place.

    An allowlist: a label nobody anticipated is refused rather than bucketed by resemblance,
    because guessing which bucket an unknown function belongs to is a clinical judgement.
    """
    text = str(label or "").strip()
    return text == NORMAL_FUNCTION or text in ALTERED_FUNCTIONS or text in UNCERTAIN_FUNCTIONS


def _frequency_table(definition: dict[str, Any]) -> tuple[dict[str, float], bool]:
    """Return (per-group frequency, whether CPIC marked the table inferred).

    Observed frequencies are preferred; CPIC's inferred table is used only when no observed
    one exists, and the fact that it was inferred travels with it.
    """
    observed = _numeric(definition.get("cpic_frequency"))
    if observed:
        return observed, False
    inferred = _numeric(definition.get("cpic_inferred_frequency"))
    return inferred, bool(inferred)


def _numeric(table: Any) -> dict[str, float]:
    """Keep only real numbers.

    `scripts/build_pgx_registry.py` already drops CPIC's nulls, but this module takes a
    registry from wherever the caller got one, so it cannot rely on that having happened. A
    null is CPIC publishing no number for that group; coercing it would either crash here or,
    worse, become a frequency of zero and shrink the residual.
    """
    if not isinstance(table, dict):
        return {}
    valid: dict[str, float] = {}
    for group, value in table.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            continue
        valid[str(group)] = number
    return valid


def _interpretable(classification: Any) -> bool:
    """Whether a genotype classification may be scored at all."""
    return str(classification or "") in INTERPRETABLE


def partition_alleles(
    spec: dict[str, Any],
    classifications: dict[str, str],
) -> dict[str, Any]:
    """Split a gene's CPIC alleles by whether this sample can discriminate them.

    An allele is discriminable when *every* one of its defining positions is interpretable
    here — that is the same condition the unconditional diplotype requires, applied per
    allele instead of per gene.
    """
    discriminable: list[str] = []
    indiscriminable: list[str] = []
    missing_positions: set[str] = set()
    covered_positions: set[str] = set()
    per_allele: dict[str, dict[str, Any]] = {}

    for allele in sorted(spec.get("alleles", {})):
        definition = spec["alleles"][allele] or {}
        defining = definition.get("defining") or []
        absent = sorted(
            {
                str(item["rsid"]).lower()
                for item in defining
                if not _interpretable(classifications.get(str(item["rsid"]).lower()))
            }
        )
        present = sorted(
            {
                str(item["rsid"]).lower()
                for item in defining
                if _interpretable(classifications.get(str(item["rsid"]).lower()))
            }
        )
        covered_positions.update(present)
        missing_positions.update(absent)
        bucket = function_bucket(definition.get("cpic_clinical_function"))
        frequency, inferred = _frequency_table(definition)
        record = {
            "allele": allele,
            "function": definition.get("cpic_clinical_function") or UNAVAILABLE,
            "function_bucket": bucket,
            "function_label_recognised": _is_recognised(definition.get("cpic_clinical_function")),
            "defining_positions": len(defining),
            "interpretable_positions": len(present),
            "missing_positions": absent,
            "frequency": frequency,
            "frequency_is_inferred": inferred,
        }
        # An allele with no defining positions at all cannot be "fully covered"; treating an
        # empty requirement as satisfied is the vacuous-truth failure this project keeps
        # finding, and here it would invent discriminability out of missing data.
        definition_complete = definition.get("definition_complete", True) is True
        if defining and not absent and definition_complete:
            discriminable.append(allele)
            record["discriminable"] = True
        else:
            indiscriminable.append(allele)
            record["discriminable"] = False
            if not defining:
                record["missing_positions"] = []
                record["basis"] = "o registro não lista posição definidora para este alelo"
            elif not definition_complete:
                record["basis"] = (
                    "o registro declara definição parcial; posições sem rsid impedem "
                    "discriminação do alelo"
                )
        per_allele[allele] = record

    return {
        "discriminable": discriminable,
        "indiscriminable": indiscriminable,
        "alleles": per_allele,
        "positions_interpretable": sorted(covered_positions),
        "positions_missing": sorted(missing_positions - covered_positions),
    }


def residual_risk(partition: dict[str, Any]) -> dict[str, Any]:
    """Price the alleles this panel could not exclude, per biogeographic group.

    Two flags carry the honesty of the number:

    ``computable``  CPIC publishes a frequency for at least one of the alleles that could not
                    be excluded, so there is a number at all.
    ``bounded``     CPIC publishes a frequency for *every* one of them, so the number is the
                    residual rather than a lower bound on it.
    """
    indiscriminable = [partition["alleles"][name] for name in partition["indiscriminable"]]

    # The group universe comes from *every* allele of the gene, not only the ones that could
    # not be excluded. Drawing it from the un-excluded set alone would quietly drop any group
    # CPIC prices elsewhere in the gene but not here — and dropping a group is indistinguishable,
    # in the output, from that group having no residual.
    groups: set[str] = set()
    for record in partition["alleles"].values():
        groups.update(record["frequency"])

    unpriced_altered = sorted(
        r["allele"] for r in indiscriminable if r["function_bucket"] == ALTERED and not r["frequency"]
    )
    unpriced_uncertain = sorted(
        r["allele"] for r in indiscriminable if r["function_bucket"] == UNCERTAIN and not r["frequency"]
    )
    unpriced_normal = sorted(
        r["allele"] for r in indiscriminable if r["function_bucket"] == NORMAL and not r["frequency"]
    )
    inferred_used = sorted(r["allele"] for r in indiscriminable if r["frequency_is_inferred"])

    populations: dict[str, dict[str, Any]] = {}
    for group in sorted(groups):
        altered = 0.0
        uncertain = 0.0
        missing_here: list[str] = []
        for record in indiscriminable:
            value = record["frequency"].get(group)
            if value is None:
                # No published frequency for this group is not a frequency of zero. The
                # allele is counted as unpriced *here* even if CPIC prices it elsewhere.
                if record["function_bucket"] in (ALTERED, UNCERTAIN):
                    missing_here.append(record["allele"])
                continue
            if record["function_bucket"] == ALTERED:
                altered += value
            elif record["function_bucket"] == UNCERTAIN:
                uncertain += value
        populations[group] = {
            "altered": round(altered, 6),
            "uncertain": round(uncertain, 6),
            "unpriced_alleles": sorted(missing_here),
            "bounded": not missing_here,
        }

    if not partition["alleles"]:
        # Vacuous truth: with no catalogued alleles at all, "nothing left to exclude" is
        # arithmetically true and clinically the opposite of what it sounds like. A gene
        # whose catalogue is empty has a residual nobody has measured, not a residual of zero.
        return {
            "computable": False,
            "bounded": False,
            "populations": {},
            "worst_population": None,
            "worst_altered": None,
            "worst_uncertain": None,
            "worst_uncertain_population": None,
            "unpriced_altered": [],
            "unpriced_uncertain": [],
            "unpriced_normal": [],
            "inferred_frequency_alleles": [],
            "basis": (
                "o registro não cataloga nenhum alelo para este gene; não há conjunto sobre o "
                "qual medir exclusão, e um residual zero aqui significaria ausência de "
                "catálogo, não ausência de risco"
            ),
        }

    if not indiscriminable:
        return {
            "computable": True,
            "bounded": True,
            "populations": {},
            "worst_population": None,
            "worst_altered": 0.0,
            "worst_uncertain": 0.0,
            "worst_uncertain_population": None,
            "unpriced_altered": [],
            "unpriced_uncertain": [],
            "unpriced_normal": [],
            "inferred_frequency_alleles": [],
            "basis": (
                "todos os alelos catalogados pelo CPIC para este gene são discrimináveis nesta "
                "amostra; não há alelo por excluir e o residual é zero por medição, não por "
                "ausência de dados"
            ),
        }

    if not populations:
        return {
            "computable": False,
            "bounded": False,
            "populations": {},
            "worst_population": None,
            "worst_altered": None,
            "worst_uncertain": None,
            "worst_uncertain_population": None,
            "unpriced_altered": unpriced_altered,
            "unpriced_uncertain": unpriced_uncertain,
            "unpriced_normal": unpriced_normal,
            "inferred_frequency_alleles": inferred_used,
            "basis": (
                f"{len(indiscriminable)} alelos não puderam ser excluídos e o CPIC não publica "
                "frequência para nenhum deles; o risco residual não é quantificável, e zero "
                "aqui significaria ausência de dado, não ausência de risco"
            ),
        }

    # Ancestry is not established for this sample, so the reported residual is the worst
    # group rather than an average: an average would understate the risk for whichever
    # population the person actually belongs to.
    #
    # Each axis gets its own worst group, because they are not the same group. Reporting the
    # uncertain fraction of whichever population happened to top the *altered* ranking did
    # exactly what the paragraph above forbids: on the shipped CPIC definitions it understated
    # the uncertain residual in six of ten genes, worst of all VKORC1 — 0.101 reported where
    # East Asian is 0.866, on the gene that dictates warfarin dosing — and TPMT, reported as
    # 0.0 where African American/Afro-Caribbean is 0.033.
    worst_group = max(populations, key=lambda g: populations[g]["altered"])
    worst_uncertain_group = max(populations, key=lambda g: populations[g]["uncertain"])
    bounded = all(entry["bounded"] for entry in populations.values()) and not (
        unpriced_altered or unpriced_uncertain
    )
    return {
        "computable": True,
        "bounded": bounded,
        "populations": populations,
        "worst_population": worst_group,
        "worst_altered": populations[worst_group]["altered"],
        "worst_uncertain": populations[worst_uncertain_group]["uncertain"],
        # Named, because the two maxima usually come from different populations and a reader
        # given one group label would attach both numbers to it.
        "worst_uncertain_population": worst_uncertain_group,
        "unpriced_altered": unpriced_altered,
        "unpriced_uncertain": unpriced_uncertain,
        "unpriced_normal": unpriced_normal,
        "inferred_frequency_alleles": inferred_used,
        "basis": (
            f"frequência somada dos {len(indiscriminable)} alelos não excluídos, por grupo "
            "biogeográfico do CPIC; o grupo de maior risco é reportado porque a ancestralidade "
            "desta amostra não foi estabelecida"
            + (
                ""
                if bounded
                else f"; {len(unpriced_altered) + len(unpriced_uncertain)} alelos sem frequência "
                "publicada tornam o valor um limite inferior, não o residual"
            )
        ),
    }


def sequencing_requisition(
    gene: str,
    spec: dict[str, Any],
    partition: dict[str, Any],
    residual: dict[str, Any],
) -> dict[str, Any]:
    """Order the uncovered defining positions by the residual each one would close.

    "Targeted sequencing is required" is a conclusion, not an instruction. This turns it into
    one: a position list with coordinates, ordered so that the frequency mass recovered per
    position sequenced is maximised, with the residual after each step. A laboratory can act
    on it; the previous refusal gave them nothing to act on.
    """
    group = residual.get("worst_population")
    uncertain_group = residual.get("worst_uncertain_population")
    targets = [
        partition["alleles"][name]
        for name in partition["indiscriminable"]
        if partition["alleles"][name]["function_bucket"] in (ALTERED, UNCERTAIN)
    ]
    if not targets:
        return {
            "status": UNAVAILABLE,
            "positions": [],
            "reason": (
                "nenhum alelo de função alterada ou incerta ficou por excluir; sequenciamento "
                "dirigido não alteraria a discriminação deste gene"
            ),
        }

    coordinates: dict[str, dict[str, Any]] = {}
    for definition in (spec.get("alleles") or {}).values():
        for item in definition.get("defining") or []:
            coordinates.setdefault(str(item["rsid"]).lower(), item)

    def weight(record: dict[str, Any]) -> float:
        """This allele's population frequency, taken from the right population for its bucket.

        Uncertain-function alleles are weighted against their own population rather than the
        altered-function one: the two maxima usually fall in different populations, and using
        one for both would rank an allele by a frequency measured somewhere else.
        """
        population = uncertain_group if record["function_bucket"] == UNCERTAIN else group
        if population is None:
            return 0.0
        value = record["frequency"].get(population)
        return float(value) if value is not None else 0.0

    remaining = {r["allele"]: set(r["missing_positions"]) for r in targets}
    weights = {r["allele"]: weight(r) for r in targets}
    altered = {r["allele"] for r in targets if r["function_bucket"] == ALTERED}

    steps: list[dict[str, Any]] = []
    covered: set[str] = set()
    open_alleles = {name for name, missing in remaining.items() if missing}
    # An allele in `targets` with no missing positions cannot occur — it would be
    # discriminable — but an allele the registry gave no defining positions at all can, and
    # no amount of sequencing at CPIC's positions would resolve it.
    undefinable = sorted(name for name, missing in remaining.items() if not missing)

    if not open_alleles and undefinable:
        return {
            "status": UNAVAILABLE,
            "gene": gene,
            "reference_population": group or UNAVAILABLE,
            "positions": [],
            "position_count": 0,
            "alleles_resolved": [],
            "alleles_unresolvable": undefinable,
            "structural_alleles_excluded": sorted(
                spec.get("structural_alleles_excluded") or []
            ),
            "reason": (
                "o catálogo contém alelos de função alterada ou incerta sem posições "
                "definidoras utilizáveis; nenhuma requisição dirigida pode ser construída"
            ),
        }

    while open_alleles:
        candidates: dict[str, tuple[float, int]] = {}
        for name in open_alleles:
            for rsid in remaining[name] - covered:
                gained, count = candidates.get(rsid, (0.0, 0))
                # Adding this position only unlocks the allele if it was its last gap.
                if remaining[name] - covered == {rsid}:
                    candidates[rsid] = (gained + weights[name], count + 1)
                else:
                    candidates[rsid] = (gained, count)
        if not candidates:
            break
        # Prefer the position that unlocks the most frequency mass; break ties by how many
        # alleles it unlocks, then by rsid so the order is reproducible.
        best = max(candidates, key=lambda r: (candidates[r][0], candidates[r][1], r))
        if candidates[best] == (0.0, 0):
            # No single position completes any allele yet; take the position appearing in the
            # most open alleles so the loop still converges instead of stalling.
            frequency_of = {
                rsid: sum(1 for name in open_alleles if rsid in remaining[name] - covered)
                for name in open_alleles
                for rsid in remaining[name] - covered
            }
            best = max(frequency_of, key=lambda r: (frequency_of[r], r))
        covered.add(best)
        unlocked = sorted(name for name in open_alleles if not (remaining[name] - covered))
        open_alleles -= set(unlocked)
        item = coordinates.get(best, {})
        steps.append(
            {
                "order": len(steps) + 1,
                "rsid": best,
                "chromosome": item.get("chromosome"),
                "position": item.get("position"),
                "reference_accession": item.get("reference_accession"),
                "cpic_location": item.get("cpic_location"),
                "chromosome_location": item.get("chromosome_location"),
                "unlocks_alleles": unlocked,
                "unlocks_altered_alleles": sorted(set(unlocked) & altered),
                "frequency_recovered": round(sum(weights[name] for name in unlocked), 6),
            }
        )

    cumulative = 0.0
    cumulative_altered = 0.0
    for step in steps:
        cumulative = round(cumulative + step["frequency_recovered"], 6)
        step["cumulative_frequency_recovered"] = cumulative
        cumulative_altered = round(
            cumulative_altered
            + sum(weights[name] for name in step["unlocks_altered_alleles"]),
            6,
        )
        start = residual.get("worst_altered")
        step["residual_altered_after"] = (
            round(max(start - cumulative_altered, 0.0), 6)
            if isinstance(start, (int, float))
            else None
        )

    return {
        "status": "PROPOSTO",
        "gene": gene,
        "reference_population": group or UNAVAILABLE,
        "positions": steps,
        "position_count": len(steps),
        "alleles_resolved": sorted({a for step in steps for a in step["unlocks_alleles"]}),
        "alleles_unresolvable": undefinable,
        "structural_alleles_excluded": sorted(spec.get("structural_alleles_excluded") or []),
        "reason": (
            f"{len(steps)} posições, nesta ordem, tornam discrimináveis todos os alelos de função "
            "alterada ou incerta que o CPIC define por substituição de base para este gene"
        ),
        "scope_note": (
            "Sequenciar estas posições não resolve alelos estruturais (duplicações, híbridos, "
            "deleções) nem estabelece fase. Um alelo que o CPIC não cataloga permanece "
            "indistinguível do haplótipo de referência mesmo com cobertura completa."
        ),
    }


def conditional_diplotype(
    gene: str,
    spec: dict[str, Any],
    partition: dict[str, Any],
    residual: dict[str, Any],
    allele_findings: list[dict[str, Any]],
    heterozygous_positions: list[str],
    *,
    structurally_unresolved: bool = False,
) -> dict[str, Any]:
    """State a diplotype restricted to the alleles this panel can actually discriminate.

    Every precondition the unconditional diplotype imposes still applies, except panel
    completeness — which is replaced by an explicit, quantified closed-world assumption. The
    result never claims the reference haplotype: it claims that the second chromosome carries
    none of the alleles that were *tested*, and states how much allele frequency that leaves
    unexcluded.
    """
    reasons: list[str] = []
    if structurally_unresolved:
        reasons.append(
            "variação clinicamente relevante deste gene é estrutural e não é resolvida por array"
        )
    if spec.get("definitions_unavailable"):
        reasons.append(str(spec["definitions_unavailable"]))
    reference = str(spec.get("reference_allele") or "").strip()
    if not reference:
        reasons.append(
            "o registro não nomeia o haplótipo de referência; sem ele um portador heterozigoto "
            "não tem segundo elemento"
        )
    if not partition["discriminable"]:
        # Zero discriminable alleles means nothing was interrogated. A "reference/reference"
        # call from an empty test set is exactly the substitution of NÃO TESTADO for
        # NÃO DETECTADO that report 09 exists to prevent.
        reasons.append(
            "nenhum alelo do CPIC é discriminável nesta amostra; não há conjunto testado sobre "
            "o qual condicionar um diplótipo"
        )

    detected = [
        f
        for f in allele_findings
        if f["status"] == "DETECTADO" and f["allele"] in set(partition["discriminable"])
    ]
    if len(detected) > 1:
        reasons.append(
            "genótipo composto: mais de um alelo discriminável foi detectado "
            f"({', '.join(sorted(f['allele'] for f in detected))}) e a atribuição a cada "
            "cromossomo exige fase"
        )
    if len(heterozygous_positions) > 1:
        reasons.append(
            f"fase não resolvida: {len(heterozygous_positions)} posições definidoras "
            f"heterozigotas ({', '.join(sorted(heterozygous_positions))}) admitem mais de um diplótipo"
        )
    unreadable = [f for f in detected if not f.get("zygosity")]
    if unreadable:
        # The branch below reads zygosity to decide whether the second chromosome carries the
        # same allele or none of the tested ones. With zygosity unreadable — a defining
        # position called with a single character, one allele observed rather than two —
        # neither statement is supported, and falling through to the heterozygous branch
        # would assert the stronger of the two.
        reasons.append(
            "zigosidade não legível em "
            f"{', '.join(sorted(f['allele'] for f in unreadable))}: "
            + "; ".join(
                sorted({str(f.get("zygosity_basis") or "base não registrada") for f in unreadable})
            )
        )

    if reasons:
        return {"status": UNAVAILABLE, "value": None, "reasons": reasons}

    tested = len(partition["discriminable"])
    not_excluded = len(partition["indiscriminable"])
    if detected:
        finding = detected[0]
        if finding["zygosity"] == "HOMOZIGOTO":
            value = f"{finding['allele']}/{finding['allele']}"
            plain = (
                f"{finding['allele']} detectado em homozigose; ambos os cromossomos carregam "
                "este alelo"
            )
        else:
            value = f"{finding['allele']}/[{NOT_DETECTED_ELEMENT}]"
            plain = (
                f"{finding['allele']} detectado em um cromossomo; o outro cromossomo não carrega "
                f"nenhum dos {tested} alelos discrimináveis, e permanece indistinguível de "
                f"{not_excluded} alelos não interrogados"
            )
    else:
        value = f"[{NOT_DETECTED_ELEMENT}]/[{NOT_DETECTED_ELEMENT}]"
        plain = (
            f"nenhum dos {tested} alelos discrimináveis foi detectado em qualquer cromossomo; "
            f"{not_excluded} alelos do catálogo CPIC não foram interrogados e não estão excluídos"
        )

    return {
        # Never VERIFICADO: the call is an inference from genotypes under a stated assumption,
        # not an observation of haplotypes.
        "status": "INFERIDO",
        "value": value,
        "plain_language": plain,
        "reference_allele_not_claimed": (
            f"o segundo elemento não é declarado {reference}: {reference} afirma a base de "
            f"referência em todas as posições definidoras, incluindo as {len(partition['positions_missing'])} "
            "que esta amostra não interrogou"
        ),
        "conditional_on": (
            f"nenhum dos {not_excluded} alelos do catálogo CPIC não interrogados está presente"
        ),
        "alleles_tested": tested,
        "alleles_not_excluded": not_excluded,
        "residual": residual,
        "reasons": [
            "diplótipo condicional ao conjunto de alelos efetivamente discriminável nesta "
            "amostra; o risco residual dos alelos não excluídos está quantificado em `residual`"
        ],
    }


def conditional_phenotype(
    gene: str,
    spec: dict[str, Any],
    diplotype: dict[str, Any],
    residual: dict[str, Any],
) -> dict[str, Any]:
    """Look the conditional diplotype up in CPIC's table, when the residual is bounded.

    A metabolizer status carries prescribing consequences, so it is emitted only when the
    assumption behind it is quantified: the residual must be *computable*, meaning CPIC prices
    at least part of what the panel could not exclude. A gene with no published frequency at
    all yields NÃO DISPONÍVEL, because "probably a normal metabolizer, no idea how probably"
    is not a phenotype.

    Boundedness is a weaker condition than computability and is **not** required — a handful
    of CPIC alleles carry no frequency in any population, which would block every gene — but
    it is never hidden. When the residual is a lower bound rather than the residual, the
    phenotype record says so in `residual_bounded`, in `caveat`, and in the count of unpriced
    alleles, so the label cannot be quoted apart from the assumption it rests on.
    """
    if diplotype.get("status") == UNAVAILABLE or not diplotype.get("value"):
        return {
            "status": UNAVAILABLE,
            "value": None,
            "reason": "fenótipo condicional depende de diplótipo condicional; nenhum foi estabelecido",
        }
    if not residual.get("computable"):
        return {
            "status": UNAVAILABLE,
            "value": None,
            "reason": (
                "o CPIC não publica frequência para nenhum dos alelos que este painel não pôde "
                "excluir; sem qualquer quantificação, um fenótipo seria asserção de prescrição "
                "sob suposição não medida"
            ),
        }
    table = spec.get("phenotype_map") or {}
    if not table:
        return {
            "status": UNAVAILABLE,
            "value": None,
            "reason": "registro não fornece tabela diplótipo→fenótipo para este gene",
        }

    reference = str(spec.get("reference_allele") or "").strip()
    # CPIC's table is keyed by star alleles, so the placeholder element has to be resolved to
    # the reference haplotype for the lookup. That substitution asserts more than the panel
    # measured, which is precisely why the substitution is named in `diplotype_used` and the
    # assumption it rests on is carried on every field below rather than left in a footnote.
    parts = list(str(diplotype["value"]).split("/"))
    resolved = [reference if part.startswith("[") else part for part in parts]
    substituted = sum(1 for part in parts if part.startswith("["))
    bounded = bool(residual.get("bounded"))
    unpriced = len(residual.get("unpriced_altered") or []) + len(
        residual.get("unpriced_uncertain") or []
    )
    # Both axes. The caveat priced only the altered-function alleles, and `residual_risk`
    # computes the uncertain-function ones separately *and from a different population* — the
    # two maxima rarely coincide. A gene whose altered residual is small and whose uncertain
    # residual is not would have carried a reassuring sentence next to the metabolizer label.
    caveat = (
        f"Fenótipo condicional: vale se nenhum dos {diplotype.get('alleles_not_excluded')} "
        f"alelos não interrogados estiver presente. Frequência somada dos alelos de função "
        f"alterada não excluídos: {residual.get('worst_altered')} no grupo "
        f"{residual.get('worst_population')}; de função incerta: "
        f"{residual.get('worst_uncertain')} no grupo {residual.get('worst_uncertain_population')}"
        + (
            "."
            if bounded
            else f"; ambos são limites inferiores, porque {unpriced} alelos não excluídos não "
            "têm frequência publicada pelo CPIC."
        )
    )
    keys = [p.replace(gene, "", 1).strip() for p in resolved]
    for key in ("/".join(keys), "/".join(reversed(keys))):
        entry = table.get(key)
        if entry:
            return {
                "status": "INFERIDO",
                "value": entry.get("phenotype"),
                "activity_score": entry.get("activity_score"),
                "description": entry.get("description"),
                "source": spec.get("phenotype_map_source", UNAVAILABLE),
                "diplotype_used": "/".join(resolved),
                "reference_substituted_elements": substituted,
                "residual_bounded": bounded,
                "residual_worst_altered": residual.get("worst_altered"),
                "residual_worst_population": residual.get("worst_population"),
                "residual_worst_uncertain": residual.get("worst_uncertain"),
                "residual_worst_uncertain_population": residual.get("worst_uncertain_population"),
                "residual_unpriced_alleles": unpriced,
                "applies_if": diplotype.get("conditional_on"),
                "caveat": caveat,
                "reason": (
                    "traduzido pela tabela diplótipo→fenótipo do CPIC sobre o diplótipo "
                    "condicional; INFERIDO, nunca EXECUTADO, porque o diplótipo de origem é "
                    "condicional ao painel efetivamente interrogado e "
                    + (
                        "o residual está medido e limitado"
                        if bounded
                        else "o residual medido é um limite inferior"
                    )
                ),
            }
    return {
        "status": UNAVAILABLE,
        "value": None,
        "reason": (
            f"diplótipo condicional {'/'.join(resolved)} não consta na tabela do CPIC; "
            "nenhum fenótipo aproximado é emitido"
        ),
    }


def analyse_gene(
    gene: str,
    spec: dict[str, Any] | None,
    classifications: dict[str, str],
    allele_findings: list[dict[str, Any]],
    heterozygous_positions: list[str],
    *,
    structurally_unresolved: bool = False,
) -> dict[str, Any]:
    """Full discrimination analysis for one gene."""
    if not spec or not spec.get("alleles"):
        return {
            "gene": gene,
            "status": UNAVAILABLE,
            "reason": (
                "registro curado não define alelos para este gene; não há conjunto sobre o qual "
                "medir discriminação"
            ),
        }

    partition = partition_alleles(spec, classifications)
    residual = residual_risk(partition)
    diplotype = conditional_diplotype(
        gene,
        spec,
        partition,
        residual,
        allele_findings,
        heterozygous_positions,
        structurally_unresolved=structurally_unresolved,
    )
    phenotype = conditional_phenotype(gene, spec, diplotype, residual)
    requisition = sequencing_requisition(gene, spec, partition, residual)

    total_positions = len(partition["positions_interpretable"]) + len(partition["positions_missing"])
    unrecognised = sorted(
        record["function"]
        for record in partition["alleles"].values()
        if not record["function_label_recognised"]
    )
    return {
        "gene": gene,
        "status": "VERIFICADO",
        "alleles_catalogued": len(partition["alleles"]),
        "alleles_discriminable": len(partition["discriminable"]),
        "alleles_indiscriminable": len(partition["indiscriminable"]),
        "discriminable_alleles": partition["discriminable"],
        "positions_total": total_positions,
        "positions_interpretable": len(partition["positions_interpretable"]),
        "positions_missing": partition["positions_missing"],
        "coverage_fraction": (
            len(partition["positions_interpretable"]) / total_positions if total_positions else 0.0
        ),
        "residual": residual,
        "conditional_diplotype": diplotype,
        "conditional_phenotype": phenotype,
        "sequencing_requisition": requisition,
        "unrecognised_function_labels": sorted(set(unrecognised)),
        "per_allele": [partition["alleles"][name] for name in sorted(partition["alleles"])],
    }
