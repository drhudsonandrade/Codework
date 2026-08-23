from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from policy_engine.genoma_policy import __version__
from policy_engine.genoma_policy import paths as policy_paths
from policy_engine.genoma_policy import ruleset as policy_ruleset
from policy_engine.genoma_policy.engine import PolicyEngine
from scripts import sealed_ruleset
from scripts.bootstrap_attestation import BootstrapAttestationError, verify_bootstrap_attestation
from scripts.validate_repo import (
    FORBIDDEN_ACTIVE_PATHS,
    OLD_ACTIVE_TOKENS,
    validate,
    validate_active_identity_text,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_SHA = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
EXPECTED_VERSION = "v3.4"
EXPECTED_DATE = "17/08/2026"
EXPECTED_ARCHIVED_BOOTSTRAP_SHA = "87af4f99bcd6b6f3f857a1ca725103e95dabf70c3c926d7f0d4e83b037e69fd8"
EXPECTED_SUPERSEDED_FIXTURE_SHA = "5a6f888f176ed4c963c43c24f38697ea363f5772be06c63e70d6a8f5c497e503"
EXPECTED_BOOTSTRAP_ATTESTATION_SHA = "dbe574cff326d3a0b429de8a2450359024be97d7bb1c64468bf6a96b8d77d5b9"
EXPECTED_BOOTSTRAP_CHECKS = frozenset(
    {
        "consult_ruleset_before_relevant_genetic_analysis",
        "require_status_vigente",
        "require_version_v3_4",
        "require_effective_date_2026_08_17",
        "fail_closed_on_missing_or_conflicting_ruleset",
        "runtime_resource_gate_before_real_calling",
        "operational_status_contract_present",
        "post_deployment_requires_live_15_of_15_zero_critical",
    }
)
HISTORY_ROOT = ROOT / "docs" / "history"
SUPERSEDED_FIXTURE = HISTORY_ROOT / "v3.3" / "superseded-identities.json"
if not SUPERSEDED_FIXTURE.is_file():
    raise RuntimeError(f"superseded identity fixture missing: {SUPERSEDED_FIXTURE}")
SUPERSEDED = json.loads(SUPERSEDED_FIXTURE.read_text(encoding="utf-8"))
EXPECTED_SUPERSEDED_TOKENS = frozenset(
    {
        SUPERSEDED["canonical_filename"],
        SUPERSEDED["manifest_filename"],
        SUPERSEDED["version"],
        SUPERSEDED["rule_id_prefix"],
        SUPERSEDED["effective_date"],
        SUPERSEDED["iso_date"],
        SUPERSEDED["raw_sha256"],
    }
)
EXPECTED_FORBIDDEN_ACTIVE_PATHS = frozenset(SUPERSEDED["forbidden_active_paths"])


class V34ActivationContractTests(unittest.TestCase):
    def test_historical_superseded_identity_fixture_is_immutable(self) -> None:
        self.assertEqual(
            hashlib.sha256(SUPERSEDED_FIXTURE.read_bytes()).hexdigest(),
            EXPECTED_SUPERSEDED_FIXTURE_SHA,
        )
        self.assertEqual(SUPERSEDED["status"], "HISTORICAL")

    def test_shared_ruleset_contract_targets_v34(self) -> None:
        self.assertEqual(sealed_ruleset.EXPECTED_NAME, EXPECTED_NAME)
        self.assertEqual(sealed_ruleset.EXPECTED_SHA, EXPECTED_SHA)
        self.assertEqual(sealed_ruleset.EXPECTED_VERSION, EXPECTED_VERSION)
        self.assertEqual(sealed_ruleset.EXPECTED_DATE, EXPECTED_DATE)

        self.assertEqual(policy_ruleset.EXPECTED_CANONICAL, EXPECTED_NAME)
        self.assertEqual(policy_ruleset.EXPECTED_VERSION, EXPECTED_VERSION)
        self.assertEqual(policy_ruleset.EXPECTED_DATE, EXPECTED_DATE)
        self.assertEqual(policy_paths.CANONICAL_RULESET_NAME, EXPECTED_NAME)
        self.assertEqual(
            policy_paths.CANONICAL_MANIFEST_RELATIVE,
            Path("manifests") / "RULESET_V3.4.sha256",
        )

    def test_sealed_transport_is_v34_and_keeps_13_chunks(self) -> None:
        manifest = json.loads(
            (ROOT / "normative" / "sealed" / "MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["canonical_filename"], EXPECTED_NAME)
        self.assertEqual(manifest["version"], EXPECTED_VERSION)
        self.assertEqual(manifest["effective_date"], EXPECTED_DATE)
        self.assertEqual(manifest["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(len(manifest["transport_parts"]), 13)
        self.assertFalse(manifest["active_at_rest"])
        evidence = sealed_ruleset.verify_transport(ROOT / "normative" / "sealed")
        self.assertEqual(evidence["canonical_filename"], EXPECTED_NAME)
        self.assertEqual(evidence["version"], EXPECTED_VERSION)
        self.assertEqual(evidence["effective_date"], EXPECTED_DATE)
        self.assertEqual(evidence["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(evidence["section_range"], [0, 262])

    def test_external_v34_manifest_is_the_active_contract(self) -> None:
        current = ROOT / "manifests" / "RULESET_V3.4.sha256"
        self.assertTrue(current.is_file())
        self.assertEqual(
            current.read_text(encoding="ascii").strip(),
            f"{EXPECTED_SHA}  {EXPECTED_NAME}",
        )

    def test_live_smoke_targets_v34_identity(self) -> None:
        text = (ROOT / "scripts" / "run_live_post_deployment_smoke.py").read_text(encoding="utf-8")
        self.assertIn(EXPECTED_SHA, text)
        self.assertIn(f"{EXPECTED_VERSION}/VIGENTE/{EXPECTED_DATE}", text)
        self.assertIn(EXPECTED_NAME, text)
        superseded_identity = (
            f"{SUPERSEDED['version']}/VIGENTE/{SUPERSEDED['effective_date']}"
        )
        self.assertNotIn(superseded_identity, text)
        self.assertIn("verify_bootstrap_attestation", text)

    def test_each_superseded_identity_token_fails_independently(self) -> None:
        self.assertEqual(frozenset(OLD_ACTIVE_TOKENS), EXPECTED_SUPERSEDED_TOKENS)
        for token in EXPECTED_SUPERSEDED_TOKENS:
            with self.subTest(token=token):
                errors: list[str] = []
                validate_active_identity_text(token, "fixture-active-surface", errors)
                self.assertTrue(errors)
                self.assertTrue(any(token in error for error in errors))

    def test_superseded_active_paths_are_forbidden_but_history_is_not(self) -> None:
        self.assertEqual(frozenset(FORBIDDEN_ACTIVE_PATHS), EXPECTED_FORBIDDEN_ACTIVE_PATHS)
        for relative in EXPECTED_FORBIDDEN_ACTIVE_PATHS:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("historical-looking active surface", encoding="utf-8")
                errors = validate(root)
                self.assertTrue(
                    any(
                        relative in error and "superseded active ruleset path" in error
                        for error in errors
                    )
                )

        history_dir = SUPERSEDED_FIXTURE.parent
        self.assertTrue((history_dir / "README.md").is_file())
        for relative in EXPECTED_FORBIDDEN_ACTIVE_PATHS:
            self.assertFalse((ROOT / relative).exists())

    def test_archived_bootstrap_is_byte_exact_historical_provenance(self) -> None:
        archived = next(SUPERSEDED_FIXTURE.parent.glob("bootstrap-project-*.HISTORICAL.json"))
        self.assertTrue(archived.is_file())
        self.assertEqual(
            hashlib.sha256(archived.read_bytes()).hexdigest(),
            EXPECTED_ARCHIVED_BOOTSTRAP_SHA,
        )

    def test_stray_superseded_identity_outside_history_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stray = root / "policy_engine" / "docs" / "stray.md"
            stray.parent.mkdir(parents=True, exist_ok=True)
            token = SUPERSEDED["rule_id_prefix"] + "-S001"
            stray.write_text(f"compiled rule {token}", encoding="utf-8")
            errors = validate(root)
            self.assertTrue(
                any(
                    "policy_engine/docs/stray.md" in error
                    and "superseded identity outside explicit history" in error
                    for error in errors
                ),
                errors,
            )

    def test_split_superseded_identity_constant_outside_history_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stray = root / "reporting" / "split_identity.py"
            stray.parent.mkdir(parents=True, exist_ok=True)
            token = SUPERSEDED["rule_id_prefix"]
            midpoint = len(token) - 1
            stray.write_text(
                f"RULESET = {token[:midpoint]!r} + {token[midpoint:]!r}\n",
                encoding="utf-8",
            )
            errors = validate(root)
            self.assertTrue(
                any(
                    "reporting/split_identity.py" in error
                    and "superseded identity outside explicit history" in error
                    and token in error
                    for error in errors
                ),
                errors,
            )

    def test_constant_fstring_superseded_identity_outside_history_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stray = root / "reporting" / "fstring_identity.py"
            stray.parent.mkdir(parents=True, exist_ok=True)
            stray.write_text('RULESET = f"GENOMA-V3.{3}"\n', encoding="utf-8")
            errors = validate(root)
            self.assertTrue(
                any(
                    "reporting/fstring_identity.py" in error
                    and "superseded identity outside explicit history" in error
                    and SUPERSEDED["rule_id_prefix"] in error
                    for error in errors
                ),
                errors,
            )

    def test_bootstrap_attestation_is_digest_bound_and_complete(self) -> None:
        path = ROOT / "deploy" / "attestations" / "bootstrap-project-v3.4.json"
        evidence = verify_bootstrap_attestation(path)
        self.assertEqual(evidence["status"], "VERIFICADO")
        self.assertEqual(evidence["file_sha256"], EXPECTED_BOOTSTRAP_ATTESTATION_SHA)
        self.assertEqual(evidence["ruleset_identity"], f"{EXPECTED_VERSION}/VIGENTE/{EXPECTED_DATE}")
        self.assertEqual(evidence["canonical_sha256"], EXPECTED_SHA)
        self.assertEqual(frozenset(evidence["checks_verified"]), EXPECTED_BOOTSTRAP_CHECKS)

        with tempfile.TemporaryDirectory() as td:
            tampered = Path(td) / path.name
            data = json.loads(path.read_text(encoding="utf-8"))
            data["checks"]["require_version_v3_4"] = False
            tampered.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(BootstrapAttestationError):
                verify_bootstrap_attestation(tampered)

    def test_engine_metadata_uses_package_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target, _ = sealed_ruleset.materialize(ROOT / "normative" / "sealed", Path(td))
            ruleset = policy_ruleset.load_ruleset(target)
            engine = PolicyEngine(ruleset)
            manifest = {
                "case_id": "VERSION",
                "session_id": "VERSION",
                "ruleset": {
                    "status": "VIGENTE",
                    "version": EXPECTED_VERSION,
                    "effective_date": EXPECTED_DATE,
                    "sha256": EXPECTED_SHA,
                },
                "operation": {
                    "name": "version-check",
                    "analysis_relevant": False,
                    "requires_real_calling": False,
                    "output": "ANALYSIS",
                },
                "claims": [],
                "sources": [],
                "section_attestations": [],
                "post_deployment": {},
            }
            report = engine.evaluate(manifest)
            self.assertEqual(report.metadata["engine_version"], __version__)


if __name__ == "__main__":
    unittest.main()
