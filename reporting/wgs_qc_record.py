"""The WGS quality-control record sections 6 and 114 require before disease interpretation.

Two sections of the ruleset are unconditional obligations that a VCF cannot answer by itself:

* **§6** — "AUDITORIA OBRIGATÓRIA QUANDO O WGS FOR ENVIADO / Antes de interpretar doenças,
  realizar QC completo", followed by a list that includes sequencing platform, read length,
  mean depth, coverage distribution, %≥10×/20×/30×, exon coverage, Ti/Tv, heterozygosity,
  SNV/indel/CNV/SV counts, chromosomal sex, mtDNA and contamination. A projected VCF carries
  per-call DP and GQ at the interrogated targets and nothing else on that list.
* **§114** — "Registrar sempre se o DNA veio de: sangue; saliva; swab bucal; outro tecido.
  Isso é obrigatório para interpretar mosaicismo, CHIP, heteroplasmia, contaminação e
  variantes somáticas incidentais." A VCF does not name the biological material.

Neither is qualified by "quando possível", so neither can be discharged the way §0 and §254
discharge an absent capability. The honest state of a VCF-only run is that §6 is applicable
and unmet, and RULE_COVERAGE_GATE refuses — which is correct, and would leave the lane
permanently unable to publish.

So the operator supplies the missing measurements as a record, and this module refuses one
that does not actually carry them. Three properties make it evidence rather than a form:

1. **Bound to the bytes.** `vcf_sha256` must equal the digest of the file being interpreted.
   A QC report from another sample, or from an earlier run of the same lab, certifies that
   other sample.
2. **No silent gaps.** Every required metric is present or explicitly `NÃO DISPONÍVEL` with a
   reason. A missing key is refused, so "we did not measure contamination" has to be written
   down rather than achieved by omission.
3. **Ranges are checked.** A depth of -1 or a percentage of 300 is refused. This catches
   transcription errors; it cannot catch a laboratory that reports a number it did not
   measure, and nothing in a file could.

What this module deliberately does *not* do is grade the metrics. It does not decide that
30× is enough or that 2% contamination is too much: that judgement belongs to the person
reading the report, and encoding a threshold here would turn an operator's measurement into
this project's clinical opinion.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "genoma-wgs-qc-record-v1"

#: The evidence id the run registers for this record, and the id the section curation cites.
WGS_QC_ARTIFACT = "wgs-qc-report"

UNAVAILABLE = "NÃO DISPONÍVEL"

#: §114's vocabulary, verbatim from the section.
ALLOWED_MATERIAL = ("SANGUE", "SALIVA", "SWAB BUCAL", "OUTRO TECIDO")

#: §6 asks whether the run was paired-end or single-end; there is no third answer.
ALLOWED_LAYOUT = ("PAIRED-END", "SINGLE-END")

#: Who the record is about and what it is bound to. Without these the record is a set of
#: numbers with no subject.
REQUIRED_IDENTITY = (
    "case_id",
    "vcf_sha256",
    "laboratory",
    "report_date",
    "captured_by",
    "source",
)

#: Every §6 determination, with the closed interval a real measurement falls in. `None` as a
#: bound means unbounded on that side. Each may instead be the explicit-unavailable form.
REQUIRED_METRICS: dict[str, tuple[float | None, float | None, str]] = {
    "mean_depth": (0, 100_000, "profundidade média"),
    "pct_bases_10x": (0, 100, "percentual de bases ≥10×"),
    "pct_bases_20x": (0, 100, "percentual de bases ≥20×"),
    "pct_bases_30x": (0, 100, "percentual de bases ≥30×"),
    "pct_exons_20x": (0, 100, "cobertura dos éxons ≥20×"),
    "pct_clinical_genes_20x": (0, 100, "cobertura de genes clinicamente importantes ≥20×"),
    "heterozygosity_rate": (0, 1, "taxa de heterozigosidade"),
    "ti_tv": (0, 10, "razão Ti/Tv"),
    "snv_count": (0, None, "número de SNVs"),
    "indel_count": (0, None, "número de indels"),
    "cnv_count": (0, None, "número de CNVs"),
    "sv_count": (0, None, "número de SVs"),
    "mtdna_mean_depth": (0, 1_000_000, "profundidade média do mtDNA"),
    "contamination_estimate": (0, 1, "estimativa de contaminação"),
}

#: Determinations that are categorical rather than numeric.
REQUIRED_CATEGORICAL = {
    "biological_material": ALLOWED_MATERIAL,
    "read_layout": ALLOWED_LAYOUT,
}

#: Free-text determinations §6 asks for. Empty is refused; the explicit-unavailable form is
#: accepted, because "the VCF header does not name the platform" is a real answer.
REQUIRED_TEXT = ("sequencing_platform", "read_length", "reference_build", "pipeline_version")


class WgsQcError(Exception):
    """The record cannot stand as the section-6 audit, and the message says why."""


def _is_unavailable(value: Any) -> bool:
    """The explicit form: `{"status": "NÃO DISPONÍVEL", "reason": "..."}`."""
    return (
        isinstance(value, dict)
        and value.get("status") == UNAVAILABLE
        and bool(str(value.get("reason") or "").strip())
    )


def _is_finite_number(value: Any) -> bool:
    """One predicate for "this is a measurement", used by validation and by the summary.

    They disagreed. `validate_record` rejected a non-finite metric, but `audit_summary`
    counted anything `isinstance(value, (int, float))` as measured — and JSON integers are
    arbitrary precision, so `mean_depth = 10**400` came back NÃO DISPONÍVEL *and* was listed
    among the laboratory's measurements. A reader would see a count that includes a value the
    record itself refused. `math.isfinite` raises OverflowError on such an int, which is why
    the call is guarded rather than trusted.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _unavailable_problem(key: str, value: Any) -> str | None:
    """Why this looks like an unavailable marker but is not a usable one."""
    if not isinstance(value, dict):
        return None
    if value.get("status") != UNAVAILABLE:
        return (
            f"{key}: um objeto aqui só é aceito na forma "
            f'{{"status": "{UNAVAILABLE}", "reason": "..."}}; recebido {value!r}'
        )
    if not str(value.get("reason") or "").strip():
        return (
            f"{key}: declarado {UNAVAILABLE} sem motivo; a seção 6 exige a determinação ou a "
            "razão pela qual ela não foi feita"
        )
    return None


