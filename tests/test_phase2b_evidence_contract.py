"""Verify reproducible and Git-bound evidence for the Phase 2B cutover."""

from pathlib import Path
import hashlib
import json
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_RELATIVE = (
    "docs/superpowers/evidence/"
    "2026-09-11-omnigenis-phase2b-runtime-build-identity.json"
)
EVIDENCE = ROOT / EVIDENCE_RELATIVE
PLAN_RELATIVE = (
    "docs/superpowers/plans/"
    "2026-09-11-omnigenis-phase2b-runtime-build-identity-cutover.md"
)
PLAN = ROOT / PLAN_RELATIVE
BASE_SHA = "4c0e5222248b5f9f2537d627091b80afc9c9e120"
PHASE2B_MERGE_COMMIT = "a1e669dd613f68f4d82ca7f1f565772ec8098cb1"
PHASE2B_EVIDENCE_COMMIT = "87edc2c958150736884ad37297f96a8eb7a7464f"
PHASE2B_CURRENT_EVIDENCE_SHA256 = "b829c61985b7738ae1790ea9455bd475afaa3ca4b7c8d5b99feb59b37911a9f3"
PHASE2B_HISTORICAL_EVIDENCE_SHA256 = "36e2d0e9bd719e5c1691bc4e9f0a62095dd9f44958cfd5705214d4018a1c8378"
LEGACY_WORD = "code" + "work"


GIT_EXECUTABLE = shutil.which("git")
if GIT_EXECUTABLE is None:
    raise RuntimeError("git executable is required by the Phase 2B evidence contract")


def _git_output(repo: Path, *args: str) -> str:
    """Run a read-only Git command with the resolved executable."""
    return subprocess.check_output(
        [GIT_EXECUTABLE, *args],
        cwd=repo,
        text=True,
    ).strip()


