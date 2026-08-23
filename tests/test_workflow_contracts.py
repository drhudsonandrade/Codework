import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowContractTest(unittest.TestCase):
    def test_production_witness_uses_current_live_smoke_cli_contract(self):
        workflow = (ROOT / ".github/workflows/genoma-production-witness.yml").read_text(encoding="utf-8")
        self.assertIn("--output evidence/live-section-260/summary.json", workflow)
        self.assertIn("--deployment-id", workflow)
        self.assertNotIn("--output-dir evidence/live-section-260", workflow)

    def test_production_witness_covers_every_main_commit(self):
        workflow = (ROOT / ".github/workflows/genoma-production-witness.yml").read_text(encoding="utf-8")
        header = workflow.split("permissions:", 1)[0]
        self.assertIn("push:\n    branches: [main]", header)
        push_block = header.split("push:\n", 1)[1].split("workflow_dispatch:", 1)[0]
        self.assertNotIn("paths:", push_block)

    def test_production_witness_write_permission_is_isolated_to_main_publish_job(self):
        workflow = (ROOT / ".github/workflows/genoma-production-witness.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("publish-witness:", workflow)
        publish = workflow.split("publish-witness:", 1)[1]
        self.assertIn("if: github.event_name == 'push' && github.ref == 'refs/heads/main'", publish)
        self.assertIn("permissions:\n      contents: write", publish)
        witness = workflow.split("jobs:", 1)[1].split("publish-witness:", 1)[0]
        self.assertNotIn("contents: write", witness)

    def test_manual_production_ceremony_does_not_duplicate_every_main_push(self):
        workflow = (ROOT / ".github/workflows/genoma-production-ceremony.yml").read_text(encoding="utf-8")
        header = workflow.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", header)
        self.assertNotIn("push:", header)

    def test_every_self_pushing_workflow_serialises_runs_on_its_ref(self):
        """A workflow that pushes back to its own ref must not race itself.

        Two runs in flight on one ref end with the loser rejected as a
        non-fast-forward, or with a commit built on a tree the other run has
        already replaced. Queueing (never cancelling) keeps each triggering push
        materialized exactly once.
        """
        workflows = sorted((ROOT / ".github/workflows").glob("*.yml"))
        self.assertTrue(workflows, "no workflows found to check")
        for path in workflows:
            text = path.read_text(encoding="utf-8")
            if "git push" not in text:
                continue
            with self.subTest(workflow=path.name):
                header = text.split("jobs:", 1)[0]
                self.assertIn("concurrency:", header, f"{path.name} pushes without a concurrency group")
                self.assertIn("${{ github.ref }}", header, f"{path.name} concurrency group is not per-ref")
                self.assertIn(
                    "cancel-in-progress: false",
                    header,
                    f"{path.name} may cancel a run that has already pushed",
                )

    def test_production_witness_derives_the_canonical_digest_from_the_manifest(self):
        """The witness must not restate the digest it is supposed to be proving.

        Parsing manifests/RULESET_V3.4.sha256 once and reusing it keeps the
        validation, the endpoint assertion and witness.json on a single source,
        so a migration cannot update the manifest and leave a stale literal.
        """
        workflow = (ROOT / ".github/workflows/genoma-production-witness.yml").read_text(encoding="utf-8")
        manifest = (ROOT / "manifests/RULESET_V3.4.sha256").read_text(encoding="ascii").split()
        self.assertEqual(len(manifest), 2, "manifest must be '<digest>  <canonical filename>'")
        digest = manifest[0]

        self.assertIn('read -r expected_sha expected_name < "$manifest"', workflow)
        self.assertIn("GENOMA_EXPECTED_RULESET_SHA=$expected_sha", workflow)
        self.assertNotIn(
            digest,
            workflow,
            "the canonical digest is duplicated as a literal instead of derived from the manifest",
        )

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
