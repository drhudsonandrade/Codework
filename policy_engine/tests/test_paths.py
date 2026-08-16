from __future__ import annotations
import os, shutil, tempfile, unittest
from pathlib import Path
from genoma_policy.paths import AssetResolutionError, resolve_manifest_path, resolve_ruleset_path
ROOT=Path(__file__).resolve().parents[1]; RULESET=resolve_ruleset_path(ROOT)
class PathResolutionTests(unittest.TestCase):
 def setUp(self): self._r=os.environ.pop("GENOMA_RULESET_PATH",None); self._m=os.environ.pop("GENOMA_RULESET_SHA_MANIFEST",None)
 def tearDown(self):
  if self._r is not None: os.environ["GENOMA_RULESET_PATH"]=self._r
  if self._m is not None: os.environ["GENOMA_RULESET_SHA_MANIFEST"]=self._m
 def test_nested_engine_resolves_single_parent_ruleset(self):
  with tempfile.TemporaryDirectory() as td:
   repo=Path(td); engine=repo/"policy_engine"; engine.mkdir(); shutil.copyfile(RULESET,repo/RULESET.name); self.assertEqual(resolve_ruleset_path(engine),repo/RULESET.name)
 def test_explicit_manifest_path_is_authoritative(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); ruleset=root/RULESET.name; shutil.copyfile(RULESET,ruleset); explicit=root/"explicit.sha256"; explicit.write_text("0"*64+"  "+RULESET.name+"\n"); other=root/"manifests"/"RULESET_V3.3.sha256"; other.parent.mkdir(); other.write_text("1"*64+"  "+RULESET.name+"\n"); os.environ["GENOMA_RULESET_SHA_MANIFEST"]=str(explicit); self.assertEqual(resolve_manifest_path(ruleset,root),explicit.resolve())
 def test_duplicate_canonical_ruleset_locations_fail_closed(self):
  with tempfile.TemporaryDirectory() as td:
   repo=Path(td); engine=repo/"policy_engine"; engine.mkdir(); shutil.copyfile(RULESET,repo/RULESET.name); shutil.copyfile(RULESET,engine/RULESET.name)
   with self.assertRaises(AssetResolutionError): resolve_ruleset_path(engine)
if __name__=="__main__": unittest.main()
