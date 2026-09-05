from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import bootstrap_attestation

ROOT = Path(__file__).resolve().parents[1]


def _valid_project_instructions() -> str:
    return "\n".join(
        [
            "Antes de qualquer análise genética relevante, abrir e consultar REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt.",
            "Confirmar STATUS NORMATIVO: VIGENTE.",
            "Confirmar VERSÃO NORMATIVA: v3.4.",
            "Confirmar DATA FORMAL DE EMISSÃO E VIGÊNCIA: 17/08/2026.",
            "Se houver conflito, declarar RULESET NÃO DISPONÍVEL/CONFLITANTE.",
            "Usar EXECUTADO, VERIFICADO, INFERIDO, PROPOSTO ou NÃO DISPONÍVEL.",
            "Antes de calling real, reexecutar o Runtime/Resource Gate antes de calling real.",
        ]
    ) + "\n"


def _write_project_attestation(root: Path) -> tuple[Path, Path]:
    source = root / "project-instructions.txt"
    output = root / "project-instructions-attestation.json"
    source.write_text(_valid_project_instructions(), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.project_instructions_attestation",
            "--source",
            str(source),
            "--source-locator",
            "chatgpt-project://GENOMA/instructions",
            "--verified-at",
            "2026-08-24T05:20:00Z",
            "--output",
            str(output),
            "--write",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return source, output


def _assert_manual_ceremony_attestation_step_is_main_gated(text: str) -> None:
    job_marker = "  live-section-260:\n"
    if job_marker not in text:
        raise AssertionError("live-section-260 job is missing")
    job = text.split(job_marker, 1)[1]
    step_marker = "      - name: Generate and pin fresh ruleset bootstrap attestation for exact main SHA\n"
    if step_marker not in job:
        raise AssertionError("bootstrap attestation step is missing from live-section-260")
    before_step, after_step = job.split(step_marker, 1)
    if "    if: github.ref == 'refs/heads/main'\n" not in before_step:
        raise AssertionError("bootstrap attestation step is not protected by the live-section-260 main gate")
    step_body = after_step.split("\n      - name:", 1)[0]
    if "python3 -m scripts.bootstrap_attestation --write" not in step_body:
        raise AssertionError("bootstrap attestation command is not in the protected step")
    if '--result-locator "$locator"' not in step_body:
        raise AssertionError("bootstrap attestation result locator is not published by the protected step")


class PostMergeBootstrapGovernanceTests(unittest.TestCase):
    def test_project_instructions_attestation_verifier_exists(self) -> None:
        self.assertIsNotNone(
            importlib.util.find_spec("scripts.project_instructions_attestation"),
            "Project Instructions snapshot needs an independent verifier",
        )

    def test_project_instructions_attestation_is_snapshot_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source, output = _write_project_attestation(Path(td))
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "VERIFICADO")
            self.assertEqual(payload["evidence_classification"], "VERIFIED_OWNER_SNAPSHOT_ONLY")
            self.assertFalse(payload["project_bootstrap_installed"])
            self.assertEqual(payload["installation_status"], "NÃO DISPONÍVEL")
            self.assertEqual(payload["source"]["locator"], "chatgpt-project://GENOMA/instructions")
            verified = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.project_instructions_attestation",
                    "--source",
                    str(source),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr or verified.stdout)

    def test_project_instructions_attestation_fails_closed_on_missing_bootstrap_clause(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "project-instructions.txt"
            output = root / "project-instructions-attestation.json"
            source.write_text(
                _valid_project_instructions().replace("RULESET NÃO DISPONÍVEL/CONFLITANTE", "RULESET indisponível"),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.project_instructions_attestation",
                    "--source",
                    str(source),
                    "--source-locator",
                    "chatgpt-project://GENOMA/instructions",
                    "--verified-at",
                    "2026-08-24T05:20:00Z",
                    "--output",
                    str(output),
                    "--write",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_project_instructions_attestation_rejects_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source, output = _write_project_attestation(Path(td))
            source.write_text(source.read_text(encoding="utf-8") + "alteração posterior\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.project_instructions_attestation",
                    "--source",
                    str(source),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match the attested digest/size", result.stdout)

    def test_project_instructions_attestation_rejects_tampered_locator(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source, output = _write_project_attestation(Path(td))
            payload = json.loads(output.read_text(encoding="utf-8"))
            payload["source"]["locator"] = ""
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.project_instructions_attestation",
                    "--source",
                    str(source),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source locator is required", result.stdout)

    def test_live_smoke_never_promotes_local_snapshot_to_installation_proof(self) -> None:
        text = (ROOT / "scripts" / "run_live_post_deployment_smoke.py").read_text(encoding="utf-8")
        self.assertIn("verify_project_instructions_attestation", text)
        self.assertIn("project_bootstrap_ok = False", text)
        self.assertNotIn('"bootstrap_installed": bootstrap_ok', text)
        self.assertIn('"bootstrap_installed": project_bootstrap_ok', text)

    def test_bootstrap_verifier_supports_runtime_binding_inputs(self) -> None:
        parameters = inspect.signature(bootstrap_attestation.verify_bootstrap_attestation).parameters
        self.assertIn("expected_source_revision", parameters)
        self.assertIn("expected_file_sha256", parameters)
        self.assertIn("expected_result_locator", parameters)

    def test_bootstrap_runtime_sha_binding_is_behavioral(self) -> None:
        path = ROOT / "deploy" / "attestations" / "bootstrap-project-v3.4.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        recorded = payload["method"]["source_commit_sha"]
        head = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if head == recorded:
            head = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD^"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        self.assertNotEqual(head, recorded)
        with self.assertRaisesRegex(
            bootstrap_attestation.BootstrapAttestationError,
            "does not match the required runtime commit",
        ):
            bootstrap_attestation.verify_bootstrap_attestation(
                path,
                expected_source_revision=head,
            )

    def test_bootstrap_digest_verification_cannot_be_disabled(self) -> None:
        path = ROOT / "deploy" / "attestations" / "bootstrap-project-v3.4.json"
        with self.assertRaisesRegex(
            bootstrap_attestation.BootstrapAttestationError,
            "digest verification cannot be disabled",
        ):
            bootstrap_attestation.verify_bootstrap_attestation(
                path,
                expected_file_sha256=None,  # type: ignore[arg-type]
            )
        try:
            bootstrap_attestation.verify_bootstrap_attestation(
                path,
                expected_file_sha256="0" * 64,
            )
        except bootstrap_attestation.BootstrapAttestationError as exc:
            self.assertIn("digest mismatch", str(exc))
        else:
            self.fail("a syntactically valid but incorrect bootstrap digest must fail closed")

    def test_bootstrap_result_locator_mismatch_fails_closed(self) -> None:
        path = ROOT / "deploy" / "attestations" / "bootstrap-project-v3.4.json"
        with self.assertRaisesRegex(
            bootstrap_attestation.BootstrapAttestationError,
            "result_locator does not match",
        ):
            bootstrap_attestation.verify_bootstrap_attestation(
                path,
                expected_result_locator="evidence/bootstrap-project-v3.4.json#/checks",
            )

    def test_production_witness_pins_fresh_bootstrap_digest_locator_and_sha(self) -> None:
        text = (ROOT / ".github" / "workflows" / "genoma-production-witness.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python3 -m scripts.bootstrap_attestation --write", text)
        self.assertIn("--result-locator \"$locator\"", text)
        self.assertIn("GENOMA_BOOTSTRAP_ATTESTATION_SHA256", text)
        self.assertIn("--bootstrap-attestation-sha256", text)
        self.assertIn("--bootstrap-result-locator", text)
        self.assertIn("--expected-source-commit \"$GITHUB_SHA\"", text)
        self.assertIn("--project-instructions-attestation", text)
        self.assertIn("--project-instructions-source", text)
        self.assertNotIn("expected_file_sha256=None", text)
        self.assertNotIn(
            "--bootstrap-attestation deploy/attestations/bootstrap-project-v3.4.json",
            text,
        )

    def test_manual_ceremony_uses_same_runtime_binding_contract(self) -> None:
        text = (ROOT / ".github" / "workflows" / "genoma-production-ceremony.yml").read_text(
            encoding="utf-8"
        )
        _assert_manual_ceremony_attestation_step_is_main_gated(text)
        self.assertIn("--bootstrap-attestation-sha256", text)
        self.assertIn("--bootstrap-result-locator", text)
        self.assertIn("--expected-source-commit \"$GITHUB_SHA\"", text)

        mutated = text.replace("    if: github.ref == 'refs/heads/main'\n", "", 1)
        self.assertNotEqual(mutated, text, "mutation must remove the main gate")
        try:
            _assert_manual_ceremony_attestation_step_is_main_gated(mutated)
        except AssertionError as exc:
            self.assertIn("not protected", str(exc))
        else:
            self.fail("mutation removing the main gate must invalidate the protected attestation-step contract")

    def test_main_ruleset_is_fail_closed(self) -> None:
        ruleset = json.loads((ROOT / ".github/governance/main-ruleset.json").read_text(encoding="utf-8"))
        self.assertEqual(ruleset["enforcement"], "active")
        self.assertEqual(ruleset["bypass_actors"], [])
        types = {rule["type"] for rule in ruleset["rules"]}
        self.assertEqual(types, {"deletion", "non_fast_forward", "required_status_checks"})
        self.assertNotIn("pull_request", types)
        status_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
        checks = {item["context"]: item.get("integration_id") for item in status_rule["parameters"]["required_status_checks"]}
        self.assertIn("CodeRabbit", checks)
        self.assertEqual(checks.get("Greptile Review"), 867647)
        self.assertEqual(checks.get("GitGuardian Security Checks"), 46505)
        for context in (
            "DeepSource: Python",
            "DeepSource: JavaScript",
            "DeepSource: Shell",
            "DeepSource: Docker",
            "DeepSource: SQL",
        ):
            self.assertEqual(checks.get(context), 16372)
        self.assertIn("security/snyk (drhudsonandrade)", checks)
        self.assertEqual(checks.get("semgrep-cloud-platform/scan"), 4836909)
        self.assertNotIn("Gitleaks secret scan", checks)
        self.assertTrue(status_rule["parameters"]["strict_required_status_checks_policy"])

    def test_main_approval_gate_is_layered_and_pr_only_bypass(self) -> None:
        approval = json.loads(
            (ROOT / ".github/governance/main-approval-ruleset.json").read_text(encoding="utf-8")
        )
        self.assertEqual(approval["name"], "GENOMA approval gate")
        self.assertEqual(approval["enforcement"], "active")
        self.assertEqual(approval["conditions"]["ref_name"]["include"], ["refs/heads/main"])
        self.assertEqual(
            approval["bypass_actors"],
            [{"actor_id": 116986656, "actor_type": "User", "bypass_mode": "pull_request"}],
        )
        self.assertEqual({rule["type"] for rule in approval["rules"]}, {"pull_request"})
        pull_request = approval["rules"][0]["parameters"]
        self.assertEqual(pull_request["required_approving_review_count"], 1)
        self.assertTrue(pull_request["dismiss_stale_reviews_on_push"])
        self.assertTrue(pull_request["require_last_push_approval"])
        self.assertTrue(pull_request["required_review_thread_resolution"])

    def test_audit_evidence_governance_is_layered(self) -> None:
        governance = ROOT / ".github/governance"
        combined = governance / "audit-evidence-ruleset.json"
        integrity = json.loads(
            (governance / "audit-evidence-integrity-ruleset.json").read_text(encoding="utf-8")
        )
        publisher = json.loads(
            (governance / "audit-evidence-publisher-ruleset.json").read_text(encoding="utf-8")
        )
        self.assertFalse(combined.exists(), "unsafe combined audit-evidence ruleset must remain removed")
        self.assertEqual(integrity["bypass_actors"], [])
        self.assertEqual({rule["type"] for rule in integrity["rules"]}, {"deletion", "non_fast_forward"})
        self.assertEqual({rule["type"] for rule in publisher["rules"]}, {"update"})
        self.assertEqual(
            publisher["bypass_actors"],
            [{"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "always"}],
        )

    def test_audit_publisher_rejects_existing_witness_mutation_and_checks_latest(self) -> None:
        text = (ROOT / ".github" / "workflows" / "genoma-production-witness.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("GENOMA_AUDIT_DEPLOY_KEY", text)
        self.assertIn("ssh-key: ${{ secrets.GENOMA_AUDIT_DEPLOY_KEY }}", text)
        self.assertIn("refusing to modify an existing witness path", text)
        self.assertIn('cmp "$tmp/witness.json" latest.json', text)
        self.assertIn('cmp "$target/witness.json" latest.json', text)


if __name__ == "__main__":
    unittest.main()
