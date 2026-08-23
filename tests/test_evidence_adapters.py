import hashlib
import json
import unittest
import urllib.request
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse


class FakeTransport:
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
    def test_registry_contains_required_primary_adapters(self):
        from evidence_adapters import ADAPTERS
        self.assertEqual(
            set(ADAPTERS),
            {"clinvar", "clingen", "cpic", "clinpgx", "gnomad", "pgs_catalog"},
        )

    def test_query_snapshot_is_verificado_only_with_retrieval_trace(self):
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
        expected = hashlib.sha256(json.dumps({"result": [{"id": "fixture"}]}, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(snapshot["retrieval_evidence"]["result_digest"], expected)

    def test_adapter_never_marks_failed_or_unreachable_source_as_verified(self):
        from evidence_adapters import get_adapter

        def failing(_request):
            raise OSError("offline")

        adapter = get_adapter("clinvar", transport=failing)
        snapshot = adapter.query({"term": "BRCA1[gene]"}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertFalse(snapshot["accessible"])
        self.assertNotIn("result_digest", snapshot.get("retrieval_evidence", {}))

    def test_oversized_payload_is_unavailable_and_not_hashed(self):
        from evidence_adapters import MAX_RESPONSE_BYTES, get_adapter

        def oversized(_request):
            return b"x" * (MAX_RESPONSE_BYTES + 1), {"content-type": "application/json"}

        adapter = get_adapter("clinvar", transport=oversized)
        snapshot = adapter.query({"term": "BRCA1[gene]"}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertFalse(snapshot["accessible"])
        self.assertEqual(snapshot["error_class"], "EvidenceResponseTooLargeError")
        self.assertNotIn("result_digest", snapshot.get("retrieval_evidence", {}))

    def test_failed_transport_does_not_expose_exception_message(self):
        from evidence_adapters import get_adapter

        secret = "sensitive-token-should-not-leak"

        def failing(_request):
            raise OSError(f"upstream error token={secret}")

        adapter = get_adapter("clinvar", transport=failing)
        snapshot = adapter.query({"term": "BRCA1[gene]"}, checked_at="2026-08-16T14:00:00Z")
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertEqual(snapshot["error"], "evidence source retrieval failed")
        self.assertNotIn(secret, serialized)
        self.assertEqual(snapshot["error_class"], "OSError")

    def test_non_allowlisted_host_is_rejected_before_transport(self):
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
        from evidence_adapters import get_adapter

        transport = FakeTransport({"unexpected": True})
        adapter = get_adapter("clinvar", transport=transport)
        insecure = urllib.request.Request("http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
        with patch.object(adapter, "_request", return_value=insecure):
            snapshot = adapter.query({}, checked_at="2026-08-16T14:00:00Z")
        self.assertEqual(snapshot["status"], "NÃO DISPONÍVEL")
        self.assertEqual(snapshot["error_class"], "EvidenceURLPolicyError")
        self.assertEqual(transport.calls, [])

    def test_multi_value_etag_is_preserved_without_ambiguity(self):
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
        from evidence_adapters import get_adapter

        adapter = get_adapter("clinpgx", transport=FakeTransport([]))
        snapshot = adapter.query({"path": "data/gene", "limit": 1}, checked_at="2026-08-16T14:00:00Z")
        self.assertNotIn("limit", parse_qs(urlparse(snapshot["locator"]).query))


if __name__ == "__main__":
    unittest.main()
