import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.workflow_test_utils import job_block as _job_block


ROOT = Path(__file__).resolve().parents[1]


RETIRED_CODACY_IDENTIFIERS = (
    "codacy_api_report",
    "codacy_pr_comment",
    "codacy-api-report",
    "CODACY_REPORT_",
    "Codacy API",
)
RETIRED_CODACY_REFERENCE_ALLOWLIST = frozenset(
    {
        "docs/superpowers/evidence/2026-09-03-pr36-local-validation-5953286.md",
        "docs/superpowers/evidence/2026-09-03-pr36-local-validation-977a531.md",
        "docs/superpowers/specs/2026-09-03-local-first-ci-architecture-design.md",
        "tests/test_workflow_contracts.py",
    }
)


def _tracked_repository_paths(root: Path) -> tuple[Path, ...]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return tuple(
        Path(raw.decode("utf-8"))
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def _retired_codacy_reference_violations(
    root: Path, paths: tuple[Path, ...]
) -> list[str]:
    violations: list[str] = []
    for relative in paths:
        normalized = relative.as_posix()
        if normalized in RETIRED_CODACY_REFERENCE_ALLOWLIST:
            continue
        candidate = root / relative
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for identifier in RETIRED_CODACY_IDENTIFIERS:
            if identifier in content:
                violations.append(f"{normalized}: {identifier}")
    return violations

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


def _shell_code_before_comment(command: str) -> str:
    in_single_quote = False
    in_double_quote = False
    escaped = False
    for index, char in enumerate(command):
        if escaped:
            escaped = False
            continue
        if char == "\\" and not in_single_quote:
            escaped = True
            continue
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            continue
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            continue
        if (
            char == "#"
            and not in_single_quote
            and not in_double_quote
            and (index == 0 or command[index - 1].isspace() or command[index - 1] in ";&|()<>")
        ):
            return command[:index].rstrip()
    return command


def _step_run_commands(step: str) -> tuple[str, ...]:
    lines = step.splitlines()
    commands: list[str] = []
    in_block = False
    control_depth = 0
    command_continuation = False
    heredoc_ends: list[str] = []
    block_starters = re.compile(r"(?:^|[;&|]\s*)(?:if|for|while|until|case)\b")
    short_circuit_group = re.compile(r"(?:&&|\|\|)\s*\{")
    continued_command = re.compile(r"(?:(?:&&|\|\|)\s*(?:\\\s*)?(?:#.*)?|\\\s*)$")
    block_enders = re.compile(r"^(?:fi|done|esac)\b")
    function_starter = re.compile(
        r"^(?:(?:function\s+)?[A-Za-z_][A-Za-z0-9_]*\s*\(\)"
        r"|function\s+[A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s*\{.*|\s*(?:#.*)?)$"
    )
    heredoc_pattern = re.compile(
        r"<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|([^\s;&|<>]+))"
    )
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
        if heredoc_ends:
            if command == heredoc_ends[0]:
                heredoc_ends.pop(0)
            continue
        shell_code = _shell_code_before_comment(command)
        if block_enders.match(shell_code) or (shell_code == "}" and control_depth > 0):
            control_depth = max(0, control_depth - 1)
            continue
        was_command_continuation = command_continuation
        command_continuation = continued_command.search(shell_code) is not None
        opens_control = block_starters.search(shell_code) is not None
        opens_function = function_starter.match(shell_code) is not None
        opens_short_circuit_group = short_circuit_group.search(shell_code) is not None
        if control_depth == 0 and not was_command_continuation and not (
            opens_control or opens_function or opens_short_circuit_group
        ):
            commands.append(shell_code)
        for heredoc in heredoc_pattern.finditer(shell_code):
            delimiter = next((group for group in heredoc.groups() if group is not None), None)
            if delimiter is not None:
                heredoc_ends.append(delimiter)
        if opens_control or opens_function or opens_short_circuit_group:
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

    def test_validate_repo_command_detection_rejects_uncalled_shell_function(self):
        function_only = """      - name: misleading
        run: |
          validate_gate() {
            python3 scripts/validate_repo.py
          }
"""
        direct = """      - name: validate
        run: python3 scripts/validate_repo.py
"""
        self.assertFalse(_step_runs_validate_repo(function_only))
        self.assertTrue(_step_runs_validate_repo(direct))

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

    def test_validate_repo_command_detection_rejects_midline_and_short_circuit_blocks(self):
        midline_if = """      - name: misleading
        run: |
          setup(); if false; then
            python3 scripts/validate_repo.py
          fi
"""
        short_circuit_group = """      - name: misleading
        run: |
          false && {
            python3 scripts/validate_repo.py
          }
"""
        self.assertFalse(_step_runs_validate_repo(midline_if))
        self.assertFalse(_step_runs_validate_repo(short_circuit_group))

    def test_validate_repo_command_detection_rejects_multiline_function_and_numeric_heredoc(self):
        multiline_function = """      - name: misleading
        run: |
          validate_gate()
          {
            python3 scripts/validate_repo.py
          }
"""
        numeric_heredoc = """      - name: misleading
        run: |
          cat <<1EOF
          python3 scripts/validate_repo.py
          1EOF
"""
        self.assertFalse(_step_runs_validate_repo(multiline_function))
        self.assertFalse(_step_runs_validate_repo(numeric_heredoc))

    def test_validate_repo_command_detection_rejects_commented_function_and_hyphenated_heredoc(self):
        commented_function = """      - name: misleading
        run: |
          validate_gate() { # definition only
            python3 scripts/validate_repo.py
          }
"""
        hyphenated_heredoc = """      - name: misleading
        run: |
          cat <<'EOF-1'
          EOF
          python3 scripts/validate_repo.py
          EOF-1
"""
        self.assertFalse(_step_runs_validate_repo(commented_function))
        self.assertFalse(_step_runs_validate_repo(hyphenated_heredoc))

    def test_validate_repo_command_detection_rejects_continued_short_circuit_operators(self):
        continued_and = """      - name: misleading
        run: |
          false &&
          python3 scripts/validate_repo.py
          true
"""
        continued_or = """      - name: misleading
        run: |
          true ||
          python3 scripts/validate_repo.py
          true
"""
        self.assertFalse(_step_runs_validate_repo(continued_and))
        self.assertFalse(_step_runs_validate_repo(continued_or))

    def test_validate_repo_command_detection_rejects_backslash_continued_short_circuit_operators(self):
        slash = "\\"
        continued_and = (
            "      - name: misleading\n"
            "        run: |\n"
            f"          false && {slash}\n"
            "          python3 scripts/validate_repo.py\n"
            "          true\n"
        )
        continued_or = (
            "      - name: misleading\n"
            "        run: |\n"
            f"          true || {slash}\n"
            "          python3 scripts/validate_repo.py\n"
            "          true\n"
        )
        self.assertFalse(_step_runs_validate_repo(continued_and))
        self.assertFalse(_step_runs_validate_repo(continued_or))

    def test_validate_repo_command_detection_rejects_generic_backslash_continuation(self):
        slash = "\\"
        continued = (
            "      - name: misleading\n"
            "        run: |\n"
            f"          true {slash}\n"
            "          python3 scripts/validate_repo.py\n"
            "          true\n"
        )
        self.assertFalse(_step_runs_validate_repo(continued))

    def test_validate_repo_command_detection_ignores_backslash_in_inline_comment(self):
        slash = "\\"
        executable = (
            "      - name: validate\n"
            "        run: |\n"
            f"          echo setup # {slash}\n"
            "          python3 scripts/validate_repo.py\n"
        )
        self.assertTrue(_step_runs_validate_repo(executable))

    def test_validate_repo_command_detection_rejects_multiple_heredocs(self):
        multiple_heredocs = """      - name: misleading
        run: |
          cat <<FIRST <<SECOND
          ignored first body
          FIRST
          python3 scripts/validate_repo.py
          SECOND
"""
        self.assertFalse(_step_runs_validate_repo(multiple_heredocs))

    def test_validate_repo_command_detection_rejects_inline_body_function_definition(self):
        inline_body_function = """      - name: misleading
        run: |
          validate_gate() { : "setup";
            python3 scripts/validate_repo.py
          }
"""
        self.assertFalse(_step_runs_validate_repo(inline_body_function))

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
        status_rule = next((rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks"), None)
        self.assertIsNotNone(status_rule)
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


    def test_retired_codacy_scan_rejects_stray_active_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stray = root / "scripts" / "stray.py"
            stray.parent.mkdir(parents=True)
            stray.write_text("value = 'CODACY_REPORT_TOKEN'\n", encoding="utf-8")
            self.assertEqual(
                ["scripts/stray.py: CODACY_REPORT_"],
                _retired_codacy_reference_violations(root, (Path("scripts/stray.py"),)),
            )

    def test_retired_codacy_scan_allows_only_explicit_history_and_its_own_contract(self):
        self.assertEqual(
            RETIRED_CODACY_REFERENCE_ALLOWLIST,
            frozenset(
                {
                    "docs/superpowers/evidence/2026-09-03-pr36-local-validation-5953286.md",
                    "docs/superpowers/evidence/2026-09-03-pr36-local-validation-977a531.md",
                    "docs/superpowers/specs/2026-09-03-local-first-ci-architecture-design.md",
                    "tests/test_workflow_contracts.py",
                }
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = root / "docs/superpowers/evidence/2026-09-03-pr36-local-validation-5953286.md"
            protected = root / "tests/stray_regression.py"
            historical.parent.mkdir(parents=True)
            protected.parent.mkdir(parents=True)
            historical.write_text("legacy codacy-api-report note\n", encoding="utf-8")
            protected.write_text("legacy codacy-api-report note\n", encoding="utf-8")
            self.assertEqual(
                ["tests/stray_regression.py: codacy-api-report"],
                _retired_codacy_reference_violations(
                    root,
                    (
                        Path("docs/superpowers/evidence/2026-09-03-pr36-local-validation-5953286.md"),
                        Path("tests/stray_regression.py"),
                    ),
                ),
            )

    def test_retired_codacy_api_reporting_is_fully_removed(self):
        retired_paths = (
            ".github/workflows/codacy-api-report.yml",
            ".github/workflows/codacy-api-report-tests.yml",
            "scripts/codacy_api_report.py",
            "scripts/codacy_pr_comment.js",
            "tests/test_codacy_api_report.py",
            "tests/test_codacy_pr_comment.js",
            "tests/test_codacy_workflow_security.py",
            "docs/CODACY_API_INTEGRATION.md",
        )
        for path in retired_paths:
            self.assertFalse((ROOT / path).exists(), f"retired Codacy API component remains: {path}")

        violations = _retired_codacy_reference_violations(
            ROOT, _tracked_repository_paths(ROOT)
        )
        self.assertEqual([], violations)

if __name__ == "__main__":
    unittest.main()
