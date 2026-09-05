import ast
import importlib.util
import re
import unittest
from pathlib import Path
from types import ModuleType

from tests.workflow_test_utils import job_block as _job_block


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CLASSIFIER = ROOT / "scripts" / "ci_change_classifier.py"


def _load_classifier() -> ModuleType:
    if not CLASSIFIER.is_file():
        raise AssertionError("CI change classifier is missing")
    spec = importlib.util.spec_from_file_location("ci_change_classifier", CLASSIFIER)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load CI change classifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

CONCURRENCY_WORKFLOWS = (
    "fallow.yml",
    "genoma-audit.yml",
    "genoma-ngs-runtime-gate.yml",
    "genoma-policy-engine.yml",
    "genoma-snp-array.yml",
    "genoma-visual-qa-candidates.yml",
    "pr30-regressions.yml",
    "scaffold-validation.yml",
)

CONCURRENCY_BLOCK = """concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
"""

DRAFT_READY_EVENT = "ready_for_review"
DRAFT_READY_TYPES_LINE = "types: [opened, synchronize, reopened, ready_for_review]"
DRAFT_GATE = "github.event_name != 'pull_request' || github.event.pull_request.draft == false"


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _pull_request_types(workflow: str) -> tuple[str, ...]:
    in_on = False
    in_pull_request = False
    for line in workflow.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = _indent(line)
        if indent == 0:
            in_on = stripped == "on:"
            in_pull_request = False
            if stripped == "jobs:":
                break
            continue
        if in_on and indent == 2:
            in_pull_request = stripped == "pull_request:"
            continue
        if in_on and in_pull_request and indent == 4 and stripped.startswith("types:"):
            value = stripped.split(":", 1)[1].strip()
            if not (value.startswith("[") and value.endswith("]")):
                raise AssertionError("pull_request.types must use the canonical inline list")
            return tuple(
                item.strip().strip("\"'")
                for item in value[1:-1].split(",")
                if item.strip()
            )
    return ()


def _runner_job_conditions(workflow: str) -> dict[str, str]:
    lines = workflow.splitlines()
    jobs_start = next(
        (index for index, line in enumerate(lines) if _indent(line) == 0 and line.strip() == "jobs:"),
        None,
    )
    if jobs_start is None:
        return {}

    jobs: dict[str, str] = {}
    index = jobs_start + 1
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indent = _indent(line)
        if stripped and indent == 0:
            break
        if not stripped or indent != 2 or not stripped.endswith(":"):
            index += 1
            continue

        job_name = stripped[:-1]
        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            if candidate.strip() and _indent(candidate) <= 2:
                break
            end += 1

        has_runner = False
        job_if = ""
        cursor = index + 1
        while cursor < end:
            candidate = lines[cursor]
            candidate_stripped = candidate.strip()
            if _indent(candidate) == 4 and candidate_stripped.startswith("runs-on:"):
                has_runner = True
            if _indent(candidate) == 4 and candidate_stripped.startswith("if:"):
                raw = candidate_stripped.split(":", 1)[1].strip()
                if raw in {">", ">-", "|", "|-"}:
                    parts: list[str] = []
                    nested = cursor + 1
                    while nested < end and (not lines[nested].strip() or _indent(lines[nested]) > 4):
                        if lines[nested].strip():
                            parts.append(lines[nested].strip())
                        nested += 1
                    job_if = " ".join(parts)
                else:
                    job_if = raw
            cursor += 1

        if has_runner:
            jobs[job_name] = " ".join(job_if.replace("${{", "").replace("}}", "").split())
        index = end
    return jobs


def _job_is_non_pr_only(condition: str) -> bool:
    if not condition or "||" in condition:
        return False
    required_events = re.findall(r"github\.event_name\s*==\s*['\"]([^'\"]+)['\"]", condition)
    return bool(required_events) and all(event != "pull_request" for event in required_events)


def _strip_wrapping_parentheses(expression: str) -> str:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        quote = ""
        wraps_entire_expression = True
        for index, char in enumerate(expression):
            if quote:
                if char == quote and (index == 0 or expression[index - 1] != "\\"):
                    quote = ""
                continue
            if char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(expression) - 1:
                    wraps_entire_expression = False
                    break
        if not wraps_entire_expression or depth != 0:
            break
        expression = expression[1:-1].strip()
    return " ".join(expression.split())


