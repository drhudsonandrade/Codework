from __future__ import annotations

import gzip
import unittest
from unittest.mock import patch

from array_pipeline.assembly import bounded_gunzip, is_beyond_end, lengths_for


class AssemblyRegressionTest(unittest.TestCase):
    """Assembly bounds and the bounded gunzip that feeds them."""
    def test_mitochondrial_m_alias_uses_same_bound_as_mt(self):
        """The mitochondrial alias M shares MT's bound, so it cannot be used to escape it."""
        lengths, _basis = lengths_for("GRCh37")
        self.assertEqual(lengths["M"], lengths["MT"])
        self.assertTrue(is_beyond_end("M", lengths["M"] + 1, lengths))

    def test_bounded_gunzip_rejects_truncated_member(self):
        """A truncated gzip member is refused rather than read as far as it goes."""
        raw = gzip.compress(b"RSID,CHROMOSOME\n" * 1000)
        with self.assertRaisesRegex(ValueError, "truncated|incomplete"):
            bounded_gunzip(raw[: len(raw) // 2], name="fixture.gz")

    def test_bounded_gunzip_counts_pending_flush_output(self):
        """Output still pending in the decompressor's flush counts against the limit."""
        class PendingOutput:
            """A decompressor whose whole output arrives at flush time."""
            eof = True
            unused_data = b""
            unconsumed_tail = b""

            def decompress(self, _data, _limit):
                """Nothing during decompression."""
                return b""

            def flush(self, _limit):
                """Seventeen bytes at flush, one past a sixteen-byte limit."""
                return b"x" * 17

        with (
            patch("zlib.decompressobj", return_value=PendingOutput()),
            patch("array_pipeline.assembly.MAX_REGISTRY_UNCOMPRESSED_BYTES", 16),
        ):
            with self.assertRaisesRegex(ValueError, "expands past"):
                bounded_gunzip(b"compressed", name="fixture.gz")

    def test_bounded_gunzip_rejects_a_second_member(self):
        """A second gzip member is refused: only the first would ever be read."""
        raw = gzip.compress(b"first member") + gzip.compress(b"second member")
        with self.assertRaisesRegex(ValueError, "trailing|multiple"):
            bounded_gunzip(raw, name="fixture.gz")


if __name__ == "__main__":
    unittest.main()
