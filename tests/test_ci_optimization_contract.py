import ast
import importlib.util
import json
import re
import unittest
from pathlib import Path
from types import ModuleType

from tests.workflow_test_utils import job_block as _job_block


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CLASSIFIER = ROOT / "scripts" / "ci_change_classifier.py"


def _ngs_script_dependency_closure() -> set[str]:
    script_dir = ROOT / "scripts"
    seeds: set[str] = set()
    for source in (
        _read("genoma-ngs-runtime-gate.yml"),
        (ROOT / "main.nf").read_text(encoding="utf-8"),
        (ROOT / "workflows/wgs.nf").read_text(encoding="utf-8"),
        (ROOT / "workflows/array.nf").read_text(encoding="utf-8"),
    ):
        seeds.update(re.findall(r"scripts/[A-Za-z0-9_.-]+\.(?:py|sh)", source))
    excluded = {"scripts/validate_repo.py", "scripts/verify_supply_chain_lock.py"}
    closure = set(seeds)
    queue = list(closure)
    filename_pattern = re.compile(
        r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+\.(?:py|sh))(?![A-Za-z0-9_.-])"
    )
    python_by_module = {candidate.stem: candidate.name for candidate in script_dir.glob("*.py")}

    while queue:
        relative = queue.pop()
        candidate = ROOT / relative
        if not candidate.is_file():
            continue
        source = candidate.read_text(encoding="utf-8")
        local_references: list[str] = []
        modules: list[str] = []

        if candidate.suffix == ".sh":
            local_references.extend(filename_pattern.findall(source))
        elif candidate.suffix == ".py":
            tree = ast.parse(source, filename=str(candidate))
            if relative not in excluded:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        local_references.extend(filename_pattern.findall(node.value))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.append(node.module)

        for filename in local_references:
            dependency = f"scripts/{filename}"
            if (ROOT / dependency).is_file() and dependency not in excluded and dependency not in closure:
                closure.add(dependency)
                queue.append(dependency)

        for module in modules:
            if module == "scripts" or module.startswith("scripts."):
                package_init = "scripts/__init__.py"
                if package_init not in closure:
                    closure.add(package_init)
                    queue.append(package_init)
            short = module.removeprefix("scripts.").split(".")[0]
            filename = python_by_module.get(short)
            dependency = f"scripts/{filename}" if filename else ""
            if dependency and dependency not in excluded and dependency not in closure:
                closure.add(dependency)
                queue.append(dependency)

    return closure - excluded

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
    "genoma-ngs-runtime-gate.yml",
    "genoma-policy-engine.yml",
    "genoma-snp-array.yml",
    "genoma-visual-qa-candidates.yml",
    "scaffold-validation.yml",
)

CONCURRENCY_BLOCK = """concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
"""

DRAFT_READY_EVENT = "ready_for_review"
REQUIRED_PR_TYPES = ("opened", "synchronize", "reopened", "ready_for_review")
DRAFT_READY_TYPES_LINE = "types: [opened, synchronize, reopened, ready_for_review]"
DRAFT_GATE = "github.event_name != 'pull_request' || github.event.pull_request.draft == false"

