#!/usr/bin/env python3
"""Run one case end to end: QC, coverage, passport, clinical join, all payloads, all PDFs.

Ten builders invoked by hand, in the right order, with matching artifact paths, is the step
where a run quietly ends up mixing two cases — one stale matrix passed to one builder and the
report is about someone else. Every consumer here already refuses mismatched inputs by
comparing `input_sha256`, so the orchestrator cannot defeat those checks; what it removes is
the chance to get the order or the paths wrong in the first place.

Nothing is skipped silently. A builder that refuses is recorded with its reason and the run
continues, so one blocked report does not hide the nine that succeeded — and the exit status
reflects whether anything was blocked.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.clinical_findings import build_clinical_findings, write_findings
from array_pipeline.completeness import build_completeness_matrix, write_matrix
from array_pipeline.pharmacogenomics import build_pharmacogenomic_passport, write_passport

DEFAULT_TARGETS = ROOT / "config/partial_genome_annotation_targets.json"
DEFAULT_PGX_REGISTRY = ROOT / "config/pgx_allele_definitions.json"
DEFAULT_PGX_PANEL = ROOT / "config/pgx_panel_targets.json"
DEFAULT_EVIDENCE = ROOT / "docs/evidence/GENE_DISEASE_VALIDITY.json"
DEFAULT_ASSESSED = ROOT / "docs/evidence/ASSESSED_ALLELES_CLINVAR.json"
DEFAULT_ANCESTRY_PANEL = ROOT / "config/ancestry_reference_panel.json.gz"


def _step(results: dict[str, Any], name: str, fn: Callable[[], Any]) -> Any:
    """Run one step, recording a refusal rather than aborting the whole run."""
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - the refusal itself is the result
        results[name] = {
            "status": "BLOQUEADO",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=3),
        }
        return None
    results[name] = {"status": "OK"}
    return value


def run(
    input_path: Path,
    qc_path: Path,
    outdir: Path,
    *,
    targets: Path,
    pgx_registry: Path | None,
    pgx_panel: Path | None,
    evidence: Path | None,
    assessed: Path | None,
    ancestry_panel: Path | None,
    template_dir: Path | None,
    dossier: Path | None,
) -> dict[str, Any]:
    outdir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    payloads: dict[str, Path] = {}

    matrix_path = _step(
        results,
        "completeness-matrix",
        lambda: write_matrix(
            build_completeness_matrix(input_path, qc_path, targets), outdir / "completeness.json"
        ),
    )
    if matrix_path is None:
        return {"steps": results, "payloads": {}, "blocked": True}

    panel_matrix_path = None
    if pgx_panel and pgx_panel.is_file():
        panel_matrix_path = _step(
            results,
            "pgx-panel-matrix",
            lambda: write_matrix(
                build_completeness_matrix(input_path, qc_path, pgx_panel),
                outdir / "panel-matrix.json",
            ),
        )

    passport_path = _step(
        results,
        "pgx-passport",
        lambda: write_passport(
            build_pharmacogenomic_passport(
                matrix_path,
                targets,
                pgx_registry_path=pgx_registry,
                panel_matrix_path=panel_matrix_path,
            ),
            outdir / "passport.json",
        ),
    )

    findings_path = None
    if evidence and evidence.is_file() and assessed and assessed.is_file():
        findings_path = _step(
            results,
            "clinical-findings",
            lambda: write_findings(
                build_clinical_findings(matrix_path, evidence, assessed),
                outdir / "clinical-findings.json",
            ),
        )
    else:
        results["clinical-findings"] = {
            "status": "BLOQUEADO",
            "error": "arquivo de evidência gene-doença ou de alelos avaliados ausente; "
            "gerar com scripts/curate_gene_disease.py e scripts/curate_assessed_alleles.py",
        }

    def payload(report_id: str, fn: Callable[[], dict]) -> None:
        out = outdir / f"payload-{report_id}.json"
        built = _step(results, f"payload-{report_id}", lambda: fn())
        if built is None:
            return
        out.write_text(
            json.dumps(built, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        payloads[report_id] = out
        results[f"payload-{report_id}"]["operational_status"] = built["operational_status"]

    from scripts.build_completeness_report import build_payload as p09
    from scripts.build_one_page_summary import build_payload as p10
    from scripts.build_pharmacogenomic_report import build_payload as p06
    from scripts.build_technical_report import build_payload as p05

    payload("05", lambda: p05(qc_path, matrix_path))
    if passport_path:
        payload("06", lambda: p06(passport_path, matrix_path))
    payload("09", lambda: p09(matrix_path, qc_path))
    if passport_path:
        payload("10", lambda: p10(matrix_path, passport_path))

    if findings_path:
        from scripts.build_association_report import build_payload as passoc
        from scripts.build_clinical_report import build_payload as p01
        from scripts.build_reproductive_report import build_payload as p03

        payload("01", lambda: p01(findings_path, matrix_path, qc_path))
        payload("03", lambda: p03(findings_path, matrix_path))
        for report_id in ("04", "07", "08"):
            payload(report_id, (lambda rid: lambda: passoc(rid, findings_path, matrix_path))(report_id))

    from scripts.build_ancestry_report import build_payload as p02

    # The ancestry panel is optional: without it report 02 measures feasibility, with it the
    # case is projected. Passing it here means one command produces either, and the report
    # states which mode it was in.
    payload(
        "02",
        lambda: p02(
            matrix_path,
            qc_path,
            panel_path=ancestry_panel if ancestry_panel and ancestry_panel.is_file() else None,
            input_path=input_path if ancestry_panel and ancestry_panel.is_file() else None,
        ),
    )

    if template_dir and template_dir.is_dir():
        from scripts.build_editorial_guide import analyse, build_payload as p11, render
        from reporting.editorial_v3 import _verified_coordinate_manifest

        def guide() -> dict:
            manifest, _hashes = _verified_coordinate_manifest(template_dir)
            rows = analyse(manifest)
            return p11(rows, manifest, render(rows, manifest))

        payload("11", guide)

        from scripts.render_report_pdfs import render as render_pdf

        pdf_dir = outdir / "pdf"
        pdf_dir.mkdir(exist_ok=True)
        for report_id, path in sorted(payloads.items()):
            _step(
                results,
                f"pdf-{report_id}",
                (lambda rid, p: lambda: render_pdf(
                    rid, p, template_dir, pdf_dir / f"GENOMA-{rid}.pdf", dossier
                ))(report_id, path),
            )

    blocked = [name for name, r in results.items() if r["status"] != "OK"]
    return {
        "steps": results,
        "payloads": {k: str(v) for k, v in sorted(payloads.items())},
        "blocked": blocked,
        "blocked_count": len(blocked),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="SNP-array CSV/gz/zip")
    parser.add_argument("--qc", required=True, help="array-qc.json from array_pipeline.qc")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--targets", default=str(DEFAULT_TARGETS))
    parser.add_argument("--pgx-registry", default=str(DEFAULT_PGX_REGISTRY))
    parser.add_argument("--pgx-panel", default=str(DEFAULT_PGX_PANEL))
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--assessed-alleles", default=str(DEFAULT_ASSESSED))
    parser.add_argument(
        "--ancestry-panel",
        default=str(DEFAULT_ANCESTRY_PANEL),
        help="population reference panel; without it report 02 measures feasibility only",
    )
    parser.add_argument("--template-dir", help="installed v3.0 template pack; renders PDFs")
    parser.add_argument("--dossier", help="case dossier JSON, bound to the analysed case")
    args = parser.parse_args()

    result = run(
        Path(args.input),
        Path(args.qc),
        Path(args.outdir),
        targets=Path(args.targets),
        pgx_registry=Path(args.pgx_registry) if args.pgx_registry else None,
        pgx_panel=Path(args.pgx_panel) if args.pgx_panel else None,
        evidence=Path(args.evidence) if args.evidence else None,
        assessed=Path(args.assessed_alleles) if args.assessed_alleles else None,
        ancestry_panel=Path(args.ancestry_panel) if args.ancestry_panel else None,
        template_dir=Path(args.template_dir) if args.template_dir else None,
        dossier=Path(args.dossier) if args.dossier else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["blocked"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
