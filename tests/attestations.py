"""One place to build the provenance attestations the array fixtures feed to QC.

Every fixture used to hand `inspect_array` a single attestation for *both* the build and
the strand — one object standing in for two different assertions, naming neither. That is
the shape of the defect it hid: `BUILD_STRAND_GATE` checked that an attestation existed,
was VERIFICADO/SATISFIED, and was bound to the input SHA-256, but never that it agreed with
the value being declared. `array_pipeline.provenance_probe` will honestly determine that a
file is on the reverse strand and emit exactly such an attestation saying so; paired with
`--strand forward` it passed every check and certified the file as forward.

`asserted_value` is now required, so a fixture has to say which assertion it is making, and
this helper exists so saying it costs one argument.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def attestation(
    input_sha: str,
    asserted_value: str,
    *,
    actor_id: str = "tests",
    attestation_id: str = "synthetic-fixture-provenance",
    justification: str = "Fixture determinístico declara explicitamente esta asserção.",
    evidence_ref: str = "synthetic-test-fixture",
    created_at: str = "2026-08-17T00:00:00Z",
) -> dict[str, Any]:
    """A structurally valid attestation for exactly one assertion."""
    return {
        "status": "VERIFICADO",
        "decision": "SATISFIED",
        "asserted_value": asserted_value,
        "justification": justification,
        "evidence_refs": [evidence_ref],
        "trace": {
            "attestation_id": attestation_id,
            "created_at": created_at,
            "actor_type": "SOFTWARE",
            "actor_id": actor_id,
            "method": "deterministic fixture",
            "run_id": "unit-test",
            "input_sha256": [input_sha],
            "output_sha256": [],
            "tool_versions": {"test": "1"},
        },
    }


def provenance_for(path: Path, *, build: str = "GRCh37", strand: str = "forward", **kwargs: Any) -> dict[str, str]:
    """The `inspect_array` provenance keyword arguments for a fixture array."""
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return {
        "build": build,
        "strand": strand,
        "build_evidence": json.dumps(attestation(sha, build, **kwargs), ensure_ascii=False),
        "strand_evidence": json.dumps(attestation(sha, strand, **kwargs), ensure_ascii=False),
    }


#: A policy-engine verdict, as the artifact `PayloadCompiler` reads it. Tests that render a
#: FINAL document need one, because the builders can no longer grant themselves a PASS: the
#: verdict is copied from a registered evaluation or the payload refuses.
POLICY_PASS = {
    "ready_for_requested_operation": True,
    "planes": {
        name: {"state": "PASS"}
        for name in ("policy_control", "scientific_data", "evidence", "audit")
    },
    "gates": [
        {"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True},
        {"gate": "CONSENT_GATE", "state": "PASS", "blocking": True},
        {"gate": "QC_GATE", "state": "PASS", "blocking": True},
    ],
}


def policy_evaluation_file(root: Path, verdict: dict[str, Any] | None = None) -> Path:
    """Write a policy evaluation into `root` and return its path."""
    path = Path(root) / "policy-evaluation.json"
    path.write_text(
        json.dumps(verdict if verdict is not None else POLICY_PASS, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def consent_record(
    *,
    case_id: str,
    input_sha256: str = "a" * 64,
    subject_id: str = "SUJEITO-TESTE",
    authorized_domains: Any = None,
    **overrides: Any,
) -> dict[str, Any]:
    """A complete consent record, as `reporting.consent` validates it.

    Defaults to the full domain vocabulary because most tests are about something else and a
    scope refusal would obscure what they are actually measuring; tests about scope pass the
    narrow list they mean.
    """
    from reporting.consent import ALLOWED_DOMAINS, REQUIRED_AFFIRMATIONS, SCHEMA

    record = {
        "schema": SCHEMA,
        "subject_id": subject_id,
        "case_id": case_id,
        "input_sha256": input_sha256,
        "version": "consentimento-teste-v1",
        "authorized_domains": list(
            authorized_domains if authorized_domains is not None else ALLOWED_DOMAINS
        ),
        "granted_at": "2026-08-01",
        "expires_at": None,
        "instrument": "termo de consentimento de teste",
        "instrument_version": "1.0",
        "captured_by": "tests",
        "affirmations": {key: True for key in REQUIRED_AFFIRMATIONS},
        "verified": True,
        "basis": "fixture determinístico de teste; nenhum sujeito real",
    }
    record.update(overrides)
    return record


def consent_file(root: Path, **kwargs: Any) -> Path:
    """Write a consent record into `root` and return its path."""
    path = Path(root) / "consent-record.json"
    path.write_text(json.dumps(consent_record(**kwargs), ensure_ascii=False), encoding="utf-8")
    return path


def consent_for(root: Path, artifact_path: Path, **kwargs: Any) -> Path:
    """A consent record bound to the case an already-written artifact names.

    The record must match the case it authorises, so tests that build an artifact and then a
    payload from it read the identifier back rather than repeating it — repeating it is how a
    fixture ends up authorising a different case than the one it renders.
    """
    payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    return consent_file(root, case_id=str(payload.get("case_id")), **kwargs)


def wgs_qc_record(*, case_id: str, vcf_sha256: str = "b" * 64, **overrides: Any) -> dict[str, Any]:
    """A complete section-6 WGS QC record, as `reporting.wgs_qc_record` validates it.

    Every required determination carries a plausible measurement, because most tests are
    about something else; tests about a gap pass the explicit-unavailable form for the one
    metric they mean.
    """
    from reporting.wgs_qc_record import REQUIRED_METRICS, SCHEMA as WGS_QC_SCHEMA

    plausible = {
        "mean_depth": 32.4, "pct_bases_10x": 98.7, "pct_bases_20x": 96.1,
        "pct_bases_30x": 88.4, "pct_exons_20x": 97.2, "pct_clinical_genes_20x": 98.0,
        "heterozygosity_rate": 0.0012, "ti_tv": 2.01, "snv_count": 4_100_000,
        "indel_count": 780_000, "cnv_count": 1_240, "sv_count": 9_800,
        "mtdna_mean_depth": 2_450.0, "contamination_estimate": 0.004,
    }
    assert set(plausible) == set(REQUIRED_METRICS), "fixture drifted from the required set"
    record = {
        "schema": WGS_QC_SCHEMA,
        "case_id": case_id,
        "vcf_sha256": vcf_sha256,
        "laboratory": "Laboratório de teste",
        "report_date": "2026-08-01",
        "source": "relatório de QC entregue com o WGS",
        "captured_by": "tests.attestations",
        "biological_material": "SANGUE",
        "read_layout": "PAIRED-END",
        "sequencing_platform": "plataforma de teste",
        "read_length": "2x150",
        "reference_build": "GRCh38",
        "pipeline_version": "pipeline de teste v1",
        "metrics": dict(plausible),
        "reliability_map": {
            "alta_confianca": "92% do genoma",
            "confianca_moderada": "5%",
            "baixa_cobertura": "2%",
            "mapeamento_dificil": "1%",
            "nao_resolvidas": "regiões centroméricas",
        },
    }
    record.update(overrides)
    return record


def wgs_qc_file(root: Path, **kwargs: Any) -> Path:
    """Write a WGS QC record into `root` and return its path."""
    path = Path(root) / "wgs-qc-record.json"
    path.write_text(json.dumps(wgs_qc_record(**kwargs), ensure_ascii=False), encoding="utf-8")
    return path