def _top_level_and_terms(expression: str) -> list[str]:
    terms: list[str] = []
    depth = 0
    quote = ""
    start = 0
    index = 0
    while index < len(expression):
        char = expression[index]
        if quote:
            if char == quote and (index == 0 or expression[index - 1] != "\\"):
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and expression.startswith("&&", index):
            terms.append(expression[start:index].strip())
            index += 2
            start = index
            continue
        index += 1
    terms.append(expression[start:].strip())
    return [term for term in terms if term]


def _draft_gate_is_required_conjunct(condition: str) -> bool:
    normalized_gate = " ".join(DRAFT_GATE.split())
    return any(
        _strip_wrapping_parentheses(term) == normalized_gate
        for term in _top_level_and_terms(condition)
    )


def _draft_contract_errors(workflow: str) -> list[str]:
    errors: list[str] = []
    pr_types = _pull_request_types(workflow)
    if DRAFT_READY_EVENT not in pr_types:
        errors.append("ready_for_review is missing from on.pull_request.types")

    runner_jobs = _runner_job_conditions(workflow)
    if not runner_jobs:
        errors.append("workflow contains no runner jobs")
        return errors

    pr_runner_jobs = {
        name: condition
        for name, condition in runner_jobs.items()
        if not _job_is_non_pr_only(condition)
    }
    if not pr_runner_jobs:
        errors.append("workflow contains no pull-request-capable runner jobs")
        return errors

    normalized_gate = " ".join(DRAFT_GATE.split())
    for job_name, condition in pr_runner_jobs.items():
        if normalized_gate not in condition:
            errors.append(f"{job_name}: job-level draft gate missing")
        elif not _draft_gate_is_required_conjunct(condition):
            errors.append(f"{job_name}: job-level draft gate not structurally enforced")
    return errors


def _subprocess_references(source: str) -> list[str]:
    findings: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            findings.extend(alias.name for alias in node.names if alias.name == "subprocess" or alias.name.startswith("subprocess."))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "subprocess" or module.startswith("subprocess."):
                findings.append(module)
        elif isinstance(node, ast.Name) and node.id == "subprocess":
            findings.append(node.id)
    return findings


