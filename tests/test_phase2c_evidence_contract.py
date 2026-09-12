"""Verify exact-head evidence for the governed Phase 2C runner cutover."""

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
    "docs/superpowers/evidence/2026-09-11-omnigenis-phase2c-runner-cutover.json"
)
EVIDENCE = ROOT / EVIDENCE_RELATIVE
BASE_MAIN_SHA = "a1e669dd613f68f4d82ca7f1f565772ec8098cb1"
PHASE2C_MERGE_COMMIT = "fe0c91c99fe4cd57e14c69cc3b3c58edcb4e8be8"
PHASE2C_EVIDENCE_COMMIT = "0c2c1649355cd998210baacdecb24681a18030ad"
PHASE2C_CURRENT_EVIDENCE_SHA256 = "1c0639f1f050cde7f7c845b33a091dd2c08073cffe8dbedb12a40dea4e9c7a7d"
PHASE2C_HISTORICAL_EVIDENCE_SHA256 = "0bc5dce4319e1ed8bef878c7a18f1bf7b4e24ace7b04a9d68fb7a7edd622d67a"
LEGACY = "code" + "work"
GIT_EXECUTABLE = shutil.which("git")
if GIT_EXECUTABLE is None:
    raise RuntimeError("git executable is required by the Phase 2C evidence contract")


def _git_output(repo: Path, *args: str) -> str:
    """Run a read-only Git command with the resolved executable."""
    return subprocess.check_output(
        [GIT_EXECUTABLE, *args], cwd=repo, text=True
    ).strip()


def _run_git(repo: Path, *args: str) -> None:
    """Run Git in an isolated regression-test repository."""
    subprocess.run(
        [GIT_EXECUTABLE, *args], cwd=repo, check=True, capture_output=True
    )


def _resolve_evidence_commit(
    repo: Path,
    implementation: str,
    evidence_relative: str,
    expected_blob_sha256: str,
) -> str:
    """Resolve the unique evidence-only child using an independent blob digest."""
    candidates: list[str] = []
    for line in _git_output(repo, "rev-list", "--parents", "HEAD").splitlines():
        fields = line.split()
        commit, parents = fields[0], fields[1:]
        if parents != [implementation]:
            continue
        changed = _git_output(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r", commit
        ).splitlines()
        if changed != [evidence_relative]:
            continue
        committed = subprocess.check_output(
            [GIT_EXECUTABLE, "show", f"{commit}:{evidence_relative}"], cwd=repo
        )
        if hashlib.sha256(committed).hexdigest() == expected_blob_sha256:
            candidates.append(commit)
    if len(candidates) != 1:
        raise AssertionError(
            "expected exactly one reachable evidence-only child of the implementation"
        )
    evidence_commit = candidates[0]
    head = _git_output(repo, "rev-parse", "HEAD")
    if head == evidence_commit:
        return evidence_commit

    head_fields = _git_output(
        repo, "rev-list", "--parents", "-n", "1", "HEAD"
    ).split()
    if len(head_fields[1:]) == 2 and head_fields[2] == evidence_commit:
        return evidence_commit

    merged = []
    for line in _git_output(repo, "rev-list", "--merges", "--parents", "HEAD").splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] == evidence_commit:
            merged.append(fields[0])
    if len(merged) != 1:
        raise AssertionError(
            "evidence commit must be HEAD, the PR merge-ref second parent, or the "
            "second parent of one reachable historical merge commit"
        )
    return evidence_commit


