"""Verify the Phase 2C trusted-runner routing cutover."""

from pathlib import Path
import json
import unittest

from tests.test_ci_optimization_contract import _job_block

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PLAN = ROOT / "docs" / "superpowers" / "plans" / "2026-09-11-omnigenis-phase2c-runner-identity-cutover.md"
LEGACY = "code" + "work"
CANONICAL_POOL = "omnigenis-isolated"
TRUSTED_SELECTOR = (
    "runs-on: ${{ ((github.event_name == 'push' || github.event_name == 'workflow_dispatch') "
    "&& github.ref == 'refs/heads/main' && github.ref_protected) && 'omnigenis-isolated' "
    "|| 'ubuntu-latest' }}"
)


class Phase2CRunnerIdentityTest(unittest.TestCase):
    """Keep canonical private routing behind the existing trust boundary."""

    @staticmethod
    def read(relative: str) -> str:
        """Read an active repository text file as UTF-8."""
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_plan_resolves_repository_selector_before_runner_api_calls(self) -> None:
        """Require the runner plan to work from a fresh shell."""
        plan = PLAN.read_text(encoding="utf-8")
        initializer = 'repo="$(gh api repositories/1212760346 --jq .full_name)"'
        first_runner_call = "gh api repos/$repo/actions/runners"
        self.assertIn(initializer, plan)
        self.assertIn(first_runner_call, plan)
        self.assertLess(plan.index(initializer), plan.index(first_runner_call))

    def test_three_trusted_jobs_use_exact_canonical_selector(self) -> None:
        """Require the canonical pool on exactly the trusted heavy jobs."""
        for relative in (
            ".github/workflows/genoma-audit.yml",
            ".github/workflows/genoma-policy-engine.yml",
            ".github/workflows/scaffold-validation.yml",
        ):
            text = self.read(relative)
            self.assertIn(TRUSTED_SELECTOR, text, relative)
            self.assertNotIn(LEGACY + "-isolated", text, relative)

    def test_untrusted_and_write_capability_jobs_remain_hosted(self) -> None:
        """Do not route PR, publish, or capability jobs to self-hosted runners."""
        hosted_expectations = {
            ".github/workflows/scaffold-validation.yml": (
                "changes",
                "container-canary",
                "publish-ghcr",
            ),
            ".github/workflows/genoma-policy-engine.yml": (
                "changes",
                "rego",
                "container",
                "publish",
            ),
        }
        for relative, job_names in hosted_expectations.items():
            text = self.read(relative)
            for job_name in job_names:
                block = _job_block(text, job_name)
                self.assertIn("runs-on: ubuntu-latest", block)
                self.assertNotIn(CANONICAL_POOL, block)

    def test_project_identity_contract_is_the_runner_authority(self) -> None:
        """Bind repository routing to the canonical runner identity contract."""
        contract = json.loads(self.read("config/project_identity.json"))
        runners = contract["runners"]
        self.assertEqual(runners["pool_label"], CANONICAL_POOL)
        self.assertEqual(runners["per_runner_labels"], ["omnigenis-01", "omnigenis-02"])
        self.assertEqual(
            runners["runner_names"],
            ["omnigenis-runner-01", "omnigenis-runner-02"],
        )

    def test_phase_two_c_ledger_entries_are_sealed(self) -> None:
        """Require retired repository runner identities to have zero budget."""
        ledger = json.loads(self.read("config/legacy_identity_ledger.json"))
        entries = {entry["id"]: entry for entry in ledger["entries"]}
        self.assertEqual(entries["runner-pool"]["locations"], {})
        self.assertEqual(entries["ci-test-function-name"]["locations"], {})



if __name__ == "__main__":
    unittest.main()