def validate_record(
    record: Any,
    *,
    case_id: str | None = None,
    vcf_sha256: str | None = None,
) -> list[str]:
    """Every problem with the record, or an empty list. Raises nothing; the caller decides."""
    problems: list[str] = []
    if not isinstance(record, dict):
        return ["o registro de QC de WGS não é um objeto JSON"]
    if record.get("schema") != SCHEMA:
        problems.append(f"o registro não declara o schema {SCHEMA!r}")

    for key in REQUIRED_IDENTITY:
        value = record.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{key}: obrigatório e deve ser texto não vazio")

    declared_sha = str(record.get("vcf_sha256") or "").strip().lower()
    if declared_sha and (len(declared_sha) != 64 or not all(c in "0123456789abcdef" for c in declared_sha)):
        problems.append("vcf_sha256: não é um SHA-256 hexadecimal de 64 caracteres")
    if vcf_sha256 is not None and declared_sha and declared_sha != str(vcf_sha256).lower():
        # The whole point: a QC report is about one file's sample.
        problems.append(
            f"vcf_sha256: o registro certifica {declared_sha!r} e este run interpreta "
            f"{str(vcf_sha256).lower()!r}; são amostras distintas"
        )
    if case_id is not None and str(record.get("case_id") or "") != str(case_id):
        problems.append(
            f"case_id: o registro é do caso {record.get('case_id')!r} e este run é "
            f"{case_id!r}"
        )

    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        problems.append("metrics: obrigatório e ausente")
        metrics = {}

    for key, (low, high, label) in REQUIRED_METRICS.items():
        if key not in metrics:
            problems.append(f"metrics.{key} ({label}): ausente; a seção 6 exige esta determinação")
            continue
        value = metrics[key]
        marker = _unavailable_problem(f"metrics.{key}", value)
        if marker:
            problems.append(marker)
            continue
        if _is_unavailable(value):
            continue
        if not _is_finite_number(value):
            problems.append(f"metrics.{key} ({label}): {value!r} não é um número finito")
            continue
        if low is not None and value < low:
            problems.append(f"metrics.{key} ({label}): {value} abaixo de {low}")
        if high is not None and value > high:
            problems.append(f"metrics.{key} ({label}): {value} acima de {high}")

    for key, allowed in REQUIRED_CATEGORICAL.items():
        value = record.get(key)
        marker = _unavailable_problem(key, value)
        if marker:
            problems.append(marker)
            continue
        if _is_unavailable(value):
            if key == "biological_material":
                # §114 says "registrar sempre"; it has no unavailable branch, and the fields
                # it feeds — mosaicism, CHIP, heteroplasmy, contamination — cannot be read
                # without it.
                problems.append(
                    "biological_material: a seção 114 exige sempre o material biológico "
                    f"({', '.join(ALLOWED_MATERIAL)}); não há forma {UNAVAILABLE} para ele"
                )
            continue
        if value not in allowed:
            problems.append(f"{key}: {value!r} fora do vocabulário {list(allowed)}")

    for key in REQUIRED_TEXT:
        value = record.get(key)
        marker = _unavailable_problem(key, value)
        if marker:
            problems.append(marker)
            continue
        if _is_unavailable(value):
            continue
        if not str(value or "").strip():
            problems.append(f"{key}: obrigatório; informe o valor ou a forma {UNAVAILABLE}")

    coverage_map = record.get("reliability_map")
    if not isinstance(coverage_map, dict):
        problems.append(
            "reliability_map: a seção 6 exige o MAPA DE CONFIABILIDADE DO GENOMA classificando "
            "regiões como alta confiança, confiança moderada, baixa cobertura, mapeamento "
            "difícil ou não resolvidas"
        )
    else:
        for band in ("alta_confianca", "confianca_moderada", "baixa_cobertura",
                     "mapeamento_dificil", "nao_resolvidas"):
            value = coverage_map.get(band)
            marker = _unavailable_problem(f"reliability_map.{band}", value)
            if marker:
                problems.append(marker)
                continue
            if _is_unavailable(value):
                continue
            if not isinstance(value, str) or not value.strip():
                problems.append(
                    f"reliability_map.{band}: obrigatório; informe o valor ou a forma "
                    f"{UNAVAILABLE}"
                )
    return problems


