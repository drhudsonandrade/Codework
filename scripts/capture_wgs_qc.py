#!/usr/bin/env python3
"""Capture the laboratory's WGS quality-control report as the record sections 6 and 114 need.

The operator transcribes what the laboratory measured. This script does not invent a metric
and has no flag that marks the record verified: a record is usable when it carries the
determinations, and refused when it does not. The `--vcf` it is bound to is hashed here, so
the binding is measured rather than typed.

A determination the laboratory did not make is written as `NÃO DISPONÍVEL` with a reason, via
`--unavailable metric=motivo`. That is a real answer to section 6; leaving the key out is not,
and is refused.

    python3 scripts/capture_wgs_qc.py \\
      --case-id CASO-001 --vcf caso.vcf.gz \\
      --laboratory "Dante Labs" --report-date 2026-08-01 \\
      --source "relatório de QC em PDF entregue com o WGS 30x" \\
      --captured-by "operador" \\
      --material SANGUE --layout PAIRED-END \\
      --platform "Illumina NovaSeq 6000" --read-length "2x150" \\
      --reference-build GRCh38 --pipeline-version "Dante v3" \\
      --metric mean_depth=32.4 --metric pct_bases_10x=98.1 ... \\
      --unavailable contamination_estimate="não estimada pelo laboratório" \\
      --reliability alta_confianca="92.4% do genoma" ... \\
      --output evidence/wgs-qc-record.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.wgs_qc_record import (
    ALLOWED_LAYOUT,
    ALLOWED_MATERIAL,
    REQUIRED_METRICS,
    SCHEMA,
    UNAVAILABLE,
    validate_record,
)

RELIABILITY_BANDS = (
    "alta_confianca",
    "confianca_moderada",
    "baixa_cobertura",
    "mapeamento_dificil",
    "nao_resolvidas",
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pairs(values: list[str] | None, flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in values or []:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise SystemExit(f"{flag} espera chave=valor, recebido {item!r}")
        out[key.strip()] = value.strip()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--vcf", required=True, help="o VCF que este QC certifica; será hasheado")
    parser.add_argument("--laboratory", required=True)
    parser.add_argument("--report-date", required=True, help="data do relatório do laboratório")
    parser.add_argument("--source", required=True, help="de onde estes números foram transcritos")
    parser.add_argument("--captured-by", required=True)
    parser.add_argument("--material", required=True, choices=list(ALLOWED_MATERIAL))
    parser.add_argument("--layout", required=True, choices=list(ALLOWED_LAYOUT))
    parser.add_argument("--platform", required=True)
    parser.add_argument("--read-length", required=True)
    parser.add_argument("--reference-build", required=True)
    parser.add_argument("--pipeline-version", required=True)
    parser.add_argument(
        "--metric", action="append", metavar="CHAVE=VALOR",
        help=f"uma das: {', '.join(sorted(REQUIRED_METRICS))}",
    )
    parser.add_argument(
        "--unavailable", action="append", metavar="CHAVE=MOTIVO",
        help=f"marca a determinação como {UNAVAILABLE} com o motivo",
    )
    parser.add_argument(
        "--reliability", action="append", metavar="FAIXA=DESCRICAO",
        help=f"mapa de confiabilidade; faixas: {', '.join(RELIABILITY_BANDS)}",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    vcf = Path(args.vcf)
    if not vcf.is_file():
        raise SystemExit(f"VCF não encontrado: {vcf}")

    metrics: dict[str, Any] = {}
    for key, raw in _pairs(args.metric, "--metric").items():
        if key not in REQUIRED_METRICS:
            raise SystemExit(f"--metric {key!r} não é uma determinação da seção 6")
        try:
            metrics[key] = float(raw) if "." in raw or "e" in raw.lower() else int(raw)
        except ValueError:
            raise SystemExit(f"--metric {key}={raw!r} não é um número") from None
    for key, reason in _pairs(args.unavailable, "--unavailable").items():
        if key not in REQUIRED_METRICS:
            raise SystemExit(f"--unavailable {key!r} não é uma determinação da seção 6")
        if key in metrics:
            raise SystemExit(f"{key} foi informado como valor e como {UNAVAILABLE}")
        if not reason:
            raise SystemExit(f"--unavailable {key} exige o motivo")
        metrics[key] = {"status": UNAVAILABLE, "reason": reason}

    reliability = _pairs(args.reliability, "--reliability")
    unknown = sorted(set(reliability) - set(RELIABILITY_BANDS))
    if unknown:
        raise SystemExit(f"--reliability com faixas desconhecidas: {unknown}")

    record = {
        "schema": SCHEMA,
        "case_id": args.case_id,
        "vcf_sha256": sha256_of(vcf),
        "vcf_filename": vcf.name,
        "laboratory": args.laboratory,
        "report_date": args.report_date,
        "source": args.source,
        "captured_by": args.captured_by,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "biological_material": args.material,
        "read_layout": args.layout,
        "sequencing_platform": args.platform,
        "read_length": args.read_length,
        "reference_build": args.reference_build,
        "pipeline_version": args.pipeline_version,
        "metrics": metrics,
        "reliability_map": reliability,
        "note": (
            "Transcrição do QC do laboratório. Este pipeline não recebeu leituras e portanto "
            "não recalcula nenhuma destas métricas; ele as registra, vincula ao SHA-256 do VCF "
            "interpretado e as publica como medidas do laboratório."
        ),
    }

    problems = validate_record(record, case_id=args.case_id, vcf_sha256=record["vcf_sha256"])
    if problems:
        print("REGISTRO NÃO ACEITO:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"registro de QC de WGS escrito em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
