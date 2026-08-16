from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from genoma_policy.ledger import append_event, verify_ledger
class AuditLedgerTests(unittest.TestCase):
 def test_append_and_verify_hash_chain(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"audit.jsonl"; first=append_event(p,"RULESET_VERIFIED",{"sha256":"a"*64}); second=append_event(p,"POLICY_EVALUATED",{"ready":False}); ok,errors=verify_ledger(p); self.assertTrue(ok,errors); self.assertEqual(second["previous_entry_sha256"],first["entry_sha256"])
 def test_tampering_is_detected(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"audit.jsonl"; append_event(p,"RULESET_VERIFIED",{"sha256":"a"*64}); append_event(p,"POLICY_EVALUATED",{"ready":False}); lines=p.read_text().splitlines(); rec=json.loads(lines[0]); rec["event_type"]="TAMPERED"; lines[0]=json.dumps(rec,ensure_ascii=False,sort_keys=True,separators=(",",":")); p.write_text("\n".join(lines)+"\n"); ok,errors=verify_ledger(p); self.assertFalse(ok); self.assertTrue(errors)
if __name__=="__main__": unittest.main()