NGS_TRIGGER_SCRIPT_PATHS = (
    "scripts/__init__.py",
    "scripts/annotate_partial_genome.py",
    "scripts/build_adapter_capabilities.py",
    "scripts/build_array_case_manifest.py",
    "scripts/build_bwa_mem2_index.sh",
    "scripts/build_wgs_curated_manifest.py",
    "scripts/check_versions.sh",
    "scripts/code_language_guard.py",
    "scripts/freshness_gate.py",
    "scripts/generate_all_reports.py",
    "scripts/generate_canary.py",
    "scripts/latest_runtime_resource_gate.py",
    "scripts/materialize_ruleset.py",
    "scripts/prepare_latest_candidate.py",
    "scripts/prepare_report_release.py",
    "scripts/promote_latest_candidate.py",
    "scripts/refresh_evidence_sources.py",
    "scripts/run_canary.sh",
    "scripts/run_snp_array.py",
    "scripts/runtime_resource_gate.py",
    "scripts/runtime_stack.py",
    "scripts/score_variants.py",
    "scripts/sealed_ruleset.py",
    "scripts/validate_bwa_mem2_functional.sh",
    "scripts/validate_grch38.sh",
    "scripts/verify_runtime_gate_manifest.py",
    "scripts/wgs_align_or_stage.sh",
    "scripts/wgs_consent_gate.py",
    "scripts/wgs_input_gate.py",
    "scripts/wgs_materialize_verified_input.py",
)


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _visual_qa_test_dependency_paths() -> set[str]:
    tests_dir = ROOT / "tests"
    local_modules = {candidate.stem: candidate for candidate in tests_dir.glob("*.py")}
    pending = [
        "tests/test_editorial_renderers.py",
        "tests/test_template_v3_contract.py",
    ]
    closure = set(pending)
    while pending:
        relative = pending.pop()
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        for module in modules:
            short = module.removeprefix("tests.").split(".")[0]
            candidate = local_modules.get(short)
            if candidate is None:
                continue
            dependency = candidate.relative_to(ROOT).as_posix()
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    return closure


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


def _has_top_level_or(expression: str) -> bool:
    depth = 0
    quote = ""
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
        elif depth == 0 and expression.startswith("||", index):
            return True
        index += 1
    return False


def _draft_gate_is_required_conjunct(condition: str) -> bool:
    normalized_gate = " ".join(DRAFT_GATE.split())
    normalized_condition = _strip_wrapping_parentheses(condition)
    if normalized_condition == normalized_gate:
        return True
    if _has_top_level_or(condition):
        return False
    return any(
        _strip_wrapping_parentheses(term) == normalized_gate
        for term in _top_level_and_terms(condition)
    )


def _draft_contract_errors(workflow: str) -> list[str]:
    errors: list[str] = []
    pr_types = _pull_request_types(workflow)
    if DRAFT_READY_EVENT not in pr_types:
        errors.append("ready_for_review is missing from on.pull_request.types")
    elif pr_types != REQUIRED_PR_TYPES:
        errors.append("on.pull_request.types does not match the required event list")

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


def _pr_template_draft_flow_errors(template: str) -> list[str]:
    errors: list[str] = []
    visible_template = re.sub(r"<!--.*?(?:-->|$)", "", template, flags=re.DOTALL)
    try:
        section = visible_template.split("## CI / GitHub Actions", 1)[1].split("## Mudan\u00e7a can\u00f4nica", 1)[0]
    except IndexError:
        return ["CI / GitHub Actions section is missing or not bounded"]
    markers = (
        "mantenha a PR como Draft",
        "Confirmar que o HEAD exato est\u00e1 validado localmente",
        "Marcar a PR como Ready for Review",
        "Ap\u00f3s Ready for Review, aguardar todos os checks obrigat\u00f3rios do GitHub Actions no HEAD exato",
    )
    positions: list[int] = []
    for marker in markers:
        index = section.find(marker)
        if index < 0:
            errors.append(f"draft-first flow marker missing: {marker}")
        positions.append(index)
    if all(index >= 0 for index in positions) and positions != sorted(positions):
        errors.append("draft-first flow markers are out of order")
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


def _job_if_expression(workflow: str, job_name: str) -> str:
    job = _job_block(workflow, job_name)
    lines = job.splitlines()
    for index, line in enumerate(lines):
        if _indent(line) != 4 or not line.strip().startswith("if:"):
            continue
        raw = line.strip().split(":", 1)[1].strip()
        if raw not in {">", ">-", "|", "|-"}:
            return " ".join(raw.replace("${{", "").replace("}}", "").split())
        parts: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and (not lines[cursor].strip() or _indent(lines[cursor]) > 4):
            if lines[cursor].strip():
                parts.append(lines[cursor].strip())
            cursor += 1
        return " ".join(parts)
    raise AssertionError(f"job {job_name!r} has no job-level if condition")


