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

import os
import subprocess

from array_pipeline.clinical_findings import build_clinical_findings, write_findings
from array_pipeline.completeness import build_completeness_matrix, write_matrix
from array_pipeline.homozygosity import analyse_array as analyse_homozygosity
from array_pipeline.pharmacogenomics import build_pharmacogenomic_passport, write_passport

# The widest registry, not the twenty-nine hand-curated loci: a registry is only an expansion
# if the default run uses it, and leaving the defaults pointing at the small one would ship a
# system that *can* interrogate 124,621 loci and interrogates 29.
#
# The default admits ClinVar's one-star tier, which is where most of that width comes from.
# That is safe only because the interpretation grades by review level rather than by
# membership: a single-submitter assertion is capped at ACHADO PRELIMINAR and can never
# become an actionable or carrier finding. On a representative array the split is 93
# preliminary to 20 actionable, so the tier is visible in the output rather than blended into
# it. The two-star pair remains selectable with --targets/--evidence for a run that should
# only ever see curated consensus.
DEFAULT_TARGETS = ROOT / "config/targets_merged_panel_1star.json.gz"
DEFAULT_PGX_REGISTRY = ROOT / "config/pgx_allele_definitions.json"
DEFAULT_PGX_PANEL = ROOT / "config/pgx_panel_targets.json"
DEFAULT_EVIDENCE = ROOT / "docs/evidence/GENE_DISEASE_VALIDITY_1STAR.json.gz"
DEFAULT_ASSESSED = ROOT / "docs/evidence/ASSESSED_ALLELES_CLINVAR.json"
DEFAULT_ANCESTRY_PANEL = ROOT / "config/ancestry_reference_panel.json.gz"


def evaluate_policy(
    input_path: Path,
    qc_path: Path,
    outdir: Path,
    *,
    consent: Path | None,
    witness: Path | None = None,
) -> tuple[Path | None, str]:
    """Run the policy engine on this case and return its evaluation.

    This entrypoint had no policy plane at all: it produced every report from its own
    builders, each of which granted itself the verdict. The audit called that a second
    execution authority, and it was — the engine was never asked, so it could never disagree.

    It is asked here. The refusal a caller now sees is the engine's, with its reasons, rather
    than the absence of one; and when the engine cannot be run the evaluation is simply
    missing, which `PayloadCompiler` already treats as "no authorisation".
    """
    annotation = outdir / "annotation.json"
    manifest = outdir / "case-manifest.json"
    evaluation = outdir / "policy-evaluation.json"
    ruleset_dir = outdir / "normative"
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/annotate_partial_genome.py"),
             "--input", str(input_path), "--qc", str(qc_path),
             "--mode", "plan-only", "--output", str(annotation)],
            check=True, capture_output=True, text=True,
        )
        command = [sys.executable, str(ROOT / "scripts/build_array_case_manifest.py"),
                   "--qc", str(qc_path), "--annotation", str(annotation),
                   "--output", str(manifest)]
        if consent is not None:
            command += ["--consent", str(consent)]
        if witness is not None:
            command += ["--post-deployment-witness", str(witness)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/materialize_ruleset.py"),
             "--output-dir", str(ruleset_dir)],
            check=True, capture_output=True, text=True,
        )
        canonical = next(ruleset_dir.glob("REGRAS_PROJETO_GENOMA_VIGENTE_*.txt"))
        environment = {
            **os.environ,
            "GENOMA_RULESET_PATH": str(canonical),
            "GENOMA_RULESET_SHA_MANIFEST": str(ROOT / "manifests/RULESET_V3.4.sha256"),
            "PYTHONPATH": str(ROOT / "policy_engine"),
        }
        completed = subprocess.run(
            [sys.executable, "-m", "genoma_policy", "evaluate", str(manifest),
             "--output", str(evaluation)],
            env=environment, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, OSError, StopIteration) as exc:
        return None, f"BLOQUEADO: {type(exc).__name__}: {exc}"
    finally:
        # The plaintext ruleset is materialised only for the duration of the evaluation.
        for stale in ruleset_dir.glob("REGRAS_PROJETO_GENOMA_VIGENTE_*.txt"):
            stale.unlink(missing_ok=True)

    if not evaluation.is_file():
        return None, f"BLOQUEADO: policy engine produced no evaluation ({completed.stderr.strip()[:200]})"
    verdict = json.loads(evaluation.read_text(encoding="utf-8"))
    blocking = [
        g for g in verdict.get("gates", [])
        if isinstance(g, dict) and g.get("blocking") and g.get("state") != "PASS"
    ]
    detail = "; ".join(
        f"{g['gate']}: {'; '.join(str(r) for r in (g.get('reasons') or [])[:2])}" for g in blocking
    )
    return evaluation, (
        "READY" if verdict.get("ready_for_requested_operation") is True
        else f"NÃO AUTORIZADO pelo policy engine — {detail or 'sem razão registrada'}"
    )


