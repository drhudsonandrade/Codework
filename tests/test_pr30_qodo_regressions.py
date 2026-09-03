"""Regressions for the final Qodo findings on PR 30."""
from __future__ import annotations

import builtins
import hashlib
import json
import math
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from array_pipeline.allele_discrimination import _numeric
from array_pipeline.clinical_findings import _clinvar_for
from array_pipeline.pharmacogenomics import build_pharmacogenomic_passport
from array_pipeline.qc import _orientation
from scripts.build_trait_targets import GWAS_RELEASE

ROOT = Path(__file__).resolve().parents[1]


class ImmutableGwasReleaseTest(unittest.TestCase):
    def test_release_identifier_is_immutable_and_preserved_by_the_builder(self):
        self.assertEqual(
            GWAS_RELEASE,
            "https://ftp.ebi.ac.uk/pub/databases/gwas/releases/2026/08/24",
        )
        self.assertNotIn("/latest", GWAS_RELEASE)


class PharmacogenomicManifestBindingTest(unittest.TestCase):
    def test_a_different_target_manifest_is_refused_before_matrix_entries_are_used(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = {
                "schema": "genoma-partial-genome-targets-v1",
                "id": "ORIGINAL",
                "version": "1",
                "targets": [
                    {
                        "rsid": "rs1",
                        "scope": "CLINICO",
                        "label": "original",
                        "queries": {"cpic": {"path": "data/gene"}},
                    }
                ],
            }
            supplied = {
                **original,
                "targets": [{**original["targets"][0], "label": "relabeled"}],
            }
            original_path = root / "original.json"
            supplied_path = root / "supplied.json"
            matrix_path = root / "matrix.json"
            original_path.write_text(json.dumps(original), encoding="utf-8")
            supplied_path.write_text(json.dumps(supplied), encoding="utf-8")
            matrix_path.write_text(
                json.dumps(
                    {
                        "schema": "genoma-genome-completeness-matrix-v1",
                        "target_manifest": {
                            "id": original["id"],
                            "version": original["version"],
                            "sha256": hashlib.sha256(original_path.read_bytes()).hexdigest(),
                        },
                        "entries": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                r"target manifest does not match.*sha256",
            ):
                build_pharmacogenomic_passport(matrix_path, supplied_path)


class ClinvarAlleleIdentityTest(unittest.TestCase):
    def test_only_the_record_for_the_assessed_allele_is_admitted(self):
        evidence = {
            "grch38": {"chromosome": "1", "position": 100},
            "clinvar": {
                "records": [
                    {
                        "accession": "VCV-WRONG",
                        "classification": "Pathogenic",
                        "alternate_allele": "T",
                        "grch38": {"chromosome": "1", "position": 100},
                    },
                    {
                        "accession": "VCV-RIGHT",
                        "classification": "Benign",
                        "alternate_allele": "A",
                        "grch38": {"chromosome": "1", "position": 100},
                    },
                ]
            },
        }
        result = _clinvar_for("rs1", evidence, set(), {"A"})
        self.assertEqual([r["accession"] for r in result["records"]], ["VCV-RIGHT"])
        self.assertFalse(result["asserts_pathogenic"])

    def test_a_record_without_allele_identity_fails_closed(self):
        evidence = {
            "grch38": {"chromosome": "1", "position": 100},
            "clinvar": {
                "records": [
                    {
                        "accession": "VCV-LEGACY",
                        "classification": "Pathogenic",
                        "grch38": {"chromosome": "1", "position": 100},
                    }
                ]
            },
        }
        result = _clinvar_for("rs1", evidence, set(), {"A"})
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertEqual(result["records"], [])


class StrandVerificationBoundaryTest(unittest.TestCase):
    def test_legacy_text_does_not_substitute_for_an_explicit_boolean_verdict(self):
        for verdict in (None, "true", 1, {}, []):
            with self.subTest(verdict=verdict):
                qc = {
                    "input": {
                        "strand": "forward",
                        "strand_evidence": "arbitrary legacy text",
                    }
                }
                if verdict is not None:
                    qc["input"]["strand_evidence_verified"] = verdict
                status, _basis = _orientation({}, "vendor", qc)
                self.assertEqual(status, "NÃO DISPONÍVEL")

    def test_only_literal_true_verifies_forward_orientation(self):
        status, _basis = _orientation(
            {},
            "vendor",
            {"input": {"strand": "forward", "strand_evidence_verified": True}},
        )
        self.assertEqual(status, "VERIFICADO")


class FrequencyDomainTest(unittest.TestCase):
    def test_invalid_probability_values_are_dropped(self):
        values = {
            "nan": math.nan,
            "positive infinity": math.inf,
            "negative infinity": -math.inf,
            "negative": -0.01,
            "above one": 1.01,
            "boolean": True,
            "zero": 0.0,
            "one": 1.0,
            "middle": 0.25,
        }
        self.assertEqual(_numeric(values), {"zero": 0.0, "one": 1.0, "middle": 0.25})


class DirectSmokeInvocationTest(unittest.TestCase):
    def test_production_entrypoint_can_be_executed_by_absolute_path(self):
        script = (ROOT / "scripts" / "run_live_post_deployment_smoke.py").resolve()
        original_cwd = Path.cwd()

        class BootstrapReached(Exception):
            pass

        real_import = builtins.__import__
        observed_paths = []

        def stop_at_first_repository_import(name, *args, **kwargs):
            if name == "scripts.bootstrap_attestation":
                observed_paths.append(sys.path.copy())
                raise BootstrapReached
            return real_import(name, *args, **kwargs)

        try:
            with tempfile.TemporaryDirectory() as td:
                os.chdir(td)
                isolated_path = [
                    entry
                    for entry in sys.path
                    if entry and Path(entry).resolve() != ROOT
                ]
                with (
                    mock.patch.object(sys, "path", isolated_path),
                    mock.patch.object(
                        builtins,
                        "__import__",
                        side_effect=stop_at_first_repository_import,
                    ),
                    self.assertRaises(BootstrapReached),
                ):
                    runpy.run_path(str(script), run_name="__main__")
        finally:
            os.chdir(original_cwd)

        self.assertEqual(observed_paths[0][0], str(ROOT))


if __name__ == "__main__":
    unittest.main()
