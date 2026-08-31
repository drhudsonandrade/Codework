"""What produced these genotypes, in the words the reports print.

Every builder had the assay written into its prose as a constant: "Genotipagem em array não
produz DP/GQ/balanço alélico", "Call rate do array", "posições que este array ensaiou",
"locus não presente no arquivo do array". True of a SNP-array export, and false the moment the
same stack reads a table projected from a WGS VCF — which it now does.

Two of those sentences were not merely imprecise. "Genotipagem em array não produz DP, GQ nem
balanço alélico; não há profundidade de leitura a reportar" tells a clinician there is no
depth behind a call, and the projected table carries DP and GQ on every row. A report that
understates the evidence it holds is as wrong as one that overstates it, and this one did it
while explaining its own methods.

So the wording is read from the schema the QC artifact recorded, which is measured from the
input's header and never chosen by a caller. An unknown schema raises: a genotype table whose
provenance nothing describes must not be narrated with a borrowed sentence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class UnknownAssayError(Exception):
    """The QC artifact names a schema no report knows how to describe."""


@dataclass(frozen=True)
class Assay:
    """How one kind of genotype table should be described in a report."""

    schema: str
    #: Long form, for a sentence that introduces the method.
    name: str
    #: Short form, for a sentence that mentions it in passing.
    short: str
    #: Whether each call carries read depth and genotype quality.
    produces_read_depth: bool
    #: The methods sentence about per-call quality.
    depth_note: str
    #: Why a target the table says nothing about was not interrogated.
    absence_note: str
    #: Why absence of a finding cannot be read genome-wide.
    genome_wide_note: str
    #: What the coverage matrix is a coverage matrix *of*.
    coverage_subject: str
    #: Prefix for the run's own evidence ids (`{prefix}-input`, `{prefix}-qc`). The case
    #: manifest registered them as the literals `array-input`/`array-qc`, so a projection run
    #: cited "array" artifacts in the very attestations RULE_COVERAGE_GATE resolves.
    evidence_prefix: str
    #: `inputs[].kind` for the analysed file.
    input_kind: str
    #: `inputs[].source` for the analysed file.
    input_source: str
    #: The first step of the execution manifest.
    ingest_step: str
    #: The manifest's one-line summary of what the Scientific Data Plane did.
    plane_summary: str
    #: How the interrogated loci were established, for the capability matrix.
    assayed_loci_method: str
    #: Why CNV/SV/repeat expansions are NÃO DISPONÍVEL here.
    not_established_reason: str
    #: Why CYP2D6 diplotyping is NÃO DISPONÍVEL here. Same verdict for both assays, different
    #: reason: an array lacks the SNPs, a generic VCF lacks structure, hybrids and phase.
    cyp2d6_reason: str
    #: Why each variant class section 117 names is or is not established here. The capability
    #: matrix used to omit indel, mtDNA, KIR, noncoding and mosaicism entirely, so a negative
    #: conclusion had nothing to be scoped against for them — which is the false negative
    #: section 117 exists to prevent, achieved by leaving the row out.
    variant_class_reasons: dict[str, str]


ARRAY_DEPTH_NOTE = (
    "Genotipagem em array não produz DP, GQ nem balanço alélico; não há profundidade de "
    "leitura a reportar por locus."
)
ARRAY_GENOME_WIDE = (
    "Ausência genome-wide não é demonstrável a partir de genotipagem em array: o ensaio só "
    "interroga as posições presentes no chip."
)

PROJECTION_DEPTH_NOTE = (
    "Cada chamada projetada carrega a profundidade (DP) e a qualidade de genótipo (GQ) que o "
    "VCF de origem declara, e chamadas abaixo do limiar foram registradas como no-call com o "
    "motivo. O balanço alélico não é reportado: o VCF não o traz por locus."
)
PROJECTION_GENOME_WIDE = (
    "Ausência genome-wide não é demonstrável a partir desta projeção: ela cobre os alvos do "
    "registro curado, não o genoma inteiro, e um alvo sem registro no VCF e sem evidência de "
    "callability não foi interrogado."
)

#: Keyed by the class names `variant_class_coverage_explicit` checks for.
ARRAY_CLASS_REASONS = {
    "indel": "genotipagem em array chama SNPs em posições fixas; indels não são ensaiados",
    "mtDNA": "os marcadores mitocondriais do chip não sustentam heteroplasmia nem haplogrupo terminal",
    "KIR": "tipagem de KIR exige pipeline especializado sobre sequenciamento",
    "noncoding": "o array cobre marcadores catalogados, não regiões regulatórias",
    "mosaicism": "genotipagem em array reporta genótipos discretos, sem fração alélica",
    "SMN1_SMN2": "SMN1/SMN2 exigem dosagem de cópias, que o array não mede",
    "PMS2": "PMS2 exige discriminação de pseudogene por sequenciamento",
    "GBA1": "GBA1 exige discriminação de pseudogene por sequenciamento",
}

PROJECTION_CLASS_REASONS = {
    "indel": (
        "o VCF de origem pode conter indels e a tabela projetada expressa apenas SNV diploide; "
        "cada indel é registrado como no-call com o motivo, nunca omitido"
    ),
    "mtDNA": "a projeção cobre os alvos mitocondriais catalogados, sem profundidade ao longo do mtDNA",
    "KIR": "tipagem de KIR exige caller especializado sobre leituras alinhadas",
    "noncoding": "a projeção retém apenas os alvos do registro curado, não regiões regulatórias",
    "mosaicism": "a projeção não lê o campo AD e portanto não estima fração alélica",
    "SMN1_SMN2": "SMN1/SMN2 exigem dosagem de cópias, ausente de um VCF de variantes pequenas",
    "PMS2": "PMS2 exige caller que discrimine o pseudogene; o VCF genérico não basta",
    "GBA1": "GBA1 exige caller que discrimine o pseudogene; o VCF genérico não basta",
}

ARRAY_MANIFEST = {
    "evidence_prefix": "array",
    "input_kind": "snp-array-export",
    "input_source": "consumer genotyping export, harmonized",
    "ingest_step": "SNP-array ingest/QC",
    "plane_summary": (
        "SNP-array Scientific Data Plane executed for interrogated target loci only. Clinical "
        "interpretation remains bounded by assay coverage, current evidence and confirmation "
        "requirements."
    ),
    "assayed_loci_method": "SNP-array observation + QC",
    "not_established_reason": "not established by this SNP-array lane",
    "cyp2d6_reason": (
        "array SNPs are insufficient for structural/hybrid/copy-number diplotyping"
    ),
    "variant_class_reasons": ARRAY_CLASS_REASONS,
}

ASSAYS: dict[str, Assay] = {
    "harmonized_genera_myheritage_v1": Assay(
        schema="harmonized_genera_myheritage_v1",
        name="genotipagem em array SNP, export harmonizado de duas plataformas",
        short="array",
        produces_read_depth=False,
        depth_note=ARRAY_DEPTH_NOTE,
        absence_note="locus não presente no arquivo do array; nada foi interrogado",
        genome_wide_note=ARRAY_GENOME_WIDE,
        coverage_subject="cobertura do array",
        **ARRAY_MANIFEST,
    ),
    "raw_snp_array_v1": Assay(
        schema="raw_snp_array_v1",
        name="genotipagem em array SNP",
        short="array",
        produces_read_depth=False,
        depth_note=ARRAY_DEPTH_NOTE,
        absence_note="locus não presente no arquivo do array; nada foi interrogado",
        genome_wide_note=ARRAY_GENOME_WIDE,
        coverage_subject="cobertura do array",
        **ARRAY_MANIFEST,
    ),
    "wgs_vcf_projection_v1": Assay(
        schema="wgs_vcf_projection_v1",
        name="projeção de um VCF de sequenciamento completo sobre o registro curado de alvos",
        short="projeção do VCF",
        produces_read_depth=True,
        depth_note=PROJECTION_DEPTH_NOTE,
        absence_note=(
            "locus sem registro no VCF e sem bloco não-variante nem região chamável que o "
            "cubra; ausência num VCF não é referência, portanto nada foi interrogado aqui"
        ),
        genome_wide_note=PROJECTION_GENOME_WIDE,
        coverage_subject="cobertura desta projeção sobre o registro de alvos",
        evidence_prefix="projection",
        input_kind="wgs-vcf-projection",
        input_source="scripts/vcf_projection.py, VCF de WGS projetado sobre o registro de alvos",
        ingest_step="VCF projection ingest/QC",
        plane_summary=(
            "Projected-VCF Scientific Data Plane executed for the curated target loci only. "
            "The source VCF may cover the whole genome; this lane interprets the projected "
            "targets, and clinical interpretation remains bounded by that projection, by "
            "current evidence and by confirmation requirements."
        ),
        assayed_loci_method="projeção do VCF sobre o registro de alvos + QC",
        not_established_reason=(
            "not established by this lane: the projection reads SNV/indel calls at target "
            "loci and computes no copy-number, structural or repeat-length call"
        ),
        cyp2d6_reason=(
            "a generic VCF is insufficient for CYP2D6: structural variants, hybrid alleles "
            "and phase require a specialized haplotype workflow"
        ),
        variant_class_reasons=PROJECTION_CLASS_REASONS,
    ),
}


def assay_for_schema(schema: str | None) -> Assay:
    """The assay for a declared input schema, refusing one this project does not know.

    Refused rather than defaulted: the assay decides how the document describes how the
    genotype was obtained, and guessing would print a method that was never used.
    """
    try:
        return ASSAYS[str(schema)]
    except KeyError as exc:
        raise UnknownAssayError(
            f"schema {schema!r} não tem descrição de ensaio; um relatório que o narrasse "
            "emprestaria a frase de outro método"
        ) from exc


def assay_for(qc: dict[str, Any]) -> Assay:
    """Read the assay from a QC artifact's recorded input schema."""
    schema = (qc.get("input") or {}).get("schema") if isinstance(qc, dict) else None
    return assay_for_schema(schema)
