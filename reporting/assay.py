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
    ),
}


def assay_for_schema(schema: str | None) -> Assay:
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
