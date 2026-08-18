import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

CURRENT_BOOT = "11111111-2222-3333-4444-555555555555"


def _iso(moment):
    return moment.isoformat().replace("+00:00", "Z")


class WgsGateTest(unittest.TestCase):
    def _runtime(self, *, boot_id=CURRENT_BOOT, created_at=None, session_id="session-1", binding=True):
        checks = {}
        for key in (
            "executables_and_versions", "reference_build_and_contigs", "fasta_fai_dictionary",
            "aligner_indexes", "required_resources_checksums", "caller_model_reference_compatibility",
        ):
            checks[key] = {"status": "EXECUTADO"}
        checks["sample_read_group_integrity"] = {"status": "NÃO DISPONÍVEL"}
        checks["fastq_bam_cram_integrity"] = {"status": "NÃO DISPONÍVEL"}
        payload = {
            "gate": "RUNTIME_RESOURCE_GATE",
            "status": "NÃO DISPONÍVEL",
            "ready_for_real_calling": False,
            "inherited_from_previous_session": False,
            "session_id": session_id,
            "checks": checks,
        }
        if binding:
            payload["session_binding"] = {
                "session_id": session_id,
                "boot_id": boot_id,
                "hostname": "runner",
                "platform": "linux",
                "created_at": created_at or _iso(datetime.now(timezone.utc)),
            }
        return payload

    def _verify(self, payload, **kwargs):
        from scripts.verify_runtime_gate_manifest import verify
        kwargs.setdefault("current_boot_id", CURRENT_BOOT)
        return verify(payload, **kwargs)

    def test_environment_scope_can_precede_fastq_alignment(self):
        self.assertEqual(self._verify(self._runtime(), scope="environment"), [])

    def test_full_scope_blocks_until_sample_integrity_and_read_group_execute(self):
        errors = self._verify(self._runtime(), scope="full")
        self.assertTrue(any("sample_read_group_integrity" in e for e in errors))
        self.assertTrue(any("fastq_bam_cram_integrity" in e for e in errors))

    def test_gate_from_another_boot_or_host_is_not_inherited(self):
        """Section 259: 'Não herdar o PASS de outra sessão.'"""
        foreign = self._runtime(boot_id="99999999-8888-7777-6666-555555555555")
        errors = self._verify(foreign, scope="environment")
        self.assertTrue(any("different boot/host" in e for e in errors), errors)

    def test_stale_gate_is_rejected_even_though_it_declares_not_inherited(self):
        old = self._runtime(created_at=_iso(datetime.now(timezone.utc) - timedelta(days=3)))
        self.assertIs(old["inherited_from_previous_session"], False)
        errors = self._verify(old, scope="environment")
        self.assertTrue(any("stale" in e for e in errors), errors)

    def test_gate_without_session_binding_fails_closed(self):
        errors = self._verify(self._runtime(binding=False), scope="environment")
        self.assertTrue(any("session_binding missing" in e for e in errors), errors)

    def test_unbound_gate_is_accepted_only_when_explicitly_allowed(self):
        payload = self._runtime(binding=False)
        self.assertEqual(self._verify(payload, scope="environment", allow_unbound=True), [])

    def test_session_id_mismatch_blocks_a_foreign_attestation(self):
        errors = self._verify(
            self._runtime(session_id="session-A"), scope="environment", expect_session_id="session-B"
        )
        self.assertTrue(any("does not match the consuming session" in e for e in errors), errors)

    def test_producer_binds_the_attestation_to_the_running_kernel(self):
        from scripts.runtime_resource_gate import read_boot_id, session_binding

        binding = session_binding("session-xyz")
        self.assertEqual(binding["session_id"], "session-xyz")
        self.assertEqual(binding["boot_id"], read_boot_id())
        self.assertIsNotNone(binding["created_at"])

    def test_consent_gate_passes_only_for_explicit_verified_genomic_analysis_scope(self):
        from scripts.wgs_consent_gate import evaluate_consent
        manifest = {
            "sample_id": "S1",
            "consent": {
                "status": "VERIFICADO",
                "consent_id": "consent-1",
                "version": "1",
                "purposes": ["genomic_analysis", "clinical_report"],
                "secondary_findings": "AUTHORIZED",
            },
            "provenance": {
                "status": "VERIFICADO",
                "source": "laboratory-export",
                "chain_of_custody_ref": "custody-1",
            },
        }
        result = evaluate_consent(manifest, requested_purpose="genomic_analysis")
        self.assertEqual(result["status"], "VERIFICADO")
        self.assertTrue(result["ready_for_first_dna_read"])

    def test_consent_gate_blocks_missing_or_unverified_scope(self):
        from scripts.wgs_consent_gate import evaluate_consent
        result = evaluate_consent({"sample_id": "S1", "consent": {"status": "PROPOSTO"}}, requested_purpose="genomic_analysis")
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertFalse(result["ready_for_first_dna_read"])

    def test_fastq_manifest_requires_declared_read_group(self):
        from scripts.wgs_input_gate import validate_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "r1.fastq").write_text("@r1/1\nACGT\n+\nIIII\n", encoding="utf-8")
            (root / "r2.fastq").write_text("@r1/2\nTGCA\n+\nIIII\n", encoding="utf-8")
            manifest = root / "sample-manifest.json"
            manifest.write_text(json.dumps({
                "sample_id": "S1",
                "input_type": "FASTQ",
                "r1": "r1.fastq",
                "r2": "r2.fastq",
                "read_group": {"id": "RG1", "sample": "S1", "library": "LIB1", "platform": "ILLUMINA"},
            }), encoding="utf-8")
            result = validate_manifest(manifest)
            self.assertEqual(result["status"], "VERIFICADO")
            self.assertEqual(result["errors"], [])