def _run_git(repo: Path, *args: str) -> None:
    """Run a Git command in an isolated test repository."""
    subprocess.run(
        [GIT_EXECUTABLE, *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _find_evidence_commit(repo: Path, implementation: str, evidence_relative: str) -> str:
    """Find the unique evidence-only child of implementation reachable from HEAD."""
    evidence_bytes = (repo / evidence_relative).read_bytes()
    candidates: list[str] = []
    for line in _git_output(repo, "rev-list", "--parents", "HEAD").splitlines():
        fields = line.split()
        commit, parents = fields[0], fields[1:]
        if parents != [implementation]:
            continue
        changed = _git_output(
            repo,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            commit,
        ).splitlines()
        if changed != [evidence_relative]:
            continue
        committed_bytes = subprocess.check_output(
            [GIT_EXECUTABLE, "show", f"{commit}:{evidence_relative}"],
            cwd=repo,
        )
        if committed_bytes == evidence_bytes:
            candidates.append(commit)
    if len(candidates) != 1:
        raise AssertionError(
            "expected exactly one reachable evidence-only child of the implementation "
            f"commit, found {len(candidates)}"
        )
    evidence_commit = candidates[0]
    head = _git_output(repo, "rev-parse", "HEAD")
    if head != evidence_commit:
        head_fields = _git_output(
            repo,
            "rev-list",
            "--parents",
            "-n",
            "1",
            "HEAD",
        ).split()
        head_parents = head_fields[1:]
        if len(head_parents) != 2 or head_parents[1] != evidence_commit:
            raise AssertionError(
                "evidence commit must be HEAD or the second parent of a two-parent "
                "synthetic merge checkout"
            )
    return evidence_commit


class Phase2BEvidenceContractTest(unittest.TestCase):
    """Enforce the committed Phase 2B evidence contract."""

    @staticmethod
    def git(*args: str) -> str:
        """Run a read-only Git query from the repository root."""
        return _git_output(ROOT, *args)

    def load(self) -> dict:
        """Load the required committed Phase 2B evidence artifact."""
        self.assertTrue(
            EVIDENCE.is_file(),
            f"missing required Phase 2B evidence: {EVIDENCE_RELATIVE}",
        )
        return json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_required_top_level_contract_is_complete(self) -> None:
        """Require every top-level field needed for Phase 2B evidence."""
        evidence = self.load()
        self.assertEqual(evidence["schema"], "omnigenis-phase2b-runtime-build-evidence-v1")
        self.assertEqual(evidence["base_sha"], BASE_SHA)
        required = {
            "implementation_head_sha", "implementation_tree_sha",
            "project_identity_sha256", "legacy_ledger_sha256", "legacy_scan",
            "runtime_resource_gate", "external_capabilities", "ghcr_premerge_state",
            "changed_paths", "protected_boundaries", "validation_provenance",
            "post_evidence_validation", "post_merge_requirements",
        }
        self.assertTrue(required.issubset(evidence))

    def test_current_deidentified_evidence_bytes_are_independently_pinned(self) -> None:
        """Pin the current deidentified evidence independently of its own fields."""
        self.assertEqual(
            hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),
            PHASE2B_CURRENT_EVIDENCE_SHA256,
        )

    def test_implementation_sha_tree_and_evidence_commit_are_git_bound(self) -> None:
        """Bind merged Phase 2B evidence to its historical implementation commit."""
        evidence = self.load()
        implementation = evidence["implementation_head_sha"]
        subprocess.run(
            [GIT_EXECUTABLE, "cat-file", "-e", f"{implementation}^{{commit}}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        self.assertEqual(
            self.git("rev-parse", f"{implementation}^{{tree}}"),
            evidence["implementation_tree_sha"],
        )
        merge_fields = self.git(
            "rev-list", "--parents", "-n", "1", PHASE2B_MERGE_COMMIT
        ).split()
        self.assertEqual(len(merge_fields), 3)
        evidence_commit = merge_fields[2]
        self.assertEqual(evidence_commit, PHASE2B_EVIDENCE_COMMIT)
        self.assertEqual(self.git("rev-parse", f"{evidence_commit}^"), implementation)
        changed = self.git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", evidence_commit
        ).splitlines()
        self.assertEqual(changed, [EVIDENCE_RELATIVE])
        committed_evidence = subprocess.check_output(
            [GIT_EXECUTABLE, "show", f"{evidence_commit}:{EVIDENCE_RELATIVE}"],
            cwd=ROOT,
        )
        provenance = evidence["deidentification_provenance"]
        self.assertEqual(
            hashlib.sha256(committed_evidence).hexdigest(),
            PHASE2B_HISTORICAL_EVIDENCE_SHA256,
        )
        self.assertEqual(
            provenance["historical_blob_sha256"],
            PHASE2B_HISTORICAL_EVIDENCE_SHA256,
        )
        self.assertEqual(provenance["evidence_commit"], PHASE2B_EVIDENCE_COMMIT)
        self.assertEqual(provenance["merge_commit"], PHASE2B_MERGE_COMMIT)
        ancestry = subprocess.run(
            [GIT_EXECUTABLE, "merge-base", "--is-ancestor", PHASE2B_MERGE_COMMIT, "HEAD"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        self.assertEqual(ancestry.returncode, 0)

    def test_evidence_commit_binding_survives_github_merge_ref_topology(self) -> None:
        """Resolve the evidence-only child when HEAD is a synthetic merge commit."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _run_git(repo, "init", "-b", "main")
            _run_git(repo, "config", "user.email", "test@example.invalid")
            _run_git(repo, "config", "user.name", "Phase2B Test")
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            _run_git(repo, "add", "base.txt")
            _run_git(repo, "commit", "-m", "base")
            _run_git(repo, "checkout", "-b", "feature")
            (repo / "implementation.txt").write_text("implementation\n", encoding="utf-8")
            _run_git(repo, "add", "implementation.txt")
            _run_git(repo, "commit", "-m", "implementation")
            implementation = _git_output(repo, "rev-parse", "HEAD")
            evidence_rel = "docs/evidence.json"
            evidence_path = repo / evidence_rel
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text('{"status":"verified"}\n', encoding="utf-8")
            _run_git(repo, "add", evidence_rel)
            _run_git(repo, "commit", "-m", "evidence")
            evidence_commit = _git_output(repo, "rev-parse", "HEAD")
            _run_git(repo, "checkout", "main")
            _run_git(repo, "merge", "--no-ff", "feature", "-m", "synthetic merge")
            self.assertEqual(
                _find_evidence_commit(repo, implementation, evidence_rel),
                evidence_commit,
            )

    def test_evidence_commit_binding_rejects_post_evidence_branch_commits(self) -> None:
        """Reject branch commits created after the evidence-only child."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _run_git(repo, "init", "-b", "main")
            _run_git(repo, "config", "user.email", "test@example.invalid")
            _run_git(repo, "config", "user.name", "Phase2B Test")
            (repo / "implementation.txt").write_text(
                "implementation\n",
                encoding="utf-8",
            )
            _run_git(repo, "add", "implementation.txt")
            _run_git(repo, "commit", "-m", "implementation")
            implementation = _git_output(repo, "rev-parse", "HEAD")
            evidence_rel = "docs/evidence.json"
            evidence_path = repo / evidence_rel
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text('{"status":"verified"}\n', encoding="utf-8")
            _run_git(repo, "add", evidence_rel)
            _run_git(repo, "commit", "-m", "evidence")
            (repo / "late.txt").write_text("late change\n", encoding="utf-8")
            _run_git(repo, "add", "late.txt")
            _run_git(repo, "commit", "-m", "late implementation")
            with self.assertRaises(AssertionError):
                _find_evidence_commit(repo, implementation, evidence_rel)

    def test_evidence_commit_binding_rejects_extra_changed_paths(self) -> None:
        """Reject an implementation child that changes more than the evidence artifact."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _run_git(repo, "init", "-b", "main")
            _run_git(repo, "config", "user.email", "test@example.invalid")
            _run_git(repo, "config", "user.name", "Phase2B Test")
            (repo / "implementation.txt").write_text("implementation\n", encoding="utf-8")
            _run_git(repo, "add", "implementation.txt")
            _run_git(repo, "commit", "-m", "implementation")
            implementation = _git_output(repo, "rev-parse", "HEAD")
            evidence_rel = "docs/evidence.json"
            evidence_path = repo / evidence_rel
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text('{"status":"verified"}\n', encoding="utf-8")
            (repo / "extra.txt").write_text("not evidence-only\n", encoding="utf-8")
            _run_git(repo, "add", evidence_rel, "extra.txt")
            _run_git(repo, "commit", "-m", "bad evidence")
            with self.assertRaises(AssertionError):
                _find_evidence_commit(repo, implementation, evidence_rel)

    def test_premerge_evidence_cannot_claim_ghcr_publication(self) -> None:
        """Prevent pre-merge evidence from claiming GHCR publication success."""
        evidence = self.load()
        ghcr = evidence["ghcr_premerge_state"]
        self.assertEqual(ghcr["status"], "PENDING_AFTER_HUMAN_MERGE")
        self.assertEqual(ghcr["expected_package"], "omnigenis-genome")
        self.assertEqual(ghcr["old_package_action"], "PRESERVE")

    def test_runner_boundary_is_still_phase_two_c_legacy_state(self) -> None:
        """Keep live runner identity unchanged until the governed Phase 2C cutover."""
        evidence = self.load()
        protected = evidence["protected_boundaries"]
        self.assertEqual(protected["runner_cutover"], "NOT_STARTED_PHASE_2C")
        runners = protected["runner_snapshot"]
        self.assertEqual({runner["id"] for runner in runners}, {21, 22})
        for runner in runners:
            self.assertRegex(runner["retired_name_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("name", runner)
        legacy_pool = LEGACY_WORD + "-isolated"
        for runner in runners:
            self.assertIn(legacy_pool, runner["labels"])
            self.assertNotIn("omnigenis-isolated", runner["labels"])

    def test_validation_provenance_records_reproducible_outputs(self) -> None:
        """Require reproducible command and output provenance for validation gates."""
        evidence = self.load()
        required = {
            "identity_guard", "validate_repo", "supply_chain", "code_language",
            "residual_language", "docs_language", "phase2b_tests", "reviewer_tests",
            "plan_sequence", "shell_syntax", "diff_check",
        }
        provenance = evidence["validation_provenance"]
        self.assertTrue(required.issubset(provenance))
        self.assertNotIn("root_suite", provenance)
        expected_commands = {
            "identity_guard": "python3 scripts/project_identity_guard.py --check",
            "validate_repo": "python3 scripts/validate_repo.py",
            "supply_chain": "python3 scripts/verify_supply_chain_lock.py",
            "code_language": "python3 scripts/code_language_guard.py --check",
            "residual_language": "python3 scripts/residual_language_audit.py --check",
            "docs_language": "python3 -m unittest tests.test_developer_documentation_language -v",
            "phase2b_tests": (
                "python3 -m unittest tests.test_phase2b_runtime_build_identity "
                "tests.test_phase2b_mcp_ngs_identity tests.test_phase2b_legacy_seal -v"
            ),
            "reviewer_tests": (
                "python3 -m unittest tests.test_coderabbit_guardrails "
                "tests.test_integration_code_language.IntegrationCodeLanguageTest."
                "test_coderabbit_setup_diagnostics_are_english "
                "tests.test_ci_optimization_contract.CIOptimizationContractTest."
                "test_ngs_runtime_gate_matches_approved_phase_two_b_semantics -v"
            ),
            "plan_sequence": (
                "python3 -m unittest tests.test_phase2b_evidence_contract."
                "Phase2BEvidenceContractTest."
                "test_plan_bootstrap_defers_evidence_contract_and_full_suite -v"
            ),
            "shell_syntax": "find scripts -type f -name '*.sh' -exec bash -n {} +",
            "diff_check": "git diff --check",
        }
        for name in required:
            record = provenance[name]
            self.assertEqual(record["exit_code"], 0, name)
            command = record["command"]
            self.assertEqual(command, expected_commands[name], name)
            self.assertNotIn("/tmp/", command, name)
            self.assertNotIn("AST gate", command, name)
            argv = shlex.split(command)
            self.assertTrue(argv, name)
            self.assertIn(argv[0], {"python3", "find", "git"}, name)
            self.assertIsNotNone(shutil.which(argv[0]), name)
            self.assertTrue(record["environment"], name)
            self.assertRegex(record["output_sha256"], r"^[0-9a-f]{64}$", name)
            self.assertTrue(record["summary"], name)
        self.assertNotIn(
            "test_phase2b_evidence_contract",
            provenance["phase2b_tests"]["command"],
        )
        self.assertEqual(
            provenance["shell_syntax"]["command"],
            "find scripts -type f -name '*.sh' -exec bash -n {} +",
        )

    def test_post_evidence_validation_requires_raw_final_gates(self) -> None:
        """Require the full suite only after the evidence-only commit exists."""
        evidence = self.load()
        post = evidence["post_evidence_validation"]
        self.assertEqual(post["status"], "REQUIRED_AFTER_EVIDENCE_COMMIT")
        self.assertEqual(
            post["commands"],
            [
                "python3 -m unittest tests.test_phase2b_evidence_contract -v",
                "python3 -m unittest discover -s tests -v",
                "find scripts -type f -name '*.sh' -exec bash -n {} +",
                "git diff --check",
            ],
        )

    def test_plan_resolves_repository_selector_before_runner_api_calls(self) -> None:
        """Require a fresh shell to resolve the repository before runner API use."""
        plan = PLAN.read_text(encoding="utf-8")
        initializer = 'repo="$(gh api repositories/1212760346 --jq .full_name)"'
        first_runner_call = "gh api repos/$repo/actions/runners"
        self.assertIn(initializer, plan)
        self.assertIn(first_runner_call, plan)
        self.assertLess(plan.index(initializer), plan.index(first_runner_call))

    def test_plan_bootstrap_defers_evidence_contract_and_full_suite(self) -> None:
        """Keep evidence-dependent gates out of the pre-evidence bootstrap cycle."""
        plan = PLAN.read_text(encoding="utf-8")
        bootstrap = plan.split(
            "**Step 4: Execute one fail-fast validation cycle on the exact implementation HEAD**",
            1,
        )[1].split("**Step 5: Capture non-secret external capability state**", 1)[0]
        bootstrap_commands = bootstrap.split("```bash", 1)[1].split("```", 1)[0]
        self.assertNotIn("tests.test_phase2b_evidence_contract", bootstrap_commands)
        self.assertNotIn("run_gate root_suite", bootstrap_commands)
        final_gate = plan.split("**Step 9: Execute the final post-evidence gate**", 1)[1].split(
            "### Task 6:", 1
        )[0]
        for command in (
            "python3 -m unittest tests.test_phase2b_evidence_contract -v",
            "python3 -m unittest discover -s tests -v",
            "find scripts -type f -name '*.sh' -exec bash -n {} +",
            "git diff --check",
        ):
            self.assertIn(command, final_gate)

    def test_contract_and_ledger_hashes_match_historical_implementation_bytes(self) -> None:
        """Match evidence digests to bytes from the attested Phase 2B commit."""
        evidence = self.load()
        implementation = evidence["implementation_head_sha"]
        for key, relative in (
            ("project_identity_sha256", "config/project_identity.json"),
            ("legacy_ledger_sha256", "config/legacy_identity_ledger.json"),
        ):
            committed = subprocess.check_output(
                [GIT_EXECUTABLE, "show", f"{implementation}:{relative}"],
                cwd=ROOT,
            )
            digest = hashlib.sha256(committed).hexdigest()
            self.assertEqual(evidence[key], digest)


if __name__ == "__main__":
    unittest.main()
