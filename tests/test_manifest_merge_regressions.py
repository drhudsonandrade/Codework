from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.merge_target_manifests import merge


class ManifestIdentityMergeTest(unittest.TestCase):
    """What survives a merge when two registries describe the same locus differently."""
    @staticmethod
    def _manifest(target, *, identifier, version="1"):
        """A manifest carrying this single target under this identity."""
        return {
            "schema": "genoma-partial-genome-targets-v1",
            "id": identifier,
            "version": version,
            "targets": [target],
        }

    @staticmethod
    def _target(position, *, assessed="A", reference="G"):
        """A target placing rs1 at this position, with these assessed and reference alleles."""
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
        """Merge manifests built from these targets, through the real script."""
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
        """Divergent coordinates are removed and the divergence recorded, not resolved by picking one."""
        payload = self._merge(self._target(10), self._target(11))
        target = payload["targets"][0]
        self.assertNotIn("coordinates", target)
        self.assertNotIn("grch38", target)
        self.assertEqual(
            {item["field"] for item in payload["identity_conflicts"]},
            {"coordinates", "grch38"},
        )

    def test_assessed_allele_conflict_removes_associated_evidence(self):
        """An assessed-allele conflict removes the evidence that supported the discarded allele."""
        payload = self._merge(self._target(10, assessed="A"), self._target(10, assessed="T"))
        target = payload["targets"][0]
        self.assertNotIn("assessed_allele", target)
        self.assertNotIn("assessed_allele_evidence", target)
        self.assertEqual(target["assessed_allele_conflict"], ["A", "T"])

    def test_three_way_allele_conflict_records_every_value(self):
        """A three-way conflict records every value, not just the first pair."""
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
        # `assessed_allele_status` too: a branch that restored only that key would leave the
        # target publishing an assessed-allele *status* with no assessed allele under it.
        self.assertNotIn("assessed_allele_status", target)

    def test_version_is_bound_to_input_content(self):
        """The merged manifest's version is bound to the input content, not to the clock."""
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