class CIOptimizationContractTest(unittest.TestCase):
    def _assert_job_gate(self, workflow: str, job_name: str, output_name: str) -> None:
        job = _job_block(workflow, job_name)
        self.assertIn("needs: changes", job)
        self.assertIn("always() &&", job)
        self.assertIn("needs.changes.result != 'success'", job)
        self.assertIn(f"needs.changes.outputs.{output_name} == 'true'", job)
        self.assertIn("Require successful scope classification", job)

    def test_validation_workflows_cancel_superseded_pr_runs(self):
        for name in CONCURRENCY_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertIn(CONCURRENCY_BLOCK, _read(name))

    def test_draft_pr_validation_defers_runner_jobs_until_ready(self):
        for workflow_name in CONCURRENCY_WORKFLOWS:
            with self.subTest(workflow=workflow_name):
                self.assertEqual([], _draft_contract_errors(_read(workflow_name)))

    def test_draft_contract_rejects_misplaced_gate_and_ready_event(self):
        workflow = _read("scaffold-validation.yml")

        gate_mutant = workflow.replace(DRAFT_GATE, "true", 1)
        gate_mutant = gate_mutant.replace(
            "    runs-on:",
            f"    # retained text must not satisfy the contract: {DRAFT_GATE}\n    runs-on:",
            1,
        )
        gate_errors = _draft_contract_errors(gate_mutant)
        self.assertTrue(any("job-level draft gate missing" in error for error in gate_errors), gate_errors)

        weakened_mutant = workflow.replace(DRAFT_GATE, f"({DRAFT_GATE}) || true", 1)
        weakened_errors = _draft_contract_errors(weakened_mutant)
        self.assertTrue(
            any("job-level draft gate not structurally enforced" in error for error in weakened_errors),
            weakened_errors,
        )

        event_mutant = workflow.replace(
            f"    {DRAFT_READY_TYPES_LINE}",
            "    types: [opened, synchronize, reopened]",
            1,
        )
        event_mutant = event_mutant.replace(
            "  push:",
            f"  # misplaced text must not satisfy the contract: {DRAFT_READY_TYPES_LINE}\n  push:",
            1,
        )
        event_errors = _draft_contract_errors(event_mutant)
        self.assertIn("ready_for_review is missing from on.pull_request.types", event_errors)

    def test_policy_classifier_behavior_on_real_path_lists(self):
        classifier = _load_classifier()
        self.assertTrue(classifier.policy_relevant(["policy_engine/policy/rego/main.rego"]))
        self.assertTrue(classifier.policy_relevant(["scripts/sealed_ruleset.py"]))
        self.assertTrue(classifier.policy_relevant([".github/governance/main-ruleset.json"]))
        self.assertTrue(
            classifier.policy_relevant(["notes.md", "policy_engine/policy/rego/main.rego"])
        )
        self.assertFalse(classifier.policy_relevant(["docs/architecture.md"]))

    def test_markdown_classifier_behavior_on_modifications_deletions_and_renames(self):
        classifier = _load_classifier()
        self.assertFalse(classifier.validation_required(["docs/architecture.md"], []))
        self.assertTrue(
            classifier.validation_required(["docs/architecture.md"], ["docs/required-contract.md"])
        )
        self.assertTrue(classifier.validation_required(["notes.md", "src/code.py"], []))
        self.assertTrue(classifier.validation_required(["src/code.py", "notes.md"], ["src/code.py"]))

    def test_classifier_is_process_free_and_path_list_driven(self):
        source = CLASSIFIER.read_text(encoding="utf-8")
        self.assertEqual([], _subprocess_references(source))
        self.assertNotEqual([], _subprocess_references("from subprocess import run\nrun([])\n"))
        self.assertIn('parser.add_argument("--changed"', source)
        self.assertIn('parser.add_argument("--deleted"', source)

    def test_fallow_runs_only_for_javascript_typescript_surfaces(self):
        workflow = _read("fallow.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertIn("paths:\n", pull_request)
        expected_paths = (
            "'mcp/**/*.ts'",
            "'mcp/**/*.js'",
            "'mcp/package.json'",
            "'mcp/package-lock.json'",
            "'mcp/tsconfig.json'",
            "'mcp/.fallowrc.json'",
            "'.fallowrc.json'",
            "'.github/workflows/fallow.yml'",
        )
        for expected in expected_paths:
            self.assertIn(expected, pull_request)
        self.assertNotIn("'mcp/**'", pull_request)

    def test_four_plane_audit_skips_only_safe_markdown_modifications(self):
        workflow = _read("genoma-audit.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        push = header.split("  push:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertNotIn("paths-ignore:", pull_request)
        self.assertNotIn("paths-ignore:", push)
        changes = _job_block(workflow, "changes")
        self.assertIn("audit_required:", changes)
        self.assertIn('changed_paths="$RUNNER_TEMP/audit-changed-paths.zlist"', changes)
        self.assertIn('deleted_paths="$RUNNER_TEMP/audit-deleted-paths.zlist"', changes)
        self.assertIn('git diff --no-renames --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$changed_paths"', changes)
        self.assertIn('git diff --no-renames --diff-filter=D --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$deleted_paths"', changes)
        self.assertIn('bash scripts/ci_changed_paths.sh "$BASE_SHA" "$HEAD_SHA" "$changed_paths" "$deleted_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py markdown --changed "$changed_paths" --deleted "$deleted_paths"', changes)
        self.assertIn('scripts/ci_changed_paths.sh|scripts/ci_change_classifier.py|.github/workflows/genoma-audit.yml', changes)
        self._assert_job_gate(workflow, "audit", "audit_required")

    def test_policy_required_checks_use_job_level_scope_gates(self):
        workflow = _read("genoma-policy-engine.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        self.assertNotIn("paths:", pull_request)
        changes = _job_block(workflow, "changes")
        self.assertIn("policy_relevant:", changes)
        self.assertIn('changed_paths="$RUNNER_TEMP/policy-changed-paths.zlist"', changes)
        self.assertIn('git diff --no-renames --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$changed_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py policy --changed "$changed_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py|.github/workflows/genoma-policy-engine.yml', changes)
        push = header.split("  push:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertIn("'scripts/sealed_ruleset.py'", push)
        self.assertIn("'scripts/ci_change_classifier.py'", push)
        self.assertIn("'.github/governance/**'", push)

        for job_name in ("policy", "rego", "container"):
            self._assert_job_gate(workflow, job_name, "policy_relevant")

        self.assertNotIn("\n  secrets:\n", workflow)
        self.assertNotIn("Gitleaks secret scan", workflow)
        publish = _job_block(workflow, "publish")
        self.assertIn("needs: [policy, rego, container]", publish)
        for required_name in (
            "Canonical policy + 263-rule contract",
            "OPA/Rego parity",
            "Real Docker + canonical read-only mount",
        ):
            self.assertIn(f"name: {required_name}", workflow)

    def test_required_check_classifiers_use_checked_diffs_without_process_substitution(self):
        for workflow_name in ("genoma-policy-engine.yml", "scaffold-validation.yml"):
            with self.subTest(workflow=workflow_name):
                changes = _job_block(_read(workflow_name), "changes")
                self.assertIn("set -euo pipefail", changes)
                self.assertIn('git diff --no-renames --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$changed_paths"', changes)
                self.assertNotIn("done < <(git diff", changes)
                self.assertIn("scripts/ci_change_classifier.py", changes)

    def test_changed_path_shell_helper_is_wired_and_behaviorally_exercised(self):
        helper = ROOT / "scripts" / "ci_changed_paths.sh"
        regression = ROOT / "tests" / "test_ci_changed_paths.sh"
        self.assertTrue(helper.is_file())
        self.assertTrue(regression.is_file())
        helper_text = helper.read_text(encoding="utf-8")
        self.assertIn("0000000000000000000000000000000000000000", helper_text)
        self.assertIn('git ls-tree -r --name-only -z "$head_sha" --', helper_text)
        self.assertIn('git diff --no-renames --name-only -z "$base_sha" "$head_sha" --', helper_text)
        self.assertIn('git diff --no-renames --diff-filter=D --name-only -z "$base_sha" "$head_sha" --', helper_text)
        static = _job_block(_read("scaffold-validation.yml"), "static")
        self.assertIn("bash tests/test_ci_changed_paths.sh", static)

    def test_scaffold_required_checks_use_job_level_markdown_gate(self):
        workflow = _read("scaffold-validation.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        push = header.split("  push:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertNotIn("paths:", pull_request)
        self.assertNotIn("paths-ignore:", push)
        changes = _job_block(workflow, "changes")
        self.assertIn("validation_required:", changes)
        self.assertIn('changed_paths="$RUNNER_TEMP/scaffold-changed-paths.zlist"', changes)
        self.assertIn('deleted_paths="$RUNNER_TEMP/scaffold-deleted-paths.zlist"', changes)
        self.assertIn('git diff --no-renames --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$changed_paths"', changes)
        self.assertIn('git diff --no-renames --diff-filter=D --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$deleted_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py markdown --changed "$changed_paths" --deleted "$deleted_paths"', changes)
        self.assertIn('scripts/ci_changed_paths.sh|scripts/ci_change_classifier.py|.github/workflows/scaffold-validation.yml', changes)
        self.assertIn('PUSH_BASE_SHA: ${{ github.event.before }}', changes)
        self.assertIn('CURRENT_SHA: ${{ github.sha }}', changes)
        self.assertIn('bash scripts/ci_changed_paths.sh "$BASE_SHA" "$HEAD_SHA" "$changed_paths" "$deleted_paths"', changes)

        for job_name in ("static", "container-canary"):
            self._assert_job_gate(workflow, job_name, "validation_required")

        self.assertIn("  static:\n", workflow)
        self.assertIn("  container-canary:\n", workflow)
        publish = _job_block(workflow, "publish-ghcr")
        self.assertIn("needs: [static, container-canary]", publish)


if __name__ == "__main__":
    unittest.main()
