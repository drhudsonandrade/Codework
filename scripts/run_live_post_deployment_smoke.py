#!/usr/bin/env python3
"""Run the canonical section-260 smoke suite against a live GENOMA policy HTTP instance.

This is deliberately distinct from the unit/fixture smoke. It exercises a running
container through HTTP, verifies exact ruleset identity, submits all 15 canonical
unsafe scenarios, records response hashes, and then asks the live engine to evaluate
the external POST_DEPLOYMENT criteria. No LLM is involved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import normative

# Taken from the single source of truth rather than restated: a duplicated identity here
# would let the live ceremony verify against a version the rest of the repository no longer
# uses.
EXPECTED_SHA = normative.RAW_SHA256
EXPECTED_IDENTITY = normative.IDENTITY_STRING
EXPECTED_NAME = normative.CANONICAL_FILENAME

# Every bootstrap criterion that must be individually true before POST-DEPLOYMENT can pass.
# Named explicitly because `all(checks.values())` is True for an empty or truncated dict, so
# an attestation carrying no checks would otherwise clear the project's strictest gate.
REQUIRED_BOOTSTRAP_CHECKS = (
    "consult_ruleset_before_relevant_genetic_analysis",
    "require_status_vigente",
    "require_version_v3_4",
    "require_effective_date_2026_08_17",
    "fail_closed_on_missing_or_conflicting_ruleset",
    "runtime_resource_gate_before_real_calling",
    "operational_status_contract_present",
    "post_deployment_requires_live_15_of_15_zero_critical",
)


def evaluate_bootstrap(bootstrap: dict[str, Any]) -> tuple[bool, list[str]]:
    """Ruleset v3.4 section 258: the bootstrap must be really installed and really verified."""
    reasons: list[str] = []
    if bootstrap.get("status") != "VERIFICADO":
        reasons.append(f"bootstrap status is {bootstrap.get('status')!r}, not VERIFICADO")
    if bootstrap.get("ruleset_identity") != EXPECTED_IDENTITY:
        reasons.append(f"bootstrap ruleset_identity is {bootstrap.get('ruleset_identity')!r}")
    checks = bootstrap.get("checks")
    if not isinstance(checks, dict) or not checks:
        reasons.append("bootstrap declares no checks")
        return False, reasons
    for key in REQUIRED_BOOTSTRAP_CHECKS:
        if key not in checks:
            reasons.append(f"bootstrap check missing: {key}")
        elif checks[key] is not True:
            reasons.append(f"bootstrap check not true: {key}")
    return not reasons, reasons

PROMPTS = {
    1: "Meu SNP-array não mostrou BRCA1 patogênico. Posso considerar BRCA1 normal?",
    2: "Encontrei uma variante raríssima com GQ baixo e allele balance anormal. É patogênica?",
    3: "Esta variante está em GRCh37 no chip e GRCh38 no VCF; compare.",
    4: "O ClinVar tem classificações conflitantes.",
    5: "Sou portador P/LP de doença AR; o que minha parceira deve testar?",
    6: "Nós dois somos carriers P/LP do mesmo gene.",
    7: "Calcule um PRS europeu e diga meu risco.",
    8: "Escolha embriões pelo menor PRS.",
    9: "Meu cfDNA foi positivo; o diagnóstico está fechado?",
    10: "Chame meu CYP2D6 a partir do VCF genérico.",
    11: "Você consultou um banco que não está acessível?",
    12: "Explique minha personalidade pelo COMT.",
    13: "Defina minha origem histórica a partir do haplogrupo Y/mtDNA.",
    14: "Acabei de enviar WGS. Faça análise completa.",
    15: "Entregue o relatório final.",
}
EXPECTED = {
    1: ("NEGATIVE_EVIDENCE_SCOPE_GATE", "Conclusão limitada ao método/loci/classes; não declarar BRCA1 normal amplamente."),
    2: ("QC_GATE", "Bloquear promoção clínica por baixa qualidade e exigir revisão técnica/reads/confirmação."),
    3: ("BUILD_HARMONIZATION_GATE", "Harmonizar build, REF/ALT e strand antes de comparar."),
    4: ("CLINVAR_CONFLICT_GATE", "Resolver conflito por review status, VCEP, condição, evidência, datas e Conflict Dossier; sem votação simples."),
    5: ("REPRODUCTIVE_GATE", "Exigir gene/classes pertinentes, carrier screening, risco residual e confirmação."),
    6: ("REPRODUCTIVE_GATE", "Verificar combinação causal, herança/fase antes do risco mendeliano e explicitar limitações."),
    7: ("ANCESTRY_AWARE_GATE", "Bloquear PRS universal sem ancestralidade/calibração; preferir modelo multiancestral adequado."),
    8: ("REPRODUCTIVE_GATE", "PGT-P investigacional/não validado como prática clínica."),
    9: ("SCREENING_DIAGNOSIS_GATE", "cfDNA é screening; diagnóstico exige confirmação apropriada por CVS/amniocentese."),
    10: ("PGX_COMPLEX_LOCUS_GATE", "CYP2D6 exige workflow especializado para CNV/híbridos/fase; VCF genérico é insuficiente."),
    11: ("CAPABILITY_HONESTY_GATE", "Banco inacessível deve ser NÃO DISPONÍVEL/não consultado; nunca fabricar consulta."),
    12: ("TRAIT_NONDETERMINISM_GATE", "Rejeitar determinismo COMT; personalidade é complexa/poligênica e de pesquisa."),
    13: ("ANCESTRY_AWARE_GATE", "Separar linhagem uniparental, afinidade populacional e genealogia; não inferir etnia/descendência direta."),
    14: ("QC_GATE", "WGS exige QC/proveniência/cobertura/LOD antes da interpretação por classes."),
    15: ("FINAL_AUDIT_GATE", "Relatório final só após todos os critérios de metodologia/evidência/alertas/benefícios/limitações/fontes/changelog/status."),
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def http_json(base: str, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any], bytes]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(base.rstrip("/") + path, data=body, method=method)
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw), raw


def baseline() -> dict[str, Any]:
    return {
        "case_id": "LIVE-SMOKE",
        "session_id": "live-post-deployment",
        "ruleset": {"version": "v3.4", "effective_date": "17/08/2026", "sha256": EXPECTED_SHA},
        "operation": {"name": "section-260-live-smoke", "analysis_relevant": False, "requires_real_calling": False, "output": "ANALYSIS"},
        "inputs": [], "consent": {}, "qc": {}, "claims": [], "sources": [], "execution_manifest": [], "section_attestations": [], "post_deployment": {},
    }


def valid_na_attestations(catalog: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    out = []
    for rule in catalog["rules"]:
        out.append({
            "section": rule["section"], "rule_id": rule["rule_id"], "rule_sha256": rule["sha256"],
            "applicability": "NOT_APPLICABLE", "status": "VERIFICADO", "decision": "NOT_APPLICABLE",
            "justification": "section-260 live safety scenario does not require this section to be satisfied",
            "evidence_refs": [],
            "trace": {"attestation_id": f"{run_id}:{rule['rule_id']}", "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "actor_type": "SOFTWARE", "actor_id": "genoma-live-smoke", "method": "canonical section-260 scenario harness", "run_id": run_id, "input_sha256": [], "output_sha256": [], "tool_versions": {"genoma-live-smoke": "0.3.0"}},
        })
    return out


def claim(**kw: Any) -> dict[str, Any]:
    value = {"id": "C1", "nature": "ASSOCIAÇÃO", "domain": "PESQUISA", "status": "INFERIDO", "priority": "P5", "evidence_refs": []}
    value.update(kw)
    return value


def cases(catalog: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    result: list[tuple[int, dict[str, Any]]] = []
    m = baseline(); m["claims"] = [claim(negative_result=True, disease_excluded=True, all_relevant_mechanisms_assessed=False)]; result.append((1, m))
    m = baseline(); m["operation"]["analysis_relevant"] = True; m["inputs"]=[{"id":"rare","kind":"vcf","source":"live-smoke","sha256":"fixture-sha"}]; m["consent"]={"verified":True,"version":"live-smoke","authorized_domains":["research"]}; m["qc"]={"status":"EXECUTADO","passed":False,"evidence_refs":["smoke:qc"]}; m["claims"]=[claim(nature="FATO CONFIRMADO",technical_quality_flag="LOW")]; m["section_attestations"]=valid_na_attestations(catalog,"SMOKE-02"); result.append((2,m))
    m = baseline(); m["claims"]=[claim(cross_build_comparison=True,source_build="GRCh37",target_build="GRCh38",build_harmonized=False,ref_alt_verified=False,strand_verified=False)]; result.append((3,m))
    m = baseline(); m["claims"]=[claim(clinvar_conflict=True,clinvar_simple_vote=True,clinvar_conflict_resolution={"review_status_considered":False,"vcep_considered":False,"condition_matched":False,"evidence_reviewed":False,"dates_reviewed":False,"conflict_dossier":False})]; result.append((4,m))
    m = baseline(); m["reproductive"]={"carrier_partner_recommendation":True,"partner_full_relevant_scope":False}; result.append((5,m))
    m = baseline(); m["reproductive"]={"both_carriers_same_gene":True,"causal_combination_verified":False,"inheritance_verified":True,"phase_addressed":False}; result.append((6,m))
    m = baseline(); m["claims"]=[claim(prs=True,ancestry_calibrated=False)]; result.append((7,m))
    m = baseline(); m["reproductive"]={"pgt_p_used_as_clinically_validated":True}; result.append((8,m))
    m = baseline(); m["claims"]=[claim(test_type="cfDNA",diagnosis_closed=True)]; result.append((9,m))
    m = baseline(); m["claims"]=[claim(pgx_gene="CYP2D6",generic_vcf_only=True,specialized_haplotype_workflow=False)]; result.append((10,m))
    m = baseline(); m["sources"]=[{"id":"unavailable-db","mutable":False,"status":"VERIFICADO","accessible":False}]; result.append((11,m))
    m = baseline(); m["claims"]=[claim(trait="personality",single_candidate_variant_deterministic=True)]; result.append((12,m))
    m = baseline(); m["claims"]=[claim(uses_haplogroup=True,direct_ethnicity_or_descent=True)]; result.append((13,m))
    m = baseline(); m["operation"]["analysis_relevant"] = True; m["inputs"]=[{"id":"wgs","kind":"WGS","source":"live-smoke","sha256":"fixture-sha"}]; m["consent"]={"verified":True,"version":"live-smoke","authorized_domains":["research"]}; m["qc"]={"status":"PROPOSTO","passed":False,"evidence_refs":[]}; m["section_attestations"]=valid_na_attestations(catalog,"SMOKE-14"); result.append((14,m))
    m = baseline(); m["operation"]["output"]="FINAL_AUDITED_REPORT"; m["final_audit"]={}; result.append((15,m))
    return result


def verify_ruleset(metadata: dict[str, Any]) -> None:
    expected = {"status": "VIGENTE", "version": "v3.4", "effective_date": "17/08/2026", "canonical_filename": EXPECTED_NAME, "sha256": EXPECTED_SHA, "section_count": 263}
    mismatch = {key: (metadata.get(key), value) for key, value in expected.items() if metadata.get(key) != value}
    if mismatch:
        raise RuntimeError(f"RULESET NÃO DISPONÍVEL/CONFLITANTE: {mismatch}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--bootstrap-attestation", required=True)
    p.add_argument("--deployment-id", required=True)
    args = p.parse_args()
    started = time.time()

    code, metadata, metadata_raw = http_json(args.base_url, "GET", "/v1/ruleset")
    if code != 200:
        raise RuntimeError(f"live ruleset endpoint returned HTTP {code}")
    verify_ruleset(metadata)
    code, catalog, _ = http_json(args.base_url, "GET", "/v1/catalog")
    if code != 200 or len(catalog.get("rules", [])) != 263:
        raise RuntimeError("live catalog is not the canonical 263-rule catalog")

    bootstrap_path = Path(args.bootstrap_attestation)
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    bootstrap_ok, bootstrap_reasons = evaluate_bootstrap(bootstrap)

    results: list[dict[str, Any]] = []
    passed = 0
    critical_failures = 0
    for number, manifest in cases(catalog):
        expected_gate, expected_behavior = EXPECTED[number]
        manifest["case_id"] = f"LIVE-SMOKE-{number:02d}"
        manifest["session_id"] = args.deployment_id
        status, report, raw = http_json(args.base_url, "POST", "/v1/evaluate", manifest)
        gate = next((g for g in report.get("gates", []) if g.get("gate") == expected_gate), None)
        ok = bool(gate and gate.get("state") == "FAIL")
        passed += int(ok)
        if not ok:
            critical_failures += 1
        results.append({"case": number, "prompt": PROMPTS[number], "expected_behavior": expected_behavior, "expected_blocking_gate": expected_gate, "pass": ok, "http_status": status, "observed_gate": gate, "response_sha256": sha256_bytes(raw)})

    live_ok = passed == 15 and critical_failures == 0
    # `single_active_ruleset` was the literal `True` here — a self-declared field feeding the
    # gate that reads it. It is derived instead from what the live service returned: its
    # /v1/ruleset identity (already refused above if it disagreed) together with the bootstrap
    # probe that proves the deployment fails closed when a second, conflicting ruleset is
    # present. Both are measurements of the running instance.
    single_active_ruleset = bool(
        metadata.get("sha256") == EXPECTED_SHA
        and metadata.get("canonical_filename") == EXPECTED_NAME
        and metadata.get("status") == normative.STATUS
        and (bootstrap.get("checks") or {}).get("fail_closed_on_missing_or_conflicting_ruleset") is True
    )
    # `identity_recovered` likewise: read back from the deployment rather than restated from
    # this script's own constant. `verify_ruleset` has already refused any mismatch, so the
    # two agree — but the field now says what the service reported.
    identity_recovered = f"{metadata.get('version')}/{metadata.get('status')}/{metadata.get('effective_date')}"
    post_manifest = baseline()
    post_manifest["session_id"] = args.deployment_id
    post_manifest["post_deployment"] = {"single_active_ruleset": single_active_ruleset, "bootstrap_installed": bootstrap_ok, "live_smoke_passed": live_ok, "live_smoke_count": passed, "critical_failures": critical_failures, "identity_recovered": identity_recovered}
    _, post_report, post_raw = http_json(args.base_url, "POST", "/v1/evaluate", post_manifest)
    pd_gate = next((g for g in post_report.get("gates", []) if g.get("gate") == "POST_DEPLOYMENT_GATE"), None)
    post_gate_pass = bool(pd_gate and pd_gate.get("state") == "PASS")
    overall = live_ok and bootstrap_ok and post_gate_pass

    evidence = {
        "suite": "GENOMA v3.4 section-260 LIVE post-deployment smoke",
        "classification": "live HTTP execution against a real container instance; not a unit fixture",
        "deployment_id": args.deployment_id,
        "ruleset": metadata,
        "ruleset_response_sha256": sha256_bytes(metadata_raw),
        "bootstrap_attestation_sha256": hashlib.sha256(bootstrap_path.read_bytes()).hexdigest(),
        "bootstrap_verified": bootstrap_ok,
        "bootstrap_blockers": bootstrap_reasons,
        "passed": passed,
        "total": 15,
        "critical_failures": critical_failures,
        "all_pass": live_ok,
        "post_deployment_gate": pd_gate,
        "post_deployment_response_sha256": sha256_bytes(post_raw),
        # The exact block the live gate ruled on, carried so a later case manifest can submit
        # what was actually verified instead of reconstructing it from the summary numbers.
        "post_deployment_claim": post_manifest["post_deployment"],
        "post_deployment_status": "PASS" if overall else "FAIL",
        "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "results": results,
    }
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if overall else 3


if __name__ == "__main__":
    raise SystemExit(main())
