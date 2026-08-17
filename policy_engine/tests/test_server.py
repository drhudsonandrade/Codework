from __future__ import annotations
import json, threading, unittest, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from genoma_policy.engine import PolicyEngine
from genoma_policy.paths import resolve_manifest_path, resolve_ruleset_path
from genoma_policy.ruleset import load_ruleset
from genoma_policy.server import PolicyHandler
ROOT=Path(__file__).resolve().parents[1]
class ServerTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  path=resolve_ruleset_path(ROOT); engine=PolicyEngine(load_ruleset(path),external_manifest=resolve_manifest_path(path,ROOT)); handler=type("BoundPolicyHandler",(PolicyHandler,),{"engine":engine}); cls.httpd=ThreadingHTTPServer(("127.0.0.1",0),handler); cls.port=cls.httpd.server_address[1]; cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True); cls.thread.start()
 @classmethod
 def tearDownClass(cls): cls.httpd.shutdown(); cls.httpd.server_close(); cls.thread.join(timeout=2)
 def test_health_and_ruleset(self):
  with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/healthz",timeout=3) as r: self.assertEqual(r.status,200); self.assertEqual(json.load(r)["status"],"ok")
  with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/v1/ruleset",timeout=3) as r: p=json.load(r); self.assertEqual(p["version"],"v3.4"); self.assertEqual(p["section_count"],263)
if __name__=="__main__": unittest.main()
