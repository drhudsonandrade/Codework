import json
import tempfile
import unittest
from pathlib import Path


class WgsGateTest(unittest.TestCase):
    def _runtime(self):
        checks = {}
        for key in (
            "executables_and_versions", "reference_build_and_contigs", "fasta_fai_dictionary",
            "aligner_indexes", "required_resources_checksums", "caller_model_reference_compatibility",
        ):
            checks[key] = {"status": "EXECUTADO"}
        checks["sample_read_group_integrity"] = {"status": "NÃO DISPONÍVEL"}
        checks["fastq_bam_cram_integrity"] = {"status": "NÃO DISPONÍVEL"}
        return {
            "gate": "RUNTIME_RESOURCE_GATE",
            "status": "NÃO DISPONÍVEL",
            "ready_for_real_calling": False,
            "inherited_from_previous_session": False,
            "session_id": "session-1",
            "checks": checks,
        }

    def test_environment_scope_can_precede_fastq_alignment(self):
        from scripts.verify_runtime_gate_manifest import verify
        self.assertEqual(verify(self._runtime(), scope="environment"), [])

    def test_full_scope_blocks_until_sample_integrity_and_read_group_execute(self):
        from scripts.verify_runtime_gate_manifest import verify
        errors = verify(self._runtime(), scope="full")
        self.assertTrue(any("sample_read_group_integrity" in e for e in errors))
        self.assertTrue(any("fastq_bam_cram_integrity" in e for e in errors))

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


class WgsInputPathContainmentTest(unittest.TestCase):
    """The manifest is sample-supplied input, so it must not confer filesystem authority.

    `resolve` handed the caller whatever the manifest named — an absolute path verbatim,
    a `../` chain joined onto the sample root — and the gate then hashed and recorded it
    as a verified sample input. Containment is asserted here at both levels: the helper
    refuses, and `validate_manifest` turns that refusal into a fail-closed status instead
    of an unhandled traceback.
    """

    def _manifest(self, root: Path, **overrides) -> Path:
        payload = {
            "sample_id": "S1",
            "input_type": "FASTQ",
            "r1": "r1.fastq",
            "r2": "r2.fastq",
            "read_group": {"id": "RG1", "sample": "S1", "library": "LIB1", "platform": "ILLUMINA"},
        }
        payload.update(overrides)
        path = root / "sample-manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_relative_path_cannot_escape_the_sample_root(self):
        from scripts.wgs_input_gate import resolve
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            for escape in ("../outside.fastq.gz", "nested/../../outside.bam", "../"):
                with self.subTest(escape=escape):
                    with self.assertRaises(ValueError):
                        resolve(root, escape)

    def test_absolute_path_is_not_ambient_authority(self):
        from scripts.wgs_input_gate import resolve
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            with self.assertRaises(ValueError):
                resolve(root, "/etc/passwd")

    def test_symlink_out_of_the_sample_root_is_refused(self):
        from scripts.wgs_input_gate import resolve
        with tempfile.TemporaryDirectory() as outer:
            outer_root = Path(outer).resolve()
            secret = outer_root / "secret.fastq"
            secret.write_text("@r1/1\nACGT\n+\nIIII\n", encoding="utf-8")
            root = outer_root / "sample"
            root.mkdir()
            (root / "r1.fastq").symlink_to(secret)
            with self.assertRaises(ValueError):
                resolve(root, "r1.fastq")

    def test_a_symlink_loop_is_a_domain_refusal_not_a_traceback(self):
        """`Path.resolve()` raises RuntimeError on a loop, which is not this gate's error.

        A sample directory containing a symlink loop killed the gate with an unhandled
        RuntimeError, so `workflows/wgs.nf` never got the NÃO DISPONÍVEL it stops on — the
        opposite of fail-closed, reached through the very call added to enforce containment.
        """
        from scripts.wgs_input_gate import resolve
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "loop").symlink_to(root / "loop2")
            (root / "loop2").symlink_to(root / "loop")
            with self.assertRaises(ValueError):
                resolve(root, "loop/r1.fastq")

    def test_a_non_string_input_is_a_domain_refusal_not_a_traceback(self):
        """A manifest is JSON, so a path field can arrive as a number, bool, list or object."""
        from scripts.wgs_input_gate import resolve
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            for value in (123, True, ["r1.fastq"], {"path": "r1.fastq"}, 1.5):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        resolve(root, value)

    def test_a_falsy_non_string_is_a_wrong_type_not_a_missing_field(self):
        """`not value` swallowed every falsy non-string as though the field were absent.

        A manifest declaring `"r1": 0` did supply r1 — just not as text. Reporting "FASTQ
        requires r1 and r2" names the wrong fact, and the type error it actually is went
        unsaid.
        """
        from scripts.wgs_input_gate import resolve
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            for value in (False, 0, 0.0, [], {}):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError) as caught:
                        resolve(root, value)
                    self.assertIn("must be a string", str(caught.exception))
            # Genuinely absent stays absent, and is not turned into a type error.
            self.assertIsNone(resolve(root, None))
            self.assertIsNone(resolve(root, ""))

    def test_the_probe_and_the_hash_read_one_handle(self):
        """Reopening the validated path by name left a window between check and read.

        `fastq_probe` opened the file to probe it and `sha256_file` opened it again to hash
        it, so the bytes recorded as this sample's input were not provably the bytes the
        probe accepted. Both now come from a single handle, and the final component is
        opened with O_NOFOLLOW.
        """
        from scripts.wgs_input_gate import fastq_probe, open_contained
        import hashlib

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            fastq = root / "r1.fastq"
            body = "@r1/1\nACGT\n+\nIIII\n"
            fastq.write_text(body, encoding="utf-8")
            ok, detail = fastq_probe(fastq)
            self.assertTrue(ok, detail)
            self.assertEqual(
                detail["sha256"], hashlib.sha256(body.encode("utf-8")).hexdigest()
            )

            # A symlink at the final component is refused by the opener itself, even when
            # the target is inside the sample directory.
            link = root / "link.fastq"
            link.symlink_to(fastq)
            with self.assertRaises(ValueError):
                open_contained(link)

    def test_a_non_string_fastq_field_fails_closed_end_to_end(self):
        from scripts.wgs_input_gate import validate_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "r2.fastq").write_text("@r1/2\nTGCA\n+\nIIII\n", encoding="utf-8")
            result = validate_manifest(self._manifest(root, r1=123))
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertTrue(result["errors"])
            self.assertNotIn("r1", result["inputs"])

    def test_contained_relative_path_still_resolves(self):
        from scripts.wgs_input_gate import resolve
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "nested").mkdir()
            (root / "nested" / "r1.fastq").write_text("@r1/1\nACGT\n+\nIIII\n", encoding="utf-8")
            self.assertEqual(resolve(root, "nested/r1.fastq"), root / "nested" / "r1.fastq")
            self.assertIsNone(resolve(root, None))
            self.assertIsNone(resolve(root, ""))

    def test_escaping_fastq_manifest_fails_closed_instead_of_raising(self):
        from scripts.wgs_input_gate import validate_manifest
        with tempfile.TemporaryDirectory() as outer:
            outer_root = Path(outer).resolve()
            (outer_root / "outside.fastq").write_text("@r1/1\nACGT\n+\nIIII\n", encoding="utf-8")
            root = outer_root / "sample"
            root.mkdir()
            (root / "r2.fastq").write_text("@r1/2\nTGCA\n+\nIIII\n", encoding="utf-8")
            result = validate_manifest(self._manifest(root, r1="../outside.fastq"))
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertTrue(any("escapes" in error for error in result["errors"]), result["errors"])
            self.assertNotIn("r1", result["inputs"])

    def test_absolute_alignment_manifest_fails_closed_instead_of_raising(self):
        from scripts.wgs_input_gate import validate_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            outside = root.parent / "outside.bam"
            result = validate_manifest(
                self._manifest(root, input_type="BAM", alignment=str(outside), r1=None, r2=None)
            )
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertTrue(any("absolute" in error for error in result["errors"]), result["errors"])
            self.assertNotIn("alignment", result["inputs"])


