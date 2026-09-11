from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = json.loads((ROOT / "config/project_identity.json").read_text(encoding="utf-8"))
LEGACY_WORD = "code" + "work"


class Phase2BRuntimeBuildIdentityTest(unittest.TestCase):
    @staticmethod
    def read(path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_runtime_and_container_identity_are_canonical(self) -> None:
        runtime = IDENTITY["runtime"]
        self.assertIn(f"WORKDIR {runtime['root']}", self.read("Dockerfile"))
        scaffold = self.read(".github/workflows/scaffold-validation.yml")
        self.assertIn(runtime["container_package"], scaffold)
        self.assertIn(runtime["cache_namespace"], scaffold)
        self.assertNotIn("/opt/" + LEGACY_WORD, scaffold)

    def test_phase_two_c_runner_boundary_remains_legacy_during_phase_two_b(self) -> None:
        legacy_runner_pool = LEGACY_WORD + "-isolated"
        canonical_runner_pool = IDENTITY["runners"]["pool_label"]
        for path in (
            ".github/workflows/genoma-audit.yml",
            ".github/workflows/genoma-policy-engine.yml",
            ".github/workflows/scaffold-validation.yml",
        ):
            text = self.read(path)
            self.assertIn(legacy_runner_pool, text, path)
            self.assertNotIn(canonical_runner_pool, text, path)


if __name__ == "__main__":
    unittest.main()
