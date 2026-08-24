"""Join observed genotypes to curated gene–disease evidence, once, for reports 01/03/07.

Reports 01 (clinical), 03 (reproductive) and 07 (prevention) all need the same join:
what was observed at each locus, what ClinVar says the variant means, and whether ClinGen
has established the gene–disease relationship at all and under which mode of inheritance.
Doing that join three times would give three chances to do it differently.

Three properties of the join are load-bearing.

**ClinVar is joined by accession, never by rsid text.** An rsid text search in ClinVar
returns unrelated variants that merely mention the identifier. `docs/evidence/
ASSESSED_ALLELES_CLINVAR.json` holds the records already verified to sit at the target's
GRCh38 coordinate; only accessions in that set are allowed through, so the condition names
and review statuses fetched by rsid attach to the right variant or to none.

**Carrier status requires a curated mode of inheritance.** A heterozygous pathogenic variant
is a carrier finding in an autosomal-recessive condition and a diagnosis-relevant finding in
a dominant one. Without ClinGen's `MOI` the two cannot be told apart, so the module reports
the genotype and refuses the interpretation rather than assuming recessive — which is the
assumption that turns a dominant finding into a reassuring one.

**A genotype is never a diagnosis, and homozygosity is never "affected".** HFE p.Cys282Tyr
homozygotes mostly do not develop haemochromatosis; F5 Leiden homozygotes mostly do not have
thrombosis. The module emits a risk genotype requiring clinical correlation, and the word
"diagnóstico" appears nowhere in what it produces.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import normative
from array_pipeline.completeness import INTERPRETABLE, NAO_DETECTADO, NAO_TESTADO
from array_pipeline.targets import read_manifest_bytes, sha256_json
from reporting.case_dossier import (
    SEX_FEMALE,
    SEX_INTERSEX,
    SEX_MALE,
    SEX_NOT_RECORDED,
    normalised_sex,
)

SCHEMA = "genoma-clinical-findings-v1"
UNAVAILABLE = "NÃO DISPONÍVEL"

#: ClinVar descriptions that assert clinical significance in the pathogenic direction. The
#: comparison is exact against ClinVar's vocabulary: a description this module does not
#: recognise is reported verbatim and treated as *not* asserting pathogenicity, so a new
#: ClinVar label cannot silently promote a variant.
PATHOGENIC_CLASSIFICATIONS = frozenset(
    {"Pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic"}
)
BENIGN_CLASSIFICATIONS = frozenset({"Benign", "Likely benign", "Benign/Likely benign"})
#: Explicitly *not* actionable and explicitly not benign either — the middle of the
#: distribution, where most consumer-array findings live.
UNCERTAIN_CLASSIFICATIONS = frozenset(
    {"Uncertain significance", "Conflicting classifications of pathogenicity", "not provided"}
)

#: ClinVar's review status, as a star count. The registry now carries a one-star tier as well
#: as the two-star one, which multiplies the loci available — and would multiply the false
#: findings just as fast if both were read the same way. One submitter asserting
#: pathogenicity is one laboratory's opinion; the two-star statuses mean either several
#: submitters agreed with no conflict, or an expert panel or practice guideline ruled.
REVIEW_STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, single submitter": 1,
    "no assertion criteria provided": 0,
    "no classification provided": 0,
    "no classification for the single variant": 0,
}
#: Stars required before a variant may become an actionable or carrier finding.
MIN_STARS_FOR_FINDING = 2

#: ClinGen validity classifications strong enough for a report to speak of the gene–disease
#: relationship as established.
ESTABLISHED_VALIDITY = frozenset({"Definitive", "Strong"})

#: Mode-of-inheritance codes. ClinGen's download uses the abbreviations; GenCC spells them
#: out, so GenCC's labels are normalised onto ClinGen's before the two are compared.
AUTOSOMAL_RECESSIVE = "AR"
AUTOSOMAL_DOMINANT = "AD"
X_LINKED = "XL"
MOI_UNKNOWN = "DESCONHECIDO"

_GENCC_MOI = {
    "autosomal recessive": AUTOSOMAL_RECESSIVE,
    "autosomal dominant": AUTOSOMAL_DOMINANT,
    "x-linked": X_LINKED,
    "x-linked recessive": X_LINKED,
    "x-linked dominant": X_LINKED,
    "unknown": MOI_UNKNOWN,
}


def normalised_moi(label: Any) -> str:
    """Map any registry's mode-of-inheritance label onto ClinGen's abbreviation.

    ClinGen writes `AR`, GenCC writes `Autosomal recessive`. Comparing them unnormalised made
    every gene both registries agreed on look like a gene they disagreed on — a false
    conflict that then blocked the carrier interpretation it was meant to protect.

    An unmapped label becomes DESCONHECIDO rather than being passed through: a mode this
    function does not recognise must not accidentally equal `AR` and license a carrier call,
    and it must not vanish from the conflict check either.
    """
    text = str(label or "").strip().lower()
    if text in {AUTOSOMAL_RECESSIVE.lower(), AUTOSOMAL_DOMINANT.lower(), X_LINKED.lower()}:
        return text.upper()
    return _GENCC_MOI.get(text, MOI_UNKNOWN)


#: Kept as a private alias so existing call sites read unchanged.
_normalised_moi = normalised_moi

#: What a locus is reported as. These are not severities; they are different *kinds* of
#: statement, and collapsing them is how a carrier finding becomes a diagnosis.
ACIONAVEL = "ACHADO ACIONÁVEL"
ACHADO_PRELIMINAR = "ACHADO PRELIMINAR"
PORTADOR = "PORTADOR"
GENOTIPO_DE_RISCO = "GENÓTIPO DE RISCO"
PREDISPOSICAO = "PREDISPOSIÇÃO"
SEM_INTERPRETACAO = "SEM INTERPRETAÇÃO ESTABELECIDA"
NEGATIVO = "NEGATIVO NESTE LOCUS"
NAO_INTERROGADO = "NÃO INTERROGADO"


class ClinicalEvidenceError(ValueError):
    """The curated evidence file is unusable."""


def _zygosity(genotype: Any) -> str | None:
    text = str(genotype or "").strip().upper()
    if len(text) != 2 or not set(text) <= set("ACGT"):
        return None
    return "HOMOZIGOTO" if text[0] == text[1] else "HETEROZIGOTO"


def _verified_accessions(assessed: dict[str, Any]) -> dict[str, set[str]]:
    """Per rsid, the ClinVar accessions verified to sit at that target's coordinate."""
    out: dict[str, set[str]] = {}
    for record in assessed.get("results", []):
        rsid = str(record.get("rsid") or "").lower()
        out[rsid] = {
            str(item.get("accession"))
            for item in record.get("clinvar_records_at_this_coordinate", [])
            if item.get("accession")
        }
    return out