class WgsAlignConsumesVerifiedInputsTest(unittest.TestCase):
    """Containment that stops at the gate's process boundary contains nothing.

    `wgs_align_or_stage.sh` re-read the raw manifest with `jq`, explicitly honoured an
    absolute path (`[[ "$r1" = /* ]] || r1="$sample_dir/$r1"`) and checked no digest, so the
    path alignment consumed was never the path the gate verified.
    """

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.script = (root / "scripts" / "wgs_align_or_stage.sh").read_text(encoding="utf-8")
        self.workflow = (root / "workflows" / "wgs.nf").read_text(encoding="utf-8")

    def test_paths_come_from_the_verified_record_not_the_raw_manifest(self):
        for key in (".r1", ".alignment"):
            with self.subTest(key=key):
                self.assertNotIn(f"jq -r '{key}' \"$manifest\"", self.script)
        self.assertIn("verified_input r1", self.script)
        self.assertIn("verified_input r2", self.script)
        self.assertIn("verified_input alignment", self.script)

    def test_an_absolute_path_is_no_longer_honoured(self):
        self.assertNotIn('= /* ]] ||', self.script)

    def test_the_recorded_digest_is_rechecked_before_use(self):
        self.assertIn("sha256sum", self.script)
        self.assertIn("changed after the gate verified it", self.script)

    def test_containment_is_rechecked_at_the_point_of_use(self):
        self.assertIn("outside the sample directory", self.script)

    def test_the_gate_verdict_gates_the_alignment(self):
        self.assertIn('jq -r \'.status\' "$input_qc"', self.script)

    def test_the_workflow_hands_the_verified_record_to_the_script(self):
        self.assertIn("aligned/sample.bam \\\n        '${input_qc}'", self.workflow)


if __name__ == "__main__":
    unittest.main()
