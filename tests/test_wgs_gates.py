import errno
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path


def _tools_available() -> bool:
    """Whether the executable script tests can run at all.

    They drive the real `wgs_align_or_stage.sh`, so bash, jq and sha256sum have to exist —
    and so does `/dev/fd`, because the script refuses outright without it rather than
    falling back to consuming a path by name. Skipping is honest where a precondition is
    absent; asserting on a script that cannot run there is not, and a suite that fails on
    the environment instead of on the code teaches readers to ignore it.
    """
    if not os.path.isdir("/dev/fd"):
        return False
    return all(shutil.which(tool) for tool in ("bash", "jq", "sha256sum"))


def _can_mkfifo() -> bool:
    """Whether this filesystem and sandbox permit creating a FIFO.

    Some sandboxes deny `mknod`/`mkfifo` outright. The property under test is about the
    gate, not about the runner's permissions, so a refusal to create the fixture is a skip.
    """
    try:
        with tempfile.TemporaryDirectory() as probe:
            os.mkfifo(Path(probe) / "fifo")
    except (OSError, NotImplementedError, AttributeError):
        return False
    return True



class WgsGateTest(unittest.TestCase):
    def _runtime(self):
        """A runtime-gate fixture whose checks all pass, so a test can vary one thing."""
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
        """Write a valid FASTQ manifest, with `overrides` replacing individual fields.

        Valid by default so each test states only the one thing it is about; a test that
        built its own manifest from scratch would restate the schema and drift from it.
        """
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

    def test_a_dotdot_component_cannot_walk_out_of_the_root(self):
        """`relative_to` does not normalise, so the walk itself must refuse `..`.

        For `root=/s` and `path=/s/../outside.fastq`, `relative_to` returns
        `../outside.fastq` and `parts` is `('..', 'outside.fastq')`. The component-wise walk
        then opens `..` with `dir_fd` and is outside the root with no symlink involved at
        all — `O_NOFOLLOW` never fires because nothing is a link. Today's callers pass paths
        `resolve` already normalised, but `open_contained` is the containment boundary and is
        called directly, so it has to hold on its own.
        """
        from scripts.wgs_input_gate import open_contained
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve() / "sample"
            root.mkdir()
            (Path(td).resolve() / "outside.fastq").write_bytes(b"@outside\nACGT\n+\nIIII\n")
            for escape in ("..", "nested/../.."):
                with self.subTest(escape=escape):
                    with self.assertRaises(ValueError) as caught:
                        open_contained(root, root.joinpath(escape, "outside.fastq"))
                    self.assertIn("escapes the sample directory", str(caught.exception))

    def test_a_containment_refusal_is_not_recorded_as_a_missing_file(self):
        """The Evidence Plane must not describe a containment breach as an absent file.

        Every `open_contained` refusal — escape, symlink, swapped parent — was flattened to
        `reason: "missing_or_empty"`, which reads as "the sample forgot to upload R1" rather
        than "something tried to redirect this read outside the sample directory".
        """
        from scripts.wgs_input_gate import fastq_probe
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            outside = root / "outside.fastq"
            outside.write_bytes(b"@outside\nACGT\n+\nIIII\n")
            sample = root / "sample"
            sample.mkdir()
            (sample / "r1.fastq").symlink_to(outside)
            ok, detail = fastq_probe(sample, sample / "r1.fastq")
            self.assertFalse(ok)
            self.assertNotEqual(detail["reason"], "missing_or_empty")
            self.assertIn("refused", detail["reason"])

    def test_a_corrupt_gzip_body_is_a_refusal_not_a_dead_gate(self):
        """`zlib.error` is not an `OSError`, so it escaped every handler in the probe.

        A FASTQ with a valid gzip header and a damaged deflate body — a truncated or
        interrupted upload, which is an ordinary way for a sample to arrive — raised
        `zlib.error` straight out of `fastq_probe`, through `validate_manifest`, and killed
        the gate. No `input-qc.json`, no status, and the WGS lane left waiting on a verdict
        that never comes. Same failure mode as the FIFO: not a refusal, an absence.
        """
        from scripts.wgs_input_gate import fastq_probe, validate_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            good = gzip.compress(b"@r1\nACGT\n+\nIIII\n")
            corrupt = good[:12] + b"\xff" * 8 + good[-8:]
            (root / "r1.fastq.gz").write_bytes(corrupt)
            (root / "r2.fastq.gz").write_bytes(corrupt)
            ok, detail = fastq_probe(root, root / "r1.fastq.gz")
            self.assertFalse(ok)
            self.assertIn("error", detail["reason"].lower())

            # And end to end: the gate answers with a document rather than dying.
            result = validate_manifest(
                self._manifest(root, r1="r1.fastq.gz", r2="r2.fastq.gz")
            )
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertTrue(result["errors"])

    def test_an_empty_file_is_still_reported_as_empty(self):
        """The refusal reason must not swallow the ordinary case it sits next to."""
        from scripts.wgs_input_gate import fastq_probe
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "r1.fastq").write_bytes(b"")
            ok, detail = fastq_probe(root, root / "r1.fastq")
            self.assertFalse(ok)
            self.assertEqual(detail["reason"], "missing_or_empty")

    def test_a_file_that_is_simply_absent_is_not_called_a_refusal(self):
        """The mirror of the previous bug, and just as wrong.

        `open_contained` turns ENOENT into a ValueError like every other failure, so
        reporting all of them as `refused` made a FASTQ the sample never delivered into
        evidence that something tried to escape the sample directory. Absent, refused and
        unreadable are three different facts about the run and each gets its own word.
        """
        from scripts.wgs_input_gate import fastq_probe
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            for label, missing in (
                ("no file", root / "r1.fastq"),
                ("no parent directory", root / "nested" / "r1.fastq"),
            ):
                with self.subTest(case=label):
                    ok, detail = fastq_probe(root, missing)
                    self.assertFalse(ok)
                    self.assertEqual(detail["reason"], "missing_or_empty")

    def test_an_absent_alignment_is_not_called_a_refusal(self):
        """Same distinction on the BAM/CRAM path, which had the same flattening."""
        from scripts.wgs_input_gate import validate_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            result = validate_manifest(
                self._manifest(root, input_type="BAM", alignment="sample.bam", r1=None, r2=None)
            )
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertIn("BAM alignment missing_or_empty", result["errors"])
            self.assertFalse(
                any("refused" in error for error in result["errors"]), result["errors"]
            )

    @unittest.skipUnless(_can_mkfifo(), "this sandbox does not permit mkfifo")
    def test_a_fifo_input_is_refused_instead_of_parking_the_gate(self):
        """A gate that never returns is not fail-closed — it is just gone.

        `os.open(fifo, O_RDONLY)` blocks until a writer appears. A manifest naming a FIFO
        inside the sample directory therefore parked the gate: nothing downstream ever read
        a status, and `input-qc.json` was never written at all. The open is now
        non-blocking and anything that is not a regular file is refused on the descriptor
        already held.

        Run on a daemon thread with a join timeout so a regression reports a failure here
        rather than hanging CI.
        """
        from scripts.wgs_input_gate import fastq_probe
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            os.mkfifo(root / "r1.fastq")
            outcome = {}

            def probe():
                outcome["result"] = fastq_probe(root, root / "r1.fastq")

            worker = threading.Thread(target=probe, daemon=True)
            worker.start()
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive(), "the gate blocked on a FIFO input")
            ok, detail = outcome["result"]
            self.assertFalse(ok)
            self.assertIn("not a regular file", detail["reason"])

    def test_an_open_that_fails_for_any_other_reason_is_unreadable(self):
        """EACCES is neither an absence nor a containment refusal, and says so.

        Forced through the syscall rather than through `chmod`, so the test states the same
        fact whatever user it runs as — root ignores the permission bits entirely.
        """
        import scripts.wgs_input_gate as gate
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "r1.fastq").write_bytes(b"@r\nACGT\n+\nIIII\n")
            (root / "sample.bam").write_bytes(b"BAM\x01")
            real_open = os.open

            def deny_the_file(path, flags, *args, **kwargs):
                if path in ("r1.fastq", "sample.bam"):
                    raise OSError(errno.EACCES, "Permission denied")
                return real_open(path, flags, *args, **kwargs)

            with unittest.mock.patch.object(gate.os, "open", side_effect=deny_the_file):
                ok, detail = gate.fastq_probe(root, root / "r1.fastq")
                self.assertFalse(ok)
                self.assertIn("unreadable", detail["reason"])
                self.assertNotIn("missing_or_empty", detail["reason"])
                self.assertNotIn("refused", detail["reason"])

                for input_type in ("BAM", "CRAM"):
                    with self.subTest(input_type=input_type):
                        result = gate.validate_manifest(
                            self._manifest(
                                root,
                                input_type=input_type,
                                alignment="sample.bam",
                                r1=None,
                                r2=None,
                            )
                        )
                        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
                        self.assertTrue(
                            any(
                                f"{input_type} alignment unreadable" in error
                                for error in result["errors"]
                            ),
                            result["errors"],
                        )

    def test_a_refused_alignment_is_not_called_absent(self):
        """And the distinction has to cut both ways, or it is just the old bug renamed."""
        from scripts.wgs_input_gate import validate_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            outside = root / "outside.bam"
            outside.write_bytes(b"BAM\x01outside")
            sample = root / "sample"
            sample.mkdir()
            (sample / "sample.bam").symlink_to(outside)
            result = validate_manifest(
                self._manifest(
                    sample, input_type="BAM", alignment="sample.bam", r1=None, r2=None
                )
            )
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertTrue(
                any("escapes the sample directory" in error for error in result["errors"]),
                result["errors"],
            )
            self.assertFalse(
                any("missing_or_empty" in error for error in result["errors"]),
                result["errors"],
            )

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

        `fastq_probe` opened the file to probe it and hashed it through a second open, so the
        bytes recorded as this sample's input were not provably the bytes the probe accepted.
        The count is asserted, not assumed: a regression that reopens the path would raise
        the number of opens even though the hash still matched.
        """
        import hashlib
        from unittest.mock import patch

        from scripts import wgs_input_gate

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            fastq = root / "r1.fastq"
            body = "@r1/1\nACGT\n+\nIIII\n"
            fastq.write_text(body, encoding="utf-8")

            real = wgs_input_gate.open_contained
            calls = []

            def counting(root_arg, path_arg):
                calls.append(path_arg)
                return real(root_arg, path_arg)

            with patch.object(wgs_input_gate, "open_contained", counting):
                ok, detail = wgs_input_gate.fastq_probe(root, fastq)
            self.assertTrue(ok, detail)
            self.assertEqual(
                detail["sha256"], hashlib.sha256(body.encode("utf-8")).hexdigest()
            )
            self.assertEqual(len(calls), 1, f"opened {len(calls)} times: {calls}")

    def test_a_symlink_final_component_is_refused_by_the_probe_itself(self):
        """Not only by the opener called directly — the probe must refuse it too."""
        from scripts.wgs_input_gate import fastq_probe, open_contained

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            fastq = root / "r1.fastq"
            fastq.write_text("@r1/1\nACGT\n+\nIIII\n", encoding="utf-8")
            link = root / "link.fastq"
            link.symlink_to(fastq)
            with self.assertRaises(ValueError):
                open_contained(root, link)
            ok, detail = fastq_probe(root, link)
            self.assertFalse(ok, detail)

    def test_a_swapped_parent_directory_cannot_redirect_the_open(self):
        """O_NOFOLLOW on the last component alone leaves the parents swappable.

        Given `nested/r1.fastq`, `nested` can be replaced with a link to somewhere else after
        containment accepted the path, and the final open then lands on an outside file that
        is a perfectly ordinary regular file. Every component is opened with O_NOFOLLOW from
        the root, so the walk refuses at `nested`.
        """
        from scripts.wgs_input_gate import open_contained

        with tempfile.TemporaryDirectory() as outer:
            outer_root = Path(outer).resolve()
            elsewhere = outer_root / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / "r1.fastq").write_text("@x/1\nACGT\n+\nIIII\n", encoding="utf-8")

            root = outer_root / "sample"
            root.mkdir()
            nested = root / "nested"
            nested.mkdir()
            (nested / "r1.fastq").write_text("@r1/1\nTGCA\n+\nIIII\n", encoding="utf-8")
            contained = nested / "r1.fastq"

            # The swap happens after the path was accepted.
            import shutil

            shutil.rmtree(nested)
            nested.symlink_to(elsewhere)
            with self.assertRaises(ValueError):
                open_contained(root, contained)

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


REPO_ROOT = Path(__file__).resolve().parents[1]
ALIGN_SCRIPT = REPO_ROOT / "scripts" / "wgs_align_or_stage.sh"

SAMTOOLS_STUB = """#!/usr/bin/env bash
echo "samtools $*" >> "$STUB_LOG"
sub="$1"; shift
case "$sub" in
  sort)
    out=""; src=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        -@) shift 2 ;;
        -o) out="$2"; shift 2 ;;
        *) src="$1"; shift ;;
      esac
    done
    if [[ -z "$src" || "$src" == "-" ]]; then cat > "$out"; else cat "$src" > "$out"; fi
    ;;
  view)
    if [[ " $* " == *" -H "* ]]; then
      printf '@HD\\tVN:1.6\\n@RG\\tID:RG1\\tSM:%s\\n' "$STUB_SAMPLE"
    else
      cat "${@: -1}"
    fi
    ;;
  index|quickcheck) : ;;
  *) echo "unexpected samtools subcommand: $sub" >&2; exit 90 ;;
