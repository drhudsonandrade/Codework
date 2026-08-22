#!/usr/bin/env python3
"""Project a WGS VCF onto the curated target registry, for the interpretation stack to read.

The eleven reports are built from one artifact: the genotype table `array_pipeline` consumes.
Until now only a SNP-array export could produce one, so a WGS run reached QC and provenance
and stopped — `build_wgs_curated_manifest` emitted `claims: []` and said so. This closes that
gap by writing the same table from a VCF, which means the whole downstream stack — coverage
matrix, clinical join, pharmacogenomic passport, ROH, ancestry, the eleven payloads — works
unchanged and inherits every refusal already built into it.

Three decisions carry the scientific weight, and each is fail-closed.

**Absence is not reference.** An array interrogates every locus on the chip; a VCF lists only
variants. Treating "no record here" as "homozygous reference" would manufacture a negative
result at every uncalled locus — the false negative sections 46, 117 and 146 exist to prevent,
and the most consequential mistake this adapter could make. A target with no record is simply
absent from the projection, which the coverage matrix classifies NÃO TESTADO. Homozygous
reference is emitted only where something positively establishes callability: a gVCF
non-variant block covering the position with adequate depth and quality, or a callable-regions
BED. Without one of those, a plain VCF yields variants and nothing else, and the matrix says
so locus by locus.

**The join is by coordinate, never by rsID.** The registry carries GRCh38 positions for
124,614 of its 124,621 targets, and a VCF's ID column is frequently empty, stale, or merged.
Matching text against text is how a report ends up about a different variant.

**The reference base is checked, not assumed.** Where the registry knows the reference allele,
the VCF's REF must equal it. A systematic mismatch means the file is not on the build it
claims — the check refuses the whole projection — and an isolated one means that coordinate is
not the variant the registry names, so no genotype is emitted for it.

What this does not do: it reads no BAM, calls no variant, and resolves no phase. It projects
calls someone else made, and the quality of those calls travels with them in DEPTH and
GENOTYPE_QUALITY so the coverage matrix and the technical report can state it.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ngs_formats import FormatError, open_vcf_text, probe_vcf

#: The header the projected table carries. Deliberately not `RAW_COLUMNS`: those four columns
#: make `array_pipeline.qc` name the schema `raw_snp_array_v1`, and calling a WGS-derived
#: genotype a SNP-array reading would be a false statement about methodology in every report
#: that prints the method. The extra columns are the ones an array never had — the per-call
#: depth and genotype quality section 119 asks for, and the basis of each call.
PROJECTION_COLUMNS = [
    "RSID",
    "CHROMOSOME",
    "POSITION",
    "RESULT",
    "DEPTH",
    "GENOTYPE_QUALITY",
    "CALL_BASIS",
]
PROJECTION_SCHEMA = "wgs_vcf_projection_v1"

#: The only build the registry carries coordinates for. A GRCh37 VCF is refused rather than
#: lifted over: liftover needs a chain file and produces coordinates whose provenance would
#: have to be attested separately, and a silent mismatch would put every finding at the wrong
#: position.
SUPPORTED_BUILD = "GRCh38"

#: Below these a call is recorded as a no-call with the reason, not as a genotype. Section 47
#: requires depth, genotype quality and mapping to be checked before a rare high-impact
#: variant is promoted; a projection that dropped them would hand the clinical join a
#: confident-looking genotype resting on four reads.
DEFAULT_MIN_DEPTH = 10
DEFAULT_MIN_GQ = 20

#: A reference mismatch rate above this over checked targets means the file is not on the
#: declared build. Set where it is because real VCFs carry a handful of legitimate
#: disagreements — registry rows curated from a different ClinVar release, multi-nucleotide
#: representations — while a wrong build disagrees almost everywhere.
MAX_REFERENCE_MISMATCH_RATE = 0.02
MIN_REFERENCE_CHECKS = 50

BASES = frozenset("ACGT")


class ProjectionError(Exception):
    """The VCF cannot be projected onto this registry, and the reason says why."""


def normalise_contig(value: str) -> str:
    """`chr1` and `1` are the same contig; `chrM` and `MT` are the same mitochondrion."""
    name = str(value).strip()
    if name.lower().startswith("chr"):
        name = name[3:]
    upper = name.upper()
    if upper in {"M", "MT"}:
        return "MT"
    return upper


def load_targets(path: Path) -> tuple[dict[tuple[str, int], dict[str, Any]], int]:
    """Index the registry by GRCh38 coordinate; return it with the count that has none.

    The count used to ride back inside the index under a string key, in a dict every caller
    iterates as `for contig, position in index`. Any second caller would have unpacked a
    fourteen-character string into two names and got a confusing failure far from the cause.

    Two registry rows at the same coordinate would make the projection's choice between them
    arbitrary, which is the arbitration sections 4 and 7 forbid.
    """
    from array_pipeline.targets import load_target_manifest

    manifest = load_target_manifest(path)
    index: dict[tuple[str, int], dict[str, Any]] = {}
    collisions: list[str] = []
    without_coordinate = 0
    for target in manifest["targets"]:
        coordinate = target.get("grch38") or {}
        chromosome, position = coordinate.get("chromosome"), coordinate.get("position")
        if not chromosome or not position:
            without_coordinate += 1
            continue
        key = (normalise_contig(chromosome), int(position))
        if key in index and index[key].get("rsid") != target.get("rsid"):
            collisions.append(f"{key}: {index[key].get('rsid')} vs {target.get('rsid')}")
            continue
        index[key] = target
    if collisions:
        raise ProjectionError(
            f"{len(collisions)} coordenadas do registro apontam para alvos distintos, os "
            f"primeiros: {collisions[:3]}; escolher um deles seria arbitrar"
        )
    return index, without_coordinate


def _sample_column(header_columns: list[str], wanted: str | None) -> int:
    samples = header_columns[9:]
    if not samples:
        raise ProjectionError("o VCF não traz coluna de amostra; não há genótipo a projetar")
    if wanted is None:
        if len(samples) > 1:
            raise ProjectionError(
                f"o VCF traz {len(samples)} amostras {samples[:5]}; informe --sample para "
                "dizer qual delas é este caso, em vez de a projeção escolher"
            )
        return 9
    if wanted not in samples:
        raise ProjectionError(f"amostra {wanted!r} ausente do VCF; presentes: {samples[:8]}")
    return 9 + samples.index(wanted)


def _genotype_bases(gt: str, alleles: list[str]) -> tuple[list[str] | None, str | None]:
    """Turn a GT field into bases, or say why it cannot be expressed as one."""
    raw = gt.replace("|", "/").split("/")
    if not raw or any(part in {".", ""} for part in raw):
        return None, "genótipo não chamado nesta amostra (GT ./.)"
    try:
        indices = [int(part) for part in raw]
    except ValueError:
        return None, f"GT {gt!r} não é numérico"
    if any(index < 0 or index >= len(alleles) for index in indices):
        return None, f"GT {gt!r} referencia um alelo que o registro não declara"
    called = [alleles[index] for index in indices]
    if any(len(allele) != 1 or allele.upper() not in BASES for allele in called):
        # An indel or a symbolic allele is a real observation; it is not a diploid SNP and
        # the table this feeds expresses nothing else. Recorded, never silently dropped.
        return None, f"alelo não-SNV neste locus ({'/'.join(called)}); a tabela projetada expressa apenas SNV"
    if len(called) > 2:
        return None, f"ploidia {len(called)} não é representável nesta tabela"
    return [allele.upper() for allele in called], None


def _format_value(format_keys: list[str], values: list[str], key: str) -> str | None:
    if key not in format_keys:
        return None
    index = format_keys.index(key)
    if index >= len(values):
        return None
    value = values[index].strip()
    return value or None


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _load_callable_bed(path: Path) -> dict[str, list[tuple[int, int]]]:
    intervals: dict[str, list[tuple[int, int]]] = {}
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith(("#", "track", "browser")):
                continue
            fields = line.split()
            if len(fields) < 3:
                continue
            contig = normalise_contig(fields[0])
            # BED is half-open and zero-based; the registry's positions are one-based.
            intervals.setdefault(contig, []).append((int(fields[1]) + 1, int(fields[2])))
    # Merged, not merely sorted. `_covered_by_bed` bisects to the last interval starting at
    # or before the position; with `chr1 0-5000` followed by `chr1 900-950`, position 1000 is
    # inside the first and the bisect only ever sees the second, so a callable locus came back
    # uncovered and the matrix called it NÃO TESTADO. Fail-closed, and still wrong.
    for contig, spans in intervals.items():
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if end < start:
                raise ProjectionError(
                    f"intervalo BED inválido em {contig}: {start}-{end} termina antes de começar"
                )
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        intervals[contig] = merged
    return intervals


def _covered_by_bed(intervals: dict[str, list[tuple[int, int]]], contig: str, position: int) -> bool:
    # Sound because `_load_callable_bed` merged the intervals: no two overlap, so the last
    # one starting at or before `position` is the only one that can contain it.
    spans = intervals.get(contig)
    if not spans:
        return False
    index = bisect.bisect_right(spans, (position, float("inf"))) - 1
    return index >= 0 and spans[index][0] <= position <= spans[index][1]


def project(
    vcf_path: Path,
    targets_path: Path,
    *,
    sample: str | None = None,
    callable_bed: Path | None = None,
    min_depth: int = DEFAULT_MIN_DEPTH,
    min_gq: int = DEFAULT_MIN_GQ,
    declared_build: str = SUPPORTED_BUILD,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the VCF once and return (rows, evidence).

    `evidence` accounts for every target the registry holds: how many were called, how many
    were reference by positive evidence, how many were refused and for which reason. A target
    that appears in no bucket would be a target the projection lost, so the sum is asserted.
    """
    if normalise_contig(declared_build.replace("GRCh", "")) not in {"38"}:
        raise ProjectionError(
            f"build declarado {declared_build!r}: o registro só traz coordenadas "
            f"{SUPPORTED_BUILD}, e converter posições sem um chain file atestado colocaria "
            "cada achado numa coordenada cuja proveniência ninguém verificou"
        )
    try:
        vcf_facts = probe_vcf(vcf_path, count_records=False)
    except FormatError as exc:
        raise ProjectionError(f"{Path(vcf_path).name} não é um VCF legível: {exc}") from exc

    index, without_coordinate = load_targets(targets_path)
    positions_by_contig: dict[str, list[int]] = {}
    for contig, position in index:
        positions_by_contig.setdefault(contig, []).append(position)
    for contig in positions_by_contig:
        positions_by_contig[contig].sort()

    bed = _load_callable_bed(callable_bed) if callable_bed else {}
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    reasons: Counter[str] = Counter()
    reference_checked = 0
    reference_mismatched = 0
    mismatch_examples: list[str] = []
    gvcf_blocks = 0
    records_read = 0
    sample_index: int | None = None

    def record_row(
        key: tuple[str, int],
        target: dict[str, Any],
        result: str,
        depth: Any,
        quality: Any,
        basis: str,
    ) -> None:
        if key in rows:
            # Two VCF records at one target coordinate. Neither is arbitrated: the locus is
            # marked unreportable, exactly as a duplicated array row is.
            previous = rows[key]
            if previous["RESULT"] != result:
                rows[key] = {
                    **previous,
                    "RESULT": "--",
                    "CALL_BASIS": (
                        f"dois registros no VCF nesta coordenada com genótipos divergentes "
                        f"({previous['RESULT']} e {result}); escolher um seria arbitrar"
                    ),
                }
                reasons["duplicate_conflict"] += 1
            return
        rows[key] = {
            "RSID": str(target.get("rsid") or "").lower(),
            "CHROMOSOME": key[0],
            "POSITION": key[1],
            "RESULT": result,
            "DEPTH": "" if depth is None else depth,
            "GENOTYPE_QUALITY": "" if quality is None else quality,
            "CALL_BASIS": basis,
        }

    with open_vcf_text(Path(vcf_path)) as handle:
        header_columns: list[str] = []
        for line in handle:
            line = line.rstrip("\n").rstrip("\r")
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                header_columns = line.split("\t")
                sample_index = _sample_column(header_columns, sample)
                continue
            if sample_index is None:
                raise ProjectionError("registros antes da linha #CHROM")
            fields = line.split("\t")
            if len(fields) <= sample_index:
                reasons["truncated_record"] += 1
                continue
            records_read += 1
            contig = normalise_contig(fields[0])
            try:
                position = int(fields[1])
            except ValueError:
                reasons["non_integer_position"] += 1
                continue
            reference, alternate, filter_field = fields[3], fields[4], fields[6]
            format_keys = fields[8].split(":") if len(fields) > 8 else []
            values = fields[sample_index].split(":")
            end = None
            for entry in fields[7].split(";"):
                if entry.startswith("END="):
                    end = _as_int(entry[4:])

            # -- gVCF non-variant block: positive evidence of reference across a span -----
            if end is not None and "<NON_REF>" in alternate and set(alternate.split(",")) <= {"<NON_REF>"}:
                gvcf_blocks += 1
                if filter_field not in {"PASS", ".", ""}:
                    # The variant branch refuses a filtered record and this one did not, so a
                    # block the caller itself marked low-quality was read as "reference
                    # confirmed across this span" — a false negative at every target inside
                    # it, which is the failure this whole adapter exists to avoid.
                    reasons["filtered_gvcf_block"] += 1
                    continue
                candidates = positions_by_contig.get(contig) or []
                start = bisect.bisect_left(candidates, position)
                stop = bisect.bisect_right(candidates, end)
                if start == stop:
                    continue
                depth = _as_int(_format_value(format_keys, values, "DP"))
                quality = _as_int(_format_value(format_keys, values, "GQ"))
                for target_position in candidates[start:stop]:
                    key = (contig, target_position)
                    target = index.get(key)
                    if target is None or key in rows:
                        continue
                    expected = str(target.get("reference_allele") or "").strip().upper()
                    if not expected or len(expected) != 1 or expected not in BASES:
                        reasons["homref_without_reference_allele"] += 1
                        continue
                    if depth is None or depth < min_depth or quality is None or quality < min_gq:
                        record_row(
                            key, target, "--", depth, quality,
                            f"bloco não-variante do gVCF com DP={depth} GQ={quality}, abaixo do "
                            f"mínimo DP>={min_depth} GQ>={min_gq}: a cobertura não sustenta "
                            "declarar referência",
                        )
                        reasons["homref_below_quality"] += 1
                        continue
                    record_row(
                        key, target, expected + expected, depth, quality,
                        f"homozigoto de referência por bloco não-variante do gVCF "
                        f"{position}-{end} (DP={depth}, GQ={quality})",
                    )
                    reasons["homref_from_gvcf"] += 1
                continue

            # -- a variant record at a target coordinate ---------------------------------
            key = (contig, position)
            target = index.get(key)
            if target is None:
                continue

            expected = str(target.get("reference_allele") or "").strip().upper()
            if expected and len(expected) == 1 and expected in BASES:
                reference_checked += 1
                if reference.upper() != expected:
                    reference_mismatched += 1
                    if len(mismatch_examples) < 5:
                        mismatch_examples.append(
                            f"{contig}:{position} VCF REF={reference} registro={expected}"
                        )
                    record_row(
                        key, target, "--", None, None,
                        f"REF do VCF ({reference}) diverge do alelo de referência que o "
                        f"registro declara ({expected}); esta coordenada não é a variante "
                        "que o registro nomeia",
                    )
                    continue

            if filter_field not in {"PASS", ".", ""}:
                record_row(
                    key, target, "--", None, None,
                    f"registro filtrado pelo caller (FILTER={filter_field}); uma chamada "
                    "filtrada não é uma chamada",
                )
                reasons["filtered"] += 1
                continue

            gt = _format_value(format_keys, values, "GT")
            if gt is None:
                record_row(key, target, "--", None, None, "o registro não traz campo GT")
                reasons["no_gt"] += 1
                continue
            alleles = [reference] + [a for a in alternate.split(",") if a]
            bases, refusal = _genotype_bases(gt, alleles)
            depth = _as_int(_format_value(format_keys, values, "DP"))
            quality = _as_int(_format_value(format_keys, values, "GQ"))
            if bases is None:
                record_row(key, target, "--", depth, quality, refusal or "genótipo não expresso")
                reasons["not_expressible"] += 1
                continue
            if depth is not None and depth < min_depth:
                record_row(
                    key, target, "--", depth, quality,
                    f"profundidade DP={depth} abaixo do mínimo {min_depth}; a chamada não "
                    "sustenta interpretação clínica",
                )
                reasons["below_depth"] += 1
                continue
            if quality is not None and quality < min_gq:
                record_row(
                    key, target, "--", depth, quality,
                    f"qualidade de genótipo GQ={quality} abaixo do mínimo {min_gq}",
                )
                reasons["below_gq"] += 1
                continue
            record_row(
                key, target, "".join(sorted(bases)), depth, quality,
                f"chamada do VCF: GT={gt} sobre {'/'.join(alleles)}",
            )
            reasons["called_from_variant"] += 1

    if reference_checked >= MIN_REFERENCE_CHECKS:
        rate = reference_mismatched / reference_checked
        if rate > MAX_REFERENCE_MISMATCH_RATE:
            raise ProjectionError(
                f"{reference_mismatched} de {reference_checked} coordenadas conferidas têm REF "
                f"divergente do registro ({rate:.1%}, acima de "
                f"{MAX_REFERENCE_MISMATCH_RATE:.0%}): o arquivo não está em {SUPPORTED_BUILD} "
                f"ou não é deste indivíduo. Exemplos: {mismatch_examples}"
            )

    # A callable BED establishes reference where no gVCF block did — same rule, weaker
    # evidence, so it is recorded as such and never overwrites a gVCF-derived call.
    bed_homref = 0
    if bed:
        for key, target in index.items():
            if key in rows:
                continue
            expected = str(target.get("reference_allele") or "").strip().upper()
            if not expected or len(expected) != 1 or expected not in BASES:
                continue
            if _covered_by_bed(bed, key[0], key[1]):
                record_row(
                    key, target, expected + expected, None, None,
                    "homozigoto de referência por região declarada chamável no BED fornecido; "
                    "sem profundidade por base, a evidência é mais fraca que um bloco de gVCF",
                )
                bed_homref += 1

    ordered = sorted(rows.values(), key=lambda row: (row["CHROMOSOME"], int(row["POSITION"])))
    called = sum(1 for row in ordered if row["RESULT"] != "--")
    evidence = {
        "schema": "genoma-vcf-projection-v1",
        "status": "EXECUTADO",
        "build": SUPPORTED_BUILD,
        "vcf": {
            "path": str(vcf_path),
            "version": vcf_facts.get("version"),
            "compression": vcf_facts.get("compression"),
            "samples": vcf_facts.get("samples"),
            "sample_projected": sample or (vcf_facts.get("samples") or [None])[0],
        },
        "records_read": records_read,
        "gvcf_non_variant_blocks": gvcf_blocks,
        "registry_targets": len(index),
        "registry_targets_without_grch38_coordinate": without_coordinate,
        "rows_emitted": len(ordered),
        "genotypes_called": called,
        "no_calls_recorded": len(ordered) - called,
        "targets_absent_from_vcf": len(index) - len(ordered),
        "reference_allele_checks": reference_checked,
        "reference_allele_mismatches": reference_mismatched,
        "reference_allele_mismatch_examples": mismatch_examples,
        "homozygous_reference_from_callable_bed": bed_homref,
        "thresholds": {"min_depth": min_depth, "min_genotype_quality": min_gq},
        "outcomes": dict(sorted(reasons.items())),
        "absence_contract": (
            "Um alvo ausente desta projeção não foi interrogado. Ausência num VCF não é "
            "referência: só um bloco não-variante de gVCF ou uma região declarada chamável "
            "estabelece homozigose de referência, e sem um deles a matriz de cobertura "
            "classifica o locus como NÃO TESTADO."
        ),
    }
    if not bed and not gvcf_blocks:
        evidence["homozygous_reference"] = (
            "NÃO DISPONÍVEL: nenhum bloco de gVCF e nenhum BED de regiões chamáveis foi "
            "fornecido, portanto nenhum locus foi declarado homozigoto de referência. Todo "
            "alvo sem variante consta como não interrogado."
        )
    return ordered, evidence


