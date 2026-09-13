"""Verify the exact-head repository-wide zero-identity seal."""

from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_RELATIVE = "docs/superpowers/evidence/2026-09-11-omnigenis-zero-identity-seal.json"
EVIDENCE = ROOT / EVIDENCE_RELATIVE
POLICY = ROOT / "config/zero_identity_policy.json"
GIT = shutil.which("git")
if GIT is None:
    raise RuntimeError("git executable is required by the zero-identity seal contract")


def _git(*args: str) -> str:
    return subprocess.check_output([GIT, *args], cwd=ROOT, text=True).strip()


def _resolve_evidence_commit(implementation: str) -> str:
    """Locate the unique evidence-only child of the attested implementation."""
    expected = EVIDENCE.read_bytes()
    candidates: list[str] = []
    for line in _git("rev-list", "--parents", "HEAD").splitlines():
        fields = line.split()
        commit, parents = fields[0], fields[1:]
        if parents != [implementation]:
            continue
        changed = _git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", commit
        ).splitlines()
        if changed != [EVIDENCE_RELATIVE]:
            continue
        committed = subprocess.check_output(
            [GIT, "show", f"{commit}:{EVIDENCE_RELATIVE}"],
            cwd=ROOT,
        )
        if committed == expected:
            candidates.append(commit)
    if len(candidates) != 1:
        raise AssertionError(
            "expected exactly one reachable evidence-only child of the implementation"
        )
    evidence_commit = candidates[0]
    head = _git("rev-parse", "HEAD")
    if head == evidence_commit:
        return evidence_commit
    head_fields = _git("rev-list", "--parents", "-n", "1", "HEAD").split()
    head_parents = head_fields[1:]
    if len(head_parents) == 2 and head_parents[1] == evidence_commit:
        return evidence_commit
    raise AssertionError(
        "evidence commit must be HEAD or the second parent of a two-parent merge"
    )


