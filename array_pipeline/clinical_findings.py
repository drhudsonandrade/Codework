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
from array_pipeline.targets import sha256_json

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


def _clinvar_for(
    rsid: str,
    locus_evidence: dict[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    """ClinVar records for this locus, restricted to coordinate-verified accessions."""
    records = [
        record
        for record in (locus_evidence.get("clinvar") or {}).get("records", [])
        if str(record.get("accession")) in allowed
    ]
    discarded = len((locus_evidence.get("clinvar") or {}).get("records", [])) - len(records)
    if not records:
        return {
            "status": UNAVAILABLE,
            "records": [],
            "classifications": [],
            "conditions": [],
            "asserts_pathogenic": False,
            "reason": (
                "nenhum registro do ClinVar recuperado por rsid coincide com um acesso já "
                f"verificado na coordenada deste alvo ({discarded} descartados); a junção é por "
                "coordenada, nunca por texto"
            ),
        }
    classifications = sorted({str(r.get("classification")) for r in records})
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
        "accessions_discarded_by_coordinate": discarded,
    }


def _validity_for(gene: str | None, evidence: dict[str, Any]) -> dict[str, Any]:
    """Gene–disease validity and mode of inheritance, from whichever registry established it.

    ClinGen and GenCC are read as two registries, not one: `established_by` says which
    carried the gene, because "Definitive by a ClinGen expert panel" and "Strong by two
    clinical laboratories in GenCC" are the same word for different weights and a report
    that hides the difference is overstating one of them.
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
    # `established` is recomputed from the curations rather than read from the evidence
    # file's own summary field, for the same reason `provenance_blockers` recomputes its
    # status floor: a stored aggregate that disagrees with the records it summarises would
    # be followed rather than caught, and here it decides whether a variant becomes a
    # clinical finding.
    established_by = [
        name
        for name, present in (("ClinGen", established_clingen), ("GenCC", established_gencc))
        if present
    ]

    def diseases_with(mode: str) -> list[str]:
        return sorted(
            {
                str(c["disease"])
                for c in established_clingen
                if str(c.get("mode_of_inheritance")) == mode and c.get("disease")
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
        ),
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

    if not validity["established"]:
        return {
            "kind": SEM_INTERPRETACAO,
            "basis": (
                "o ClinVar assere patogenicidade, mas nem o ClinGen nem o GenCC estabelecem a "
                "relação gene-doença em nível Definitivo ou Forte "
                f"({', '.join(validity['classifications']) or 'sem curadoria'}); sem validade "
                "gene-doença estabelecida este sistema não converte a variante em achado clínico"
            ),
        }

    sources = " e ".join(validity["established_by"]) or "registro curado"
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


def build_clinical_findings(
    completeness_path: Path,
    evidence_path: Path,
    assessed_alleles_path: Path,
    *,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    """Assemble the clinical join reports 01, 03 and 07 read from."""
    matrix = json.loads(Path(completeness_path).read_text(encoding="utf-8"))
    if matrix.get("schema") != "genoma-genome-completeness-matrix-v1":
        raise ValueError("completeness matrix schema mismatch")

    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    if evidence.get("schema") != "genoma-gene-disease-validity-v1":
        raise ClinicalEvidenceError(
            f"unsupported gene-disease evidence schema: {evidence.get('schema')!r}"
        )
    if not evidence.get("sources"):
        raise ClinicalEvidenceError("gene-disease evidence must cite its sources")

    assessed = json.loads(Path(assessed_alleles_path).read_text(encoding="utf-8"))
    allowed_by_rsid = _verified_accessions(assessed)

    by_rsid = {str(x["rsid"]).lower(): x for x in evidence.get("loci", [])}

    findings: list[dict[str, Any]] = []
    for entry in matrix.get("entries", []):
        rsid = str(entry["rsid"]).lower()
        locus_evidence = by_rsid.get(rsid, {})
        clinvar = _clinvar_for(rsid, locus_evidence, allowed_by_rsid.get(rsid, set()))
        validity = _validity_for(entry.get("gene"), evidence)
        interpretation = _interpretation(entry, clinvar, validity)
        findings.append(
            {
                "rsid": rsid,
                "gene": entry.get("gene"),
                "scope": entry.get("scope"),
                "coverage_class": entry.get("classification"),
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
                in (ACIONAVEL, PORTADOR, GENOTIPO_DE_RISCO),
            }
        )

    kinds = (
        ACIONAVEL, PORTADOR, GENOTIPO_DE_RISCO, PREDISPOSICAO,
        SEM_INTERPRETACAO, NEGATIVO, NAO_INTERROGADO,
    )
    now = evaluated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        # Never stronger than the matrix that supplied the genotypes.
        "operational_status": matrix.get("operational_status", UNAVAILABLE),
        "evaluated_at": now,
        "ruleset": normative.attested_ruleset_block(),
        "case_id": matrix.get("case_id"),
        "input_sha256": matrix.get("input_sha256"),
        "completeness_matrix_sha256": matrix.get("sha256"),
        "evidence": {
            "sha256": evidence.get("sha256"),
            "curated_at": evidence.get("curated_at"),
            "sources": evidence.get("sources"),
            "clingen_file_created": evidence.get("clingen_file_created"),
        },
        "findings": findings,
        "totals": {
            "loci": len(findings),
            **{f"kind_{kind}": sum(1 for f in findings if f["interpretation"] == kind) for kind in kinds},
            "genes_with_established_validity": len(
                {f["gene"] for f in findings if f["validity"]["established"] and f["gene"]}
            ),
            "genes_without_established_validity": len(
                {f["gene"] for f in findings if not f["validity"]["established"] and f["gene"]}
            ),
            "genes_established_by_gencc_only": len(
                {f["gene"] for f in findings if f["validity"]["established_by"] == ["GenCC"] and f["gene"]}
            ),
            "genes_with_mode_of_inheritance_conflict": len(
                {f["gene"] for f in findings if f["validity"]["mode_of_inheritance_conflict"] and f["gene"]}
            ),
            "confirmation_required": sum(1 for f in findings if f["confirmation_required"]),
        },
        "interpretation_policy": (
            "Genótipo não é diagnóstico. Achado acionável exige variante com patogenicidade "
            "asserida no ClinVar na coordenada verificada E relação gene-doença estabelecida em "
            "nível Definitivo ou Forte pelo ClinGen ou pelo GenCC com submetentes independentes. "
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