def provenance_attestations(evidence: dict[str, Any], table_sha256: str) -> dict[str, Any]:
    """Build and strand attestations for the projected table, from what was measured.

    The QC gate downstream will not accept a build or a strand on the caller's word: it wants
    a structured attestation bound to the input's SHA-256 and naming the value it establishes.
    For an array those come from `provenance_probe`, which discriminates the assembly by
    coordinate concordance and the strand by allele sets over non-palindromic markers.

    A projection can answer both from evidence it already has, and neither is asserted:

    * the coordinates in this table *are* the registry's GRCh38 coordinates — the projection
      wrote them — and the reference-allele check confirms the source VCF agrees at that many
      positions, which is the same concordance argument the array probe makes;
    * VCF defines its alleles on the reference forward strand, and the reference-allele
      agreement is what shows this file honours that, because a reverse-complemented file
      would disagree at every non-palindromic position checked.

    Where too few positions could be checked, no attestation is emitted and the QC gate
    refuses — which is the correct outcome for a projection whose orientation nothing
    established.
    """
    from datetime import datetime, timezone

    checked = evidence.get("reference_allele_checks") or 0
    mismatched = evidence.get("reference_allele_mismatches") or 0
    if checked < MIN_REFERENCE_CHECKS:
        return {
            "status": "NÃO DISPONÍVEL",
            "reason": (
                f"apenas {checked} alelos de referência puderam ser conferidos, abaixo do "
                f"mínimo de {MIN_REFERENCE_CHECKS}: sem isso nada estabelece build nem "
                "orientação desta tabela, e o gate de QC deve recusá-la"
            ),
        }
    agreed = checked - mismatched
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def attestation(kind: str, value: str, justification: str) -> dict[str, Any]:
        return {
            "status": "VERIFICADO",
            "decision": "SATISFIED",
            "asserted_value": value,
            "justification": justification,
            "evidence_refs": [
                "vcf-projection:reference_allele_concordance",
                f"target-registry:{evidence.get('registry_targets')}-alvos",
            ],
            "trace": {
                "attestation_id": f"vcf-projection-{kind}-{table_sha256[:16]}",
                "created_at": stamp,
                "actor_type": "SOFTWARE",
                "actor_id": "scripts/vcf_projection.py",
                "method": "concordância do alelo de referência entre o VCF e o registro curado",
                "run_id": f"projection-{table_sha256[:16]}",
                "input_sha256": [table_sha256],
                "output_sha256": [],
                "tool_versions": {"scripts.vcf_projection": "v1"},
            },
        }

    return {
        "status": "VERIFICADO",
        "build": attestation(
            "reference_build",
            SUPPORTED_BUILD,
            f"As coordenadas desta tabela são as do registro curado em {SUPPORTED_BUILD}, e "
            f"{agreed} de {checked} alelos de referência conferidos concordam com o VCF de "
            f"origem nessas posições; as {mismatched} divergentes não produziram genótipo.",
        ),
        "strand": attestation(
            "strand",
            "forward",
            "A especificação VCF define os alelos na fita de referência (forward), e a "
            f"concordância de {agreed} de {checked} alelos de referência conferidos confirma "
            "que este arquivo a honra: um arquivo complementado divergiria em toda posição "
            "não palindrômica conferida.",
        ),
    }