def _four_plane_audit_orchestration_errors(scaffold: str, audit: str) -> list[str]:
    errors: list[str] = []
    caller = _job_block(scaffold, "four-plane-audit")
    for token in (
        "needs: [changes, static]",
        "uses: ./.github/workflows/genoma-audit.yml",
    ):
        if token not in caller:
            errors.append(f"four-plane-audit caller missing: {token}")

    condition = _job_if_expression(scaffold, "four-plane-audit")
    if _has_top_level_or(condition):
        errors.append("four-plane-audit caller has top-level OR bypass")
    terms = {_strip_wrapping_parentheses(term) for term in _top_level_and_terms(condition)}
    required_terms = {
        "always()",
        _strip_wrapping_parentheses(DRAFT_GATE),
        "needs.changes.result == 'success'",
        "needs.changes.outputs.validation_required == 'true'",
        "needs.static.result == 'success'",
    }
    for term in required_terms - terms:
        errors.append(f"four-plane-audit caller missing exact condition term: {term}")

    header = audit.split("permissions:", 1)[0]
    if "on:\n  workflow_call:\n" not in header:
        errors.append("genoma-audit must expose workflow_call")
    for forbidden in ("pull_request:", "push:", "workflow_dispatch:"):
        if forbidden in header:
            errors.append(f"genoma-audit direct trigger forbidden: {forbidden}")
    if "concurrency:" in audit:
        errors.append("reusable genoma-audit must not own concurrency")
    return errors


