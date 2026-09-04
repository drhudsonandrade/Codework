import json
import re
import unittest
from pathlib import Path

from tests.workflow_test_utils import job_block as _job_block


ROOT = Path(__file__).resolve().parents[1]


def _job_if_condition(workflow: str, job_name: str) -> str:
    job = _job_block(workflow, job_name)
    conditions = [line.removeprefix("    if: ").strip() for line in job.splitlines() if line.startswith("    if: ")]
    if len(conditions) != 1:
        raise AssertionError(f"job {job_name!r} must have exactly one job-level if condition")
    return conditions[0]


def _named_step_block(workflow: str, job_name: str, step_name: str) -> str:
    job = _job_block(workflow, job_name)
    marker = f"      - name: {step_name}\n"
    if marker not in job:
        raise AssertionError(f"step {step_name!r} is missing from job {job_name!r}")
    tail = job.split(marker, 1)[1]
    return tail.split("\n      - ", 1)[0]


def _shell_test_lines(step: str) -> list[str]:
    return [line.strip() for line in step.splitlines() if line.strip().startswith("test ")]


def _job_steps(workflow: str, job_name: str) -> list[str]:
    job = _job_block(workflow, job_name)
    marker = "    steps:\n"
    if marker not in job:
        raise AssertionError(f"job {job_name!r} has no steps")
    tail = job.split(marker, 1)[1]
    parts = tail.split("\n      - ")
    steps: list[str] = []
    for index, part in enumerate(parts):
        block = part if index == 0 else "      - " + part
        if block.strip():
            steps.append(block)
    return steps


def _step_run_commands(step: str) -> tuple[str, ...]:
    lines = step.splitlines()
    commands: list[str] = []
    in_block = False
    control_depth = 0
    heredoc_end: str | None = None
    block_starters = re.compile(r"^(?:if|for|while|until|case)\b")
    block_enders = re.compile(r"^(?:fi|done|esac)\b")
    heredoc_pattern = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
    for line in lines:
        if line.startswith("        run:"):
            value = line.split("run:", 1)[1].strip()
            if value in {"|", ">"}:
                in_block = True
            elif value:
                commands.append(value)
            continue
        if not in_block:
            continue
        if not line.startswith("          "):
            break
        command = line.strip()
        if not command or command.startswith("#"):
            continue
        if heredoc_end is not None:
            if command == heredoc_end:
                heredoc_end = None
            continue
        if block_enders.match(command):
            control_depth = max(0, control_depth - 1)
            continue
        if control_depth == 0:
            commands.append(command)
        heredoc = heredoc_pattern.search(command)
        if heredoc is not None:
            heredoc_end = heredoc.group(1)
        if block_starters.match(command):
            control_depth += 1
    return tuple(commands)


def _step_runs_validate_repo(step: str) -> bool:
    pattern = re.compile(r"^(?:python3|python)\s+scripts/validate_repo\.py$")
    return any(pattern.fullmatch(command) is not None for command in _step_run_commands(step))


def _with_mapping(step: str) -> dict[str, object]:
    lines = step.splitlines()
    try:
        start = lines.index("        with:") + 1
    except ValueError:
        return {}
    values: dict[str, object] = {}
    for line in lines[start:]:
        if not line.startswith("          "):
            break
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if ":" not in stripped:
            break
        key, raw = stripped.split(":", 1)
        value = raw.strip()
        if value == "false":
            parsed: object = False
        elif value == "true":
            parsed = True
        elif value.isdigit():
            parsed = int(value)
        else:
            parsed = value.strip("'\"")
        values[key] = parsed
    return values


def _assert_attestation_step_is_in_main_gated_ceremony_job(workflow: str) -> None:
    expected_if = "github.ref == 'refs/heads/main'"
    if _job_if_condition(workflow, "live-section-260") != expected_if:
        raise AssertionError("live-section-260 must remain restricted to main")
    step = _named_step_block(
        workflow,
        "live-section-260",
        "Generate and pin fresh ruleset bootstrap attestation for exact main SHA",
    )
    if "python3 -m scripts.bootstrap_attestation --write" not in step:
        raise AssertionError("bootstrap attestation command must remain in the main-gated job")
    if '--result-locator "$locator"' not in step:
        raise AssertionError("bootstrap attestation result locator must remain in the main-gated job")