def load_record(
    path: Path | str,
    *,
    case_id: str | None = None,
    vcf_sha256: str | None = None,
) -> dict[str, Any]:
    """Read and validate, or raise with every problem at once."""
    source = Path(path)
    try:
        record = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WgsQcError(f"registro de QC de WGS ilegível em {source}: {exc}") from exc
    problems = validate_record(record, case_id=case_id, vcf_sha256=vcf_sha256)
    if problems:
        raise WgsQcError(
            f"o registro de QC de WGS em {source} não sustenta a auditoria da seção 6:\n  - "
            + "\n  - ".join(problems)
        )
    return record


def audit_summary(record: dict[str, Any]) -> dict[str, Any]:
    """What the manifest and the report print about the section-6 audit.

    Counts what was measured and what was declared unavailable, so a reader sees the shape of
    the audit without reading the record — and so a record where most of §6 is `NÃO
    DISPONÍVEL` cannot look like a complete one.
    """
    problems = validate_record(record)
    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
    measured = sorted(k for k in REQUIRED_METRICS if _is_finite_number(metrics.get(k)))
    unavailable = sorted(k for k in REQUIRED_METRICS if _is_unavailable(metrics.get(k)))
    return {
        "schema": SCHEMA,
        "status": UNAVAILABLE if problems else "VERIFICADO",
        "problems": problems,
        "laboratory": record.get("laboratory"),
        "report_date": record.get("report_date"),
        "vcf_sha256": record.get("vcf_sha256"),
        "biological_material": record.get("biological_material"),
        "sequencing_platform": record.get("sequencing_platform"),
        "read_layout": record.get("read_layout"),
        "read_length": record.get("read_length"),
        "pipeline_version": record.get("pipeline_version"),
        "measured": measured,
        "not_measured": unavailable,
        "measured_count": len(measured),
        "required_count": len(REQUIRED_METRICS),
        "basis": (
            f"auditoria da seção 6 sobre o VCF {str(record.get('vcf_sha256'))[:16]}…: "
            f"{len(measured)} de {len(REQUIRED_METRICS)} determinações medidas pelo laboratório "
            f"{record.get('laboratory')!r} e {len(unavailable)} declaradas {UNAVAILABLE} com "
            "motivo. As métricas são do laboratório; este pipeline as registra e não as "
            "recalcula, porque não recebeu leituras."
        ),
    }
