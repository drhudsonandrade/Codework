from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_snp_array.py"


def load_script():
    spec = importlib.util.spec_from_file_location("run_snp_array", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load run_snp_array.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ArrayProvenanceAttestationTest(unittest.TestCase):
    def _input(self) -> tuple[Path, str]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "array.csv"
        path.write_text("RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,100,AA\n", encoding="utf-8")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _verified(self, input_sha: str, asserted_value: str = "GRCh37") -> dict:
        return {
            "status": "VERIFICADO",
            "decision": "SATISFIED",
            "asserted_value": asserted_value,
            "justification": "Vendor/reference provenance independently establishes this assertion.",
            "evidence_refs": ["vendor-metadata"],
            "trace": {
                "attestation_id": "att-array-provenance-001",
                "created_at": "2026-08-17T00:00:00Z",
                "actor_type": "SOFTWARE",
                "actor_id": "test-suite",
                "method": "fixture",
                "run_id": "unit-test",
                "input_sha256": [input_sha],
                "output_sha256": [],
                "tool_versions": {"test": "1"},
            },
        }

    def test_plain_text_evidence_is_rejected(self):
        module = load_script()
        path, _ = self._input()
        with self.assertRaises(ValueError):
            module.load_verified_attestation("fixture", assertion="build", input_path=path)

    def test_inferred_attestation_cannot_unlock_verified_gate(self):
        module = load_script()
        path, sha = self._input()
        payload = self._verified(sha)
        payload["status"] = "INFERIDO"
        with self.assertRaises(ValueError):
            module.load_verified_attestation(json.dumps(payload), assertion="build", input_path=path)

    def test_verified_attestation_must_bind_exact_input_sha(self):
        module = load_script()
        path, sha = self._input()
        payload = self._verified(sha)
        payload["trace"]["input_sha256"] = ["0" * 64]
        with self.assertRaises(ValueError):
            module.load_verified_attestation(json.dumps(payload), assertion="strand", input_path=path)

    def test_verified_inline_attestation_is_accepted(self):
        module = load_script()
        path, sha = self._input()
        payload = self._verified(sha)
        normalized = module.load_verified_attestation(json.dumps(payload), assertion="build", input_path=path)
        self.assertEqual(normalized["status"], "VERIFICADO")
        self.assertEqual(normalized["decision"], "SATISFIED")
        self.assertIn(sha, normalized["trace"]["input_sha256"])

    def test_verified_attestation_file_is_accepted(self):
        module = load_script()
        path, sha = self._input()
        payload = self._verified(sha)
        attestation = path.parent / "build-attestation.json"
        attestation.write_text(json.dumps(payload), encoding="utf-8")
        normalized = module.load_verified_attestation(str(attestation), assertion="build", input_path=path)
        self.assertEqual(normalized["status"], "VERIFICADO")


if __name__ == "__main__":
    unittest.main()
