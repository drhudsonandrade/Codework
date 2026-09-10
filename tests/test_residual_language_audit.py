"""Stage 8 residual-language and compatibility-cleanup contract."""

from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from array_pipeline import clinical_findings, homozygosity
from policy_engine.genoma_policy.models import (
    ClaimNature,
    Domain,
    OperationalStatus,
)
from scripts import validate_repo
from scripts.residual_language_audit import (
    ALLOWED_CATEGORIES,
    audit_repository,
    detect_text,
    findings_for_path,
)

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "config" / "residual_language_classification.json"
INVENTORY = ROOT / "docs" / "ENGLISH_CODEBASE_MIGRATION_FINAL_INVENTORY.md"
CODERABBIT_STRUCTURE_SHA256 = (
    "2384fda094768a8f16b01efd20f0150a7ac3acf81de51fb4867334ba1e57f25b"
)


def _coderabbit_nonprose_contract(text: str) -> str:
    lines: list[str] = []
    block_indent: int | None = None
    for raw in text.splitlines():
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if block_indent is not None:
            if not stripped:
                continue
            if indent > block_indent:
                continue
            block_indent = None
        if not stripped:
            continue
        if stripped in {
            "tone_instructions: >-",
            "instructions: |",
            "requirements: >-",
        }:
            lines.append(raw.rstrip())
            block_indent = indent
            continue
        if re.fullmatch(r'- name: ".*"', stripped):
            lines.append(" " * indent + "- name: <translated-display-name>")
            continue
        lines.append(raw.rstrip())
    return "\n".join(lines) + "\n"


class ResidualLanguageAuditTest(unittest.TestCase):
    """Require every retained Portuguese surface to be explicit and stable."""

    def test_detector_finds_portuguese_tooling_prose(self) -> None:
        self.assertTrue(
            detect_text("Revise apenas problemas introduzidos por este PR.")
        )
        self.assertTrue(detect_text("NÃO DISPONÍVEL"))
        self.assertFalse(
            detect_text(
                "Review only problems introduced by this pull request."
            )
        )

    def test_current_repository_has_no_unclassified_or_drifted_residual(
        self,
    ) -> None:
        report = audit_repository(ROOT)
        self.assertEqual(report["unclassified"], [])
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["drift"], [])

    def test_validate_repo_invokes_residual_language_audit(self) -> None:
        with mock.patch.object(
            validate_repo,
            "validate_residual_language",
            side_effect=lambda _root, out: out.append(
                "residual audit sentinel"
            ),
        ) as guard:
            errors = validate_repo.validate(ROOT)
        guard.assert_called_once()
        called_root, called_errors = guard.call_args.args
        self.assertEqual(called_root, ROOT)
        self.assertIs(called_errors, errors)
        self.assertIn("residual audit sentinel", errors)

    def test_ledger_categories_are_closed_and_reasons_are_explicit(
        self,
    ) -> None:
        payload = json.loads(LEDGER.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["schema"], "genoma-residual-language-classification-v1"
        )
        root_entries = payload["root_entries"]
        categories = {entry["category"] for entry in payload["entries"]}
        categories.update(entry["category"] for entry in root_entries)
        self.assertEqual(categories, set(ALLOWED_CATEGORIES))
        self.assertEqual(
            [entry["root"] for entry in root_entries], ["docs/history"]
        )
        self.assertNotIn(
            ".coderabbit.yaml", {entry["path"] for entry in payload["entries"]}
        )
        for entry in payload["entries"]:
            with self.subTest(path=entry["path"]):
                self.assertTrue(entry["reason"].strip())
                self.assertGreater(entry["count"], 0)
                self.assertRegex(entry["fingerprint"], r"^[0-9a-f]{64}$")
        ledger_text = LEDGER.read_text(encoding="utf-8")
        self.assertNotIn("v3.3", ledger_text)
        self.assertNotIn("RULESET_V3.3", ledger_text)

    def test_coderabbit_technical_instructions_are_english(self) -> None:
        self.assertEqual(
            findings_for_path(ROOT / ".coderabbit.yaml", root=ROOT), ()
        )
        config = (ROOT / ".coderabbit.yaml").read_text(encoding="utf-8")
        self.assertIn('language: "pt-BR"', config)
        self.assertIn('profile: "assertive"', config)
        self.assertIn("fail_commit_status: true", config)
        self.assertIn("autofix:\n      enabled: false", config)
        self.assertIn("fix_ci:\n      enabled: false", config)
        self.assertIn("resolve_merge_conflict:\n      enabled: false", config)

    def test_coderabbit_nonprose_configuration_matches_stage_eight_base(
        self,
    ) -> None:
        config = (ROOT / ".coderabbit.yaml").read_text(encoding="utf-8")
        observed = hashlib.sha256(
            _coderabbit_nonprose_contract(config).encode()
        ).hexdigest()
        self.assertEqual(observed, CODERABBIT_STRUCTURE_SHA256)

    def test_private_moi_alias_is_removed(self) -> None:
        self.assertFalse(hasattr(clinical_findings, "_normalised_moi"))
        self.assertEqual(
            clinical_findings.normalised_moi("Autosomal recessive"), "AR"
        )
        self.assertEqual(
            clinical_findings.normalised_moi("unexpected mode"), "DESCONHECIDO"
        )

    def test_supported_compatibility_aliases_remain(self) -> None:
        self.assertIs(OperationalStatus.EXECUTED, OperationalStatus.EXECUTADO)
        self.assertIs(OperationalStatus.VERIFIED, OperationalStatus.VERIFICADO)
        self.assertIs(ClaimNature.CONFIRMED_FACT, ClaimNature.FATO_CONFIRMADO)
        self.assertIs(Domain.CLINICAL, Domain.CLINICO)
        self.assertEqual(
            homozygosity.CHROMOSOME_KB,
            homozygosity.CHROMOSOME_KB_BY_BUILD["GRCh37"],
        )
        self.assertEqual(
            homozygosity.AUTOSOME_KB,
            homozygosity.AUTOSOME_KB_BY_BUILD["GRCh37"],
        )

    def test_final_inventory_documents_stage_eight_decisions(self) -> None:
        text = INVENTORY.read_text(encoding="utf-8")
        for category in ALLOWED_CATEGORIES:
            self.assertIn(f"`{category}`", text)
        for literal in (
            ".coderabbit.yaml",
            "_normalised_moi",
            "OperationalStatus.EXECUTED",
            "CHROMOSOME_KB",
            "GENOMA-RULESET-v3.4",
            "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
            "python3 scripts/residual_language_audit.py --check",
            "POST-DEPLOYMENT",
        ):
            with self.subTest(literal=literal):
                self.assertIn(literal, text)


if __name__ == "__main__":
    unittest.main()