esac
"""

BWA_STUB = """#!/usr/bin/env bash
echo "bwa-mem2 $*" >> "$STUB_LOG"
# A hostile agent that owns the sample directory acts here: between the digest check and
# the read, it repoints the verified name at content of its choosing.
if [[ -n "${STUB_SWAP_TARGET:-}" ]]; then
  rm -f "$STUB_SWAP_TARGET"
  printf 'SWAPPED-BY-THE-ATTACKER\\n' > "$STUB_SWAP_TARGET"
fi
cat "${@: -2:1}" > "$STUB_R1_SEEN"
cat "${@: -1}" > "$STUB_R2_SEEN"
printf 'ALIGNED\\n'
"""



@unittest.skipUnless(_tools_available(), "bash, jq, sha256sum and /dev/fd are required")
class WgsAlignConsumesVerifiedInputsTest(unittest.TestCase):
    """Containment that stops at the gate's process boundary contains nothing.

    `wgs_align_or_stage.sh` re-read the raw manifest with `jq`, explicitly honoured an
    absolute path (`[[ "$r1" = /* ]] || r1="$sample_dir/$r1"`) and checked no digest, so the
    path alignment consumed was never the path the gate verified.

    Reading the script's source text cannot show any of that: an assertion that the string
    `sha256sum` appears still passes when the digest is compared against itself, and one that
    a refusal message exists still passes when nothing reaches it. So the script is *run*
    here, against stubbed `bwa-mem2` and `samtools` that record every invocation, and each
    refusal is asserted to happen before either tool is called.
    """

    def _fixture(self, root: Path, *, status="VERIFICADO", r1_path=None, r1_digest=None):
        """Lay out a sample directory plus the stub toolchain; return (paths, env)."""
        sample_dir = root / "sample"
        sample_dir.mkdir()
        r1 = sample_dir / "r1.fastq"
        r2 = sample_dir / "r2.fastq"
        r1.write_bytes(b"@read1\nACGT\n+\nIIII\n")
        r2.write_bytes(b"@read1\nTGCA\n+\nIIII\n")
        ref = root / "ref.fasta"
        ref.write_text(">chr1\nACGT\n", encoding="utf-8")

        manifest = sample_dir / "sample-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "sample_id": "S1",
                    "input_type": "FASTQ",
                    "r1": "r1.fastq",
                    "r2": "r2.fastq",
                    "read_group": {"id": "RG1", "sample": "S1", "library": "L1", "platform": "ILLUMINA"},
                }
            ),
            encoding="utf-8",
        )
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()  # noqa: E731
        input_qc = root / "input-qc.json"
        input_qc.write_text(
            json.dumps(
                {
                    "status": status,
                    "inputs": {
                        "r1": {"path": r1_path or str(r1), "sha256": r1_digest or digest(r1)},
                        "r2": {"path": str(r2), "sha256": digest(r2)},
                    },
                }
            ),
            encoding="utf-8",
        )

        stub_dir = root / "bin"
        stub_dir.mkdir()
        for name, body in (("samtools", SAMTOOLS_STUB), ("bwa-mem2", BWA_STUB)):
            stub = stub_dir / name
            stub.write_text(body, encoding="utf-8")
            stub.chmod(0o755)

        env = dict(os.environ)
        env.update(
            PATH=f"{stub_dir}{os.pathsep}{env['PATH']}",
            STUB_LOG=str(root / "tools.log"),
            STUB_SAMPLE="S1",
            STUB_R1_SEEN=str(root / "r1.seen"),
            STUB_R2_SEEN=str(root / "r2.seen"),
        )
        return {"manifest": manifest, "ref": ref, "out": root / "out" / "sample.bam", "qc": input_qc, "r1": r1}, env

    def _run(self, paths, env):
        """Run the real alignment script against the stub toolchain and capture everything."""
        return subprocess.run(
            [
                "bash",
                str(ALIGN_SCRIPT),
                str(paths["manifest"]),
                str(paths["ref"]),
                str(paths["out"]),
                str(paths["qc"]),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    def _assert_no_tool_ran(self, env):
        """Assert the refusal happened *before* bwa-mem2 or samtools were reached.

        A non-zero exit alone would also be satisfied by a script that ran the aligner and
        then failed, which is the opposite of the property under test.
        """
        log = Path(env["STUB_LOG"])
        self.assertFalse(log.exists() and log.read_text(encoding="utf-8").strip(),
                         f"alignment tools ran: {log.read_text(encoding='utf-8') if log.exists() else ''}")

    def test_a_gate_verdict_short_of_verificado_stops_before_any_tool_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, env = self._fixture(Path(tmp), status="NÃO DISPONÍVEL")
            result = self._run(paths, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("input gate did not verify this sample", result.stderr)
            self._assert_no_tool_ran(env)

    def test_a_recorded_path_outside_the_sample_directory_stops_before_any_tool_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.fastq"
            outside.write_bytes(b"@evil\nACGT\n+\nIIII\n")
            paths, env = self._fixture(
                root,
                r1_path=str(outside),
                r1_digest=hashlib.sha256(outside.read_bytes()).hexdigest(),
            )
            result = self._run(paths, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside the sample directory", result.stderr)
            self._assert_no_tool_ran(env)

    def test_a_digest_that_no_longer_matches_stops_before_any_tool_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, env = self._fixture(Path(tmp))
            paths["r1"].write_bytes(b"@read1\nTTTT\n+\nIIII\n")  # changed after the gate ran
            result = self._run(paths, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("changed after the gate verified it", result.stderr)
            self._assert_no_tool_ran(env)

    def test_an_input_the_record_does_not_cover_stops_before_any_tool_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, env = self._fixture(Path(tmp))
            record = json.loads(paths["qc"].read_text(encoding="utf-8"))
            del record["inputs"]["r1"]["sha256"]
            paths["qc"].write_text(json.dumps(record), encoding="utf-8")
            result = self._run(paths, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("records no verified r1", result.stderr)
            self._assert_no_tool_ran(env)

    def test_verified_inputs_reach_the_aligner(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, env = self._fixture(Path(tmp))
            result = self._run(paths, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(env["STUB_R1_SEEN"]).read_bytes(), b"@read1\nACGT\n+\nIIII\n")
            self.assertEqual(Path(env["STUB_R2_SEEN"]).read_bytes(), b"@read1\nTGCA\n+\nIIII\n")

    def test_the_aligner_reads_the_verified_bytes_even_if_the_name_is_repointed(self):
        """The digest and the read must be bound to one inode, not to one name.

        `sha256sum "$path"` certifies the bytes at that instant and then hands the *name* on;
        anything able to write in the sample directory replaces the file before bwa-mem2
        opens it and the aligner consumes bytes no gate ever saw, with the run still
        reported as VERIFICADO. The stub performs exactly that swap at the moment of the
        read, so this test fails against any implementation that passes a name.
        """
        with tempfile.TemporaryDirectory() as tmp:
            paths, env = self._fixture(Path(tmp))
            env["STUB_SWAP_TARGET"] = str(paths["r1"])
            result = self._run(paths, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(paths["r1"].read_bytes(), b"SWAPPED-BY-THE-ATTACKER\n")
            self.assertEqual(Path(env["STUB_R1_SEEN"]).read_bytes(), b"@read1\nACGT\n+\nIIII\n")

    def test_a_symlinked_sample_directory_does_not_break_containment(self):
        """The gate records physical paths, so the containment test needs a physical root.

        A logical `pwd` prints the symlink the run was launched through, no recorded input
        is a prefix match against it, and every legitimate sample reached that way is
        refused — a gate that refuses everything teaches operators to route around it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, env = self._fixture(root)
            link = root / "sample-link"
            link.symlink_to(paths["manifest"].parent, target_is_directory=True)
            paths["manifest"] = link / "sample-manifest.json"
            result = self._run(paths, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(env["STUB_R1_SEEN"]).read_bytes(), b"@read1\nACGT\n+\nIIII\n")

    def test_an_absolute_path_is_no_longer_honoured(self):
        script = ALIGN_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('= /* ]] ||', script)
        for key in (".r1", ".alignment"):
            with self.subTest(key=key):
                self.assertNotIn(f"jq -r '{key}' \"$manifest\"", script)

    def test_the_workflow_hands_the_verified_record_to_the_script(self):
        workflow = (REPO_ROOT / "workflows" / "wgs.nf").read_text(encoding="utf-8")
        self.assertIn("aligned/sample.bam \\\n        '${input_qc}'", workflow)


if __name__ == "__main__":
    unittest.main()
