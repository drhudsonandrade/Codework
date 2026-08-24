from __future__ import annotations

import unittest
import urllib.request
from unittest.mock import patch

from evidence_adapters import (
    MAX_RESPONSE_BYTES,
    EvidenceResponseTooLargeError,
    _default_transport,
)


class _Headers:
    def __iter__(self):
        return iter(("Content-Type",))

    def get_all(self, name):
        if str(name).lower() == "content-type":
            return ["application/json"]
        return []


class _ShortReadResponse:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _size=-1):
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        if _size >= 0 and len(chunk) > _size:
            self._chunks.insert(0, chunk[_size:])
            return chunk[:_size]
        return chunk


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, _request, timeout):
        self.timeout = timeout
        return self.response


class DefaultTransportShortReadTest(unittest.TestCase):
    def test_short_reads_are_accumulated_until_eof(self):
        response = _ShortReadResponse([b'{"', b'ok', b'":', b'true', b'}'])
        request = urllib.request.Request(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        )
        with patch("urllib.request.build_opener", return_value=_Opener(response)):
            payload, headers = _default_transport(request)
        self.assertEqual(payload, b'{"ok":true}')
        self.assertEqual(headers["content-type"], ("application/json",))

    def test_oversize_body_is_rejected_even_when_stream_short_reads(self):
        chunk = b"x" * (32 * 1024)
        response = _ShortReadResponse(
            [chunk] * (MAX_RESPONSE_BYTES // len(chunk) + 1)
        )
        request = urllib.request.Request(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        )
        with patch("urllib.request.build_opener", return_value=_Opener(response)):
            with self.assertRaises(EvidenceResponseTooLargeError):
                _default_transport(request)


if __name__ == "__main__":
    unittest.main()