class CIOptimizationContractTest(unittest.TestCase):
    def _assert_job_gate(self, workflow: str, job_name: str, output_name: str) -> None:
        job = _job_block(workflow, job_name)
        self.assertIn("needs: changes", job)
        self.assertIn("always() &&", job)
        self.assertIn("needs.changes.result != 'success'", job)
        self.assertIn(f"needs.changes.outputs.{output_name} == 'true'", job)
        self.assertIn("Require successful scope classification", job)

    def test_pr_template_documents_draft_first_final_ci_boundary(self):
        template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
        self.assertEqual([], _pr_template_draft_flow_errors(template))

    def test_pr_template_draft_flow_rejects_unrelated_or_reordered_markers(self):
        template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
        ci_section, rest = template.split("## Mudan\u00e7a can\u00f4nica", 1)
        final_line = "- [ ] Ap\u00f3s Ready for Review, aguardar todos os checks obrigat\u00f3rios do GitHub Actions no HEAD exato\n"
        mutant = ci_section.replace(final_line, "") + "## Mudan\u00e7a can\u00f4nica" + rest + "\n" + final_line
        self.assertTrue(_pr_template_draft_flow_errors(mutant))

        markers = (
            "mantenha a PR como Draft",
            "Confirmar que o HEAD exato est\u00e1 validado localmente",
            "Marcar a PR como Ready for Review",
            "Ap\u00f3s Ready for Review, aguardar todos os checks obrigat\u00f3rios do GitHub Actions no HEAD exato",
        )
        commented = template
        for marker in markers:
            commented = commented.replace(marker, "", 1)
        payload = "<!-- " + " | ".join(markers) + " -->\n"
        commented = commented.replace("## Mudan\u00e7a can\u00f4nica", payload + "## Mudan\u00e7a can\u00f4nica", 1)
        self.assertTrue(_pr_template_draft_flow_errors(commented))

        spanning_comment = template.replace("## CI / GitHub Actions", "<!--\n## CI / GitHub Actions", 1)
        spanning_comment = spanning_comment.replace("## Mudan\u00e7a can\u00f4nica", "-->\n## Mudan\u00e7a can\u00f4nica", 1)
        self.assertTrue(_pr_template_draft_flow_errors(spanning_comment))

        unclosed_comment = template.replace("## CI / GitHub Actions", "<!--\n## CI / GitHub Actions", 1)
        self.assertTrue(_pr_template_draft_flow_errors(unclosed_comment))

    def test_pr30_regressions_are_covered_by_required_static_suite_without_duplicate_workflow(self):
        self.assertFalse((WORKFLOWS / "pr30-regressions.yml").exists())
        self.assertTrue((ROOT / "tests" / "test_pr30_regressions.py").is_file())
        static = _job_block(_read("scaffold-validation.yml"), "static")
        self.assertIn("reporting/requirements.txt", static)
        self.assertIn("python3 -m unittest discover -s tests -v", static)

    def test_static_reuses_repository_contract_from_full_unittest_suite(self):
        static = _job_block(_read("scaffold-validation.yml"), "static")
        repo_contract = (ROOT / "tests" / "test_repo_contract.py").read_text(encoding="utf-8")
        self.assertIn("python3 -m unittest discover -s tests -v", static)
        self.assertNotIn("python3 scripts/validate_repo.py", static)
        self.assertIn("def test_contract_accepts_repository_scaffold", repo_contract)
        self.assertIn("validator.validate(root)", repo_contract)

    def test_visual_qa_uses_exact_test_dependencies_instead_of_all_tests(self):
        workflow = _read("genoma-visual-qa-candidates.yml")
        header = workflow.split("permissions:", 1)[0]
        push = header.split("  push:\n", 1)[1].split("  pull_request:\n", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        expected = _visual_qa_test_dependency_paths()
        self.assertEqual(
            expected,
            {
                "tests/test_editorial_renderers.py",
                "tests/test_template_v3_contract.py",
                "tests/ruleset_test_support.py",
            },
        )
        for event_block in (push, pull_request):
            self.assertNotIn("'tests/**'", event_block)
            self.assertIn("'normative/**'", event_block)
            configured = set(re.findall(r"^\s+- '(tests/[^']+)'$", event_block, re.MULTILINE))
            self.assertEqual(configured, expected)
        job = _job_block(workflow, "render-candidates")
        self.assertIn(
            "python3 -m unittest tests.test_editorial_renderers tests.test_template_v3_contract -v",
            job,
        )

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

        top_level_or_mutant = workflow.replace(
            DRAFT_GATE,
            f"({DRAFT_GATE}) && false || true",
            1,
        )
        top_level_or_errors = _draft_contract_errors(top_level_or_mutant)
        self.assertTrue(
            any("job-level draft gate not structurally enforced" in error for error in top_level_or_errors),
            top_level_or_errors,
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

        incomplete_event_mutant = workflow.replace(
            f"    {DRAFT_READY_TYPES_LINE}",
            "    types: [synchronize, reopened, ready_for_review]",
            1,
        )
        incomplete_event_errors = _draft_contract_errors(incomplete_event_mutant)
        self.assertIn("on.pull_request.types does not match the required event list", incomplete_event_errors)

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

    def test_container_classifier_skips_only_dockerignored_or_documentation_only_paths(self):
        classifier = _load_classifier()
        self.assertFalse(classifier.container_required(["tests/test_ci_optimization_contract.py"]))
        self.assertFalse(classifier.container_required(["docs/superpowers/plans/change.md"]))
        self.assertFalse(classifier.container_required([".github/workflows/fallow.yml"]))
        self.assertTrue(classifier.container_required([".github/workflows/new-runtime.yml"]))
        self.assertFalse(classifier.container_required(["README.md", "docs/architecture.md"]))
        self.assertTrue(classifier.container_required(["Dockerfile"]))
        self.assertTrue(classifier.container_required(["environment.yml"]))
        self.assertTrue(classifier.container_required(["mcp/src/server.ts"]))
        self.assertTrue(classifier.container_required(["scripts/run_canary.sh"]))
        self.assertTrue(classifier.container_required(["tests/unit.py", "main.nf"]))
        self.assertTrue(classifier.container_required([".github/workflows/scaffold-validation.yml"]))

    def test_scaffold_canary_uses_container_specific_path_gate(self):
        workflow = _read("scaffold-validation.yml")
        changes = _job_block(workflow, "changes")
        self.assertIn("container_required:", changes)
        self.assertIn('scripts/ci_change_classifier.py container --changed "$changed_paths"', changes)
        self._assert_job_gate(workflow, "static", "validation_required")
        self._assert_job_gate(workflow, "container-canary", "container_required")
        publish = _job_block(workflow, "publish-ghcr")
        self.assertIn("needs: [static, container-canary]", publish)

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

    def test_ngs_runtime_gate_uses_explicit_ngs_script_paths_instead_of_all_scripts(self):
        workflow = _read("genoma-ngs-runtime-gate.yml")
        closure = _ngs_script_dependency_closure()
        self.assertEqual(set(), closure - set(NGS_TRIGGER_SCRIPT_PATHS))
        for script_path in NGS_TRIGGER_SCRIPT_PATHS:
            self.assertTrue((ROOT / script_path).is_file(), script_path)

        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        push = header.split("  push:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        for event_block in (pull_request, push):
            self.assertIn("paths:\n", event_block)
            self.assertNotIn("'scripts/**'", event_block)
            self.assertNotIn("'scripts/validate_repo.py'", event_block)
            self.assertNotIn("'scripts/verify_supply_chain_lock.py'", event_block)
            for script_path in NGS_TRIGGER_SCRIPT_PATHS:
                self.assertIn(f"'{script_path}'", event_block)
            for preserved in (
                "'environment.yml'", "'Dockerfile'", "'main.nf'", "'nextflow.config'",
                "'workflows/**'", "'evidence_adapters/**'", "'locks/**'", "'normative/**'",
                "'.github/workflows/genoma-ngs-runtime-gate.yml'",
            ):
                self.assertIn(preserved, event_block)

    def test_trusted_heavy_checks_use_private_codework_runners_without_moving_write_jobs(self):
        trusted_runner = (
            "runs-on: ${{ github.event_name == 'pull_request' && "
            "'ubuntu-latest' || 'codework-isolated' }}"
        )
        private_jobs = {
            "scaffold-validation.yml": ("static",),
            "genoma-audit.yml": ("audit",),
            "genoma-policy-engine.yml": ("policy",),
        }
        for filename, jobs in private_jobs.items():
            workflow = _read(filename)
            for job_name in jobs:
                block = _job_block(workflow, job_name)
                self.assertIn(trusted_runner, block, f"{filename}:{job_name}")
                self.assertNotIn("runs-on: ubuntu-latest", block, f"{filename}:{job_name}")

        hosted_jobs = {
            "scaffold-validation.yml": ("changes", "container-canary", "publish-ghcr"),
            "genoma-policy-engine.yml": ("changes", "rego", "container", "publish"),
        }
        for filename, jobs in hosted_jobs.items():
            workflow = _read(filename)
            for job_name in jobs:
                block = _job_block(workflow, job_name)
                self.assertIn("runs-on: ubuntu-latest", block, f"{filename}:{job_name}")
                self.assertNotIn("codework-isolated", block, f"{filename}:{job_name}")

        static = _job_block(_read("scaffold-validation.yml"), "static")
        self.assertIn('export TMPDIR="$RUNNER_TEMP"', static)
        self.assertIn('run: TMPDIR="$RUNNER_TEMP" bash tests/test_wgs_align_or_stage.sh', static)
        self.assertIn('run: TMPDIR="$RUNNER_TEMP" bash tests/test_ci_changed_paths.sh', static)

    def test_four_plane_audit_is_reusable_and_gated_by_required_static(self):
        scaffold = _read("scaffold-validation.yml")
        audit = _read("genoma-audit.yml")
        self.assertEqual([], _four_plane_audit_orchestration_errors(scaffold, audit))

    def test_four_plane_audit_orchestration_rejects_weakened_static_boundary(self):
        scaffold = _read("scaffold-validation.yml")
        audit = _read("genoma-audit.yml")
        caller = _job_block(scaffold, "four-plane-audit")
        weakened_draft_caller = caller.replace(DRAFT_GATE, "true", 1)
        mutations = (
            scaffold.replace("needs: [changes, static]", "needs: changes", 1),
            scaffold.replace(caller, weakened_draft_caller, 1),
            scaffold.replace("needs.static.result == 'success'", "needs.static.result != 'failure'", 1),
            scaffold.replace("needs.static.result == 'success'", "needs.static.result == 'success' || true", 1),
            scaffold.replace("needs.changes.result == 'success'", "needs.changes.result != 'failure'", 1),
        )
        for mutated in mutations:
            self.assertTrue(_four_plane_audit_orchestration_errors(mutated, audit))
        bypass_mutations = (
            scaffold.replace("needs.static.result == 'success'", "(needs.static.result == 'success' || true)", 1),
            scaffold.replace("needs.changes.result == 'success'", "(needs.changes.result == 'success' || true)", 1),
            scaffold.replace(
                caller,
                caller.replace(
                    "needs.changes.outputs.validation_required == 'true'",
                    "(needs.changes.outputs.validation_required == 'true' || true)",
                    1,
                ),
                1,
            ),
            scaffold.replace(caller, caller.replace(DRAFT_GATE, f"({DRAFT_GATE}) || true", 1), 1),
        )
        for mutated in bypass_mutations:
            self.assertTrue(_four_plane_audit_orchestration_errors(mutated, audit))
        direct_trigger = audit.replace("on:\n  workflow_call:\n", "on:\n  workflow_call:\n  pull_request:\n", 1)
        self.assertTrue(_four_plane_audit_orchestration_errors(scaffold, direct_trigger))

    def test_reusable_four_plane_audit_keeps_only_unique_evidence_work(self):
        audit = _read("genoma-audit.yml")
        job = _job_block(audit, "audit")
        self.assertNotIn("Repository and supply-chain contracts", job)
        self.assertNotIn("Unit tests for v0.8 architecture", job)
        self.assertNotIn("python3 -m unittest", job)
        self.assertIn("python3 scripts/genoma_audit.py --allow-template-sealed-only --output audit.json", job)
        self.assertIn("python3 scripts/verify_template_store.py --allow-sealed-only", job)
        self.assertIn("name: genoma-v0.8-audit-${{ github.sha }}", job)
        self.assertIn("retention-days: 365", job)
        self.assertIn("if: always()", job)

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

    def test_scaffold_publish_owns_build_cache_without_widening_permissions(self):
        workflow = _read("scaffold-validation.yml")
        canary = _job_block(workflow, "container-canary")
        publish = _job_block(workflow, "publish-ghcr")
        lock = json.loads((ROOT / "locks" / "actions-lock.json").read_text(encoding="utf-8"))
        buildx = "docker/setup-buildx-action@" + lock["actions"]["docker/setup-buildx-action"]["sha"]
        builder = "docker/build-push-action@" + lock["actions"]["docker/build-push-action"]["sha"]
        cache_from = "cache-from: type=gha,scope=codework-genome-scaffold-v1"
        cache_to = "cache-to: type=gha,mode=min,scope=codework-genome-scaffold-v1,ignore-error=true"

        self.assertIn("docker build --tag codework-genome:${{ github.sha }} .", canary)
        self.assertNotIn(buildx, canary)
        self.assertNotIn(builder, canary)
        self.assertNotIn("cache-from:", canary)
        self.assertNotIn("cache-to:", canary)
        self.assertNotIn("packages: write", canary)

        self.assertIn(buildx, publish)
        self.assertIn("driver: docker-container", publish)
        self.assertIn(builder, publish)
        self.assertIn(cache_from, publish)
        self.assertIn(cache_to, publish)
        self.assertIn("packages: write", publish)
        self.assertIn("needs: [static, container-canary]", publish)

    def test_language_baseline_does_not_rescan_full_checkout(self):
        language_tests = (ROOT / "tests" / "test_code_language_guard.py").read_text(
            encoding="utf-8"
        )
        repo_contract = (ROOT / "tests" / "test_repo_contract.py").read_text(encoding="utf-8")
        validator = (ROOT / "scripts" / "validate_repo.py").read_text(encoding="utf-8")

        self.assertEqual(len(re.findall(r"\bscan_repository\b", language_tests)), 1)
        self.assertIn("scan_repository as _scan_repository_impl", language_tests)
        self.assertEqual(language_tests.count("_scan_repository_impl"), 2)
        self.assertIn("def _scan_fixture_repository(", language_tests)
        self.assertIn("if root.resolve() == ROOT:", language_tests)
        self.assertIn("return _scan_repository_impl(root, policy)", language_tests)
        self.assertIn("validator.validate(root)", repo_contract)
        self.assertIn("validate_language_policy(root, errors)", validator)

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

        self._assert_job_gate(workflow, "static", "validation_required")

        self.assertIn("  static:\n", workflow)
        self.assertIn("  container-canary:\n", workflow)
        publish = _job_block(workflow, "publish-ghcr")
        self.assertIn("needs: [static, container-canary]", publish)


if __name__ == "__main__":
    unittest.main()
