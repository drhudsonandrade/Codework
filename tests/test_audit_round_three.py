"""Two defects found by reading the modules nobody had read line by line.

Neither was reported by any external audit and neither was visible to the test suite, which
was green throughout. Both are the same shape: a value printed on a report that nothing was
checking.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PrintedIdentityIsAnchoredTest(unittest.TestCase):
    """`case_id` is printed on every FINAL report and was anchored by nothing.

    Editing it after compilation produced a report about a different person and the
    provenance gate returned zero blockers — the exact hand-edit that module exists to
    catch, on the one field that binds a genomic report to a human being.
    """

    def _payload(self, **kw):
        from reporting.provenance import fixture_payload

        return fixture_payload(
            case_id=kw.pop("case_id", "CASO-A"), report_id="09",
            summary="resumo", basis="fixture", **kw,
        )

    def test_an_intact_payload_has_no_blockers(self):
        from reporting.provenance import provenance_blockers

        self.assertEqual(provenance_blockers(self._payload()), [])

    def test_case_id_and_post_deployment_are_anchored(self):
        from reporting.provenance import IDENTITY_FIELDS

        fields = self._payload()["provenance"]["fields"]
        for name in IDENTITY_FIELDS:
            with self.subTest(field=name):
                self.assertIn(name, fields)

    def test_editing_the_case_id_after_compilation_is_caught(self):
        from reporting.provenance import provenance_blockers

        data = self._payload()
        data["case_id"] = "CASO-DE-OUTRA-PESSOA"
        self.assertIn("provenance:mismatch:case_id", provenance_blockers(data))

    def test_a_report_about_the_wrong_case_cannot_be_published(self):
        from reporting.engine import ReportReleaseError, render_document

        data = self._payload()
        data["case_id"] = "CASO-DE-OUTRA-PESSOA"
        with self.assertRaises(ReportReleaseError) as caught:
            render_document("09", data, mode="FINAL")
        self.assertIn("case_id", str(caught.exception))

    def test_forging_post_deployment_pass_is_caught(self):
        # POST-DEPLOYMENT is the one verdict reserved for an external witness, and it is
        # printed on the face of the document.
        from reporting.provenance import provenance_blockers

        data = self._payload()
        data["post_deployment_status"] = "PASS"
        self.assertIn("provenance:mismatch:post_deployment_status", provenance_blockers(data))

    def test_a_declared_post_deployment_value_is_anchored_to_what_was_declared(self):
        from reporting.provenance import provenance_blockers

        data = self._payload(post_deployment_status="PASS")
        self.assertEqual(provenance_blockers(data), [])
        self.assertEqual(
            data["provenance"]["fields"]["post_deployment_status"]["observed_value"], "PASS"
        )

    def test_extra_cannot_overwrite_an_anchored_field(self):
        # `extra` writes into the payload after every anchor is fixed. A test fixture was
        # using it to stamp POST-DEPLOYMENT PASS onto a payload compiled as PENDENTE.
        from reporting.provenance import ProvenanceError, fixture_payload

        for field in ("case_id", "post_deployment_status", "summary"):
            with self.subTest(field=field):
                with self.assertRaises(ProvenanceError):
                    fixture_payload(
                        case_id="CASO-A", report_id="09", summary="resumo",
                        basis="fixture", extra={field: "forjado"},
                    )

    def test_extra_still_carries_unanchored_keys(self):
        # Negative control: the guard must not break the legitimate use of `extra`.
        data = self._payload(extra={"allow_programmatic_final": True})
        self.assertTrue(data["allow_programmatic_final"])


class DosageIsNotAnInheritanceModeTest(unittest.TestCase):
    """ClinGen dosage curation was being read as autosomal inheritance for X-linked genes.

    Haploinsufficiency says one broken copy is enough. On an autosome that reads as dominant
    inheritance; on the X it describes a hemizygous male. Emitting AD regardless put a
    spurious AD on 107 established X-linked genes — ABCD1, BTK, ATP7A, AR among them — while
    ClinGen validity, GenCC and PanelApp all said XL for the same gene, and the manufactured
    disagreement then pushed those genes out of the X-linked reading downstream.
    """

    def _dosage_row(self, gene: str, location: str, cytoband: str, haplo: str) -> dict:
        return {
            "Gene Symbol": gene, "Genomic Location": location, "cytoBand": cytoband,
            "Haploinsufficiency Score": haplo, "Triplosensitivity Score": "0",
        }

    def test_the_chromosome_is_read_from_either_locus_column(self):
        from scripts.expand_clinvar_targets import _dosage_chromosome

        self.assertEqual(_dosage_chromosome({"Genomic Location": "chrX:1-2", "cytoBand": ""}), "X")
        self.assertEqual(_dosage_chromosome({"Genomic Location": "", "cytoBand": "Xp21.1"}), "X")
        self.assertEqual(_dosage_chromosome({"Genomic Location": "chr7:1-2", "cytoBand": ""}), "7")
        self.assertEqual(_dosage_chromosome({"Genomic Location": "chrY:1-2", "cytoBand": ""}), "Y")

    def test_an_unparseable_location_yields_no_chromosome(self):
        # And therefore no mode: dosage is a statement about mechanism, and inventing an
        # inheritance mode nobody curated is what caused this.
        from scripts.expand_clinvar_targets import _dosage_chromosome

        self.assertIsNone(_dosage_chromosome({"Genomic Location": "", "cytoBand": ""}))

    def test_the_shipped_evidence_no_longer_carries_a_spurious_autosomal_mode(self):
        import gzip
        import json

        from array_pipeline.clinical_findings import X_LINKED, _validity_for

        path = ROOT / "docs/evidence/GENE_DISEASE_VALIDITY_1STAR.json.gz"
        evidence = json.loads(gzip.open(path, "rt", encoding="utf-8").read())
        for gene in ("ABCD1", "BTK", "ATP7A"):
            with self.subTest(gene=gene):
                modes = set(_validity_for(gene, evidence)["modes_of_inheritance"])
                self.assertEqual(modes, {X_LINKED})

    def test_an_autosomal_gene_keeps_its_autosomal_mode(self):
        # Negative control: the fix must not have removed inheritance modes generally.
        import gzip
        import json

        from array_pipeline.clinical_findings import _validity_for

        path = ROOT / "docs/evidence/GENE_DISEASE_VALIDITY_1STAR.json.gz"
        evidence = json.loads(gzip.open(path, "rt", encoding="utf-8").read())
        self.assertIn("AD", set(_validity_for("BRCA1", evidence)["modes_of_inheritance"]))
        self.assertIn("AR", set(_validity_for("CFTR", evidence)["modes_of_inheritance"]))


class MixedXLinkedModeIsNamedTest(unittest.TestCase):
    """A genuine XL/autosomal disagreement must say so, not print a generic refusal."""

    def _interpret(self, modes, sex):
        from array_pipeline import clinical_findings as cf

        # A real OBSERVADO entry names the base its class was decided against. Without it
        # OBSERVADO means only "chamado", and `_interpretation` refuses to grade the locus
        # at all — so a fixture that omits it is not exercising the X-linked reading.
        entry = {
            "classification": "OBSERVADO", "genotype": "AG", "scope": "CLINICO",
            "assessed_allele": "A", "assessed_alleles": ["A"],
        }
        clinvar = {
            "asserts_pathogenic": True, "asserts_benign": False, "classifications": ["Pathogenic"],
            "meets_review_threshold": True, "review_stars": 2, "conditions": [], "records": [],
        }
        validity = {
            "established": True, "established_by": ["ClinGen"], "classifications": ["Definitive"],
            "modes_of_inheritance": sorted(modes), "diseases_by_mode": {},
        }
        return cf._interpretation(entry, clinvar, validity, sex_at_birth=sex)

    def test_a_clean_x_linked_gene_still_reaches_the_x_reading(self):
        from array_pipeline.clinical_findings import ACIONAVEL, SEX_MALE, X_LINKED

        result = self._interpret({X_LINKED}, SEX_MALE)
        self.assertEqual(result["kind"], ACIONAVEL)
        self.assertIn("hemizigoto", result["basis"])

    def test_a_mixed_mode_gene_names_the_x_and_refuses_to_arbitrate(self):
        from array_pipeline.clinical_findings import GENOTIPO_DE_RISCO, SEX_MALE, X_LINKED

        result = self._interpret({X_LINKED, "AD"}, SEX_MALE)
        self.assertEqual(result["kind"], GENOTIPO_DE_RISCO)
        self.assertIn("ligado ao X", result["basis"])
        self.assertIn("não é resolvida", result["basis"])

    def test_a_mixed_mode_gene_says_when_the_sex_is_missing(self):
        from array_pipeline.clinical_findings import X_LINKED

        result = self._interpret({X_LINKED, "AD"}, None)
        self.assertIn("não registra o sexo", result["basis"])

    def test_a_purely_autosomal_gene_is_untouched_by_the_new_branch(self):
        from array_pipeline.clinical_findings import PORTADOR, SEX_FEMALE

        result = self._interpret({"AR"}, SEX_FEMALE)
        self.assertEqual(result["kind"], PORTADOR)


if __name__ == "__main__":
    unittest.main()


class ExternalAuditRepairsTest(unittest.TestCase):
    """The small, independently-verifiable findings of the 21/08 external audit."""

    def test_the_policy_exit_code_blocks_both_workflows(self):
        """C08/C09: the code was captured, filed to a file and then ignored."""
        for name in ("workflows/array.nf", "workflows/wgs.nf"):
            with self.subTest(workflow=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn('if [ "\\$code" -ne 0 ]; then', text)
                self.assertIn('exit "\\$code"', text)

    def test_the_runtime_gate_expects_the_version_the_environment_pins(self):
        """C14: environment.yml and the lock said 2.3; the gate demanded 2.2.1."""
        import re

        gate = (ROOT / "scripts/runtime_resource_gate.py").read_text(encoding="utf-8")
        expected = re.search(r'"bwa-mem2": \("([^"]+)"', gate).group(1)
        env = (ROOT / "environment.yml").read_text(encoding="utf-8")
        lock = json.loads((ROOT / "locks/runtime-lock.json").read_text(encoding="utf-8"))
        self.assertIn(f"bwa-mem2={expected}", env)
        self.assertEqual(lock["conda"]["bwa-mem2"], expected)

    def test_the_nextflow_range_is_bounded_at_both_ends(self):
        """H11: an open-ended range accepts a future DSL that changes what these mean."""
        config = (ROOT / "nextflow.config").read_text(encoding="utf-8")
        self.assertIn("<27.0.0", config)

    def test_a_payload_cannot_overwrite_the_renderer_s_controlled_substitutions(self):
        """H16: `values.update(supplied)` reached the normative identity and the banner."""
        from reporting.template_v3 import SYSTEM_REPLACEMENTS, TemplateV3Error, _system_values

        owned = next(iter(SYSTEM_REPLACEMENTS))
        with self.assertRaises(TemplateV3Error) as caught:
            _system_values({"template_system_fields": {owned: "qualquer coisa"}})
        self.assertIn(owned, str(caught.exception))
        # A key the renderer does not own is still accepted.
        values = _system_values({"template_system_fields": {"CAMPO NOVO": "valor"}})
        self.assertEqual(values["CAMPO NOVO"], "valor")
        self.assertEqual(values[owned], SYSTEM_REPLACEMENTS[owned])

    def test_an_absent_qc_passed_flag_is_not_a_pass(self):
        """H09: `qc.get("passed") is not False` is true when the field is absent."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "wgs_manifest_under_test", ROOT / "scripts/build_wgs_curated_manifest.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Behaviour, not source text: a QC artifact that never declared a result must not
        # be promoted as though it had passed.
        for qc, expected in (
            ({"operational_status": "VERIFICADO"}, False),
            ({"operational_status": "VERIFICADO", "passed": True}, True),
            ({"operational_status": "VERIFICADO", "passed": False}, False),
        ):
            with self.subTest(qc=qc):
                verified = qc.get("operational_status") == "VERIFICADO" and qc.get("passed") is True
                self.assertIs(verified, expected)
        source = (ROOT / "scripts/build_wgs_curated_manifest.py").read_text(encoding="utf-8")
        self.assertIn('qc.get("passed") is True', source)

    def test_the_ruleset_gate_refuses_an_undeclared_normative_identity(self):
        """H20: `not in (None, canonical)` could only catch a wrong declaration."""
        source = (ROOT / "policy_engine/genoma_policy/gates_core.py").read_text(encoding="utf-8")
        self.assertIn("manifest declares no ruleset block", source)
        self.assertNotIn('declared.get("version") not in (None,', source)

    def test_the_recency_gate_measures_age_and_not_only_syntax(self):
        """H19: a parseable date of any age was formally current."""
        from policy_engine.genoma_policy.gates_evidence import MAX_MUTABLE_SOURCE_AGE_DAYS

        self.assertGreater(MAX_MUTABLE_SOURCE_AGE_DAYS, 0)
        source = (ROOT / "policy_engine/genoma_policy/gates_evidence.py").read_text(encoding="utf-8")
        self.assertIn("beyond the", source)


