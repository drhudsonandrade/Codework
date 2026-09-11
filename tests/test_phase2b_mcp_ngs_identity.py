from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = json.loads((ROOT / "config/project_identity.json").read_text(encoding="utf-8"))
LEGACY_WORD = "code" + "work"


class Phase2BMcpNgsIdentityTest(unittest.TestCase):
    @staticmethod
    def read(path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_mcp_package_and_server_use_canonical_identity(self) -> None:
        expected = IDENTITY["mcp"]["identity"]
        package = json.loads(self.read("mcp/package.json"))
        lock = json.loads(self.read("mcp/package-lock.json"))
        self.assertEqual(package["name"], expected)
        self.assertEqual(lock["name"], expected)
        self.assertEqual(lock["packages"][""]["name"], expected)
        self.assertIn(expected, self.read("mcp/src/server.ts"))

    def test_ngs_and_canary_identities_are_canonical(self) -> None:
        ngs = IDENTITY["ngs"]
        self.assertIn(f"name: {ngs['conda_environment']}", self.read("environment.yml"))
        self.assertIn(f"name = '{ngs['nextflow_manifest']}'", self.read("nextflow.config"))
        self.assertIn(f'"fixture": "{ngs["synthetic_fixture"]}"', self.read("scripts/generate_canary.py"))

    def test_active_mcp_tests_use_canonical_temp_prefixes(self) -> None:
        pattern = rf"{LEGACY_WORD}-(audit|server|claim|lock|release|budget|timeout|reaped|exit)"
        for path in ("mcp/test/core.test.ts", "mcp/test/server.test.ts"):
            self.assertNotRegex(self.read(path), pattern)


if __name__ == "__main__":
    unittest.main()