class Phase2CRunnerEvidenceContractTest(unittest.TestCase):
    """Enforce exact pre-merge Phase 2C evidence and post-merge blocks."""

    def load(self) -> dict:
        """Load the required Phase 2C evidence artifact."""
        self.assertTrue(EVIDENCE.is_file(), f"missing evidence: {EVIDENCE}")
        return json.loads(EVIDENCE.read_text(encoding="utf-8"))

    @staticmethod
    def by_id(snapshot: list[dict]) -> dict[int, dict]:
        """Index a runner snapshot by stable runner ID."""
        return {int(item["id"]): item for item in snapshot}

    def assert_additive_snapshot(
        self, before_snapshot: list[dict], after_snapshot: list[dict]
    ) -> None:
        """Require unique stable IDs and additive-only runner labels."""
        before = self.by_id(before_snapshot)
        after = self.by_id(after_snapshot)
        self.assertEqual(len(before_snapshot), len(before))
        self.assertEqual(len(after_snapshot), len(after))
        self.assertEqual(set(before), set(after))
        for runner_id in before:
            self.assertLessEqual(
                set(before[runner_id]["labels"]),
                set(after[runner_id]["labels"]),
            )

    def test_current_deidentified_evidence_bytes_are_independently_pinned(self) -> None:
        """Pin the current deidentified evidence independently of its own fields."""
        self.assertEqual(
            hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),
            PHASE2C_CURRENT_EVIDENCE_SHA256,
        )

    def test_exact_head_identity_and_evidence_only_commit_are_git_bound(self) -> None:
        """Bind the evidence-only commit to the exact implementation SHA and tree."""
        evidence = self.load()
        implementation = evidence["implementation_head_sha"]
        self.assertEqual(
            _git_output(ROOT, "rev-parse", f"{implementation}^{{tree}}"),
            evidence["implementation_tree_sha"],
        )
        evidence_commit = _resolve_evidence_commit(
            ROOT,
            implementation,
            EVIDENCE_RELATIVE,
            PHASE2C_HISTORICAL_EVIDENCE_SHA256,
        )
        self.assertEqual(evidence_commit, PHASE2C_EVIDENCE_COMMIT)
        provenance = evidence["deidentification_provenance"]
        committed = subprocess.check_output(
            [GIT_EXECUTABLE, "show", f"{evidence_commit}:{EVIDENCE_RELATIVE}"], cwd=ROOT
        )
        self.assertEqual(
            hashlib.sha256(committed).hexdigest(),
            PHASE2C_HISTORICAL_EVIDENCE_SHA256,
        )
        self.assertEqual(
            provenance["historical_blob_sha256"],
            PHASE2C_HISTORICAL_EVIDENCE_SHA256,
        )
        self.assertEqual(provenance["evidence_commit"], PHASE2C_EVIDENCE_COMMIT)
        self.assertEqual(provenance["merge_commit"], PHASE2C_MERGE_COMMIT)
        self.assertEqual(
            _git_output(ROOT, "rev-parse", f"{evidence_commit}^"), implementation
        )

    def test_historical_hashes_match_implementation_bytes(self) -> None:
        """Hash the identity contract and ledger from the attested implementation."""
        evidence = self.load()
        implementation = evidence["implementation_head_sha"]
        for key, relative in (
            ("project_identity_sha256", "config/project_identity.json"),
            ("legacy_ledger_sha256", "config/legacy_identity_ledger.json"),
        ):
            committed = subprocess.check_output(
                [GIT_EXECUTABLE, "show", f"{implementation}:{relative}"], cwd=ROOT
            )
            self.assertEqual(evidence[key], hashlib.sha256(committed).hexdigest())

    def test_dual_label_expansion_preserves_runner_identity(self) -> None:
        """Require canonical labels without changing IDs or runner names."""
        evidence = self.load()
        self.assertEqual(evidence["schema"], "omnigenis-phase2c-runner-cutover-v2")
        self.assertEqual(evidence["stage"], "REPOSITORY_CUTOVER_READY_FOR_REVIEW")
        self.assertEqual(evidence["base_main_sha"], BASE_MAIN_SHA)
        before_snapshot = evidence["runner_snapshot_before"]
        after_snapshot = evidence["runner_snapshot_after"]
        self.assert_additive_snapshot(before_snapshot, after_snapshot)
        before = self.by_id(before_snapshot)
        after = self.by_id(after_snapshot)
        self.assertEqual(set(before), {21, 22})
        self.assertEqual(set(after), {21, 22})
        for runner_id in (21, 22):
            self.assertEqual(
                after[runner_id]["retired_name_sha256"],
                before[runner_id]["retired_name_sha256"],
            )
            self.assertRegex(after[runner_id]["retired_name_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("name", after[runner_id])
            self.assertEqual(after[runner_id]["status"], "online")
            self.assertFalse(after[runner_id]["busy"])

    def test_duplicate_runner_id_snapshot_is_rejected(self) -> None:
        """Reject snapshots where duplicate runner IDs would collapse under indexing."""
        evidence = self.load()
        before = list(evidence["runner_snapshot_before"])
        after = list(evidence["runner_snapshot_after"])
        before.append(dict(before[0]))
        with self.assertRaises(AssertionError):
            self.assert_additive_snapshot(before, after)

    def test_removed_legacy_label_snapshot_is_rejected(self) -> None:
        """Reject a post snapshot that silently removes any pre-existing label."""
        evidence = self.load()
        before = json.loads(json.dumps(evidence["runner_snapshot_before"]))
        after = json.loads(json.dumps(evidence["runner_snapshot_after"]))
        removed = after[0]["labels"].pop(0)
        self.assertIn(removed, before[0]["labels"])
        with self.assertRaises(AssertionError):
            self.assert_additive_snapshot(before, after)

    def test_canonical_and_legacy_labels_coexist_until_merge_canary(self) -> None:
        """Keep rollback labels while exposing the canonical routing labels."""
        evidence = self.load()
        after = self.by_id(evidence["runner_snapshot_after"])
        legacy_pool = LEGACY + "-isolated"
        for runner_id in (21, 22):
            self.assertIn(legacy_pool, after[runner_id]["labels"])
            self.assertIn("omnigenis-isolated", after[runner_id]["labels"])
        self.assertIn(LEGACY + "-01", after[21]["labels"])
        self.assertIn(LEGACY + "-02", after[22]["labels"])
        self.assertIn("omnigenis-01", after[21]["labels"])
        self.assertIn("omnigenis-02", after[22]["labels"])
        self.assertEqual(evidence["repository_selector_cutover"], "NOT_MERGED")

    def test_post_merge_actions_remain_blocked(self) -> None:
        """Do not claim canary, contraction, or re-registration before merge."""
        evidence = self.load()
        post_merge = evidence["post_merge"]
        self.assertEqual(
            post_merge["protected_main_canary"], "PENDING_AFTER_HUMAN_MERGE"
        )
        self.assertEqual(
            post_merge["legacy_runner_label_removal"], "BLOCKED_UNTIL_CANARY_PASS"
        )
        self.assertEqual(
            post_merge["runner_name_reregistration"],
            "BLOCKED_UNTIL_RUNTIME_RESOURCE_GATE",
        )
        self.assertEqual(evidence["removed_labels"], [])
        self.assertFalse(evidence["secret_material_recorded"])


    def test_phase_two_b_prerequisite_is_exact(self) -> None:
        """Bind Phase 2C to the verified Phase 2B protected-main image."""
        evidence = self.load()
        prerequisite = evidence["phase2b_prerequisite"]
        self.assertEqual(prerequisite["status"], "VERIFIED")
        registry, qualified = prerequisite["image_reference"].split("/", 1)
        package_path, digest = qualified.rsplit("@", 1)
        self.assertEqual(registry, "ghcr.io")
        self.assertEqual(package_path.rsplit("/", 1)[-1], "omnigenis-genome")
        self.assertEqual(
            digest,
            "sha256:b34cddd157132f0b039bebb1674abb4957e024fd0332568fc3ae9c2ca0fa8454",
        )
        self.assertEqual(prerequisite["workflow_run_id"], 34617560951)
        self.assertEqual(prerequisite["successful_attempt"], 2)

    def test_validation_provenance_is_replayable(self) -> None:
        """Require exact executable commands and digested outputs for every gate."""
        evidence = self.load()
        expected = {
            "identity_guard": "python3 scripts/project_identity_guard.py --check",
            "validate_repo": "python3 scripts/validate_repo.py",
            "supply_chain": "python3 scripts/verify_supply_chain_lock.py",
            "code_language": "python3 scripts/code_language_guard.py --check",
            "residual_language": "python3 scripts/residual_language_audit.py --check",
            "docs_language": (
                "python3 -m unittest tests.test_developer_documentation_language -v"
            ),
            "phase2b_prerequisite": (
                "python3 -m unittest tests.test_phase2b_post_merge_ghcr_evidence "
                "tests.test_phase2b_evidence_contract -v"
            ),
            "runner_contracts": (
                "python3 -m unittest tests.test_phase2c_runner_identity "
                "tests.test_ci_optimization_contract "
                "tests.test_repository_identity_migration -v"
            ),
            "evidence_topology": (
                "python3 -m unittest "
                "tests.test_phase2c_evidence_contract."
                "Phase2CRunnerEvidenceContractTest."
                "test_binding_survives_merge_then_later_descendant "
                "tests.test_phase2c_evidence_contract."
                "Phase2CRunnerEvidenceContractTest."
                "test_binding_rejects_post_evidence_commit_before_merge -v"
            ),
            "shell_syntax": "find scripts -type f -name '*.sh' -exec bash -n {} +",
            "diff_check": "git diff --check",
        }
        provenance = evidence["validation_provenance"]
        self.assertEqual(set(provenance), set(expected))
        for name, command in expected.items():
            record = provenance[name]
            self.assertEqual(record["command"], command, name)
            self.assertEqual(record["exit_code"], 0, name)
            self.assertRegex(record["output_sha256"], r"^[0-9a-f]{64}$", name)
            self.assertEqual(record["output_kind"], "inline_sanitized_summary", name)
            locator = f"inline:validation_provenance.{name}.sanitized_output"
            self.assertEqual(record["output_locator"], locator, name)
            sanitized = record["sanitized_output"]
            self.assertTrue(sanitized, name)
            self.assertNotIn("/tmp/", sanitized, name)
            self.assertEqual(
                record["output_sha256"],
                hashlib.sha256(sanitized.encode("utf-8")).hexdigest(),
                name,
            )
            self.assertTrue(record["summary"], name)
            self.assertEqual(record["summary_locator"], locator, name)
            for value in record.get("environment", {}).values():
                if isinstance(value, str):
                    self.assertNotIn("/tmp/", value, name)
            argv = shlex.split(command)
            self.assertTrue(argv, name)
            self.assertIn(argv[0], {"python3", "find", "git"}, name)
            self.assertIsNotNone(shutil.which(argv[0]), name)
            self.assertNotIn("/tmp/", command, name)

    def test_protected_boundaries_are_explicit(self) -> None:
        """Require hosted untrusted jobs and unchanged scientific/normative surfaces."""
        evidence = self.load()
        protected = evidence["protected_boundaries"]
        self.assertEqual(protected["untrusted_pull_requests"], "GITHUB_HOSTED")
        self.assertEqual(protected["hosted_write_capability_jobs"], "UNCHANGED")
        self.assertEqual(protected["scientific_surface_changes"], [])
        self.assertEqual(protected["normative_surface_changes"], [])

    def test_binding_survives_merge_then_later_descendant(self) -> None:
        """Keep evidence verifiable after a real merge and later-phase commits."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _run_git(repo, "init", "-b", "main")
            _run_git(repo, "config", "user.email", "test@example.invalid")
            _run_git(repo, "config", "user.name", "Phase2C Test")
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
            expected_evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            _run_git(repo, "add", evidence_rel)
            _run_git(repo, "commit", "-m", "evidence")
            evidence_commit = _git_output(repo, "rev-parse", "HEAD")
            _run_git(repo, "checkout", "main")
            _run_git(repo, "merge", "--no-ff", "feature", "-m", "merge feature")
            (repo / "later.txt").write_text("later\n", encoding="utf-8")
            _run_git(repo, "add", "later.txt")
            _run_git(repo, "commit", "-m", "later phase")
            self.assertEqual(
                _resolve_evidence_commit(
                    repo, implementation, evidence_rel, expected_evidence_sha
                ),
                evidence_commit,
            )

    def test_binding_rejects_post_evidence_commit_before_merge(self) -> None:
        """Reject ordinary branch commits added after evidence but before merge."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _run_git(repo, "init", "-b", "main")
            _run_git(repo, "config", "user.email", "test@example.invalid")
            _run_git(repo, "config", "user.name", "Phase2C Test")
            (repo / "implementation.txt").write_text("implementation\n", encoding="utf-8")
            _run_git(repo, "add", "implementation.txt")
            _run_git(repo, "commit", "-m", "implementation")
            implementation = _git_output(repo, "rev-parse", "HEAD")
            evidence_rel = "docs/evidence.json"
            evidence_path = repo / evidence_rel
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text('{"status":"verified"}\n', encoding="utf-8")
            expected_evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            _run_git(repo, "add", evidence_rel)
            _run_git(repo, "commit", "-m", "evidence")
            (repo / "late.txt").write_text("late\n", encoding="utf-8")
            _run_git(repo, "add", "late.txt")
            _run_git(repo, "commit", "-m", "late")
            with self.assertRaises(AssertionError):
                _resolve_evidence_commit(
                    repo, implementation, evidence_rel, expected_evidence_sha
                )


if __name__ == "__main__":
    unittest.main()