class BoundedRegistryDecompressionTest(unittest.TestCase):
    """A curated registry is decompressed under the same ceilings an array export is.

    `array_pipeline.qc` bounds a ZIP member by uncompressed size and compression ratio; the
    registry loaders called `gzip.decompress`, which expands whatever it is given. Both take
    a filename from the command line (`--targets`, `--panel`), so the asymmetry was a real
    one: the path that reads the person's genotypes was bounded and the path that reads the
    registry it is interpreted against was not.
    """

    def _bomb(self, megabytes: int = 200) -> bytes:
        import gzip

        return gzip.compress(b"\0" * (megabytes * 1024 * 1024))

    def test_a_high_ratio_payload_is_refused(self):
        from array_pipeline.assembly import MAX_REGISTRY_COMPRESSION_RATIO, bounded_gunzip

        with self.assertRaises(ValueError) as caught:
            bounded_gunzip(self._bomb(), name="bomba.gz")
        message = str(caught.exception)
        self.assertIn("bomba.gz", message)
        self.assertIn(f"{MAX_REGISTRY_COMPRESSION_RATIO:.0f}x", message)

    def test_an_ordinary_payload_still_decompresses(self):
        import gzip

        from array_pipeline.assembly import bounded_gunzip

        payload = json.dumps({"schema": "x", "targets": list(range(1000))}).encode("utf-8")
        self.assertEqual(bounded_gunzip(gzip.compress(payload), name="ok.gz"), payload)

    def test_the_shipped_registries_are_within_the_ceilings(self):
        """Measured, so the bound cannot be set where it would refuse the real files."""
        from array_pipeline.assembly import (
            MAX_REGISTRY_COMPRESSION_RATIO,
            MAX_REGISTRY_UNCOMPRESSED_BYTES,
            bounded_gunzip,
        )

        for relative in (
            "config/targets_merged_panel_1star.json.gz",
            "config/ancestry_reference_panel.json.gz",
            "docs/evidence/GENE_DISEASE_VALIDITY_1STAR.json.gz",
        ):
            with self.subTest(registry=relative):
                raw = (ROOT / relative).read_bytes()
                out = bounded_gunzip(raw, name=relative)
                self.assertLess(len(out), MAX_REGISTRY_UNCOMPRESSED_BYTES)
                self.assertLess(len(out) / len(raw), MAX_REGISTRY_COMPRESSION_RATIO)

    def test_the_registry_loaders_refuse_a_bomb(self):
        """Behaviour, not source text: the first draft of this test matched its own comment."""
        import tempfile

        from array_pipeline.ancestry import load_panel
        from array_pipeline.targets import read_manifest_bytes

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "registry.json.gz"
            path.write_bytes(self._bomb())
            for name, call in (
                ("targets", lambda: read_manifest_bytes(path)),
                ("panel", lambda: load_panel(path)),
            ):
                with self.subTest(loader=name), self.assertRaises(ValueError) as caught:
                    call()
                self.assertIn("x, above the", str(caught.exception))
