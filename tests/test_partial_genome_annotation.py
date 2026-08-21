"""Annotation over a two-row fixture whose provenance is written down.

An external audit noted that the fixture's (rsid, chromosome, position, genotype) tuple also
appears in personal datasets and asked for the fixture's origin to be recorded. The overlap
is expected rather than evidence of copying: rs1799807 at 3:165548529 is the published BCHE
coordinate — reference data, the same in every file that carries the locus — and CT is one of
three possible calls there, so any carrier matches. What the audit is right about is that
nothing in the repository said where these rows came from.

Provenance, stated so the question does not need to be asked again:

* `rs1799807` — identifier and GRCh37 coordinate read from the target registry at
  `config/partial_genome_annotation_targets.json`; the genotype `CT` is written here to
  exercise the heterozygous branch and is chosen by this test, not copied from a subject.
* `rs999999` — an identifier that exists in no catalogue, at chr1:100, to exercise the
  "absent from the registry" branch. Nothing about it can match a person.

No row here is derived from any individual's data. The audit's content scanner in
`scripts/genoma_audit.py` enforces the general rule this note documents for one file.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from array_pipeline.annotation import annotate_partial_genome
from array_pipeline.qc import inspect_array
from array_pipeline.targets import build_query_plan, load_target_manifest


class PartialGenomeAnnotationTest(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        p = root / "array.csv.gz"
        with gzip.open(p, "wt", encoding="utf-8", newline="") as f:
            f.write("RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n")
            f.write("rs1799807,3,165548529,CT,consensus,CT,CT,GM\n")
            f.write("rs999999,1,100,AA,consensus,AA,AA,GM\n")
        return p

    def _evidence(self, array: Path, asserted_value: str = "forward") -> str:
        sha = hashlib.sha256(array.read_bytes()).hexdigest()
        return json.dumps({
            "status": "VERIFICADO",
            "decision": "SATISFIED",
            "asserted_value": asserted_value,
            "justification": "Synthetic annotation fixture explicitly controls build and strand.",
            "evidence_refs": ["synthetic-annotation-fixture"],
            "trace": {
                "attestation_id": "annotation-fixture-provenance",
                "created_at": "2026-08-17T00:00:00Z",
                "actor_type": "SOFTWARE",
                "actor_id": "tests.test_partial_genome_annotation",
                "method": "deterministic fixture",
                "run_id": "unit-test",
                "input_sha256": [sha],
                "output_sha256": [],
                "tool_versions": {"test": "1"},
            },
        })

    def test_plan_only_is_target_first_and_not_verified_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = self._fixture(root)
            evidence = self._evidence(array)
            qc = inspect_array(
                array,
                case_id="SYN",
                build="GRCh37",
                strand="forward",
                build_evidence=self._evidence(array, "GRCh37"),
                strand_evidence=evidence,
            )
            qc_path = root / "qc.json"
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            target_path = Path(__file__).resolve().parents[1] / "config" / "partial_genome_annotation_targets.json"
            result = annotate_partial_genome(array, qc_path, target_path, mode="plan-only")
            self.assertEqual(result["operational_status"], "PROPOSTO")
            self.assertEqual(result["evidence_gate"]["state"], "BLOCKED")
            observed = {x["rsid"] for x in result["observations"]}
            self.assertEqual(observed, {"rs1799807"})
            self.assertGreater(result["query_plan"]["query_count"], 0)
            self.assertTrue(all(x["status"] == "PROPOSTO" for x in result["evidence_retrievals"]))
            self.assertIn("genome-wide negative/exclusion claims", result["unsupported_claims"])

    def test_query_budget_fails_closed(self):
        manifest = {
            "schema": "genoma-partial-genome-targets-v1",
            "targets": [
                {"rsid": "rs1", "scope": "PESQUISA", "queries": {"clinvar": {"term": "rs1"}}},
                {"rsid": "rs2", "scope": "PESQUISA", "queries": {"clinvar": {"term": "rs2"}}},
            ],
        }
        with self.assertRaises(ValueError):
            build_query_plan({"rs1", "rs2"}, manifest, max_targets=1)

    def test_default_manifest_is_well_formed_and_bounded(self):
        path = Path(__file__).resolve().parents[1] / "config" / "partial_genome_annotation_targets.json"
        payload = load_target_manifest(path)
        self.assertEqual(payload["schema"], "genoma-partial-genome-targets-v1")
        self.assertLessEqual(len(payload["targets"]), 250)
        scopes = {x["scope"] for x in payload["targets"]}
        self.assertTrue(scopes <= {"CLINICO", "PREDISPOSICAO", "PESQUISA", "CURIOSIDADE"})


if __name__ == "__main__":
    unittest.main()


class CoordinateReachesTheObservationStatusTest(unittest.TestCase):
    """The coordinate check was computed, stored, and consumed by nothing.

    `check_coordinate` compares the observed position against the registry's canonical one —
    an rsID is a label, and a file carrying the right label at the wrong position is annotated
    on another assembly. The result was written onto every record and
    `observation_operational_status` read the orientation alone, so a locus whose coordinate
    diverged still reached VERIFICADO. On the first real array, rs4307059 was VERIFICADO with
    `coordinate_operational_status: NÃO DISPONÍVEL` beside it.
    """

    def _status(self, **row):
        from array_pipeline.annotation import _observation_status

        base = {"orientation_operational_status": "VERIFICADO"}
        return _observation_status([{**base, **row}])

    def test_both_checks_must_hold_for_verificado(self):
        self.assertEqual(self._status(coordinate_operational_status="VERIFICADO"), "VERIFICADO")

    def test_a_divergent_coordinate_blocks_the_locus(self):
        status = self._status(
            coordinate_operational_status="NÃO DISPONÍVEL",
            coordinate_basis="coordenada divergente em GRCh37: o arquivo traz chr1:100 e o registro chr1:200",
        )
        self.assertEqual(status, "NÃO DISPONÍVEL")

    def test_a_registry_without_a_canonical_coordinate_is_inferido_not_verified(self):
        """Not the file's fault, and not a verification either."""
        status = self._status(
            coordinate_operational_status="NÃO DISPONÍVEL",
            coordinate_basis="registro não traz coordenada canônica para rs4307059: rsid ausente",
        )
        self.assertEqual(status, "INFERIDO")

    def test_an_unchecked_coordinate_is_inferido(self):
        """No target metadata means nothing established where this rsid sits."""
        self.assertEqual(self._status(), "INFERIDO")

    def test_an_unverified_orientation_still_blocks_first(self):
        self.assertEqual(
            self._status(
                orientation_operational_status="NÃO DISPONÍVEL",
                coordinate_operational_status="VERIFICADO",
            ),
            "INFERIDO",
        )

    def test_duplicate_rows_for_one_rsid_are_never_verified(self):
        from array_pipeline.annotation import _observation_status

        rows = [
            {"orientation_operational_status": "VERIFICADO", "coordinate_operational_status": "VERIFICADO"},
            {"orientation_operational_status": "VERIFICADO", "coordinate_operational_status": "VERIFICADO"},
        ]
        self.assertEqual(_observation_status(rows), "NÃO DISPONÍVEL")
