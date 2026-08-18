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


if __name__ == "__main__":
    unittest.main()
