from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from genoma_policy.engine import PolicyEngine
from genoma_policy.paths import resolve_manifest_path, resolve_ruleset_path
from genoma_policy.ruleset import load_ruleset
from genoma_policy.server import PolicyHandler

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA256 = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = resolve_ruleset_path(ROOT)
        engine = PolicyEngine(load_ruleset(path), external_manifest=resolve_manifest_path(path, ROOT))
        handler = type("BoundPolicyHandler", (PolicyHandler,), {"engine": engine})
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def test_health_and_ruleset(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/healthz", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)["status"], "ok")

        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/v1/ruleset", timeout=3) as response:
            payload = json.load(response)
            self.assertEqual(payload["status"], "VIGENTE")
            self.assertEqual(payload["version"], "v3.4")
            self.assertEqual(payload["effective_date"], "17/08/2026")
            self.assertEqual(payload["sha256"], EXPECTED_SHA256)
            self.assertEqual(payload["section_count"], 263)


if __name__ == "__main__":
    unittest.main()
