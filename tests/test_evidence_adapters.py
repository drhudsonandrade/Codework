import hashlib
import json
import unittest
from urllib.parse import parse_qs, urlparse


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        return json.dumps(self.payload, sort_keys=True).encode("utf-8"), {
            "content-type": "application/json",
            "etag": '"fixture-etag"',
        }


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
