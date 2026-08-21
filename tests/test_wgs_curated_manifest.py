"""The curation manifest wrote verdicts it had not measured.

An external audit found three constants in this builder: `post_deployment_status` was the
literal "PASS" — the one verdict the project reserves for an independent live witness, which
even the four-plane audit refuses to grant itself — `qc_verified` was the literal True while
every other publication criterion was False, and two of the four plane states were declared
PASS by a script that runs no policy engine. The workflow separately staged an evidence
snapshot and an input QC artifact, proved both non-empty, and then never passed either, so
`sources` came out empty on every run.
"""
from __future__ import annotations

import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_wgs_curated_manifest.py"


class CuratedManifestTest(unittest.TestCase):
    def _fixture(self, root: Path, *, qc_status: str = "VERIFICADO", evidence_status: str = "VERIFICADO"):
        vcf = root / "s.vcf.gz"
        with gzip.open(vcf, "wt", encoding="utf-8") as fh:
            fh.write("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
            for i in range(3):
                fh.write(f"1\t{1000 + i}\t.\tA\tG\t50\tPASS\t.\n")
        (root / "runtime.json").write_text(
            json.dumps({"ready_for_real_calling": True, "status": "EXECUTADO"}), encoding="utf-8"
        )
        (root / "ev.json").write_text(
            json.dumps({"status": evidence_status, "adapter": "fixture"}), encoding="utf-8"
        )
        (root / "qc.json").write_text(
            json.dumps({"operational_status": qc_status, "passed": True}), encoding="utf-8"
        )
        return vcf

    def _run(self, root: Path, vcf: Path, *extra: str):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--case-id", "C", "--sample-id", "S",
             "--vcf", str(vcf), "--runtime-gate", str(root / "runtime.json"),
             "--output", str(root / "out.json"), *extra],
            capture_output=True, text=True,
        )

    def _built(self, root: Path, vcf: Path, *extra: str) -> dict:
        result = self._run(root, vcf, "--evidence", str(root / "ev.json"), *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((root / "out.json").read_text(encoding="utf-8"))

    def test_post_deployment_is_never_granted_by_this_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._built(root, self._fixture(root))
        self.assertEqual(payload["post_deployment_status"], "PENDENTE")
        self.assertIn("Production Witness", payload["post_deployment_note"])

    def test_a_run_without_evidence_is_refused_rather_than_written_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = self._run(root, self._fixture(root))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("zero sources", result.stdout + result.stderr)

    def test_evidence_that_failed_verification_is_counted_not_silently_dropped(self):
        # "no sources" and "sources that did not verify" are different situations.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = self._run(
                root, self._fixture(root, evidence_status="PROPOSTO"),
                "--evidence", str(root / "ev.json"),
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Rejected", result.stdout + result.stderr)

    def test_qc_verified_is_derived_from_the_artifact_and_names_its_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._built(root, self._fixture(root), "--input-qc", str(root / "qc.json"))
        self.assertTrue(payload["publication_gate"]["qc_verified"])
        self.assertIn("sha256=", payload["publication_gate"]["qc_basis"])

    def test_a_qc_artifact_that_did_not_verify_does_not_yield_qc_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vcf = self._fixture(root, qc_status="NÃO DISPONÍVEL")
            payload = self._built(root, vcf, "--input-qc", str(root / "qc.json"))
        self.assertFalse(payload["publication_gate"]["qc_verified"])

    def test_without_a_qc_artifact_qc_is_not_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._built(root, self._fixture(root))
        self.assertFalse(payload["publication_gate"]["qc_verified"])
        self.assertIn("NÃO DISPONÍVEL", payload["publication_gate"]["qc_basis"])

    def test_no_plane_is_declared_pass_by_a_script_that_evaluates_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._built(root, self._fixture(root))
        states = {p["state"] for p in payload["policy_evaluation"]["planes"].values()}
        self.assertEqual(states, {"PENDING"})

    def test_the_normative_identity_is_read_from_the_sealed_source(self):
        # A constant copy of the identity is a copy that can fall behind the norm it names.
        import normative

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._built(root, self._fixture(root))
        self.assertEqual(payload["ruleset"]["sha256"], normative.ruleset_block()["sha256"])
        self.assertEqual(payload["ruleset"]["version"], normative.ruleset_block()["version"])

    def test_a_vcf_that_is_not_valid_utf8_is_refused_not_repaired(self):
        # errors="replace" turned undecodable bytes into U+FFFD and counted the line anyway,
        # so a corrupt VCF produced a plausible record count.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fixture(root)
            bad = root / "bad.vcf.gz"
            with gzip.open(bad, "wb") as fh:
                fh.write(b"##fileformat=VCFv4.2\n#CHROM\tPOS\n1\t100\t\xff\xfe\x00rubbish\n")
            result = self._run(root, bad, "--evidence", str(root / "ev.json"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not valid UTF-8", result.stdout + result.stderr)


class WorkflowWiringTest(unittest.TestCase):
    """Staging a file and proving it non-empty is not the same as reading it."""

    def test_the_workflow_passes_the_evidence_and_qc_it_stages(self):
        text = (ROOT / "workflows" / "wgs.nf").read_text(encoding="utf-8")
        self.assertIn("--evidence '${evidence_snapshot}'", text)
        self.assertIn("--input-qc '${input_qc}'", text)

    def test_the_workflow_asserts_the_manifest_carries_sources_and_stays_pendente(self):
        text = (ROOT / "workflows" / "wgs.nf").read_text(encoding="utf-8")
        self.assertIn(".sources | length > 0", text)
        self.assertIn('.post_deployment_status == "PENDENTE"', text)


if __name__ == "__main__":
    unittest.main()
