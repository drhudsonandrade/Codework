from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from policy_engine.genoma_policy import __version__
from policy_engine.genoma_policy import paths as policy_paths
from policy_engine.genoma_policy import ruleset as policy_ruleset
from policy_engine.genoma_policy.engine import PolicyEngine
from scripts import bootstrap_attestation, sealed_ruleset
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
EXPECTED_ARCHIVED_BOOTSTRAP_SHA = "33ace0f91f524ddf3fed1ced5ca95bcebcfe230570660615ac6ff57164420e22"
EXPECTED_SUPERSEDED_FIXTURE_SHA = "5a6f888f176ed4c963c43c24f38697ea363f5772be06c63e70d6a8f5c497e503"
EXPECTED_BOOTSTRAP_ATTESTATION_SHA = "f7ce057e27a08c1e08c2bb1a74ab6c0fc777f323a852a2d946df344731ee8a2e"
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

    def test_archived_bootstrap_is_deidentified_and_provenance_bound(self) -> None:
        archived = next(SUPERSEDED_FIXTURE.parent.glob("bootstrap-project-*.HISTORICAL.json"))
        self.assertTrue(archived.is_file())
        self.assertEqual(
            hashlib.sha256(archived.read_bytes()).hexdigest(),
            EXPECTED_ARCHIVED_BOOTSTRAP_SHA,
        )
        payload = json.loads(archived.read_text(encoding="utf-8"))
        migration = payload["provenance_migration"]
        self.assertEqual(migration["status"], "DEIDENTIFIED_CURRENT_TREE")
        self.assertEqual(
            migration["pre_deidentification_sha256"],
            "87af4f99bcd6b6f3f857a1ca725103e95dabf70c3c926d7f0d4e83b037e69fd8",
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


class BootstrapAttestationReproducibilityTests(unittest.TestCase):
    """VERIFICADO has to be re-derivable, never merely declared.

    The attestation records how it was produced — verifier, immutable input digests,
    command, result locator and per-check evidence — and verification recomputes all of
    it from the sealed canonical ruleset. Prose, or evidence that no longer matches the
    ruleset, must fail closed.
    """

    ATTESTATION = ROOT / "deploy" / "attestations" / "bootstrap-project-v3.4.json"

    def _verify_mutated(self, mutate) -> None:
        """Write a mutated attestation, re-pin its digest, and verify it."""
        payload = json.loads(self.ATTESTATION.read_text(encoding="utf-8"))
        mutate(payload)
        raw = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / self.ATTESTATION.name
            target.write_text(raw, encoding="utf-8")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            # Re-pinning isolates the method check from the byte-digest check, which would
            # otherwise reject every mutation before the method is even read.
            with patch.object(bootstrap_attestation, "EXPECTED_FILE_SHA256", digest):
                bootstrap_attestation.verify_bootstrap_attestation(target)

    def test_committed_attestation_records_reproducible_verifier_metadata(self) -> None:
        payload = json.loads(self.ATTESTATION.read_text(encoding="utf-8"))
        method = payload["method"]
        self.assertEqual(method["kind"], "DETERMINISTIC_VERIFIER")
        self.assertEqual(method["verifier"]["id"], bootstrap_attestation.VERIFIER_ID)
        self.assertEqual(method["verifier"]["version"], bootstrap_attestation.VERIFIER_VERSION)
        self.assertEqual(method["verifier"]["command"], bootstrap_attestation.VERIFIER_COMMAND)
        self.assertEqual(method["input"]["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(method["input"]["canonical_filename"], EXPECTED_NAME)
        self.assertRegex(method["source_commit_sha"], r"^[0-9a-f]{40}$")
        self.assertEqual(method["result_locator"], bootstrap_attestation.RESULT_LOCATOR)
        self.assertEqual(set(method["checks_evidence"]), EXPECTED_BOOTSTRAP_CHECKS)

    def test_every_check_is_re_derived_from_the_sealed_ruleset(self) -> None:
        evidence = bootstrap_attestation.verify_project_bootstrap()
        self.assertEqual(set(evidence["checks"]), EXPECTED_BOOTSTRAP_CHECKS)
        for name, result in evidence["checks"].items():
            with self.subTest(check=name):
                self.assertTrue(result["satisfied"])
                self.assertIsInstance(result["line"], int)
                self.assertRegex(result["clause_sha256"], r"^[0-9a-f]{64}$")

    def test_prose_method_is_rejected(self) -> None:
        def to_prose(payload):
            payload["method"] = "direct verification of the active project instructions"

        with self.assertRaisesRegex(BootstrapAttestationError, "not prose"):
            self._verify_mutated(to_prose)

    def test_missing_source_commit_sha_is_rejected(self) -> None:
        with self.assertRaisesRegex(BootstrapAttestationError, "source_commit_sha"):
            self._verify_mutated(lambda payload: payload["method"].pop("source_commit_sha"))

    def test_input_digest_that_does_not_match_the_sealed_transport_is_rejected(self) -> None:
        def drift(payload):
            payload["method"]["input"]["raw_sha256"] = "0" * 64

        with self.assertRaisesRegex(BootstrapAttestationError, "input does not match"):
            self._verify_mutated(drift)

    def test_check_evidence_that_is_not_reproducible_is_rejected(self) -> None:
        def drift(payload):
            payload["method"]["checks_evidence"]["require_version_v3_4"]["line"] = 9999

        with self.assertRaisesRegex(BootstrapAttestationError, "not reproducible"):
            self._verify_mutated(drift)

    def test_a_clause_absent_from_the_ruleset_yields_a_pending_status(self) -> None:
        clauses = dict(bootstrap_attestation.BOOTSTRAP_CLAUSES)
        clauses["require_version_v3_4"] = "VERSÃO NORMATIVA: v9.9-not-in-this-ruleset"
        with patch.object(bootstrap_attestation, "BOOTSTRAP_CLAUSES", clauses):
            payload = bootstrap_attestation.build_attestation(verified_at="2026-08-22T18:46:00-03:00")
        self.assertEqual(payload["status"], "PENDENTE")
        self.assertFalse(payload["checks"]["require_version_v3_4"])

    def test_regenerating_the_attestation_is_byte_stable(self) -> None:
        committed = json.loads(self.ATTESTATION.read_text(encoding="utf-8"))
        regenerated = bootstrap_attestation.build_attestation(verified_at=committed["verified_at"])
        # source_commit_sha moves with HEAD by design; everything else must reproduce.
        regenerated["method"]["source_commit_sha"] = committed["method"]["source_commit_sha"]
        self.assertEqual(regenerated, committed)


if __name__ == "__main__":
    unittest.main()
