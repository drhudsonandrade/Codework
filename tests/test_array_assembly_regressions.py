from __future__ import annotations

import gzip
import unittest

from array_pipeline.assembly import bounded_gunzip, is_beyond_end, lengths_for


class AssemblyRegressionTest(unittest.TestCase):
    def test_mitochondrial_m_alias_uses_same_bound_as_mt(self):
        lengths, _basis = lengths_for("GRCh37")
        self.assertEqual(lengths["M"], lengths["MT"])
        self.assertTrue(is_beyond_end("M", lengths["M"] + 1, lengths))

    def test_bounded_gunzip_rejects_truncated_member(self):
        raw = gzip.compress(b"RSID,CHROMOSOME\n" * 1000)
        with self.assertRaisesRegex(ValueError, "truncated|incomplete"):
            bounded_gunzip(raw[: len(raw) // 2], name="fixture.gz")

    def test_bounded_gunzip_rejects_a_second_member(self):
        raw = gzip.compress(b"first member") + gzip.compress(b"second member")
        with self.assertRaisesRegex(ValueError, "trailing|multiple"):
            bounded_gunzip(raw, name="fixture.gz")


if __name__ == "__main__":
    unittest.main()
