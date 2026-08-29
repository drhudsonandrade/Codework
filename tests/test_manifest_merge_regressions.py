from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.merge_target_manifests import merge


class ManifestIdentityMergeTest(unittest.TestCase):
    @staticmethod
    def _manifest(target, *, identifier, version="1"):
        return {
            "schema": "genoma-partial-genome-targets-v1",
            "id": identifier,
            "version": version,
            "targets": [target],
        }

    @staticmethod
    def _target(position, *, assessed="A", reference="G"):
        return {
            "rsid": "rs1",
            "scope": "CLINICO",
            "queries": {"clinvar": {"term": "rs1"}},
            "coordinates": {
                "status": "VERIFICADO",
                "GRCh38": {"chromosome": "1", "position": position},
            },
            "grch38": {"chromosome": "1", "position": position},
            "reference_allele": reference,
            "assessed_allele": assessed,
            "assessed_allele_source": "fixture",
            "assessed_allele_status": "VERIFICADO",
            "assessed_allele_evidence": {"accession": "VCV1"},
        }

    def _merge(self, *targets):
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for index, target in enumerate(targets):
                path = Path(td) / f"manifest-{index}.json"
                path.write_text(
                    json.dumps(self._manifest(target, identifier=f"registry-{index}")),
                    encoding="utf-8",
                )
                paths.append(path)
            return merge(paths)

    def test_divergent_coordinates_are_removed_and_recorded(self):
        payload = self._merge(self._target(10), self._target(11))
        target = payload["targets"][0]
        self.assertNotIn("coordinates", target)
        self.assertNotIn("grch38", target)
        self.assertEqual(
            {item["field"] for item in payload["identity_conflicts"]},
            {"coordinates", "grch38"},
        )

    def test_assessed_allele_conflict_removes_associated_evidence(self):
        payload = self._merge(self._target(10, assessed="A"), self._target(10, assessed="T"))
        target = payload["targets"][0]
        self.assertNotIn("assessed_allele", target)
        self.assertNotIn("assessed_allele_evidence", target)
        self.assertEqual(target["assessed_allele_conflict"], ["A", "T"])

    def test_three_way_allele_conflict_records_every_value(self):
        payload = self._merge(
            self._target(10, assessed="A"),
            self._target(10, assessed="T"),
            self._target(10, assessed="G"),
        )
        target = payload["targets"][0]
        self.assertEqual(target["assessed_allele_conflict"], ["A", "G", "T"])
        self.assertEqual(
            payload["assessed_allele_conflicts"][0]["assessed_alleles"],
            ["A", "G", "T"],
        )
        # Listing the conflicting values is not the same as refusing the locus. Asserting
        # only the list, a regression where the already-conflicted branch copied
        # `assessed_allele` back from the third registry would still have passed here, and
        # the manifest would ship an arbitrated allele beside the record of the conflict.
        self.assertNotIn("assessed_allele", target)
        self.assertNotIn("assessed_allele_evidence", target)
        self.assertNotIn("assessed_allele_source", target)

    def test_version_is_bound_to_input_content(self):
        with tempfile.TemporaryDirectory() as td:
            one = Path(td) / "one.json"
            first = self._manifest(self._target(10), identifier="one", version="1")
            one.write_text(json.dumps(first), encoding="utf-8")
            with patch("scripts.merge_target_manifests.datetime") as clock:
                clock.now.return_value.isoformat.return_value = "2026-08-24T00:00:00+00:00"
                initial = merge([one])
                first["version"] = "2"
                one.write_text(json.dumps(first), encoding="utf-8")
                changed = merge([one])
        self.assertNotEqual(initial["version"], changed["version"])


if __name__ == "__main__":
    unittest.main()