def _coordinate(value: Any) -> tuple[str, int] | None:
    if not isinstance(value, dict):
        return None
    chromosome = str(value.get("chromosome") or "").strip().replace("chr", "")
    position = value.get("position")
    if not chromosome or not isinstance(position, int):
        return None
    return chromosome, position


def _clinvar_for(
    rsid: str,
    locus_evidence: dict[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    """ClinVar records for this locus, admitted only on a coordinate they can be checked at.

    Two evidence routes reach this function and they carry different risks, so each is
    checked on its own terms rather than through one weakened rule.

    The **API route** finds records by an rsid *text* search, which returns unrelated variants
    that merely mention the identifier — on rs4244285 it returned twelve. Those records carry
    no coordinate of their own, so they are admitted only if their accession appears in the
    set already verified to sit at the target's GRCh38 coordinate.

    The **bulk route** reads accession, classification and coordinate from one row of
    ClinVar's own release. There is no cross-source join to get wrong, and the record carries
    its coordinate, so it is admitted when that coordinate matches the locus's. This is a
    check performed here, not a flag the evidence file can set to exempt itself: a record with
    no coordinate falls back to the allowlist however the file describes its provenance.
    """
    all_records = (locus_evidence.get("clinvar") or {}).get("records", [])
    locus_coordinate = _coordinate(locus_evidence.get("grch38"))

    records: list[dict[str, Any]] = []
    by_coordinate = 0
    for record in all_records:
        record_coordinate = _coordinate(record.get("grch38"))
        if record_coordinate is not None and locus_coordinate is not None:
            if record_coordinate == locus_coordinate:
                records.append(record)
                by_coordinate += 1
            continue
        if str(record.get("accession")) in allowed:
            records.append(record)
    discarded = len(all_records) - len(records)
    if not records:
        return {
            "status": UNAVAILABLE,
            "records": [],
            "classifications": [],
            "conditions": [],
            "asserts_pathogenic": False,
            "reason": (
                "nenhum registro do ClinVar para este locus pôde ser confirmado na coordenada "
                f"do alvo ({discarded} descartados); a junção é por coordenada, nunca por texto"
            ),
        }
    classifications = sorted({str(r.get("classification")) for r in records})
    # The best review level among the records that actually assert pathogenicity — a benign
    # record reviewed by an expert panel says nothing about how well-reviewed the pathogenic
    # claim is.
    pathogenic_records = [
        r for r in records if str(r.get("classification")) in PATHOGENIC_CLASSIFICATIONS
    ]
    stars = max(
        (REVIEW_STARS.get(str(r.get("review_status") or "").strip(), 0) for r in pathogenic_records),
        default=0,
    )
    unrecognised_reviews = sorted(
        {
            str(r.get("review_status"))
            for r in pathogenic_records
            if str(r.get("review_status") or "").strip() not in REVIEW_STARS
        }
    )
    conditions = sorted(
        {
            str(condition.get("name"))
            for record in records
            for condition in record.get("conditions", [])
            if condition.get("name")
        }
    )
    unrecognised = sorted(
        set(classifications)
        - PATHOGENIC_CLASSIFICATIONS
        - BENIGN_CLASSIFICATIONS
        - UNCERTAIN_CLASSIFICATIONS
    )
    return {
        "status": "VERIFICADO",
        "records": records,
        "classifications": classifications,
        "conditions": conditions,
        "condition_xrefs": {
            str(condition.get("name")): condition.get("xrefs", {})
            for record in records
            for condition in record.get("conditions", [])
            if condition.get("name")
        },
        "review_statuses": sorted({str(r.get("review_status")) for r in records}),
        "asserts_pathogenic": any(c in PATHOGENIC_CLASSIFICATIONS for c in classifications),
        "asserts_benign": bool(classifications) and all(
            c in BENIGN_CLASSIFICATIONS for c in classifications
        ),
        # Surfaced rather than absorbed: a ClinVar vocabulary this module does not know must
        # not be silently treated as "not pathogenic" without the reader being told.
        "unrecognised_classifications": unrecognised,
        # An unrecognised review status scores zero stars rather than being waved through,
        # so a ClinVar vocabulary change cannot promote a finding by accident.
        "unrecognised_review_statuses": unrecognised_reviews,
        "review_stars": stars,
        "meets_review_threshold": stars >= MIN_STARS_FOR_FINDING,
        "accessions_discarded_by_coordinate": discarded,
        # Which route admitted the records, so a reader can tell a coordinate-native release
        # row from a text search checked against an allowlist.
        "records_verified_by_coordinate": by_coordinate,
        "records_verified_by_accession": len(records) - by_coordinate,
    }


def _validity_for(gene: str | None, evidence: dict[str, Any]) -> dict[str, Any]:
    """Gene–disease validity and mode of inheritance, from whichever registry established it.

    ClinGen, GenCC and PanelApp are read as three registries, not one: `established_by` says
    which carried the gene, because "Definitive by a ClinGen expert panel", "Strong by two
    clinical laboratories in GenCC" and "green on an NHS diagnostic panel" are the same word
    for different weights and a report that hides the difference is overstating one of them.

    gnomAD constraint travels with the gene but is deliberately kept out of `established_by`:
    intolerance to loss of function is a population-genetic observation, not a gene–disease
    assertion, and letting it establish anything would convert "this gene is rarely broken in
    healthy people" into "this variant means something", which is a different claim.
    """
    validity = (evidence.get("gene_validity") or {}).get(str(gene or ""), None)
    if not validity:
        return {
            "status": UNAVAILABLE,
            "established": False,
            "established_by": [],
            "modes_of_inheritance": [],
            "classifications": [],
            "diseases": [],
            "recessive_diseases": [],
            "dominant_diseases": [],
            "mode_of_inheritance_conflict": False,
            "panelapp_green_panels": 0,
            "clingen_dosage": {"status": UNAVAILABLE},
            "gnomad_constraint": {"status": UNAVAILABLE},
            "reason": (
                "gene ausente do arquivo de validade curada"
                if gene
                else "o alvo não declara gene, portanto não há relação gene-doença a avaliar"
            ),
        }

    clingen = validity.get("clingen") or {}
    gencc = validity.get("gencc") or {}
    established_clingen = [
        c
        for c in clingen.get("curations", [])
        if str(c.get("classification")) in ESTABLISHED_VALIDITY
    ]
    established_gencc = [g for g in gencc.get("established_groups", []) if g.get("established")]
    panelapp = validity.get("panelapp") or {}
    established_panelapp = bool(panelapp.get("established"))
    dosage = validity.get("clingen_dosage") or {}
    established_dosage = bool(dosage.get("established"))
    # `established` is recomputed from the curations rather than read from the evidence
    # file's own summary field, for the same reason `provenance_blockers` recomputes its
    # status floor: a stored aggregate that disagrees with the records it summarises would
    # be followed rather than caught, and here it decides whether a variant becomes a
    # clinical finding.
    established_by = [
        name
        for name, present in (
            ("ClinGen", established_clingen),
            ("GenCC", established_gencc),
            ("PanelApp", established_panelapp),
            ("ClinGen Dosage", established_dosage),
        )
        if present
    ]

    def diseases_with(mode: str) -> list[str]:
        return sorted(
            {
                str(c["disease"])
                for c in established_clingen
                if _normalised_moi(c.get("mode_of_inheritance")) == mode and c.get("disease")
            }
            | {
                str(g["disease"])
                for g in established_gencc
                if _normalised_moi(g.get("mode_of_inheritance")) == mode and g.get("disease")
            }
        )

    modes = sorted(
        {
            normalised_moi(c["mode_of_inheritance"])
            for c in established_clingen
            if c.get("mode_of_inheritance")
        }
        | {
            normalised_moi(g.get("mode_of_inheritance"))
            for g in established_gencc
            if g.get("mode_of_inheritance")
        }
        # PanelApp contributes a mode only where it is green. An amber gene's mode is a
        # curator's provisional note on a relationship the panel declined to endorse.
        | (
            {normalised_moi(m) for m in (panelapp.get("modes_of_inheritance") or [])}
            if established_panelapp
            else set()
        )
        # Dosage contributes its mode whenever the curators scored the gene. A score of 30 —
        # "gene associated with autosomal recessive phenotype" — does not establish the
        # relationship, but it is still an expert panel stating the inheritance, and the mode
        # is only ever consulted for a gene some registry already established.
        | {normalised_moi(m) for m in (dosage.get("modes_of_inheritance") or [])}
    )
    # Per-disease MONDO index. A gene can be dominant for one condition and recessive for
    # another — F5 is dominant for thrombophilia and recessive for factor V deficiency — so
    # the mode that applies to *this variant* is the mode of the condition ClinVar names for
    # it, not the union over the gene.
    by_mondo: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for curation in established_clingen:
        entry = {
            "disease": curation.get("disease"),
            "mondo": curation.get("mondo"),
            "mode": normalised_moi(curation.get("mode_of_inheritance")),
            "source": "ClinGen",
        }
        if curation.get("mondo"):
            by_mondo.setdefault(str(curation["mondo"]).upper(), entry)
        if curation.get("disease"):
            by_name.setdefault(str(curation["disease"]).strip().lower(), entry)
    for group in established_gencc:
        entry = {
            "disease": group.get("disease"),
            "mondo": group.get("disease_curie"),
            "mode": normalised_moi(group.get("mode_of_inheritance")),
            "source": "GenCC",
        }
        if group.get("disease_curie"):
            by_mondo.setdefault(str(group["disease_curie"]).upper(), entry)
        if group.get("disease"):
            by_name.setdefault(str(group["disease"]).strip().lower(), entry)

    return {
        "diseases_by_mondo": by_mondo,
        "diseases_by_name": by_name,
        "status": "VERIFICADO" if established_by else UNAVAILABLE,
        "established": bool(established_by),
        "established_by": established_by,
        "modes_of_inheritance": modes,
        "mode_of_inheritance_conflict": bool(validity.get("mode_of_inheritance_conflict")),
        "classifications": sorted(
            set(clingen.get("classifications", []))
            | {c for g in gencc.get("groups", []) for c in g.get("classifications", [])}
            | (
                {f"PanelApp verde em {panelapp.get('green_panel_count', 0)} painel(éis)"}
                if established_panelapp
                else set()
            )
            | (
                {f"ClinGen dosagem: {dosage.get('haploinsufficiency', '')}".strip(": ")}
                if established_dosage
                else set()
            )
        ),
        "clingen_dosage": dosage or {"status": UNAVAILABLE},
        "panelapp_green_panels": int(panelapp.get("green_panel_count") or 0),
        "panelapp_instances": list(panelapp.get("established_by") or []),
        # True where GenCC and PanelApp both carry the gene. GenCC's export already includes
        # the PanelApp submissions, so that is one body of curation appearing twice, not two
        # registries agreeing, and `established_by` must not be read as two votes.
        "panelapp_overlaps_gencc": bool(validity.get("panelapp_overlaps_gencc")),
        "modes_without_disease_anchor": list(validity.get("modes_without_disease_anchor") or []),
        # Carried, displayed, and never permitted to establish anything.
        "gnomad_constraint": validity.get("gnomad_constraint") or {"status": UNAVAILABLE},
        "diseases": sorted(
            {str(c["disease"]) for c in established_clingen if c.get("disease")}
            | {str(g["disease"]) for g in established_gencc if g.get("disease")}
        ),
        "recessive_diseases": diseases_with(AUTOSOMAL_RECESSIVE),
        "dominant_diseases": diseases_with(AUTOSOMAL_DOMINANT),
        "clingen_curations": clingen.get("curations", []),
        "gencc_groups": established_gencc,
        "gencc_submitters": sorted({s for g in established_gencc for s in g.get("submitters", [])}),
        # The carrier-screening denominator travels with the gene, because a negative screen
        # is only interpretable against how much of the gene's catalogue was interrogated.
        "clinvar_variant_counts": validity.get("clinvar_variant_counts")
        or {"status": UNAVAILABLE, "pathogenic": None, "total": None},
        **({"reason": validity["reason"]} if validity.get("reason") else {}),
    }


def _matched_diseases(clinvar: dict[str, Any], validity: dict[str, Any]) -> list[dict[str, Any]]:
    """Curated diseases that match a condition ClinVar asserts for *this* variant.

    Matching is by MONDO identifier first, because a disease name is written a dozen ways
    across registries and a string comparison silently misses most of them. The name index is
    a fallback for conditions ClinVar carries without a MONDO cross-reference.
    """
    by_mondo = validity.get("diseases_by_mondo") or {}
    by_name = validity.get("diseases_by_name") or {}
    matched: dict[str, dict[str, Any]] = {}
    for name, xrefs in (clinvar.get("condition_xrefs") or {}).items():
        mondo = str((xrefs or {}).get("MONDO") or "").upper()
        entry = by_mondo.get(mondo) if mondo else None
        if entry is None:
            entry = by_name.get(str(name).strip().lower())
        if entry is not None:
            matched[str(entry.get("disease"))] = entry
    return sorted(matched.values(), key=lambda e: str(e.get("disease")))


def _interpretation(
    entry: dict[str, Any],
    clinvar: dict[str, Any],
    validity: dict[str, Any],
    sex_at_birth: str | None = None,
) -> dict[str, Any]:
    """Decide what *kind* of statement this locus supports, and say why."""
    classification = str(entry.get("classification"))
    if classification == NAO_TESTADO:
        return {
            "kind": NAO_INTERROGADO,
            "basis": "locus ausente do array; nada foi interrogado e nada pode ser afirmado",
        }
    if classification not in INTERPRETABLE:
        return {
            "kind": NAO_INTERROGADO,
            "basis": f"locus classificado {classification}: {entry.get('basis')}",
        }
    if classification == NAO_DETECTADO:
        return {
            "kind": NEGATIVO,
            "basis": (
                "alelo avaliado ausente no genótipo chamado; a afirmação negativa vale apenas "
                "para este locus e não para o gene nem para a condição"
            ),
        }

    # OBSERVADO carries two different facts and only one of them is presence. When the
    # registry named at least one base to test for, OBSERVADO means the genotype contains it.
    # When it named none, OBSERVADO means only "this locus was called" — the matrix says so
    # in its own basis — and everything below reads it as presence: it grades the genotype as
    # a pathogenic variant, calls a homozygous reference call "homozigoto para variante
    # patogênica", and marks the finding as requiring confirmation.
    #
    # On the first real array that fail-open produced 3.152 of 3.153 reported risk genotypes,
    # among them familial adenomatous polyposis in APC from a plain TT reference call. The
    # completeness classifier now tests the full alternate set, which resolves most of these
    # to a real NÃO DETECTADO; this refusal is the backstop for whatever the registry still
    # cannot name, and it fails closed by construction rather than by coverage.
    if not (entry.get("assessed_alleles") or entry.get("assessed_allele")):
        return {
            "kind": SEM_INTERPRETACAO,
            "basis": (
                "o registro não declara nenhuma base avaliada nesta coordenada, então o "
                "genótipo chamado não pode ser comparado: nem presença nem ausência da "
                f"variante é estabelecida ({entry.get('basis')}). O genótipo é reportado como "
                "observação, não como achado"
            ),
        }

    zygosity = _zygosity(entry.get("genotype"))
    if not clinvar["asserts_pathogenic"]:
        if clinvar.get("asserts_benign"):
            return {
                "kind": SEM_INTERPRETACAO,
                "basis": (
                    "o ClinVar classifica esta variante como benigna nesta coordenada; "
                    "presença do alelo não sustenta achado clínico"
                ),
            }
        return {
            "kind": PREDISPOSICAO if str(entry.get("scope")) == "PREDISPOSICAO" else SEM_INTERPRETACAO,
            "basis": (
                "o ClinVar não assere patogenicidade nesta coordenada "
                f"({', '.join(clinvar['classifications']) or 'sem classificação recuperada'}); "
                "o genótipo é reportado como observação, não como achado"
            ),
        }

    # Review level is checked before validity, because a single-submitter assertion in a
    # gene with Definitive validity is still a single-submitter assertion. Expanding the
    # registry to ClinVar's one-star tier multiplied the loci available; reading both tiers
    # the same way would have multiplied the findings just as fast.
    if not clinvar.get("meets_review_threshold"):
        return {
            "kind": ACHADO_PRELIMINAR if validity["established"] else SEM_INTERPRETACAO,
            "basis": (
                "o ClinVar assere patogenicidade nesta coordenada, mas com revisão de "
                f"{clinvar.get('review_stars', 0)} estrela(s) — abaixo das "
                f"{MIN_STARS_FOR_FINDING} exigidas. Uma asserção de submetente único é a "
                "opinião de um laboratório, não consenso curado, e não sustenta achado "
                "acionável nem estado de portador. Confirmação por método ortogonal e "
                "reavaliação quando o nível de revisão mudar."
            ),
        }

    if not validity["established"]:
        return {
            "kind": SEM_INTERPRETACAO,
            "basis": (
                "o ClinVar assere patogenicidade, mas nenhum dos registros curados — ClinGen, "
                "GenCC, PanelApp ou a curadoria de dosagem do ClinGen — estabelece a relação "
                "gene-doença "
                f"({', '.join(validity['classifications']) or 'sem curadoria'}); sem validade "
                "gene-doença estabelecida este sistema não converte a variante em achado clínico"
            ),
        }

    sources = " e ".join(validity["established_by"]) or "registro curado"

    def dossier_sex_clause() -> str:
        if sex_at_birth in (SEX_MALE, SEX_FEMALE):
            return f"o dossiê registra {sex_at_birth}"
        if sex_at_birth == SEX_INTERSEX:
            return (
                "o dossiê registra intersexo; esse valor não determina complemento "
                "cromossômico nem permite inferir hemizigose ou heterozigose"
            )
        if sex_at_birth == SEX_NOT_RECORDED:
            return (
                "o dossiê registra explicitamente que o sexo ao nascer não foi registrado"
            )
        return "o campo de sexo ao nascer está ausente do dossiê"

    matched = _matched_diseases(clinvar, validity)
    # The mode that applies is the one curated for the condition ClinVar names for *this*
    # variant. Only when no condition matches does the gene-level union stand in, and the
    # basis text says which of the two happened.
    if matched:
        modes = {entry["mode"] for entry in matched}
        condition_note = (
            "condição correspondente: " + ", ".join(sorted({str(e["disease"]) for e in matched}))
        )
    else:
        modes = set(validity["modes_of_inheritance"])
        condition_note = (
            "nenhuma condição do ClinVar coincide com uma doença curada para este gene; o modo "
            "de herança usado é a união do gene"
        )
    # X-linked before the autosomal branches, because on the X the same genotype means
    # different things in different people and the autosomal reading of "heterozygous" does
    # not apply. A male has one X: he is hemizygous, not a carrier, and a pathogenic variant
    # there is expressed. A female heterozygote is usually a carrier, but X-inactivation is
    # random and skewed inactivation does produce affected women, so she is never called
    # unaffected here.
    #
    # None of this can be decided from the genotype: this system does not call sex
    # chromosomes. It comes from the dossier, and without it the interpretation is refused
    # rather than defaulted — defaulting to female would call an affected boy a carrier.
    # A gene whose curated modes include X-linked *and* something else does not enter the
    # branch below, and the autosomal reading that follows never mentions the X at all. That
    # was silent for 107 established genes — ABCD1, BTK, ATP7A, AR among them — because the
    # ClinGen dosage reader turned haploinsufficiency into "AD" for X-linked genes too. The
    # reader is fixed at the source; this says the remaining case out loud instead of
    # letting a real XL/autosomal disagreement print as a generic "divergent mode".
    #
    # It deliberately does not resolve the disagreement. Picking the X-linked reading for a
    # male would decide he is affected rather than a carrier on the strength of one registry
    # disagreeing with another, which is the arbitration sections 4 and 7 forbid.
    if X_LINKED in modes and modes != {X_LINKED}:
        return {
            "kind": GENOTIPO_DE_RISCO,
            "basis": (
                f"variante patogênica em gene cujos modos curados divergem: "
                f"{', '.join(sorted(modes))} ({condition_note}). Um dos modos é ligado ao X, "
                "e no X o sexo ao nascer decide entre hemizigoto afetado e heterozigota "
                "portadora — "
                + dossier_sex_clause()
                + ", mas a divergência entre registros curados não é resolvida por este sistema"
                + ". Confirmação por método ortogonal e revisão da curadoria gene-doença "
                "antes de qualquer conduta"
            ),
        }
    if modes == {X_LINKED}:
        if sex_at_birth == SEX_MALE:
            return {
                "kind": ACIONAVEL,
                "basis": (
                    "variante patogênica em condição de herança ligada ao X segundo "
                    f"{sources} ({condition_note}), em pessoa registrada como do sexo "
                    "masculino ao nascer. Um único cromossomo X torna o genótipo "
                    "hemizigoto: não há segunda cópia para compensar, e o estado não é de "
                    "portador. Exige correlação clínica e confirmação por método ortogonal"
                ),
            }
        if sex_at_birth == SEX_FEMALE:
            return {
                "kind": PORTADOR if zygosity == "HETEROZIGOTO" else GENOTIPO_DE_RISCO,
                "basis": (
                    "variante patogênica em condição de herança ligada ao X segundo "
                    f"{sources} ({condition_note}), em pessoa registrada como do sexo "
                    "feminino ao nascer. "
                    + (
                        "Heterozigose no X costuma ser estado de portadora, mas a "
                        "inativação do X é aleatória e a inativação enviesada produz "
                        "mulheres afetadas — portadora não é sinônimo de não afetada"
                        if zygosity == "HETEROZIGOTO"
                        else (
                            "Genótipo homozigoto no X; exige correlação clínica"
                            if zygosity == "HOMOZIGOTO"
                            else (
                                "A zigosidade não foi determinada a partir desta chamada; "
                                "não se afirma heterozigose nem homozigose"
                            )
                        )
                    )
                ),
            }
        if sex_at_birth == SEX_INTERSEX:
            return {
                "kind": GENOTIPO_DE_RISCO,
                "basis": (
                    "variante patogênica em condição de herança ligada ao X segundo "
                    f"{sources} ({condition_note}); o dossiê registra intersexo. Esse registro "
                    "não determina complemento cromossômico, hemizigose ou heterozigose, e "
                    "este sistema não infere essas características do array. A interpretação "
                    "ligada ao X permanece indeterminada e exige correlação clínica"
                ),
            }
        if sex_at_birth == SEX_NOT_RECORDED:
            return {
                "kind": GENOTIPO_DE_RISCO,
                "basis": (
                    "variante patogênica em condição de herança ligada ao X segundo "
                    f"{sources} ({condition_note}); o dossiê registra explicitamente que o "
                    "sexo ao nascer não foi registrado. Sem essa informação, este sistema "
                    "não distingue hemizigose de heterozigose e mantém a interpretação "
                    "ligada ao X indeterminada"
                ),
            }
        return {
            "kind": GENOTIPO_DE_RISCO,
            "basis": (
                "variante patogênica em condição de herança ligada ao X segundo "
                f"{sources} ({condition_note}), mas o dossiê não registra o sexo ao nascer. "
                "No X o mesmo genótipo significa coisas diferentes — hemizigoto afetado ou "
                "heterozigota portadora — e este sistema não chama cromossomos sexuais. "
                "Preencha identification.sex_recorded_at_birth no dossiê para que a "
                "interpretação seja possível; assumir um dos dois chamaria um menino "
                "afetado de portador"
            ),
        }

    if zygosity == "HETEROZIGOTO":
        if modes == {AUTOSOMAL_RECESSIVE}:
            return {
                "kind": PORTADOR,
                "basis": (
                    "heterozigoto para variante patogênica em condição de herança autossômica "
                    f"recessiva segundo {sources} ({condition_note}); estado de portador não é "
                    "diagnóstico e em geral não produz fenótipo"
                ),
            }
        if modes == {AUTOSOMAL_DOMINANT}:
            return {
                "kind": ACIONAVEL,
                "basis": (
                    "heterozigoto para variante patogênica em condição de herança autossômica "
                    f"dominante segundo {sources} ({condition_note}); exige correlação clínica e "
                    "confirmação por método ortogonal"
                ),
            }
        # Two modes for the condition this variant is actually asserted for is a real
        # disagreement between registries or submitters. Picking one would decide whether
        # this person is a carrier or a patient, which sections 4 and 7 forbid arbitrating.
        return {
            "kind": GENOTIPO_DE_RISCO,
            "basis": (
                "heterozigoto para variante patogênica, mas o modo de herança curado é "
                f"divergente ou indeterminado ({', '.join(sorted(modes)) or 'não declarado'}); "
                f"{condition_note}. Portador e afetado não podem ser distinguidos, e a "
                "interpretação é recusada em vez de arbitrada"
            ),
        }
    if zygosity == "HOMOZIGOTO":
        return {
            "kind": GENOTIPO_DE_RISCO,
            "basis": (
                "homozigoto para variante patogênica em gene com relação gene-doença "
                f"estabelecida por {sources} ({condition_note}). Genótipo de risco, não "
                "diagnóstico: penetrância é incompleta em boa parte das condições relevantes, e "
                "a conclusão clínica depende de correlação fenotípica e confirmação ortogonal"
            ),
        }
    return {
        "kind": SEM_INTERPRETACAO,
        "basis": "genótipo chamado não é bialélico legível; zigosidade não determinada",
    }


def _registry_totals(evidence: dict[str, Any]) -> dict[str, Any]:
    """What the curated registry contains, independent of what this sample interrogated.

    The distinction is the whole point of a carrier-screening denominator. A count taken over
    the findings answers "how many genes did we look at", which is not a denominator; this
    answers "how many genes could have been looked at", which is.
    """
    validity = evidence.get("gene_validity") or {}
    computed = [_validity_for(gene, evidence) for gene in validity]
    established = [record for record in computed if record["established"]]

    def with_mode(mode: str) -> int:
        return sum(
            1
            for record in established
            if mode in set(record.get("modes_of_inheritance") or [])
        )

    return {
        "status": "VERIFICADO" if validity else UNAVAILABLE,
        "genes": len(validity),
        "genes_with_established_validity": len(established),
        "recessive_genes_established": with_mode(AUTOSOMAL_RECESSIVE),
        "dominant_genes_established": with_mode(AUTOSOMAL_DOMINANT),
        "x_linked_genes_established": with_mode(X_LINKED),
        "basis": (
            "contagem sobre todo o arquivo de evidência curada, não sobre os genes que esta "
            "amostra alcançou"
        ),
    }


def build_clinical_findings(
    completeness_path: Path,
    evidence_path: Path,
    assessed_alleles_path: Path,
    *,
    evaluated_at: str | None = None,
    sex_at_birth: str | None = None,
) -> dict[str, Any]:
    """Assemble the clinical join reports 01, 03 and 07 read from."""
    matrix = json.loads(Path(completeness_path).read_text(encoding="utf-8"))
    if matrix.get("schema") != "genoma-genome-completeness-matrix-v1":
        raise ValueError("completeness matrix schema mismatch")

    # Through the same content-sniffing reader the manifests use. The bulk evidence file is
    # 88 MB of JSON and ships compressed; reading it with `read_text` raised a
    # UnicodeDecodeError about byte 0x8b, which says nothing about the real cause and is why
    # the expanded evidence could not be made the default in the first place.
    evidence = json.loads(read_manifest_bytes(Path(evidence_path)))
    if evidence.get("schema") != "genoma-gene-disease-validity-v1":
        raise ClinicalEvidenceError(
            f"unsupported gene-disease evidence schema: {evidence.get('schema')!r}"
        )
    if not evidence.get("sources"):
        raise ClinicalEvidenceError("gene-disease evidence must cite its sources")

    assessed = json.loads(Path(assessed_alleles_path).read_text(encoding="utf-8"))
    allowed_by_rsid = _verified_accessions(assessed)

    # Normalised once, here, rather than at each comparison. A value the vocabulary does not
    # recognise becomes None and every X-linked locus is refused with a reason the operator
    # can act on — it never silently matches neither branch and lands in a generic bucket.
    sex = normalised_sex(sex_at_birth)
    if str(sex_at_birth or "").strip() and sex is None:
        raise ValueError(
            f"sex_at_birth {sex_at_birth!r} is outside the controlled case-dossier vocabulary"
        )

    by_rsid = {str(x["rsid"]).lower(): x for x in evidence.get("loci", [])}

    # Validity is computed once per gene and stored once. Copying it into every finding cost
    # 391 MB and 2.8 GB of peak memory on the 54,845-locus registry, because a gene with
    # hundreds of catalogued variants carried hundreds of identical copies of its ClinGen and
    # GenCC curations. Normalising loses nothing: every finding names its gene.
    validity_cache: dict[str, dict[str, Any]] = {}

    def validity_for(gene: Any) -> dict[str, Any]:
        key = str(gene or "")
        if key not in validity_cache:
            validity_cache[key] = _validity_for(gene, evidence)
        return validity_cache[key]

    findings: list[dict[str, Any]] = []
    for entry in matrix.get("entries", []):
        rsid = str(entry["rsid"]).lower()
        classification = str(entry.get("classification"))
        gene = entry.get("gene")
        interrogated = classification in INTERPRETABLE

        if not interrogated:
            # A locus the array never carried has nothing per-locus to say beyond its
            # identity and why it is out of reach. Its ClinVar records and its gene's
            # curations are unchanged in the evidence file, which this artifact names by
            # SHA-256 — the detail is normalised away, not dropped, and the omission is
            # stated rather than left for a reader to infer from a missing key.
            findings.append(
                {
                    "rsid": rsid,
                    "gene": gene,
                    "scope": entry.get("scope"),
                    "coverage_class": classification,
                    "coverage_basis": entry.get("basis"),
                    "genotype": None,
                    "genotype_withheld": bool(entry.get("genotype_withheld")),
                    "zygosity": None,
                    "assessed_allele": entry.get("assessed_allele"),
                    "interpretation": NAO_INTERROGADO,
                    # "not on the chip" and "on the chip but unusable in this sample" are
                    # different facts, and collapsing them would hide which of the two a
                    # missing answer came from.
                    "interpretation_basis": (
                        "locus não presente no array; nada foi interrogado e nada pode ser afirmado"
                        if classification == NAO_TESTADO
                        else f"locus classificado {classification}: {entry.get('basis')}"
                    ),
                    "detail_omitted": (
                        "registros do ClinVar e curadoria do gene não são repetidos para um "
                        "locus não interrogado; constam do arquivo de evidência citado por "
                        "SHA-256"
                    ),
                    "confirmation_required": False,
                }
            )
            continue

        locus_evidence = by_rsid.get(rsid, {})
        clinvar = _clinvar_for(rsid, locus_evidence, allowed_by_rsid.get(rsid, set()))
        validity = validity_for(gene)
        interpretation = _interpretation(entry, clinvar, validity, sex)
        findings.append(
            {
                "rsid": rsid,
                "gene": gene,
                "scope": entry.get("scope"),
                "coverage_class": classification,
                "coverage_basis": entry.get("basis"),
                "genotype": entry.get("genotype"),
                "genotype_withheld": bool(entry.get("genotype_withheld")),
                "zygosity": _zygosity(entry.get("genotype")),
                "assessed_allele": entry.get("assessed_allele"),
                "interpretation": interpretation["kind"],
                "interpretation_basis": interpretation["basis"],
                "clinvar": clinvar,
                "validity": validity,
                "gwas": locus_evidence.get("gwas") or {"status": UNAVAILABLE, "traits": []},
                "confirmation_required": interpretation["kind"]
                in (ACIONAVEL, ACHADO_PRELIMINAR, PORTADOR, GENOTIPO_DE_RISCO),
            }
        )

    kinds = (
        ACIONAVEL, ACHADO_PRELIMINAR, PORTADOR, GENOTIPO_DE_RISCO, PREDISPOSICAO,
        SEM_INTERPRETACAO, NEGATIVO, NAO_INTERROGADO,
    )
    now = evaluated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        # Never stronger than the matrix that supplied the genotypes.
        "operational_status": matrix.get("operational_status", UNAVAILABLE),
        **(
            {"qc_reservations": matrix["qc_reservations"]}
            if "qc_reservations" in matrix
            else {}
        ),
        "evaluated_at": now,
        "ruleset": normative.attested_ruleset_block(),
        # Registry-wide counts, over every gene the curated evidence carries — not only the
        # genes this sample happened to reach. Report 03 needs the second number to state a
        # carrier-screening denominator: without it the only available count is "genes with
        # an interrogated locus", which equals itself and prints as N of N.
        "registry": _registry_totals(evidence),
        "case_id": matrix.get("case_id"),
        # Recorded so a reader can tell an X-linked refusal caused by a missing dossier field
        # from one caused by the evidence. It comes from the dossier and is never inferred:
        # this system does not call sex chromosomes.
        "sex_recorded_at_birth": sex or UNAVAILABLE,
        "sex_source": "dossiê do caso" if sex else "não informado no dossiê",
        "input_sha256": matrix.get("input_sha256"),
        "completeness_matrix_sha256": matrix.get("sha256"),
        "evidence": {
            "sha256": evidence.get("sha256"),
            "curated_at": evidence.get("curated_at"),
            "sources": evidence.get("sources"),
            "clingen_file_created": evidence.get("clingen_file_created"),
        },
        "findings": findings,
        # Validity per gene, stored once. Findings for interrogated loci also carry their
        # gene's block inline so a reader following one finding does not have to resolve a
        # reference; findings for loci the array never carried point here instead.
        "gene_validity": {
            gene: block for gene, block in sorted(validity_cache.items()) if gene
        },
        "totals": {
            "loci": len(findings),
            **{f"kind_{kind}": sum(1 for f in findings if f["interpretation"] == kind) for kind in kinds},
            # Counted over the genes of the loci this run actually interrogated, since a gene
            # reached only by untested loci says nothing about this sample.
            "genes_interrogated": len(
                {f["gene"] for f in findings if f["gene"] and "validity" in f}
            ),
            "genes_with_established_validity": len(
                {f["gene"] for f in findings if f.get("validity", {}).get("established") and f["gene"]}
            ),
            "genes_without_established_validity": len(
                {
                    f["gene"]
                    for f in findings
                    if "validity" in f and not f["validity"]["established"] and f["gene"]
                }
            ),
            "genes_established_by_gencc_only": len(
                {
                    f["gene"]
                    for f in findings
                    if f.get("validity", {}).get("established_by") == ["GenCC"] and f["gene"]
                }
            ),
            "genes_established_by_panelapp_only": len(
                {
                    f["gene"]
                    for f in findings
                    if f.get("validity", {}).get("established_by") == ["PanelApp"] and f["gene"]
                }
            ),
            # Genes both GenCC and PanelApp carry. GenCC aggregates the PanelApp submissions,
            # so this is the count of genes where `established_by` lists two names for one
            # body of curation.
            "genes_where_panelapp_overlaps_gencc": len(
                {
                    f["gene"]
                    for f in findings
                    if f.get("validity", {}).get("panelapp_overlaps_gencc") and f["gene"]
                }
            ),
            "genes_with_gnomad_constraint": len(
                {
                    f["gene"]
                    for f in findings
                    if f.get("validity", {}).get("gnomad_constraint", {}).get("status")
                    == "VERIFICADO"
                    and f["gene"]
                }
            ),
            "genes_with_mode_of_inheritance_conflict": len(
                {
                    f["gene"]
                    for f in findings
                    if f.get("validity", {}).get("mode_of_inheritance_conflict") and f["gene"]
                }
            ),
            "loci_not_interrogated": sum(1 for f in findings if "detail_omitted" in f),
            "confirmation_required": sum(1 for f in findings if f["confirmation_required"]),
        },
        "interpretation_policy": (
            "Genótipo não é diagnóstico. Achado acionável exige variante com patogenicidade "
            "asserida no ClinVar na coordenada verificada E relação gene-doença estabelecida em "
            "nível Definitivo ou Forte pelo ClinGen ou pelo GenCC com submetentes independentes. "
            "Achado acionável e estado de portador exigem ainda revisão do ClinVar de duas "
            f"estrelas ou mais ({MIN_STARS_FOR_FINDING}+): submetente único é opinião de um "
            "laboratório, e o registro carrega também a camada de uma estrela. "
            "Estado de portador exige modo de herança autossômico recessivo curado e sem "
            "divergência entre fontes. Homozigose para variante patogênica é genótipo de risco, "
            "nunca condição estabelecida: penetrância é incompleta. Toda conclusão exige "
            "correlação clínica e confirmação por método ortogonal."
        ),
        "negative_statement_policy": matrix.get("negative_statement_policy", UNAVAILABLE),
        "limitations": [
            "Este documento é triagem por array, não sequenciamento; ausência de achado não exclui condição.",
            "Só as posições ensaiadas foram interrogadas; genes sem alvo no registro não foram avaliados em nenhum grau.",
            "Validade gene-doença ausente no ClinGen não significa relação falsa; significa ausência de curadoria por painel de especialistas.",
            "Classificação do ClinVar muda com o tempo; a data de avaliação de cada registro consta do achado.",
            "Nenhum achado aqui substitui avaliação clínica, aconselhamento genético ou confirmação por método ortogonal.",
        ],
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def write_findings(result: dict[str, Any], output: Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output
