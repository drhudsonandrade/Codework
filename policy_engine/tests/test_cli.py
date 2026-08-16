from __future__ import annotations
import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CliTests(unittest.TestCase):
 def run_cli(self,*args): return subprocess.run([sys.executable,"-m","genoma_policy",*args],cwd=ROOT,check=False,capture_output=True,text=True)
 def test_ruleset_check(self):
  r=self.run_cli("ruleset-check"); self.assertEqual(r.returncode,0,r.stderr); self.assertEqual(json.loads(r.stdout)["ruleset"]["section_count"],263)
 def test_catalog_contains_all_rules(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/"catalog.json"; r=self.run_cli("catalog","--output",str(out)); self.assertEqual(r.returncode,0,r.stderr); p=json.loads(out.read_text()); self.assertEqual(len(p["rules"]),263); self.assertEqual(p["rules"][0]["rule_id"],"GENOMA-V3.3-S000"); self.assertEqual(p["rules"][-1]["rule_id"],"GENOMA-V3.3-S262")
 def test_ledger_cli_append_and_verify(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); payload=root/"payload.json"; ledger=root/"audit.jsonl"; payload.write_text(json.dumps({"ready":False})); a=self.run_cli("ledger-append",str(ledger),"POLICY_EVALUATED",str(payload)); self.assertEqual(a.returncode,0,a.stderr); v=self.run_cli("ledger-verify",str(ledger)); self.assertEqual(v.returncode,0,v.stderr); self.assertTrue(json.loads(v.stdout)["valid"])
if __name__=="__main__": unittest.main()
