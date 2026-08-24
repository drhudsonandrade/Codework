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


class PostMergeBootstrapGovernanceTests(unittest.TestCase):
    def test_project_instructions_attestation_verifier_exists(self) -> None:
        self.assertIsNotNone(
            importlib.util.find_spec("scripts.project_instructions_attestation"),
            "PROJECT_BOOTSTRAP_INSTALLED needs an independent Project Instructions attestation verifier",
        )

    def test_project_instructions_attestation_is_derived_from_owner_export(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source, output = _write_project_attestation(Path(td))
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "VERIFICADO")
            self.assertTrue(payload["project_bootstrap_installed"])
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

    def test_live_smoke_does_not_reuse_ruleset_bootstrap_as_installation_proof(self) -> None:
        text = (ROOT / "scripts" / "run_live_post_deployment_smoke.py").read_text(encoding="utf-8")
        self.assertIn("verify_project_instructions_attestation", text)
        self.assertNotIn('"bootstrap_installed": bootstrap_ok', text)
        self.assertIn('"bootstrap_installed": project_bootstrap_ok', text)

    def test_bootstrap_verifier_supports_runtime_main_sha_binding(self) -> None:
        parameters = inspect.signature(bootstrap_attestation.verify_bootstrap_attestation).parameters
        self.assertIn("expected_source_revision", parameters)
        self.assertIn("expected_file_sha256", parameters)

    def test_production_witness_generates_fresh_bootstrap_for_exact_main_sha(self) -> None:
        text = (ROOT / ".github" / "workflows" / "genoma-production-witness.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python3 -m scripts.bootstrap_attestation --write", text)
        self.assertIn("--expected-source-commit \"$GITHUB_SHA\"", text)
        self.assertIn("--project-instructions-attestation", text)
        self.assertIn("--project-instructions-source", text)
        self.assertNotIn(
            "--bootstrap-attestation deploy/attestations/bootstrap-project-v3.4.json",
            text,
        )

    def test_manual_ceremony_uses_same_external_bootstrap_contract(self) -> None:
        text = (ROOT / ".github" / "workflows" / "genoma-production-ceremony.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python3 -m scripts.bootstrap_attestation --write", text)
        self.assertIn("--expected-source-commit \"$GITHUB_SHA\"", text)
        self.assertIn("--project-instructions-attestation", text)
        self.assertIn("--project-instructions-source", text)

    def test_main_ruleset_is_fail_closed(self) -> None:
        ruleset = json.loads((ROOT / ".github/governance/main-ruleset.json").read_text(encoding="utf-8"))
        self.assertEqual(ruleset["enforcement"], "active")
        self.assertEqual(ruleset["bypass_actors"], [])
        types = {rule["type"] for rule in ruleset["rules"]}
        self.assertTrue({"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= types)
        status_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
        contexts = {item["context"] for item in status_rule["parameters"]["required_status_checks"]}
        self.assertIn("CodeRabbit", contexts)
        self.assertIn("Gitleaks secret scan", contexts)
        self.assertTrue(status_rule["parameters"]["strict_required_status_checks_policy"])

    def test_audit_evidence_ruleset_preserves_append_only_publisher(self) -> None:
        ruleset = json.loads((ROOT / ".github/governance/audit-evidence-ruleset.json").read_text(encoding="utf-8"))
        self.assertEqual(ruleset["enforcement"], "active")
        types = {rule["type"] for rule in ruleset["rules"]}
        self.assertEqual(types, {"deletion", "non_fast_forward"})


if __name__ == "__main__":
    unittest.main()
