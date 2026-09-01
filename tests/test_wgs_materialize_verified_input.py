import contextlib
import errno
import hashlib
import io
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import wgs_materialize_verified_input as materializer


class WgsMaterializerFailureClassificationTest(unittest.TestCase):
    """Staging failures must stay fail-closed and preserve their evidence category."""

    def _fixture(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name) / "sample"
        root.mkdir()
        source = root / "r1.fastq"
        source.write_bytes(b"@r1\nACGT\n+\nIIII\n")
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        output = Path(temporary.name) / "stage" / "r1"
        return temporary, root, source, expected, output

    def test_exit_code_contract_is_exported_from_one_authority(self):
        self.assertEqual(
            materializer.exit_code_contract(),
            {
                "INVALID_ARGUMENT": 2,
                "STAGING_UNAVAILABLE": 3,
                "DIGEST_MISMATCH": 4,
                "INPUT_REFUSED": 5,
                "INPUT_MISSING": 6,
                "INPUT_UNREADABLE": 7,
            },
        )

    def test_containment_refusal_returns_input_refused_without_staging(self):
        temporary, root, source, expected, output = self._fixture()
        self.addCleanup(temporary.cleanup)
        outside = root.parent / "outside.fastq"
        outside.write_bytes(source.read_bytes())

        rc = materializer.materialize(root, root / ".." / outside.name, expected, output)

        self.assertEqual(rc, materializer.INPUT_REFUSED)
        self.assertFalse(output.exists())

    def test_missing_input_returns_input_missing_without_staging(self):
        temporary, root, _source, expected, output = self._fixture()
        self.addCleanup(temporary.cleanup)

        rc = materializer.materialize(root, root / "missing.fastq", expected, output)

        self.assertEqual(rc, materializer.INPUT_MISSING)
        self.assertFalse(output.exists())

    def test_unreadable_input_returns_input_unreadable_without_staging(self):
        temporary, root, source, expected, output = self._fixture()
        self.addCleanup(temporary.cleanup)
        real_open = materializer.os.open

        def deny_source(path, flags, *args, **kwargs):
            if path == source.name:
                raise OSError(errno.EACCES, "permission denied")
            return real_open(path, flags, *args, **kwargs)

        with unittest.mock.patch.object(materializer.os, "open", side_effect=deny_source):
            rc = materializer.materialize(root, source, expected, output)

        self.assertEqual(rc, materializer.INPUT_UNREADABLE)
        self.assertFalse(output.exists())

    def test_digest_mismatch_removes_staging(self):
        temporary, root, source, _expected, output = self._fixture()
        self.addCleanup(temporary.cleanup)

        rc = materializer.materialize(root, source, "0" * 64, output)

        self.assertEqual(rc, materializer.DIGEST_MISMATCH)
        self.assertFalse(output.exists())

    def test_valid_input_materializes_exact_bytes_with_private_mode(self):
        temporary, root, source, expected, output = self._fixture()
        self.addCleanup(temporary.cleanup)

        rc = materializer.materialize(root, source, expected, output)

        self.assertEqual(rc, 0)
        self.assertEqual(output.read_bytes(), source.read_bytes())
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_staging_directory_failure_is_classified_without_traceback(self):
        temporary, root, source, expected, output = self._fixture()
        self.addCleanup(temporary.cleanup)
        stderr = io.StringIO()
        with unittest.mock.patch.object(
            Path,
            "mkdir",
            side_effect=OSError(errno.EACCES, "permission denied"),
        ), contextlib.redirect_stderr(stderr):
            rc = materializer.materialize(root, source, expected, output)

        self.assertEqual(rc, materializer.STAGING_UNAVAILABLE)
        self.assertIn("staging directory unavailable", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_cleanup_failure_does_not_erase_digest_mismatch_cause_with_traceback(self):
        temporary, root, source, _expected, output = self._fixture()
        self.addCleanup(temporary.cleanup)
        output.parent.mkdir(parents=True)
        wrong_digest = "0" * 64
        stderr = io.StringIO()
        with unittest.mock.patch.object(
            Path,
            "unlink",
            side_effect=OSError(errno.EACCES, "permission denied"),
        ), contextlib.redirect_stderr(stderr):
            rc = materializer.materialize(root, source, wrong_digest, output)

        self.assertEqual(rc, materializer.STAGING_UNAVAILABLE)
        self.assertIn("staging cleanup unavailable", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