def _write_json(payload: dict[str, Any], path: Path) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


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
    probe_path: Path | None = None,
    consent: Path | None = None,
    post_deployment_witness: Path | None = None,
) -> dict[str, Any]:
    outdir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    payloads: dict[str, Path] = {}

    # The POST-DEPLOYMENT witness is resolved first because both authorities need it: the
    # policy engine, whose POST_DEPLOYMENT_GATE reads the claim the witness backs, and every
    # report builder, whose payload prints the verdict. One file, named once, handed to both —
    # otherwise the engine and the report can disagree about the same deployment.
    #
    # Deliberately *not* recorded in `results`: a run without a witness is not a blocked run.
    # It produces every payload correctly, each stating POST-DEPLOYMENT PENDENTE, which is the
    # true state of a system with no deployed service. Recording it as a failed step would
    # make the honest outcome look like a broken pipeline.
    witness_path = post_deployment_witness
    if witness_path is not None and not witness_path.is_file():
        raise FileNotFoundError(f"testemunha de pós-implantação não encontrada: {witness_path}")
    witness_state: dict[str, Any] = (
        {"status": "OK", "path": str(witness_path)}
        if witness_path is not None
        else {
            "status": "PENDENTE",
            "path": None,
            "reason": "nenhuma testemunha fornecida; os relatórios declaram POST-DEPLOYMENT "
            "PENDENTE. Produzir uma exige scripts/run_live_post_deployment_smoke.py contra "
            "um serviço implantado",
        }
    )

    # Asked before anything is compiled, so every builder receives the same verdict and none
    # of them composes one. A missing or refusing evaluation does not stop the measurements —
    # the matrix, the passport and the clinical join are facts about the file either way — it
    # stops publication, which is the decision the engine owns.
    policy_path, policy_state = evaluate_policy(
        input_path, qc_path, outdir, consent=consent, witness=witness_path
    )
    results["policy-evaluation"] = {
        "status": "OK" if policy_path is not None else "BLOQUEADO",
        "verdict": policy_state,
        "path": str(policy_path) if policy_path else None,
    }

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

    # Sex recorded at birth reaches the clinical join because on the X the same genotype means
    # different things: a hemizygous male is affected, a heterozygous female is usually a
    # carrier. It is read from the dossier and never inferred — this pipeline does not call
    # sex chromosomes, and without the field every X-linked locus is refused with a reason.
    sex_at_birth = None
    if dossier and dossier.is_file():
        from reporting.case_dossier import load_dossier

        loaded = _step(results, "case-dossier", lambda: load_dossier(dossier))
        if loaded:
            sex_at_birth = (loaded.get("identification") or {}).get("sex_recorded_at_birth")

    # Runs of homozygosity are computed over the whole autosome, not over the registry, so
    # this reads the array again rather than reusing the completeness matrix: tract structure
    # lives between the targets, and measuring it at the targets would measure their spacing.
    homozygosity_path = _step(
        results,
        "homozygosity",
        lambda: _write_json(
            {
                **analyse_homozygosity(input_path),
                "case_id": json.loads(matrix_path.read_text(encoding="utf-8")).get("case_id"),
                "input_sha256": json.loads(
                    matrix_path.read_text(encoding="utf-8")
                ).get("input_sha256"),
            },
            outdir / "homozygosity.json",
        ),
    )

    findings_path = None
    if evidence and evidence.is_file() and assessed and assessed.is_file():
        findings_path = _step(
            results,
            "clinical-findings",
            lambda: write_findings(
                build_clinical_findings(
                    matrix_path, evidence, assessed, sex_at_birth=sex_at_birth
                ),
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

    # The provenance probe is optional and its absence is a weaker report, not a blocked one.
    # `probe_path` is positional in build_payload, so omitting it raised a TypeError that
    # blocked report 05 in every orchestrated run — a failure of the call, read as a failure
    # of the report.
    payload("05", lambda: p05(qc_path, matrix_path, probe_path, policy_path, witness_path))
    if passport_path:
        payload("06", lambda: p06(passport_path, matrix_path, policy_path, witness_path))
    payload("09", lambda: p09(matrix_path, qc_path, policy_path, witness_path))
    if passport_path:
        payload("10", lambda: p10(matrix_path, passport_path, policy_path, witness_path))

    if findings_path:
        from scripts.build_association_report import build_payload as passoc
        from scripts.build_clinical_report import build_payload as p01
        from scripts.build_reproductive_report import build_payload as p03

        payload("01", lambda: p01(findings_path, matrix_path, qc_path, policy_path, witness_path))
        payload(
            "03",
            lambda: p03(findings_path, matrix_path, homozygosity_path, policy_path, witness_path),
        )
        for report_id in ("04", "07", "08"):
            payload(
                report_id,
                (lambda rid: lambda: passoc(
                    rid, findings_path, matrix_path, policy_path, witness_path
                ))(report_id),
            )

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
            policy_evaluation=policy_path,
            post_deployment_witness=witness_path,
        ),
    )

    if template_dir and template_dir.is_dir():
        from scripts.build_editorial_guide import analyse, build_payload as p11, render
        from reporting.editorial_v3 import _verified_coordinate_manifest

        def guide() -> dict:
            manifest, _hashes = _verified_coordinate_manifest(template_dir)
            rows = analyse(manifest)
            return p11(rows, manifest, render(rows, manifest), policy_path, witness_path)

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
        "post_deployment_witness": witness_state,
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
    parser.add_argument(
        "--probe",
        help="provenance-probe.json; without it report 05 states the probe was not run",
    )
    parser.add_argument("--template-dir", help="installed v3.0 template pack; renders PDFs")
    parser.add_argument("--dossier", help="case dossier JSON, bound to the analysed case")
    parser.add_argument(
        "--consent",
        help="operator's consent record (JSON or path): verified, version, "
        "authorized_domains. Without it CONSENT_GATE fails and no report may publish.",
    )
    parser.add_argument(
        "--post-deployment-witness",
        help="witness written by scripts/run_live_post_deployment_smoke.py against a deployed "
        "service. Without it every report states POST-DEPLOYMENT PENDENTE, which is correct "
        "for a system with no live deployment.",
    )
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
        probe_path=Path(args.probe) if args.probe else None,
        consent=Path(args.consent) if args.consent else None,
        post_deployment_witness=(
            Path(args.post_deployment_witness) if args.post_deployment_witness else None
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["blocked"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
