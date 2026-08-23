from __future__ import annotations

import unittest
from pathlib import Path

from genoma_policy import __version__
from genoma_policy.paths import resolve_ruleset_path
from genoma_policy.ruleset import load_ruleset
from genoma_policy.scaffold import scaffold_manifest
from genoma_policy.smoke import smoke_cases

ROOT = Path(__file__).resolve().parents[1]
RULESET = resolve_ruleset_path(ROOT)


class VersionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ruleset = load_ruleset(RULESET)

    def test_scaffold_trace_uses_package_version(self) -> None:
        manifest = scaffold_manifest(self.ruleset)
        versions = {
            attestation["trace"]["tool_versions"]["genoma-policy-engine"]
            for attestation in manifest["section_attestations"]
        }
        self.assertEqual(versions, {__version__})

    def test_smoke_trace_uses_package_version(self) -> None:
        observed = {
            attestation["trace"]["tool_versions"]["genoma-policy-engine"]
            for _, _, manifest in smoke_cases(self.ruleset)
            for attestation in manifest["section_attestations"]
        }
        self.assertEqual(observed, {__version__})


if __name__ == "__main__":
    unittest.main()
