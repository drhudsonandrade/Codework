import importlib.util
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_repo.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_repo", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load repository validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepoContractTest(unittest.TestCase):
    def test_contract_detects_missing_paths(self):
        validator = load_validator()
        with tempfile.TemporaryDirectory() as directory:
            errors = validator.validate(Path(directory))
        self.assertTrue(any("missing required path" in error for error in errors))

    def test_contract_accepts_repository_scaffold(self):
        validator = load_validator()
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(validator.validate(root), [])


    def test_validate_repo_invokes_project_identity_guard(self):
        validator = load_validator()
        root = Path(__file__).resolve().parents[1]
        with patch.object(
            validator,
            "validate_project_identity",
            return_value=["project identity sentinel"],
        ) as guard:
            errors = validator.validate(root)
        guard.assert_called_once_with(root)
        self.assertIn("project identity sentinel", errors)

    def test_validate_repo_invokes_zero_identity_guard(self):
        validator = load_validator()
        root = Path(__file__).resolve().parents[1]
        with patch.object(
            validator,
            "validate_zero_identity",
            return_value=["zero identity sentinel"],
        ) as guard:
            errors = validator.validate(root)
        guard.assert_called_once_with(root)
        self.assertIn("zero identity sentinel", errors)

    def test_zero_identity_paths_are_required(self):
        validator = load_validator()
        for relative in (
            "config/zero_identity_policy.json",
            "scripts/zero_identity_guard.py",
        ):
            self.assertIn(relative, validator.REQUIRED_PATHS)

    def test_official_validator_rejects_each_prohibited_fingerprint_class(self):
        validator = load_validator()
        policy_source = Path(__file__).resolve().parents[1] / "config" / "zero_identity_policy.json"
        mutations = {
            "P1": bytes.fromhex("6472687564736f6e"),
            "P2": bytes.fromhex("687564736f6e"),
            "P3": bytes.fromhex("63686174677074"),
            "P4": bytes.fromhex("636c61756465"),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "config").mkdir()
            (root / "config" / "zero_identity_policy.json").write_bytes(
                policy_source.read_bytes()
            )
            subprocess.run(
                ["git", "add", "config/zero_identity_policy.json"],
                cwd=root,
                check=True,
            )
            for class_id, payload in mutations.items():
                with self.subTest(class_id=class_id):
                    target = root / "identity-mutation.bin"
                    target.write_bytes(b"safe-" + payload + b"-fixture")
                    subprocess.run(
                        ["git", "add", "identity-mutation.bin"],
                        cwd=root,
                        check=True,
                    )
                    errors = validator.validate(root)
                    self.assertTrue(
                        any(
                            class_id in error and "identity-mutation.bin" in error
                            for error in errors
                        ),
                        errors,
                    )
                    subprocess.run(
                        ["git", "rm", "--cached", "-f", "identity-mutation.bin"],
                        cwd=root,
                        check=True,
                        stdout=subprocess.DEVNULL,
                    )
                    target.unlink()

    def test_identity_contract_paths_are_required(self):
        validator = load_validator()
        for relative in (
            "config/project_identity.json",
            "config/legacy_identity_ledger.json",
            "scripts/project_identity_guard.py",
            "docs/PROJECT_IDENTITY_CONTRACT.md",
        ):
            self.assertIn(relative, validator.REQUIRED_PATHS)

    def test_json_scan_reads_utf8_explicitly(self):
        validator = load_validator()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "utf8.json"
            payload.write_text('{"label": "≥"}', encoding="utf-8")
            original_read_text = Path.read_text

            def guarded_read_text(candidate, encoding=None, errors=None) -> str:
                if candidate == payload and encoding != "utf-8":
                    raise UnicodeDecodeError("charmap", b"\x8d", 0, 1, "test non-UTF-8 encoding")
                return original_read_text(candidate, encoding=encoding, errors=errors)

            with patch.object(Path, "read_text", guarded_read_text):
                with self.assertRaises(UnicodeDecodeError):
                    payload.read_text(encoding="latin-1")
                errors = validator.validate(root)
        self.assertFalse(any("invalid JSON: utf8.json" in error for error in errors), errors)

    def test_contract_rejects_micromamba_entrypoint_bypass(self):
        validator = load_validator()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runbook = root / "docs" / "MAGALU_PRIVATE_MCP_SETUP.md"
            runbook.parent.mkdir(parents=True)
            runbook.write_text(
                "PRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE\n"
                "docker run --entrypoint /bin/bash image command\n",
                encoding="utf-8",
            )
            errors = validator.validate(root)
        self.assertIn("runbook must not bypass the micromamba container entrypoint", errors)

    def test_non_ascii_ruleset_manifest_is_reported_not_raised(self):
        """A non-ASCII SHA manifest must fail the check, not abort the whole run.

        read_text(encoding="ascii") raises on the first non-ASCII byte, and that
        UnicodeDecodeError used to propagate out of validate(), skipping every check
        after it instead of reporting the manifest as invalid.
        """
        validator = load_validator()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifests" / "RULESET_V3.4.sha256"
            manifest.parent.mkdir(parents=True)
            # A non-breaking space: valid UTF-8, not decodable as ASCII.
            manifest.write_text(
                "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580  "
                "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt\u00a0\n",
                encoding="utf-8",
            )
            # This deliberately wrong dependency is checked after the ruleset manifest,
            # so its diagnostic proves validate() continued beyond the failed ASCII read.
            package = root / "mcp" / "package.json"
            package.parent.mkdir(parents=True)
            package.write_text(
                json.dumps({"devDependencies": {"fallow": "0.0.0"}}),
                encoding="utf-8",
            )
            with self.assertRaises(UnicodeDecodeError):
                manifest.read_text(encoding="ascii")
            errors = validator.validate(root)
        self.assertIn("ruleset external manifest does not match the verified v3.4 artifact", errors)
        self.assertIn("mcp/package.json must pin fallow 3.16.0 exactly", errors)


if __name__ == "__main__":
    unittest.main()
