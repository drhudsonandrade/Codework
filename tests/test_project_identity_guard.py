from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

from scripts.project_identity_guard import validate_project_identity


ROOT = Path(__file__).resolve().parents[1]
LEGACY_WORD = "code" + "work"
LEGACY_RUNTIME_ROOT = "/opt/" + LEGACY_WORD
LEGACY_SURPRISE = LEGACY_WORD + "-surprise"

EXPECTED_SCAN_SUFFIXES = [
    "", ".example", ".json", ".md", ".nf", ".py", ".service",
    ".sh", ".toml", ".ts", ".txt", ".yaml", ".yml",
]
EXPECTED_HISTORICAL_PREFIXES = [
    "docs/history/",
    "docs/superpowers/specs/",
    "docs/superpowers/plans/",
    "docs/superpowers/evidence/",
    "docs/superpowers/checkpoints/",
]


IDENTITY = {
    "schema": "omnigenis-project-identity-v1",
    "version": "2026-09-10.1",
    "repository": {"product_name": "OmniGenis", "full_name": "drhudsonandrade/OmniGenis"},
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
        "runner_names": ["drhudson-omnigenis-01", "drhudson-omnigenis-02"],
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


class ProjectIdentityGuardTest(unittest.TestCase):
    def make_repo(
        self,
        text: str,
        max_count: int = 1,
        scan_suffixes: list[str] | None = None,
        historical_prefixes: list[str] | None = None,
    ) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "config").mkdir()
        (root / "config/project_identity.json").write_text(
            json.dumps(IDENTITY), encoding="utf-8"
        )
        ledger = {
            "schema": "omnigenis-legacy-identity-ledger-v1",
            "baseline_commit": "939dfea5cc7cb2745638168d518d2005e941e9c6",
            "phase": "2A",
            "scan_suffixes": EXPECTED_SCAN_SUFFIXES if scan_suffixes is None else scan_suffixes,
            "historical_prefixes": (
                EXPECTED_HISTORICAL_PREFIXES
                if historical_prefixes is None
                else historical_prefixes
            ),
            "entries": [
                {
                    "id": "runtime-root",
                    "matcher": {"kind": "literal", "value": LEGACY_RUNTIME_ROOT},
                    "replacement": "/opt/omnigenis",
                    "retire_by": "2B",
                    "reason": "Temporary runtime-root compatibility.",
                    "locations": {"active.txt": max_count},
                }
            ],
        }
        (root / "config/legacy_identity_ledger.json").write_text(
            json.dumps(ledger), encoding="utf-8"
        )
        (root / "active.txt").write_text(text, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        return root


    def make_real_repo_subset(self, relative_paths: list[str]) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        required = [
            "config/project_identity.json",
            "config/legacy_identity_ledger.json",
            *relative_paths,
        ]
        for relative in required:
            source = ROOT / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        return root

    def test_reviewed_occurrence_passes(self) -> None:
        self.assertEqual(validate_project_identity(self.make_repo(LEGACY_RUNTIME_ROOT)), [])

    def test_removing_a_legacy_occurrence_is_allowed(self) -> None:
        self.assertEqual(validate_project_identity(self.make_repo("clean", max_count=1)), [])

    def test_new_unclassified_legacy_identity_fails(self) -> None:
        errors = validate_project_identity(self.make_repo(LEGACY_SURPRISE))
        self.assertTrue(any("unclassified legacy identity" in error for error in errors))

    def test_reviewed_count_may_not_increase(self) -> None:
        errors = validate_project_identity(self.make_repo(f"{LEGACY_RUNTIME_ROOT} {LEGACY_RUNTIME_ROOT}"))
        self.assertTrue(any("legacy occurrence count increased" in error for error in errors))

    def test_reviewed_identity_may_not_move_to_an_unlisted_path(self) -> None:
        root = self.make_repo("clean")
        (root / "moved.txt").write_text(LEGACY_RUNTIME_ROOT, encoding="utf-8")
        subprocess.run(["git", "add", "moved.txt"], cwd=root, check=True)
        errors = validate_project_identity(root)
        self.assertTrue(any("unclassified legacy identity" in error for error in errors))


    def test_control_metadata_ledger_is_not_scanned(self) -> None:
        root = self.make_repo(LEGACY_RUNTIME_ROOT)
        errors = validate_project_identity(root)
        self.assertEqual(errors, [])

    def test_untracked_file_does_not_affect_official_guard(self) -> None:
        root = self.make_repo("clean")
        (root / "local.txt").write_text(LEGACY_SURPRISE, encoding="utf-8")
        errors = validate_project_identity(root)
        self.assertEqual(errors, [])

    def test_empty_scan_suffix_policy_fails_closed(self) -> None:
        root = self.make_repo("clean", scan_suffixes=[])
        errors = validate_project_identity(root)
        self.assertTrue(any("scan suffix policy mismatch" in error for error in errors))

    def test_empty_historical_prefix_bypass_fails_closed(self) -> None:
        root = self.make_repo("clean", historical_prefixes=[""])
        errors = validate_project_identity(root)
        self.assertTrue(any("historical prefix policy mismatch" in error for error in errors))

    def test_invalid_utf8_tracked_file_fails_closed(self) -> None:
        root = self.make_repo("clean")
        (root / "invalid.txt").write_bytes(b"\xff\xfelegacy")
        subprocess.run(["git", "add", "invalid.txt"], cwd=root, check=True)
        errors = validate_project_identity(root)
        self.assertTrue(any("legacy identity scan failed closed" in error for error in errors))


    def test_real_repository_has_no_unclassified_legacy_identity(self) -> None:
        self.assertEqual(validate_project_identity(ROOT), [])

    def test_real_ledger_rejects_new_unclassified_identity(self) -> None:
        root = self.make_real_repo_subset([])
        (root / "active.txt").write_text(LEGACY_WORD + "-new-identity", encoding="utf-8")
        subprocess.run(["git", "add", "active.txt"], cwd=root, check=True)
        errors = validate_project_identity(root)
        self.assertTrue(any("unclassified legacy identity" in error for error in errors))

    def test_real_ledger_rejects_increased_reviewed_count(self) -> None:
        root = self.make_real_repo_subset(["Dockerfile"])
        dockerfile = root / "Dockerfile"
        dockerfile.write_text(
            dockerfile.read_text(encoding="utf-8") + f"\n# {LEGACY_RUNTIME_ROOT}\n",
            encoding="utf-8",
        )
        errors = validate_project_identity(root)
        self.assertTrue(any("legacy occurrence count increased" in error for error in errors))

    def test_real_ledger_rejects_reviewed_identity_on_unlisted_path(self) -> None:
        root = self.make_real_repo_subset([])
        (root / "moved.txt").write_text(LEGACY_RUNTIME_ROOT, encoding="utf-8")
        subprocess.run(["git", "add", "moved.txt"], cwd=root, check=True)
        errors = validate_project_identity(root)
        self.assertTrue(any("unclassified legacy identity" in error for error in errors))

    def test_ledger_replacement_must_be_canonical(self) -> None:
        root = self.make_repo(LEGACY_RUNTIME_ROOT)
        ledger_path = root / "config/legacy_identity_ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["entries"][0]["replacement"] = "/opt/not-omnigenis"
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        errors = validate_project_identity(root)
        self.assertTrue(any("replacement is not canonical" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
