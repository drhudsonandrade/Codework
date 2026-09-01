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
        temporary, root, source, expected, output = self._fixture()
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
