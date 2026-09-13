from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "project_identity.json"

EXPECTED = {
    "schema": "omnigenis-project-identity-v1",
    "version": "2026-09-11.1",
    "repository": {
        "repository_id": 1212760346,
        "repository_name": "OmniGenis",
    },
    "runtime": {
        "root": "/opt/omnigenis",
        "config_root": "/etc/omnigenis",
        "state_root": "/var/lib/omnigenis-tunnel",
        "container_package": "omnigenis-genome",
        "cache_namespace": "omnigenis-genome-scaffold-v2",
        "tunnel_profile": "omnigenis-genome",
    },
    "mcp": {"identity": "omnigenis-genome-mcp"},
    "ngs": {
        "conda_environment": "omnigenis-ngs",
        "nextflow_manifest": "omnigenis/genome-runtime",
        "synthetic_fixture": "omnigenis-synthetic-germline-v2",
    },
    "runners": {
        "pool_label": "omnigenis-isolated",
        "per_runner_labels": ["omnigenis-01", "omnigenis-02"],
        "runner_names": ["omnigenis-runner-01", "omnigenis-runner-02"],
    },
    "codex": {
        "marketplace": "omnigenis-codex",
        "plugin": "coderabbit@omnigenis-codex",
        "bin_dir_env": "OMNIGENIS_CODERABBIT_BIN_DIR",
        "lock_schema": "omnigenis-coderabbit-cli-release-lock-v2",
    },
    "testing": {
        "temp_prefix_namespace": "omnigenis-",
        "runner_test_symbol": "private_omnigenis_runners",
    },
}


class ProjectIdentityContractTest(unittest.TestCase):
    def test_identity_contract_is_exact(self) -> None:
        self.assertTrue(CONTRACT.is_file())
        payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertNotIn("full_name", payload["repository"])
        self.assertEqual(payload, EXPECTED)

    def test_contract_contains_no_legacy_identity(self) -> None:
        raw = CONTRACT.read_text(encoding="utf-8")
        legacy_word = "code" + "work"
        self.assertNotIn(legacy_word, raw.lower())


if __name__ == "__main__":
    unittest.main()
