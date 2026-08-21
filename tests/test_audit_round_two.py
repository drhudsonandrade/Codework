"""Second batch of external-audit findings, each pinned by the failure it describes.

The report these come from audited a commit 35 behind this branch, so every item was
re-tested here before anything was written. The ones that turned out to be real are pinned
below; one of them (A-04's proposal to unify two publication flags) is pinned in the
opposite direction, because following it literally would have made honest reports
unpublishable.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "policy_engine") not in sys.path:
    sys.path.insert(0, str(ROOT / "policy_engine"))


class LedgerChainTest(unittest.TestCase):
    """A-07: the chain was verifiable after the fact and never verified before extension.

    `append_event` read only the last line, so a tampered entry anywhere earlier stayed
    invisible and every later append chained onto the rewritten history.
    """

    def _ledger(self, root: Path, events: int = 3) -> Path:
        from genoma_policy.ledger import append_event

        path = root / "ledger.jsonl"
        for i in range(events):
            append_event(path, "test-event", {"i": i})
        return path

    def test_an_intact_chain_accepts_an_append(self):
        from genoma_policy.ledger import append_event, verify_ledger

        with tempfile.TemporaryDirectory() as td:
            path = self._ledger(Path(td))
            append_event(path, "test-event", {"i": 99})
            self.assertTrue(verify_ledger(path)[0])

    def test_a_tampered_earlier_entry_refuses_the_next_append(self):
        from genoma_policy.ledger import LedgerError, append_event

        with tempfile.TemporaryDirectory() as td:
            path = self._ledger(Path(td))
            lines = path.read_text(encoding="utf-8").splitlines()
            record = json.loads(lines[0])
            record["payload_sha256"] = "f" * 64
            lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                append_event(path, "test-event", {"i": 100})

    def test_the_refusal_says_which_line_broke(self):
        from genoma_policy.ledger import LedgerError, append_event

        with tempfile.TemporaryDirectory() as td:
            path = self._ledger(Path(td))
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[1] = json.dumps({"sequence": 2, "entry_sha256": "0" * 64})
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(LedgerError) as caught:
                append_event(path, "test-event", {"i": 100})
        self.assertIn("line 2", str(caught.exception))

    def test_a_fresh_ledger_still_starts(self):
        # Negative control: the refusal must not make the first append impossible.
        from genoma_policy.ledger import append_event

        with tempfile.TemporaryDirectory() as td:
            record = append_event(Path(td) / "new.jsonl", "first", {"a": 1})
        self.assertEqual(record["sequence"], 1)


class EvidenceSemanticsTest(unittest.TestCase):
    """M-03: the parse result was discarded, so any decodable JSON became VERIFICADO."""

    def _query(self, body, key: str = "clinvar"):
        from evidence_adapters import get_adapter

        payload = json.dumps(body).encode("utf-8")
        adapter = get_adapter(key, transport=lambda req: (payload, {"Content-Type": "application/json"}))
        return adapter.query({"term": "rs1799807"}, checked_at="2026-08-20")

    def test_an_empty_document_is_not_verified(self):
        result = self._query({})
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIn("vazia", result["semantic_refusal"])

    def test_a_provider_error_envelope_is_not_verified(self):
        result = self._query({"error": "rate limit exceeded"})
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIn("rate limit", result["semantic_refusal"])

    def test_clinvar_reports_its_failure_inside_the_result_object(self):
        result = self._query({"esearchresult": {"ERROR": "Invalid db name"}})
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIn("Invalid db name", result["semantic_refusal"])

    def test_a_genuine_zero_result_is_verified_and_counted(self):
        # "the query ran and found nothing" is an answer; "the query failed" is not. The
        # two used to be indistinguishable.
        result = self._query({"esearchresult": {"idlist": []}})
        self.assertEqual(result["status"], "VERIFICADO")
        self.assertEqual(result["record_count"], 0)

    def test_records_are_counted_when_present(self):
        result = self._query({"esearchresult": {"idlist": ["1", "2", "3"]}})
        self.assertEqual(result["record_count"], 3)

    def test_retrieval_is_graded_apart_from_curation(self):
        # VERIFICADO here has always meant "bytes fetched and parsed". Saying so in its own
        # field stops a successful HTTP call being read as reviewed science.
        result = self._query({"esearchresult": {"idlist": ["1"]}})
        self.assertEqual(result["evidence_grade"], "RECUPERAÇÃO VERIFICADA")
        self.assertIn("Não é curadoria", result["evidence_grade_note"])

    def test_an_uncountable_provider_returns_none_not_zero(self):
        # None is not zero: "not counted" must not read as "counted and empty", the same
        # distinction this project draws between NÃO INTERROGADO and NEGATIVO.
        from evidence_adapters import _record_count

        self.assertIsNone(_record_count("cpic", {"anything": 1}))
        self.assertEqual(_record_count("pgs_catalog", {"results": [1, 2]}), 2)


class PolicyInputTest(unittest.TestCase):
    """A-04: the policy evaluation authorises publication and was the optional argument."""

    def test_policy_is_required_by_the_cli(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_all_reports.py"),
             "--input", "x.json", "--output-dir", "out"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--policy", result.stderr)

    def test_the_help_no_longer_offers_a_working_directory_fallback(self):
        # The fallback silently applied `evaluation.json` from wherever the run started.
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_all_reports.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertNotIn("evaluation.json", result.stdout)


class SurvivingPlaceholderTest(unittest.TestCase):
    """A-04: `placeholders_resolved` was a literal nothing measured."""

    def test_a_surviving_token_is_detected(self):
        from reporting.engine import _surviving_placeholders

        found = _surviving_placeholders("texto [[CAMPO_A]] e [[CAMPO_B]] e [[CAMPO_A]]")
        self.assertEqual(found, ["[[CAMPO_A]]", "[[CAMPO_B]]"])

    def test_clean_text_reports_nothing(self):
        from reporting.engine import _surviving_placeholders

        self.assertEqual(_surviving_placeholders("NÃO DISPONÍVEL em toda parte"), [])

    def test_nao_disponivel_is_a_resolution_not_a_survival(self):
        # The audit proposed unifying `placeholders_resolved` with
        # `template_fields_complete`. They are different claims: completeness means no field
        # came back NÃO DISPONÍVEL, resolution means no raw token survived. Printing NÃO
        # DISPONÍVEL is this project's design, so unifying them would make every honest
        # report unpublishable — the opposite of what the audit wanted.
        from reporting.engine import _surviving_placeholders

        self.assertEqual(_surviving_placeholders("Campo: NÃO DISPONÍVEL"), [])

    def test_a_final_render_refuses_to_publish_a_surviving_token(self):
        from reporting.engine import ReportReleaseError, render_document
        from reporting.provenance import fixture_payload

        data = fixture_payload(
            case_id="CASE-PH", report_id="09",
            summary="resumo com [[TOKEN_ESQUECIDO]] dentro", basis="fixture",
        )
        with self.assertRaises(ReportReleaseError) as caught:
            render_document("09", data, mode="FINAL")
        self.assertIn("TOKEN_ESQUECIDO", str(caught.exception))

    def test_an_ordinary_final_render_still_publishes(self):
        from reporting.engine import render_document
        from reporting.provenance import fixture_payload

        data = fixture_payload(
            case_id="CASE-OK", report_id="09", summary="resumo limpo", basis="fixture"
        )
        self.assertIn("markdown", render_document("09", data, mode="FINAL"))


class CoordinateValidationTest(unittest.TestCase):
    """M-07 / A-05: the registry held no coordinates, so an rsID could not be checked.

    An rsID is a label. A file carrying the right label at the wrong position is annotated
    on another assembly, or its coordinate column was rebuilt by a tool nobody recorded —
    and either way the locus is not the one the registry means.
    """

    REGISTRY = ROOT / "config/partial_genome_annotation_targets.json"

    def _registry(self):
        return json.loads(self.REGISTRY.read_text(encoding="utf-8"))

    def _target(self, rsid: str):
        return next(t for t in self._registry()["targets"] if t["rsid"] == rsid)

    def test_every_target_declares_a_coordinate_status(self):
        for target in self._registry()["targets"]:
            with self.subTest(rsid=target["rsid"]):
                self.assertIn("coordinates", target)
                self.assertIn(target["coordinates"]["status"], {"VERIFICADO", "NÃO DISPONÍVEL"})

    def test_a_verified_coordinate_carries_both_builds_and_alleles(self):
        target = self._target("rs1799807")
        block = target["coordinates"]
        self.assertEqual(block["status"], "VERIFICADO")
        for build in ("GRCh37", "GRCh38"):
            with self.subTest(build=build):
                for key in ("chromosome", "position", "reference_allele", "alternate_allele"):
                    self.assertIn(key, block[build])
        # The two builds must not agree by accident: a lift-over moved this locus.
        self.assertNotEqual(block["GRCh37"]["position"], block["GRCh38"]["position"])

    def test_the_curation_block_names_its_source(self):
        curation = self._registry()["coordinate_curation"]
        self.assertIn("clinvar", curation["locator"].lower())
        self.assertEqual(curation["status"], "VERIFICADO")

    def test_a_locus_absent_from_clinvar_is_unavailable_not_invented(self):
        # rs4307059 has no ClinVar coordinate, which the audit independently observed. The
        # honest record is that there is nothing to compare against.
        block = self._target("rs4307059")["coordinates"]
        self.assertEqual(block["status"], "NÃO DISPONÍVEL")
        self.assertIn("ClinVar", block["reason"])

    def test_a_matching_coordinate_verifies(self):
        from array_pipeline.annotation import check_coordinate

        target = self._target("rs1799807")
        expected = target["coordinates"]["GRCh37"]
        status, basis = check_coordinate(
            {"chromosome": expected["chromosome"], "position": str(expected["position"])},
            target, "GRCh37",
        )
        self.assertEqual(status, "VERIFICADO")
        self.assertIn("confere", basis)

    def test_a_chr_prefix_is_not_treated_as_a_mismatch(self):
        from array_pipeline.annotation import check_coordinate

        target = self._target("rs1799807")
        expected = target["coordinates"]["GRCh37"]
        status, _ = check_coordinate(
            {"chromosome": f"chr{expected['chromosome']}", "position": str(expected["position"])},
            target, "GRCh37",
        )
        self.assertEqual(status, "VERIFICADO")

    def test_the_wrong_position_is_refused_and_both_coordinates_are_named(self):
        from array_pipeline.annotation import check_coordinate

        target = self._target("rs1799807")
        expected = target["coordinates"]["GRCh37"]
        status, basis = check_coordinate(
            {"chromosome": expected["chromosome"], "position": "12345"}, target, "GRCh37"
        )
        self.assertEqual(status, "NÃO DISPONÍVEL")
        self.assertIn("12,345", basis)
        self.assertIn("outra montagem", basis)

    def test_the_grch38_coordinate_of_a_grch37_case_is_a_mismatch(self):
        # The failure this catches in the field: a file on the other build whose rsIDs all
        # match and whose positions are all wrong.
        from array_pipeline.annotation import check_coordinate

        target = self._target("rs1799807")
        other = target["coordinates"]["GRCh38"]
        status, _ = check_coordinate(
            {"chromosome": other["chromosome"], "position": str(other["position"])},
            target, "GRCh37",
        )
        self.assertEqual(status, "NÃO DISPONÍVEL")

    def test_an_unverified_build_cannot_validate_a_coordinate(self):
        from array_pipeline.annotation import check_coordinate

        target = self._target("rs1799807")
        status, basis = check_coordinate({"chromosome": "3", "position": "165548529"}, target, None)
        self.assertEqual(status, "NÃO DISPONÍVEL")
        self.assertIn("build", basis)

    def test_a_locus_without_a_canonical_coordinate_is_unavailable_not_mismatched(self):
        # Nothing to disagree with is not disagreement.
        from array_pipeline.annotation import check_coordinate

        status, basis = check_coordinate(
            {"chromosome": "1", "position": "100"}, self._target("rs4307059"), "GRCh37"
        )
        self.assertEqual(status, "NÃO DISPONÍVEL")
        self.assertIn("não traz coordenada canônica", basis)


class PhaseDeclarationTest(unittest.TestCase):
    """M-07: `_canonical_gt` sorts the alleles, and nothing said the result was unphased."""

    def test_every_observation_declares_unphased_and_keeps_the_original(self):
        import gzip

        from array_pipeline.annotation import extract_target_observations

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "a.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
                fh.write("RSID,CHROMOSOME,POSITION,RESULT\n")
                fh.write("rs1799807,3,165548529,TC\n")
            observations = extract_target_observations(path, {"rs1799807"}, {"input": {}})

        observation = observations["rs1799807"][0]
        self.assertEqual(observation["phase_status"], "UNPHASED")
        self.assertIn("fase", observation["phase_basis"])
        # The canonical form is a derivation, not a replacement: both survive.
        self.assertEqual(observation["genotype_as_reported"], "TC")
        self.assertEqual(observation["genotype"], "CT")


if __name__ == "__main__":
    unittest.main()