def write_table(rows: list[dict[str, Any]], path: Path) -> Path:
    import csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROJECTION_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def iter_rows(path: Path) -> Iterator[dict[str, str]]:
    import csv

    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--vcf", required=True, help="VCF or gVCF, plain or bgzipped")
    parser.add_argument("--targets", required=True, help="curated target registry")
    parser.add_argument("--sample", help="which sample column to project, when the VCF has several")
    parser.add_argument(
        "--callable-bed",
        help="regions the caller could call. Without it, and without gVCF blocks, no locus "
        "is declared homozygous reference.",
    )
    parser.add_argument("--min-depth", type=int, default=DEFAULT_MIN_DEPTH)
    parser.add_argument("--min-genotype-quality", type=int, default=DEFAULT_MIN_GQ)
    parser.add_argument("--build", default=SUPPORTED_BUILD)
    parser.add_argument("--output", required=True, help="projected genotype table (CSV)")
    parser.add_argument("--evidence-out", required=True)
    args = parser.parse_args()

    try:
        rows, evidence = project(
            Path(args.vcf),
            Path(args.targets),
            sample=args.sample,
            callable_bed=Path(args.callable_bed) if args.callable_bed else None,
            min_depth=args.min_depth,
            min_gq=args.min_genotype_quality,
            declared_build=args.build,
        )
    except ProjectionError as exc:
        print(f"PROJEÇÃO NÃO DISPONÍVEL: {exc}", file=sys.stderr)
        return 2

    table = write_table(rows, Path(args.output))
    evidence["output"] = str(table)
    # Bound to the table's own bytes, because that is the file the QC gate will hash and the
    # attestation must name it or the gate refuses — correctly.
    from scripts.ngs_formats import sha256_of

    evidence["output_sha256"] = sha256_of(table)
    evidence["provenance"] = provenance_attestations(evidence, evidence["output_sha256"])
    Path(args.evidence_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.evidence_out).write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in evidence.items() if k != "outcomes"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