class WorkflowContractTest(unittest.TestCase):
    def test_production_witness_uses_current_live_smoke_cli_contract(self):
        workflow = (ROOT / ".github/workflows/genoma-production-witness.yml").read_text(encoding="utf-8")
        self.assertIn("--output evidence/live-section-260/summary.json", workflow)
        self.assertIn("--deployment-id", workflow)
        self.assertIn("--bootstrap-attestation-sha256", workflow)
        self.assertIn("--bootstrap-result-locator", workflow)
        self.assertNotIn("--output-dir evidence/live-section-260", workflow)

    def test_production_witness_covers_every_main_commit(self):
        workflow = (ROOT / ".github/workflows/genoma-production-witness.yml").read_text(encoding="utf-8")
        header = workflow.split("permissions:", 1)[0]
        self.assertIn("push:\n    branches: [main]", header)
        push_block = header.split("push:\n", 1)[1].split("workflow_dispatch:", 1)[0]
        self.assertNotIn("paths:", push_block)

    def test_production_witness_publisher_uses_restricted_deploy_key_without_token_write(self):
        workflow = (ROOT / ".github/workflows/genoma-production-witness.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("publish-witness:", workflow)
        self.assertEqual(
            _job_if_condition(workflow, "publish-witness"),
            "github.event_name == 'push' && github.ref == 'refs/heads/main'",
        )
        publish = _job_block(workflow, "publish-witness")
        self.assertIn("permissions:\n      contents: read", publish)
        self.assertIn("GENOMA_AUDIT_DEPLOY_KEY", publish)
        self.assertIn("ssh-key: ${{ secrets.GENOMA_AUDIT_DEPLOY_KEY }}", publish)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("GENOMA_AUDIT_PUBLISH_TOKEN", workflow)

        mutated = workflow.replace(
            "    if: github.event_name == 'push' && github.ref == 'refs/heads/main'\n",
            "    if: github.event_name == 'push' && github.ref == 'refs/heads/main' || github.event_name == 'workflow_dispatch'\n",
            1,
        )
        self.assertNotEqual(mutated, workflow, "mutation must alter the publisher branch condition")
        self.assertNotEqual(
            _job_if_condition(mutated, "publish-witness"),
            "github.event_name == 'push' && github.ref == 'refs/heads/main'",
        )

    def test_manual_production_ceremony_does_not_duplicate_every_main_push(self):
        workflow = (ROOT / ".github/workflows/genoma-production-ceremony.yml").read_text(encoding="utf-8")
        header = workflow.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", header)
        self.assertNotIn("push:", header)

    def test_manual_production_ceremony_is_main_only(self):
        workflow = (ROOT / ".github/workflows/genoma-production-ceremony.yml").read_text(encoding="utf-8")
        self.assertEqual(_job_if_condition(workflow, "live-section-260"), "github.ref == 'refs/heads/main'")
        protected_step = _named_step_block(workflow, "live-section-260", "Require protected main ref")
        self.assertEqual(_shell_test_lines(protected_step), ['test "$GITHUB_REF" = \'refs/heads/main\''])
        checkout = workflow.split("uses: actions/checkout@", 1)[1].split("- uses:", 1)[0]
        self.assertIn("persist-credentials: false", checkout)

        permissive_job = workflow.replace(
            "    if: github.ref == 'refs/heads/main'\n",
            "    if: github.ref == 'refs/heads/main' || github.event_name == 'workflow_dispatch'\n",
            1,
        )
        self.assertNotEqual(permissive_job, workflow, "mutation must alter the ceremony job condition")
        self.assertNotEqual(_job_if_condition(permissive_job, "live-section-260"), "github.ref == 'refs/heads/main'")

        permissive_shell = workflow.replace(
            '          test "$GITHUB_REF" = \'refs/heads/main\'\n',
            '          test "$GITHUB_REF" = \'refs/heads/main\' || true\n',
            1,
        )
        self.assertNotEqual(permissive_shell, workflow, "mutation must alter the shell guard")
        mutated_step = _named_step_block(permissive_shell, "live-section-260", "Require protected main ref")
        self.assertNotEqual(_shell_test_lines(mutated_step), ['test "$GITHUB_REF" = \'refs/heads/main\''])

    def test_attestation_step_cannot_move_to_an_unprotected_job(self):
        workflow = (ROOT / ".github/workflows/genoma-production-ceremony.yml").read_text(encoding="utf-8")
        _assert_attestation_step_is_in_main_gated_ceremony_job(workflow)

        step_name = "Generate and pin fresh ruleset bootstrap attestation for exact main SHA"
        mutated = workflow.replace(f"      - name: {step_name}\n", "      - name: displaced attestation step\n", 1)
        mutated += (
            "\n  unprotected-attestation:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            f"      - name: {step_name}\n"
            "        run: |\n"
            "          locator='production-evidence/bootstrap-project-v3.4.json#/checks'\n"
            "          python3 -m scripts.bootstrap_attestation --write --result-locator \"$locator\"\n"
        )
        with self.assertRaises(AssertionError):
            _assert_attestation_step_is_in_main_gated_ceremony_job(mutated)

    def test_validate_repo_command_detection_rejects_unreachable_shell_and_heredoc(self):
        false_branch = """      - name: misleading
        run: |
          if false; then
            python3 scripts/validate_repo.py
          fi
"""
        heredoc = """      - name: misleading
        run: |
          cat <<'EOF'
          python3 scripts/validate_repo.py
          EOF
"""
        direct = """      - name: validate
        run: |
          python3 scripts/validate_repo.py
"""
        self.assertFalse(_step_runs_validate_repo(false_branch))
        self.assertFalse(_step_runs_validate_repo(heredoc))
        self.assertTrue(_step_runs_validate_repo(direct))

    def test_validate_repo_command_detection_ignores_non_executable_mentions(self):
        echo_only = "      - name: misleading\n        run: |\n          echo 'python3 scripts/validate_repo.py'\n          # python3 scripts/validate_repo.py\n"
        executable = "      - name: validate\n        run: python3 scripts/validate_repo.py\n"
        self.assertFalse(_step_runs_validate_repo(echo_only))
        self.assertTrue(_step_runs_validate_repo(executable))

    def test_validate_repo_jobs_fetch_full_history_for_baseline_provenance(self):
        targets = {
            "genoma-audit.yml": ("audit",),
            "genoma-ngs-runtime-gate.yml": ("preflight", "full-grch38"),
            "genoma-policy-engine.yml": ("policy",),
            "genoma-production-ceremony.yml": ("live-section-260",),
            "genoma-production-witness.yml": ("witness",),
            "genoma-snp-array.yml": ("array-qc-contract",),
            "scaffold-validation.yml": ("static",),
        }
        for filename, jobs in targets.items():
            workflow = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
            for job_name in jobs:
                with self.subTest(workflow=filename, job=job_name):
                    steps = _job_steps(workflow, job_name)
                    checkout_indexes = [i for i, step in enumerate(steps) if "uses: actions/checkout@" in step]
                    validation_indexes = [i for i, step in enumerate(steps) if _step_runs_validate_repo(step)]
                    self.assertEqual(len(checkout_indexes), 1)
                    self.assertTrue(validation_indexes)
                    checkout_index = checkout_indexes[0]
                    self.assertLess(checkout_index, min(validation_indexes))
                    checkout_config = _with_mapping(steps[checkout_index])
                    self.assertEqual(checkout_config.get("fetch-depth"), 0)
                    hardened = {
                        ("genoma-ngs-runtime-gate.yml", "preflight"),
                        ("genoma-ngs-runtime-gate.yml", "full-grch38"),
                        ("genoma-policy-engine.yml", "policy"),
                        ("genoma-snp-array.yml", "array-qc-contract"),
                    }
                    if (filename, job_name) in hardened:
                        self.assertIs(checkout_config.get("persist-credentials"), False)

    def test_main_required_policy_checks_have_unconditional_pr_provider(self):
        policy = (ROOT / ".github/workflows/genoma-policy-engine.yml").read_text(encoding="utf-8")
        header = policy.split("permissions:", 1)[0]
        pull_request_block = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        self.assertNotIn("paths:", pull_request_block)

        ruleset = json.loads((ROOT / ".github/governance/main-ruleset.json").read_text(encoding="utf-8"))
        status_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
        contexts = {item["context"] for item in status_rule["parameters"]["required_status_checks"]}
        for context in (
            "Canonical policy + 263-rule contract",
            "OPA/Rego parity",
            "Gitleaks secret scan",
            "Real Docker + canonical read-only mount",
        ):
            self.assertIn(context, contexts)
            self.assertIn(f"name: {context}", policy)

    def test_legacy_editorial_chunk_materializer_is_removed(self):
        self.assertFalse((ROOT / ".github/workflows/genoma-materialize-editorial-upload.yml").exists())

    def test_highmem_probe_is_manual_and_not_bound_to_retired_feature_branch(self):
        workflow = (ROOT / ".github/workflows/genoma-highmem-probe.yml").read_text(encoding="utf-8")
        header = workflow.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", header)
        self.assertNotIn("fix/genoma-v3-pixel-qa-highmem", header)
        self.assertNotIn("push:", header)

    def test_ngs_canary_does_not_bypass_micromamba_entrypoint_with_login_shell(self):
        workflow = (ROOT / ".github/workflows/genoma-ngs-runtime-gate.yml").read_text(encoding="utf-8")
        self.assertIn("/opt/codework/scripts/run_canary.sh /workspace/results/canary", workflow)
        self.assertNotIn("bash -lc './scripts/run_canary.sh", workflow)

    def test_latest_candidate_must_execute_nextflow_orchestration_before_promotion(self):
        workflow = (ROOT / ".github/workflows/genoma-ngs-runtime-gate.yml").read_text(encoding="utf-8")
        self.assertIn("nextflow run /opt/codework/main.nf --mode canary", workflow)
        self.assertIn("results/nextflow-canary/canary/report.json", workflow)
        self.assertIn("--functional-canary results/canary/report.json", workflow)
        self.assertIn("--orchestration-canary results/nextflow-canary/canary/report.json", workflow)
        self.assertNotIn("results/nextflow-canary/report.json", workflow)
        config = (ROOT / "nextflow.config").read_text(encoding="utf-8")
        self.assertIn("nextflowVersion = '!>=26.04.6'", config)

    def test_nextflow_runtime_contains_procps_and_resolve_promote_share_one_contract(self):
        environment = (ROOT / "environment.yml").read_text(encoding="utf-8")
        self.assertIn("- procps-ng", environment)
        self.assertIn("- poppler=26.07.0", environment)
        contract = (ROOT / "scripts/runtime_stack.py").read_text(encoding="utf-8")
        self.assertIn('"procps-ng"', contract)
        self.assertIn('"poppler"', contract)
        candidate = (ROOT / "scripts/prepare_latest_candidate.py").read_text(encoding="utf-8")
        promotion = (ROOT / "scripts/promote_latest_candidate.py").read_text(encoding="utf-8")
        self.assertIn("MANAGED_RUNTIME_PACKAGES", candidate)
        self.assertIn("MANAGED_RUNTIME_PACKAGES", promotion)

    def test_functional_canary_includes_editorial_runtime_before_promotion(self):
        canary = (ROOT / "scripts/run_canary.sh").read_text(encoding="utf-8")
        self.assertIn("editorial-runtime.json", canary)
        self.assertIn("pdftoppm -singlefile", canary)
        self.assertIn("pdftocairo -svg", canary)
        self.assertIn("editorial_runtime: $editorial[0]", canary)
        promotion = (ROOT / "scripts/promote_latest_candidate.py").read_text(encoding="utf-8")
        self.assertIn("functional canary editorial runtime is not PASS", promotion)

    def test_full_grch38_remains_explicit_highmem_dispatch(self):
        workflow = (ROOT / ".github/workflows/genoma-ngs-runtime-gate.yml").read_text(encoding="utf-8")
        self.assertIn("[self-hosted, linux, x64, genoma-production, highmem]", workflow)
        self.assertIn("validate_grch38.sh", workflow)
        self.assertIn("GRCh38.lock.sha256.approved", workflow)
        self.assertIn("validate_bwa_mem2_functional.sh", workflow)


if __name__ == "__main__":
    unittest.main()
