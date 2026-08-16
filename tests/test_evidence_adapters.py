import hashlib
import json
import unittest


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

    def test_clinpgx_uses_new_hostname_not_retired_pharmgkb_hostname(self):
        from evidence_adapters import get_adapter

        adapter = get_adapter("clinpgx", transport=FakeTransport({"data": []}))
        snapshot = adapter.query({"path": "data/gene", "limit": 1}, checked_at="2026-08-16T14:00:00Z")
        self.assertTrue(snapshot["locator"].startswith("https://api.clinpgx.org/"))
        self.assertNotIn("api.pharmgkb.org", snapshot["locator"])


if __name__ == "__main__":
    unittest.main()
