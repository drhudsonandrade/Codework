from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.zero_identity_guard import (
    PolicyError,
    RepositoryScanError,
    load_policy,
    scan_repository,
    validate_zero_identity,
)

MUTATIONS = {
    "P1": bytes.fromhex("6472687564736f6e"),
    "P2": bytes.fromhex("687564736f6e"),
    "P3": bytes.fromhex("63686174677074"),
    "P4": bytes.fromhex("636c61756465"),
}


class ZeroIdentityGuardTest(unittest.TestCase):
    def make_repo(self) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        (root / "config").mkdir()
        policy = json.loads((Path(__file__).parents[1] / "config/zero_identity_policy.json").read_text())
        (root / "config/zero_identity_policy.json").write_text(json.dumps(policy), encoding="utf-8")
        subprocess.run(["git", "add", "config/zero_identity_policy.json"], cwd=root, check=True)
        return root

    @staticmethod
    def track(root: Path, relative: str, data: bytes) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        subprocess.run(["git", "add", "--", relative], cwd=root, check=True)

    @staticmethod
    def findings(root: Path):
        return scan_repository(root)

    def test_each_class_is_detected_in_blob_content(self) -> None:
        for class_id, token in MUTATIONS.items():
            with self.subTest(class_id=class_id):
                root = self.make_repo()
                self.track(root, "sample.bin", b"aa" + token + b"zz")
                findings = self.findings(root)
                self.assertTrue(any(f.class_id == class_id and f.path == "sample.bin" and f.offset == 2 for f in findings))

    def test_mixed_ascii_case_is_detected(self) -> None:
        root = self.make_repo()
        token = MUTATIONS["P3"]
        mixed = bytes(byte - 32 if i % 2 == 0 and 97 <= byte <= 122 else byte for i, byte in enumerate(token))
        self.track(root, "mixed.txt", b"x" + mixed)
        self.assertTrue(any(f.class_id == "P3" and f.offset == 1 for f in self.findings(root)))

    def test_each_class_is_detected_in_tracked_path_name(self) -> None:
        for class_id, token in MUTATIONS.items():
            with self.subTest(class_id=class_id):
                root = self.make_repo()
                relative = (b"x-" + token + b".txt").decode("ascii")
                self.track(root, relative, b"safe")
                self.assertTrue(any(f.class_id == class_id and f.path == relative and f.offset == 2 for f in self.findings(root)))

    def test_binary_blob_is_scanned(self) -> None:
        root = self.make_repo()
        self.track(root, "binary.dat", b"\x00\xff" + MUTATIONS["P4"] + b"\x00")
        self.assertTrue(any(f.class_id == "P4" and f.offset == 2 for f in self.findings(root)))

    def test_history_directory_is_not_exempt(self) -> None:
        root = self.make_repo()
        self.track(root, "docs/history/sample.bin", MUTATIONS["P2"])
        self.assertTrue(any(f.class_id == "P2" for f in self.findings(root)))

    def test_untracked_files_do_not_affect_official_scan(self) -> None:
        root = self.make_repo()
        (root / "untracked.bin").write_bytes(MUTATIONS["P1"])
        self.assertEqual([], self.findings(root))

    def test_tracked_symlink_fails_closed(self) -> None:
        root = self.make_repo()
        (root / "target.txt").write_text("safe", encoding="utf-8")
        (root / "link.txt").symlink_to("target.txt")
        subprocess.run(["git", "add", "link.txt"], cwd=root, check=True)
        with self.assertRaises(RepositoryScanError):
            self.findings(root)

    def test_symlink_error_does_not_echo_prohibited_path_component(self) -> None:
        root = self.make_repo()
        token = MUTATIONS["P1"]
        relative = (b"link-" + token).decode("ascii")
        (root / "target.txt").write_text("safe", encoding="utf-8")
        (root / relative).symlink_to("target.txt")
        subprocess.run(["git", "add", "--", relative], cwd=root, check=True)
        with self.assertRaises(RepositoryScanError) as ctx:
            self.findings(root)
        rendered = str(ctx.exception).encode("utf-8").lower()
        self.assertNotIn(token, rendered)

    def test_git_enumeration_failure_fails_closed(self) -> None:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        policy = Path(__file__).parents[1] / "config/zero_identity_policy.json"
        with self.assertRaises(RepositoryScanError):
            scan_repository(Path(td.name), policy_path=policy)

    def test_policy_rejects_duplicate_ids_pairs_malformed_digest_and_zero_length(self) -> None:
        valid = json.loads((Path(__file__).parents[1] / "config/zero_identity_policy.json").read_text())
        mutations = []
        dup_id = json.loads(json.dumps(valid)); dup_id["classes"][1]["id"] = dup_id["classes"][0]["id"]; mutations.append(dup_id)
        dup_pair = json.loads(json.dumps(valid)); dup_pair["classes"][1]["length"] = dup_pair["classes"][0]["length"]; dup_pair["classes"][1]["sha256"] = dup_pair["classes"][0]["sha256"]; mutations.append(dup_pair)
        bad_digest = json.loads(json.dumps(valid)); bad_digest["classes"][0]["sha256"] = "xyz"; mutations.append(bad_digest)
        zero_length = json.loads(json.dumps(valid)); zero_length["classes"][0]["length"] = 0; mutations.append(zero_length)
        missing_class = json.loads(json.dumps(valid)); missing_class["classes"].pop(); mutations.append(missing_class)
        extra_class = json.loads(json.dumps(valid)); extra_class["classes"].append({"id": "P5", "length": 5, "sha256": "a" * 64}); mutations.append(extra_class)
        for payload in mutations:
            with self.subTest(payload=payload):
                td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
                path = Path(td.name) / "policy.json"; path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(PolicyError):
                    load_policy(path)

    def test_scan_uses_index_blob_not_worktree_bytes(self) -> None:
        root = self.make_repo()
        self.track(root, "staged.bin", b"aa" + MUTATIONS["P2"] + b"zz")
        (root / "staged.bin").write_bytes(b"safe-working-tree")
        findings = self.findings(root)
        self.assertTrue(
            any(f.class_id == "P2" and f.path == "staged.bin" and f.offset == 2 for f in findings),
            findings,
        )

    def test_diagnostic_redacts_prohibited_token_from_tracked_path(self) -> None:
        root = self.make_repo()
        relative = (b"x-" + MUTATIONS["P1"] + b".txt").decode("ascii")
        self.track(root, relative, b"safe")
        diagnostics = validate_zero_identity(root)
        rendered = "\n".join(diagnostics).encode("utf-8").lower()
        self.assertNotIn(MUTATIONS["P1"], rendered)
        self.assertTrue(any(line.startswith("P1\t") and "byte_offset=2" in line for line in diagnostics))

    def test_findings_do_not_expose_matched_bytes(self) -> None:
        root = self.make_repo()
        self.track(root, "sample.bin", b"aa" + MUTATIONS["P1"])
        finding = self.findings(root)[0]
        self.assertEqual({"class_id", "path", "offset"}, set(finding.__dict__))
        rendered = repr(finding).encode("utf-8").lower()
        self.assertNotIn(MUTATIONS["P1"], rendered)


if __name__ == "__main__":
    unittest.main()
