from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import bootstrap_attestation


class BootstrapAttestationCliTests(unittest.TestCase):
    @staticmethod
    def _reproducible_evidence() -> dict:
        return {
            "verifier": {"id": "test", "version": "1", "command": "test"},
            "input": {"raw_sha256": "0" * 64},
            "result_locator": "test#/checks",
            "checks": {"fixture": {"satisfied": True}},
        }

    @classmethod
    def _payload_with_revision(cls, revision: str) -> tuple[dict, dict]:
        evidence = cls._reproducible_evidence()
        payload = {
            "method": {
                "kind": "DETERMINISTIC_VERIFIER",
                "verifier": evidence["verifier"],
                "source_commit_sha": revision,
                "input": evidence["input"],
                "result_locator": evidence["result_locator"],
                "checks_evidence": evidence["checks"],
            }
        }
        return payload, evidence

    @staticmethod
    def _init_git_repo(root: Path) -> tuple[str, str]:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        tracked = root / "tracked.txt"
        tracked.write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", tracked.name], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=GENOMA Test",
                "-c",
                "user.email=genoma-test@example.invalid",
                "commit",
                "-q",
                "-m",
                "fixture",
            ],
            check=True,
        )
        commit_sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        blob_sha = subprocess.run(
            ["git", "-C", str(root), "hash-object", tracked.name],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return commit_sha, blob_sha

    def test_write_requires_fresh_verified_at_even_when_prior_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "bootstrap.json"
            output.write_text('{"verified_at":"2026-01-01T00:00:00Z"}', encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                bootstrap_attestation.main(["--write", "--output", str(output)])
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                '{"verified_at":"2026-01-01T00:00:00Z"}',
            )

    def test_explicit_verified_at_recovers_from_corrupt_prior_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "bootstrap.json"
            output.write_text("not-json", encoding="utf-8")
            payload = {
                "attestation_type": "GENOMA_PROJECT_BOOTSTRAP",
                "verified_at": "2026-08-23T22:15:00Z",
            }
            with patch.object(bootstrap_attestation, "build_attestation", return_value=payload):
                rc = bootstrap_attestation.main(
                    [
                        "--write",
                        "--verified-at",
                        payload["verified_at"],
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), payload)

    def test_reproducible_method_rejects_unknown_source_revision(self) -> None:
        payload, evidence = self._payload_with_revision("UNKNOWN")
        with self.assertRaisesRegex(
            bootstrap_attestation.BootstrapAttestationError,
            "source_commit_sha is UNKNOWN",
        ):
            bootstrap_attestation._require_reproducible_method(payload, evidence)

    def test_reproducible_method_rejects_malformed_source_revisions(self) -> None:
        for revision in ("a" * 39, "g" * 40, "A" * 40, "0" * 41):
            with self.subTest(revision=revision):
                payload, evidence = self._payload_with_revision(revision)
                with self.assertRaisesRegex(
                    bootstrap_attestation.BootstrapAttestationError,
                    "full 40-character lowercase hex Git commit SHA",
                ):
                    bootstrap_attestation._require_reproducible_method(payload, evidence)

    def test_reproducible_method_rejects_well_formed_sha_missing_from_repository(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            commit_sha, _ = self._init_git_repo(root)
            missing_sha = "0" * 40
            self.assertNotEqual(commit_sha, missing_sha)
            payload, evidence = self._payload_with_revision(missing_sha)
            with self.assertRaisesRegex(
                bootstrap_attestation.BootstrapAttestationError,
                "does not resolve to a commit in the associated Git repository",
            ):
                bootstrap_attestation._require_reproducible_method(payload, evidence, root=root)

    def test_reproducible_method_rejects_git_object_that_is_not_a_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _commit_sha, blob_sha = self._init_git_repo(root)
            payload, evidence = self._payload_with_revision(blob_sha)
            with self.assertRaisesRegex(
                bootstrap_attestation.BootstrapAttestationError,
                "does not resolve to a commit in the associated Git repository",
            ):
                bootstrap_attestation._require_reproducible_method(payload, evidence, root=root)

    def test_reproducible_method_accepts_existing_commit_sha(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            commit_sha, _ = self._init_git_repo(root)
            payload, evidence = self._payload_with_revision(commit_sha)
            bootstrap_attestation._require_reproducible_method(payload, evidence, root=root)

    def test_build_attestation_rejects_invalid_source_revision_before_write(self) -> None:
        evidence = self._reproducible_evidence()
        for revision in ("UNKNOWN", "not-a-full-git-sha"):
            with self.subTest(revision=revision):
                with (
                    patch.object(bootstrap_attestation, "verify_project_bootstrap", return_value=evidence),
                    patch.object(bootstrap_attestation, "_source_revision", return_value=revision),
                    self.assertRaises(bootstrap_attestation.BootstrapAttestationError),
                ):
                    bootstrap_attestation.build_attestation(
                        verified_at="2026-08-23T20:26:00-03:00"
                    )

    def test_build_attestation_rejects_well_formed_sha_missing_from_repository(self) -> None:
        evidence = self._reproducible_evidence()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._init_git_repo(root)
            with (
                patch.object(bootstrap_attestation, "verify_project_bootstrap", return_value=evidence),
                patch.object(bootstrap_attestation, "_source_revision", return_value="0" * 40),
                self.assertRaisesRegex(
                    bootstrap_attestation.BootstrapAttestationError,
                    "does not resolve to a commit in the associated Git repository",
                ),
            ):
                bootstrap_attestation.build_attestation(
                    root=root,
                    verified_at="2026-08-23T20:26:00-03:00",
                )


if __name__ == "__main__":
    unittest.main()