class ZeroIdentitySealTest(unittest.TestCase):
    """Bind the seal evidence to the exact implementation and zero inventory."""

    def load(self) -> dict:
        self.assertTrue(EVIDENCE.is_file(), f"missing evidence: {EVIDENCE}")
        return json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_schema_repository_and_policy_are_exact(self) -> None:
        evidence = self.load()
        self.assertEqual(evidence["schema"], "omnigenis-zero-identity-seal-v1")
        self.assertEqual(evidence["repository_id"], 1212760346)
        self.assertEqual(
            evidence["policy_sha256"], hashlib.sha256(POLICY.read_bytes()).hexdigest()
        )

    def test_implementation_sha_tree_and_evidence_only_commit_are_bound(self) -> None:
        evidence = self.load()
        implementation = evidence["implementation_head_sha"]
        self.assertEqual(
            _git("rev-parse", f"{implementation}^{{tree}}"),
            evidence["implementation_tree_sha"],
        )
        evidence_commit = _resolve_evidence_commit(implementation)
        self.assertEqual(_git("rev-parse", f"{evidence_commit}^"), implementation)
        changed = _git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", evidence_commit
        ).splitlines()
        self.assertEqual(changed, [EVIDENCE_RELATIVE])

    def test_evidence_binding_accepts_evidence_as_second_parent_of_merge(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            def git(*args: str) -> str:
                return subprocess.check_output([GIT, *args], cwd=repo, text=True).strip()
            def run(*args: str) -> None:
                subprocess.run([GIT, *args], cwd=repo, check=True, capture_output=True)

            run("init", "-b", "main")
            run("config", "user.email", "test@example.invalid")
            run("config", "user.name", "Seal Test")
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            run("add", "base.txt")
            run("commit", "-m", "base")
            run("checkout", "-b", "feature")
            (repo / "implementation.txt").write_text("implementation\n", encoding="utf-8")
            run("add", "implementation.txt")
            run("commit", "-m", "implementation")
            implementation = git("rev-parse", "HEAD")
            evidence_relative = "docs/evidence.json"
            evidence_path = repo / evidence_relative
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text('{"status":"verified"}\n', encoding="utf-8")
            run("add", evidence_relative)
            run("commit", "-m", "evidence")
            evidence_commit = git("rev-parse", "HEAD")
            run("checkout", "main")
            (repo / "main.txt").write_text("main change\n", encoding="utf-8")
            run("add", "main.txt")
            run("commit", "-m", "main change")
            run("merge", "--no-ff", "feature", "-m", "merge feature")

            module = __name__
            with (
                mock.patch(f"{module}.ROOT", repo),
                mock.patch(f"{module}.EVIDENCE", evidence_path),
                mock.patch(f"{module}.EVIDENCE_RELATIVE", evidence_relative),
            ):
                self.assertEqual(_resolve_evidence_commit(implementation), evidence_commit)

    def test_evidence_binding_rejects_later_branch_commit_even_after_merge(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            def git(*args: str) -> str:
                return subprocess.check_output([GIT, *args], cwd=repo, text=True).strip()
            def run(*args: str) -> None:
                subprocess.run([GIT, *args], cwd=repo, check=True, capture_output=True)

            run("init", "-b", "main")
            run("config", "user.email", "test@example.invalid")
            run("config", "user.name", "Seal Test")
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            run("add", "base.txt")
            run("commit", "-m", "base")
            run("checkout", "-b", "feature")
            (repo / "implementation.txt").write_text("implementation\n", encoding="utf-8")
            run("add", "implementation.txt")
            run("commit", "-m", "implementation")
            implementation = git("rev-parse", "HEAD")
            evidence_relative = "docs/evidence.json"
            evidence_path = repo / evidence_relative
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text('{"status":"verified"}\n', encoding="utf-8")
            run("add", evidence_relative)
            run("commit", "-m", "evidence")
            (repo / "later.txt").write_text("later change\n", encoding="utf-8")
            run("add", "later.txt")
            run("commit", "-m", "later")
            run("checkout", "main")
            run("merge", "--no-ff", "feature", "-m", "merge feature")

            module = __name__
            with (
                mock.patch(f"{module}.ROOT", repo),
                mock.patch(f"{module}.EVIDENCE", evidence_path),
                mock.patch(f"{module}.EVIDENCE_RELATIVE", evidence_relative),
                self.assertRaises(AssertionError),
            ):
                _resolve_evidence_commit(implementation)

    def test_all_fingerprint_classes_are_zero(self) -> None:
        evidence = self.load()
        self.assertEqual(set(evidence["class_counts"]), {"P1", "P2", "P3", "P4"})
        for class_id, counts in evidence["class_counts"].items():
            self.assertEqual(counts, {"path": 0, "blob": 0}, class_id)

    def test_protected_surfaces_are_unchanged_from_base(self) -> None:
        evidence = self.load()
        for relative, record in evidence["protected_surfaces"].items():
            current = (ROOT / relative).read_bytes()
            self.assertEqual(hashlib.sha256(current).hexdigest(), record["sha256"])
            base = subprocess.check_output([GIT, "show", f"{evidence['base_sha']}:{relative}"], cwd=ROOT)
            self.assertEqual(hashlib.sha256(base).hexdigest(), record["sha256"])

    def test_validation_provenance_is_self_contained(self) -> None:
        evidence = self.load()
        for name, record in evidence["validation_provenance"].items():
            self.assertEqual(record["exit_code"], 0, name)
            output = record["sanitized_output"].encode("utf-8")
            self.assertEqual(hashlib.sha256(output).hexdigest(), record["output_sha256"], name)
            self.assertTrue(record["command"], name)
            self.assertNotIn("/tmp/", record["command"], name)

    def test_post_merge_runner_operation_remains_pending(self) -> None:
        evidence = self.load()
        self.assertEqual(evidence["post_merge"]["runner_operation"], "PENDING_HUMAN_MERGE")
        self.assertFalse(evidence["secret_material_recorded"])


if __name__ == "__main__":
    unittest.main()
