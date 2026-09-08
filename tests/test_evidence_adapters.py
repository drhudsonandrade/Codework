import hashlib
import json
import unittest
import urllib.request
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse


class FakeTransport:
    """Record requests and return deterministic JSON bytes with fixture response headers."""

    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {
            "content-type": "application/json",
            "etag": '"fixture-etag"',
        }
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        return json.dumps(self.payload, sort_keys=True).encode("utf-8"), self.headers


class EvidenceAdapterTest(unittest.TestCase):
    """Verify adapter provenance, request construction, and fail-closed retrieval behavior."""

    def test_registry_contains_required_primary_adapters(self):
        """Require the six primary adapter identifiers in the shipped registry."""
        from evidence_adapters import ADAPTERS
        self.assertEqual(
            set(ADAPTERS),
            {"clinvar", "clingen", "cpic", "clinpgx", "gnomad", "pgs_catalog"},
        )

    def test_query_snapshot_is_verified_only_with_retrieval_trace(self):
        """Bind a verified snapshot to its request, response digest, and retrieval metadata."""
        from evidence_adapters import get_adapter

        transport = FakeTransport({"result": [{"id": "fixture"}]})
        adapter = get_adapter("pgs_catalog", transport=transport)
        snapshot = adapter.query({"score_id": "PGS000001"}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "VERIFICADO")
        self.assertTrue(snapshot["primary_or_official"])
        self.assertTrue(snapshot["locator"].startswith("https://www.pgscatalog.org/rest/"))
        self.assertEqual(snapshot["retrieval_evidence"]["method"], "HTTPS")
        self.assertEqual(len(snapshot["retrieval_evidence"]["result_digest"]), 64)
        self.assertEqual(snapshot["retrieval_evidence"]["etag"], '"fixture-etag"')
        self.assertEqual(snapshot["query"], {"score_id": "PGS000001"})
        expected = hashlib.sha256(json.dumps(
            {"result": [{"id": "fixture"}]}, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(snapshot["retrieval_evidence"]["result_digest"], expected)

    def test_adapter_never_marks_failed_or_unreachable_source_as_verified(self):
        """Keep a failed transport unavailable without manufacturing a response digest."""
        from evidence_adapters import get_adapter

        def failing(_request):
            """Simulate an unavailable upstream transport."""
            raise OSError("offline")

        adapter = get_adapter("clinvar", transport=failing)
        snapshot = adapter.query({"term": "BRCA1[gene]"}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertFalse(snapshot["accessible"])
        self.assertNotIn("result_digest", snapshot.get("retrieval_evidence", {}))

    def test_oversized_payload_is_unavailable_and_not_hashed(self):
        """Reject a response beyond the byte limit without hashing it as usable evidence."""
        from evidence_adapters import MAX_RESPONSE_BYTES, get_adapter

        def oversized(_request):
            """Return a synthetic response one byte larger than the configured maximum."""
            return b"x" * (MAX_RESPONSE_BYTES + 1), {"content-type": "application/json"}

        adapter = get_adapter("clinvar", transport=oversized)
        snapshot = adapter.query({"term": "BRCA1[gene]"}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertFalse(snapshot["accessible"])
        self.assertEqual(snapshot["error_class"], "EvidenceResponseTooLargeError")
        self.assertNotIn("result_digest", snapshot.get("retrieval_evidence", {}))

    def test_failed_transport_does_not_expose_exception_message(self):
        """Keep the exception message out of the serialized failure snapshot."""
        from evidence_adapters import get_adapter

        secret = "sensitive-token-should-not-leak"

        def failing(_request):
            """Raise a synthetic error containing the marker used by the disclosure test."""
            raise OSError(f"upstream error token={secret}")

        adapter = get_adapter("clinvar", transport=failing)
        snapshot = adapter.query({"term": "BRCA1[gene]"}, checked_at="2026-08-16T14:00:00Z")
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertEqual(snapshot["error"], "evidence source retrieval failed")
        self.assertNotIn(secret, serialized)
        self.assertEqual(snapshot["error_class"], "OSError")

    def test_non_allowlisted_host_is_rejected_before_transport(self):
        """Reject a disallowed request host before invoking the transport."""
        from evidence_adapters import get_adapter

        transport = FakeTransport({"unexpected": True})
        adapter = get_adapter("clinvar", transport=transport)
        disallowed = urllib.request.Request("https://127.0.0.1/internal")
        with patch.object(adapter, "_request", return_value=disallowed):
            snapshot = adapter.query({}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertFalse(snapshot["accessible"])
        self.assertEqual(snapshot["error_class"], "EvidenceURLPolicyError")
        self.assertEqual(transport.calls, [])

    def test_adapter_cannot_switch_to_another_allowlisted_provider_host(self):
        """Pin the adapter to its own provider even when another provider is allowlisted."""
        from evidence_adapters import get_adapter

        transport = FakeTransport({"unexpected": True})
        adapter = get_adapter("clinvar", transport=transport)
        cross_provider = urllib.request.Request("https://www.pgscatalog.org/rest/info")
        with patch.object(adapter, "_request", return_value=cross_provider):
            snapshot = adapter.query({}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertEqual(snapshot["error_class"], "EvidenceURLPolicyError")
        self.assertEqual(transport.calls, [])

    def test_non_https_url_is_rejected_before_transport(self):
        """Refuse an HTTP request before invoking the transport."""
        from evidence_adapters import get_adapter

        transport = FakeTransport({"unexpected": True})
        adapter = get_adapter("clinvar", transport=transport)
        insecure = urllib.request.Request(
            "http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
        with patch.object(adapter, "_request", return_value=insecure):
            snapshot = adapter.query({}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertEqual(snapshot["error_class"], "EvidenceURLPolicyError")
        self.assertEqual(transport.calls, [])

    def test_multi_value_etag_is_preserved_without_ambiguity(self):
        """Preserve all ETag values while selecting the first as the snapshot version."""
        from evidence_adapters import get_adapter

        transport = FakeTransport(
            {"result": []},
            headers={
                "content-type": ["application/json"],
                "etag": ['"fixture-etag-a"', '"fixture-etag-b"'],
            },
        )
        adapter = get_adapter("pgs_catalog", transport=transport)
        snapshot = adapter.query({"score_id": "PGS000001"}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "VERIFICADO")
        self.assertEqual(snapshot["version"], '"fixture-etag-a"')
        self.assertEqual(
            snapshot["retrieval_evidence"]["etag_values"],
            ['"fixture-etag-a"', '"fixture-etag-b"'],
        )

    def test_clinpgx_uses_current_openapi_parameters_and_new_hostname(self):
        """Build the expected ClinPGx hostname, path, and explicitly supplied parameters."""
        from evidence_adapters import get_adapter

        transport = FakeTransport([{"id": "PA124", "symbol": "CYP2C19"}])
        adapter = get_adapter("clinpgx", transport=transport)
        snapshot = adapter.query(
            {"path": "data/gene", "params": {"symbol": "CYP2C19", "view": "min"}},
            checked_at="2026-08-16T14:00:00Z",
        )
        parsed = urlparse(snapshot["locator"])
        self.assertEqual(parsed.netloc, "api.clinpgx.org")
        self.assertEqual(parsed.path, "/v1/data/gene")
        self.assertEqual(parse_qs(parsed.query), {"symbol": ["CYP2C19"], "view": ["min"]})
        self.assertNotIn("api.pharmgkb.org", snapshot["locator"])
        self.assertNotIn("limit", parse_qs(parsed.query))

    def test_clinpgx_does_not_invent_unsupported_top_level_limit_parameter(self):
        """Do not project an unsupported top-level limit into the query string."""
        from evidence_adapters import get_adapter

        adapter = get_adapter("clinpgx", transport=FakeTransport([]))
        snapshot = adapter.query({"path": "data/gene", "limit": 1},
                                 checked_at="2026-08-16T14:00:00Z")
        self.assertNotIn("limit", parse_qs(urlparse(snapshot["locator"]).query))


class EvidenceUrlPolicyTest(unittest.TestCase):
    """Every rejection branch of the outbound URL policy is pinned independently.

    An allowlisted host is not sufficient on its own: embedded credentials, a port other
    than 443 and a fragment each have to fail closed by themselves, otherwise a single
    surviving branch is enough to reach an unintended endpoint.
    """

    def _assert_rejected(self, url, message):
        """Require the URL policy exception and its expected diagnostic text."""
        from evidence_adapters import EvidenceURLPolicyError, _validate_url

        with self.assertRaises(EvidenceURLPolicyError) as caught:
            _validate_url(url)
        self.assertIn(message, str(caught.exception))

    def test_allowlisted_https_url_on_the_default_port_is_accepted(self):
        """Accept the provider HTTPS endpoint with an implicit or explicit port 443."""
        from evidence_adapters import _validate_url

        _validate_url("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=clinvar")
        _validate_url("https://eutils.ncbi.nlm.nih.gov:443/entrez/eutils/esearch.fcgi")

    def test_embedded_credentials_are_rejected(self):
        """Reject user information embedded in an otherwise allowlisted URL."""
        self._assert_rejected(
            "https://user:secret@eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            "credentials are not allowed",
        )

    def test_non_default_port_is_rejected(self):
        """Reject HTTPS endpoints using a port other than 443."""
        self._assert_rejected(
            "https://eutils.ncbi.nlm.nih.gov:8443/entrez/eutils/esearch.fcgi",
            "only allow HTTPS port 443",
        )

    def test_invalid_port_is_rejected_without_crashing(self):
        """Convert a malformed port into the expected URL policy refusal."""
        self._assert_rejected(
            "https://eutils.ncbi.nlm.nih.gov:notaport/entrez/eutils/esearch.fcgi",
            "invalid port",
        )

    def test_fragment_is_rejected(self):
        """Refuse a URL fragment rather than silently discarding it."""
        self._assert_rejected(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi#fragment",
            "fragments are not allowed",
        )

    def test_expected_host_pins_the_adapter_to_its_own_provider(self):
        """Refuse a provider hostname different from the explicitly pinned host."""
        from evidence_adapters import EvidenceURLPolicyError, _validate_url

        with self.assertRaises(EvidenceURLPolicyError) as caught:
            _validate_url(
                "https://www.pgscatalog.org/rest/info",
                expected_host="eutils.ncbi.nlm.nih.gov",
            )
        self.assertIn("changed its configured host", str(caught.exception))


class AllowlistedRedirectHandlerTest(unittest.TestCase):
    """A redirect is an outbound request too, and obeys the same host pin."""

    def _redirect(self, new_url, expected_host="eutils.ncbi.nlm.nih.gov"):
        """Exercise the pinned redirect handler with a synthetic initial request."""
        from evidence_adapters import _AllowlistedRedirectHandler

        handler = _AllowlistedRedirectHandler(expected_host)
        request = urllib.request.Request(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        )
        return handler.redirect_request(request, None, 302, "Found", {}, new_url)

    def test_redirect_to_another_allowlisted_host_is_rejected(self):
        """Keep redirects pinned to the original provider hostname."""
        from evidence_adapters import EvidenceURLPolicyError

        with self.assertRaises(EvidenceURLPolicyError) as caught:
            self._redirect("https://www.pgscatalog.org/rest/info")
        self.assertIn("changed its configured host", str(caught.exception))

    def test_redirect_to_a_non_allowlisted_host_is_rejected(self):
        """Refuse a redirect to an unapproved host."""
        from evidence_adapters import EvidenceURLPolicyError

        with self.assertRaises(EvidenceURLPolicyError):
            self._redirect("https://attacker.example/entrez")

    def test_redirect_downgrade_to_http_is_rejected(self):
        """Refuse a redirect that downgrades the provider connection to HTTP."""
        from evidence_adapters import EvidenceURLPolicyError

        with self.assertRaises(EvidenceURLPolicyError) as caught:
            self._redirect("http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
        self.assertIn("require HTTPS", str(caught.exception))

    def test_redirect_with_credentials_is_rejected(self):
        """Refuse a redirect URL carrying user information."""
        from evidence_adapters import EvidenceURLPolicyError

        with self.assertRaises(EvidenceURLPolicyError):
            self._redirect("https://user:secret@eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")

    def test_same_host_redirect_is_delegated_to_the_standard_handler(self):
        """Allow a same-host HTTPS redirect through the standard request handler."""
        redirected = self._redirect("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi")
        self.assertEqual(
            redirected.full_url,
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        )


if __name__ == "__main__":
    unittest.main()
