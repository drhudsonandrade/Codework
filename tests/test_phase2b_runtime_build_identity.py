"""Verify Phase 2B runtime/build identities while freezing the Phase 2C runner boundary."""

from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = json.loads((ROOT / "config/project_identity.json").read_text(encoding="utf-8"))
LEGACY_WORD = "code" + "work"
PHASE2B_MERGE_COMMIT = "a1e669dd613f68f4d82ca7f1f565772ec8098cb1"
GIT_EXECUTABLE = shutil.which("git")
if GIT_EXECUTABLE is None:
    raise RuntimeError("git is required for Phase 2B historical boundary checks")


class Phase2BRuntimeBuildIdentityTest(unittest.TestCase):
    """Enforce canonical runtime/build identities and preserve runner boundaries."""

    @staticmethod
    def read(path: str) -> str:
        """Read a repository text file as UTF-8."""
        return (ROOT / path).read_text(encoding="utf-8")

    def test_runtime_and_container_identity_are_canonical(self) -> None:
        """Require canonical runtime root, container image, and cache namespace."""
        runtime = IDENTITY["runtime"]
        self.assertIn(f"WORKDIR {runtime['root']}", self.read("Dockerfile"))
        scaffold = self.read(".github/workflows/scaffold-validation.yml")
        self.assertIn(runtime["container_package"], scaffold)
        self.assertIn(runtime["cache_namespace"], scaffold)
        self.assertNotIn("/opt/" + LEGACY_WORD, scaffold)

    def test_phase_two_c_runner_boundary_remained_legacy_during_phase_two_b(self) -> None:
        """Verify the Phase 2B runner boundary from its merged historical bytes."""
        legacy_runner_pool = LEGACY_WORD + "-isolated"
        canonical_runner_pool = IDENTITY["runners"]["pool_label"]
        phase_two_b_head = subprocess.check_output(
            [GIT_EXECUTABLE, "rev-parse", f"{PHASE2B_MERGE_COMMIT}^2"],
            cwd=ROOT,
            text=True,
        ).strip()
        for path in (
            ".github/workflows/genoma-audit.yml",
            ".github/workflows/genoma-policy-engine.yml",
            ".github/workflows/scaffold-validation.yml",
        ):
            text = subprocess.check_output(
                [GIT_EXECUTABLE, "show", f"{phase_two_b_head}:{path}"],
                cwd=ROOT,
                text=True,
            )
            self.assertIn(legacy_runner_pool, text, path)
            self.assertNotIn(canonical_runner_pool, text, path)


if __name__ == "__main__":
    unittest.main()