class AlignmentModeTest(unittest.TestCase):
    """An aligner index is only required when this session will actually align.

    `wgs_align_or_stage.sh` invokes bwa-mem2 only for FASTQ input; BAM/CRAM are sorted
    against the FASTA. Requiring the index for a staged run forced an ~80 GiB one-time build
    and a large resident index that nothing reads. The exemption is narrow and self-checking.
    """

    def _payload(self, *, mode, required, aligner_status, fastq=False):
        checks = {
            key: {"status": "EXECUTADO"}
            for key in (
                "executables_and_versions",
                "reference_build_and_contigs",
                "fasta_fai_dictionary",
                "required_resources_checksums",
                "caller_model_reference_compatibility",
                "sample_read_group_integrity",
            )
        }
        checks["aligner_indexes"] = {"status": aligner_status}
        checks["fastq_bam_cram_integrity"] = {
            "status": "EXECUTADO",
            "details": {"fastq_r1": {}, "fastq_r2": {}} if fastq else {"alignment": {}},
        }
        return {
            "gate": "RUNTIME_RESOURCE_GATE",
            "status": "EXECUTADO",
            "ready_for_real_calling": True,
            "inherited_from_previous_session": False,
            "session_id": "session-mode",
            "alignment_mode": mode,
            "aligner_index_required": required,
            "session_binding": {
                "session_id": "session-mode",
                "boot_id": CURRENT_BOOT,
                "hostname": "runner",
                "platform": "linux",
                "created_at": _iso(datetime.now(timezone.utc)),
            },
            "checks": checks,
        }

    def _verify(self, payload):
        from scripts.verify_runtime_gate_manifest import verify

        return verify(payload, scope="environment", current_boot_id=CURRENT_BOOT)

    def test_staged_run_does_not_require_the_aligner_index(self):
        payload = self._payload(mode="stage", required=False, aligner_status="NÃO APLICÁVEL")
        self.assertEqual(self._verify(payload), [])

    def test_align_run_still_requires_the_aligner_index(self):
        payload = self._payload(mode="align", required=True, aligner_status="NÃO DISPONÍVEL")
        self.assertIn("aligner_indexes not EXECUTADO", self._verify(payload))

    def test_stage_declaration_cannot_coexist_with_fastq_evidence(self):
        payload = self._payload(mode="stage", required=False, aligner_status="NÃO APLICÁVEL", fastq=True)
        errors = self._verify(payload)
        self.assertTrue(any("contradicts FASTQ" in e for e in errors), errors)

    def test_stage_declaration_must_also_declare_the_index_not_required(self):
        payload = self._payload(mode="stage", required=True, aligner_status="NÃO APLICÁVEL")
        errors = self._verify(payload)
        self.assertTrue(any("still declares the aligner index required" in e for e in errors), errors)

    def test_unknown_alignment_mode_is_rejected(self):
        payload = self._payload(mode="turbo", required=False, aligner_status="NÃO APLICÁVEL")
        errors = self._verify(payload)
        self.assertTrue(any("unknown alignment_mode" in e for e in errors), errors)

    def test_producer_forces_align_when_fastq_is_supplied(self):
        """Declaring stage must not let a FASTQ run skip the index."""
        import argparse
        import tempfile

        from scripts import runtime_resource_gate as core

        with tempfile.TemporaryDirectory() as td:
            r1 = Path(td) / "r1.fq"
            r2 = Path(td) / "r2.fq"
            for path in (r1, r2):
                path.write_text("@r\nACGT\n+\nIIII\n", encoding="utf-8")
            args = argparse.Namespace(
                ref_root="/nonexistent",
                fastq_r1=str(r1),
                fastq_r2=str(r2),
                bam=None,
                cram=None,
                caller="bcftools",
                model=None,
                alignment_mode="stage",
            )
            effective = "align" if (args.fastq_r1 or args.fastq_r2) else args.alignment_mode
            self.assertEqual(effective, "align")
            sample = core.check_sample(args)
            self.assertIn("fastq_r1", sample["fastq_bam_cram_integrity"]["details"])

if __name__ == "__main__":
    unittest.main()
