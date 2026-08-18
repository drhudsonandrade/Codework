"""A pharmacogenomic report must not turn a partial panel into a diplotype.

The conventional output of a PGx panel is a diplotype and a metabolizer phenotype. A
consumer SNP array can almost never support either: `*1` is an assertion about every
defining position including the ones the chip never carried, and a diplotype needs phase
that array genotyping does not provide. These tests pin each refusal.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.completeness import build_completeness_matrix, write_matrix
from array_pipeline.pharmacogenomics import (
    PgxRegistryError,
    build_pharmacogenomic_passport,
    load_pgx_registry,
    write_passport,
)
from array_pipeline.qc import inspect_array

HEADER = "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"

TARGETS = {
    "schema": "genoma-partial-genome-targets-v1",
    "id": "TEST-PGX",
    "version": "test.1",
    "targets": [
        # Pharmacogenomic: routed to a PGx knowledge base.
        {"rsid": "rs1799807", "gene": "BCHE", "scope": "CLINICO", "label": "BCHE",
         "queries": {"clinpgx": {"path": "data/gene"}, "clinvar": {"term": "rs1799807"}}},
        {"rsid": "rs1803274", "gene": "BCHE", "scope": "CLINICO", "label": "BCHE",
         "queries": {"clinpgx": {"path": "data/gene"}, "clinvar": {"term": "rs1803274"}}},
        {"rsid": "rs4244285", "gene": "CYP2C19", "scope": "CLINICO", "label": "CYP2C19*2",
         "queries": {"clinpgx": {"path": "data/gene"}, "clinvar": {"term": "rs4244285"}}},
        {"rsid": "rs4986893", "gene": "CYP2C19", "scope": "CLINICO", "label": "CYP2C19*3",
         "queries": {"clinpgx": {"path": "data/gene"}, "clinvar": {"term": "rs4986893"}}},
        # Not pharmacogenomic: ClinVar only, must stay out of the passport.
        {"rsid": "rs6025", "gene": "F5", "scope": "CLINICO", "label": "F5",
         "queries": {"clinvar": {"term": "rs6025"}}},
    ],
}

REGISTRY = {
    "schema": "genoma-pgx-registry-v1",
    "id": "TEST-PGX-DEFS",
    "version": "test.1",
    "source": "Fixture de teste; não é uma fonte clínica real.",
    "genes": {
        "BCHE": {
            "anesthesia_relevant": True,
            "anesthesia_note": "Atividade de butirilcolinesterase requer dosagem enzimática.",
            "alleles": {"BCHE*2": {"defining": [{"rsid": "rs1799807", "allele": "T"}]}},
        },
        "CYP2C19": {
            "alleles": {
                "CYP2C19*2": {"defining": [{"rsid": "rs4244285", "allele": "A"}]},
                "CYP2C19*3": {"defining": [{"rsid": "rs4986893", "allele": "A"}]},
            },
        },
    },
}


def _artifacts(root: Path, rows: str, *, registry: dict | None = None):
    array = root / "array.csv.gz"
    with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
        fh.write(HEADER)
        fh.write(rows)
    sha = hashlib.sha256(array.read_bytes()).hexdigest()
    evidence = json.dumps({
        "status": "VERIFICADO", "decision": "SATISFIED",
        "justification": "Fixture determinístico declara build e fita.",
        "evidence_refs": ["synthetic-pgx-fixture"],
        "trace": {
            "attestation_id": "pgx-fixture", "created_at": "2026-08-18T00:00:00Z",
            "actor_type": "SOFTWARE", "actor_id": "tests.test_pharmacogenomics",
            "method": "deterministic fixture", "run_id": "unit-test",
            "input_sha256": [sha], "output_sha256": [], "tool_versions": {"test": "1"},
        },
    })
    qc = inspect_array(array, case_id="SYN-PGX", build="GRCh37", strand="forward",
                       build_evidence=evidence, strand_evidence=evidence)
    (root / "qc.json").write_text(json.dumps(qc), encoding="utf-8")
    targets_path = root / "targets.json"
    targets_path.write_text(json.dumps(TARGETS), encoding="utf-8")
    matrix = build_completeness_matrix(array, root / "qc.json", targets_path)
    matrix_path = write_matrix(matrix, root / "completeness.json")

    registry_path = None
    if registry is not None:
        registry_path = root / "pgx-registry.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

    passport = build_pharmacogenomic_passport(
        matrix_path, targets_path, pgx_registry_path=registry_path
    )
    return matrix_path, passport, root


#: Every PGx locus called cleanly, homozygous reference at the star-allele positions.
CLEAN_ROWS = (
    "rs1799807,3,165548529,CC,consensus,CC,CC,GM\n"
    "rs1803274,3,165551201,CC,consensus,CC,CC,GM\n"
    "rs4244285,10,96541616,GG,consensus,GG,GG,GM\n"
    "rs4986893,10,96540410,GG,consensus,GG,GG,GM\n"
    "rs6025,1,169519049,GG,consensus,GG,GG,GM\n"
)


class PassportScopeTest(unittest.TestCase):
    def test_only_pharmacogenomic_targets_enter_the_passport(self):
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), CLEAN_ROWS)
        genes = {g["gene"] for g in passport["genes"]}
        self.assertEqual(genes, {"BCHE", "CYP2C19"})
        # F5 is ClinVar-only; it is a clinical target but not a pharmacogenomic one.
        self.assertNotIn("F5", genes)

    def test_the_passport_cannot_outrank_the_matrix_that_fed_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = root / "array.csv.gz"
            with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
                fh.write(HEADER)
                fh.write(CLEAN_ROWS)
            qc = inspect_array(array, case_id="SYN-PGX")  # no build/strand evidence
            (root / "qc.json").write_text(json.dumps(qc), encoding="utf-8")
            targets_path = root / "targets.json"
            targets_path.write_text(json.dumps(TARGETS), encoding="utf-8")
            matrix = build_completeness_matrix(array, root / "qc.json", targets_path)
            matrix_path = write_matrix(matrix, root / "completeness.json")
            passport = build_pharmacogenomic_passport(matrix_path, targets_path)
        self.assertEqual(passport["operational_status"], "NÃO DISPONÍVEL")


class DiplotypeRefusalTest(unittest.TestCase):
    """The headline refusals: no diplotype, no phenotype, no invented reference call."""

    def test_no_diplotype_without_a_curated_allele_registry(self):
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), CLEAN_ROWS)
        for record in passport["genes"]:
            with self.subTest(gene=record["gene"]):
                self.assertEqual(record["diplotype"]["status"], "NÃO DISPONÍVEL")
                self.assertTrue(
                    any("registro curado" in r for r in record["diplotype"]["reasons"]),
                    record["diplotype"]["reasons"],
                )

    def test_no_diplotype_when_the_registry_does_not_declare_a_complete_panel(self):
        """Absence of the tested alleles is not *1: untested alleles stay indistinguishable."""
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), CLEAN_ROWS, registry=REGISTRY)
        cyp = next(g for g in passport["genes"] if g["gene"] == "CYP2C19")
        self.assertEqual(cyp["diplotype"]["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("painel completo" in r for r in cyp["diplotype"]["reasons"]))
        # The defining alleles were interrogated and not detected — that much IS reportable.
        statuses = {f["allele"]: f["status"] for f in cyp["allele_findings"]}
        self.assertEqual(statuses, {"CYP2C19*2": "NÃO DETECTADO", "CYP2C19*3": "NÃO DETECTADO"})

    def test_an_untested_defining_position_makes_the_allele_unavailable_not_absent(self):
        rows = CLEAN_ROWS.replace("rs4986893,10,96540410,GG,consensus,GG,GG,GM\n", "")
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), rows, registry=REGISTRY)
        cyp = next(g for g in passport["genes"] if g["gene"] == "CYP2C19")
        statuses = {f["allele"]: f["status"] for f in cyp["allele_findings"]}
        self.assertEqual(statuses["CYP2C19*3"], "NÃO DISPONÍVEL")
        self.assertEqual(statuses["CYP2C19*2"], "NÃO DETECTADO")

    def test_a_no_call_defining_position_makes_the_allele_unavailable(self):
        rows = CLEAN_ROWS.replace(
            "rs4986893,10,96540410,GG,consensus,GG,GG,GM\n",
            "rs4986893,10,96540410,--,consensus,--,--,GM\n",
        )
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), rows, registry=REGISTRY)
        cyp = next(g for g in passport["genes"] if g["gene"] == "CYP2C19")
        statuses = {f["allele"]: f["status"] for f in cyp["allele_findings"]}
        self.assertEqual(statuses["CYP2C19*3"], "NÃO DISPONÍVEL")

    def test_unresolved_phase_blocks_a_diplotype_even_on_a_complete_panel(self):
        registry = json.loads(json.dumps(REGISTRY))
        registry["genes"]["CYP2C19"]["complete_panel"] = True
        rows = CLEAN_ROWS.replace(
            "rs4244285,10,96541616,GG,consensus,GG,GG,GM\n"
            "rs4986893,10,96540410,GG,consensus,GG,GG,GM\n",
            "rs4244285,10,96541616,AG,consensus,AG,AG,GM\n"
            "rs4986893,10,96540410,AG,consensus,AG,AG,GM\n",
        )
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), rows, registry=registry)
        cyp = next(g for g in passport["genes"] if g["gene"] == "CYP2C19")
        self.assertEqual(cyp["diplotype"]["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("fase não resolvida" in r for r in cyp["diplotype"]["reasons"]))

    def test_a_complete_panel_must_also_name_the_reference_haplotype(self):
        """A heterozygous carrier needs a second element, and this module will not coin *1."""
        registry = json.loads(json.dumps(REGISTRY))
        registry["genes"]["CYP2C19"]["complete_panel"] = True
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), CLEAN_ROWS, registry=registry)
        cyp = next(g for g in passport["genes"] if g["gene"] == "CYP2C19")
        self.assertEqual(cyp["diplotype"]["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("reference_allele" in r for r in cyp["diplotype"]["reasons"]))

    def _complete_registry(self):
        registry = json.loads(json.dumps(REGISTRY))
        registry["genes"]["CYP2C19"]["complete_panel"] = True
        registry["genes"]["CYP2C19"]["reference_allele"] = "CYP2C19*1"
        return registry

    def test_a_diplotype_on_a_complete_unambiguous_panel_is_inferido_never_executado(self):
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(
                Path(td), CLEAN_ROWS, registry=self._complete_registry()
            )
        cyp = next(g for g in passport["genes"] if g["gene"] == "CYP2C19")
        self.assertEqual(cyp["diplotype"]["status"], "INFERIDO")
        self.assertEqual(cyp["diplotype"]["value"], "CYP2C19*1/CYP2C19*1")

    def test_a_heterozygous_carrier_gets_two_elements_not_one(self):
        """The diplotype used to be "/".join(detected), which emits a single allele."""
        rows = CLEAN_ROWS.replace(
            "rs4244285,10,96541616,GG,consensus,GG,GG,GM\n",
            "rs4244285,10,96541616,AG,consensus,AG,AG,GM\n",
        )
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), rows, registry=self._complete_registry())
        cyp = next(g for g in passport["genes"] if g["gene"] == "CYP2C19")
        self.assertEqual(cyp["diplotype"]["status"], "INFERIDO")
        value = cyp["diplotype"]["value"]
        self.assertEqual(len(value.split("/")), 2, value)
        self.assertEqual(value, "CYP2C19*1/CYP2C19*2")
        finding = next(f for f in cyp["allele_findings"] if f["allele"] == "CYP2C19*2")
        self.assertEqual(finding["zygosity"], "HETEROZIGOTO")

    def test_a_homozygous_carrier_gets_the_allele_on_both_chromosomes(self):
        rows = CLEAN_ROWS.replace(
            "rs4244285,10,96541616,GG,consensus,GG,GG,GM\n",
            "rs4244285,10,96541616,AA,consensus,AA,AA,GM\n",
        )
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), rows, registry=self._complete_registry())
        cyp = next(g for g in passport["genes"] if g["gene"] == "CYP2C19")
        self.assertEqual(cyp["diplotype"]["value"], "CYP2C19*2/CYP2C19*2")
        finding = next(f for f in cyp["allele_findings"] if f["allele"] == "CYP2C19*2")
        self.assertEqual(finding["zygosity"], "HOMOZIGOTO")

    def test_a_compound_genotype_needs_phase_and_is_withheld(self):
        """Two defined alleles homozygous at different loci cannot be assigned to strands."""
        rows = CLEAN_ROWS.replace(
            "rs4244285,10,96541616,GG,consensus,GG,GG,GM\n"
            "rs4986893,10,96540410,GG,consensus,GG,GG,GM\n",
            "rs4244285,10,96541616,AA,consensus,AA,AA,GM\n"
            "rs4986893,10,96540410,AA,consensus,AA,AA,GM\n",
        )
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), rows, registry=self._complete_registry())
        cyp = next(g for g in passport["genes"] if g["gene"] == "CYP2C19")
        self.assertEqual(cyp["diplotype"]["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("composto" in r for r in cyp["diplotype"]["reasons"]))

    def test_the_phenotype_count_is_computed_not_asserted(self):
        """Hardcoding 0 stays true only until something emits a phenotype."""
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(
                Path(td), CLEAN_ROWS, registry=self._complete_registry()
            )
        expected = sum(
            1 for g in passport["genes"] if g["phenotype"]["status"] != "NÃO DISPONÍVEL"
        )
        self.assertEqual(passport["totals"]["genes_with_phenotype"], expected)
        self.assertEqual(
            passport["totals"]["genes_with_diplotype"],
            sum(1 for g in passport["genes"] if g["diplotype"]["status"] != "NÃO DISPONÍVEL"),
        )

    def test_a_phenotype_is_never_emitted(self):
        registry = json.loads(json.dumps(REGISTRY))
        registry["genes"]["CYP2C19"]["complete_panel"] = True
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), CLEAN_ROWS, registry=registry)
        for record in passport["genes"]:
            with self.subTest(gene=record["gene"]):
                self.assertEqual(record["phenotype"]["status"], "NÃO DISPONÍVEL")
                self.assertIsNone(record["phenotype"]["value"])
        self.assertEqual(passport["totals"]["genes_with_phenotype"], 0)

    def test_a_structurally_unresolved_gene_is_never_diplotyped(self):
        """CYP2D6's clinical variation is structural; no SNP set makes it callable."""
        targets = json.loads(json.dumps(TARGETS))
        targets["targets"].append({
            "rsid": "rs3892097", "gene": "CYP2D6", "scope": "CLINICO", "label": "CYP2D6*4",
            "queries": {"clinpgx": {"path": "data/gene"}},
        })
        registry = json.loads(json.dumps(REGISTRY))
        registry["genes"]["CYP2D6"] = {
            "complete_panel": True,
            "alleles": {"CYP2D6*4": {"defining": [{"rsid": "rs3892097", "allele": "A"}]}},
        }
        rows = CLEAN_ROWS + "rs3892097,22,42128945,GG,consensus,GG,GG,GM\n"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = root / "array.csv.gz"
            with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
                fh.write(HEADER)
                fh.write(rows)
            sha = hashlib.sha256(array.read_bytes()).hexdigest()
            evidence = json.dumps({
                "status": "VERIFICADO", "decision": "SATISFIED", "justification": "fixture",
                "evidence_refs": ["x"],
                "trace": {"attestation_id": "a", "created_at": "2026-08-18T00:00:00Z",
                          "actor_type": "SOFTWARE", "actor_id": "t", "method": "m", "run_id": "r",
                          "input_sha256": [sha], "output_sha256": [], "tool_versions": {"t": "1"}},
            })
            qc = inspect_array(array, case_id="SYN-PGX", build="GRCh37", strand="forward",
                               build_evidence=evidence, strand_evidence=evidence)
            (root / "qc.json").write_text(json.dumps(qc), encoding="utf-8")
            targets_path = root / "targets.json"
            targets_path.write_text(json.dumps(targets), encoding="utf-8")
            registry_path = root / "reg.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            matrix_path = write_matrix(
                build_completeness_matrix(array, root / "qc.json", targets_path),
                root / "completeness.json",
            )
            passport = build_pharmacogenomic_passport(
                matrix_path, targets_path, pgx_registry_path=registry_path
            )
        cyp2d6 = next(g for g in passport["genes"] if g["gene"] == "CYP2D6")
        self.assertEqual(cyp2d6["diplotype"]["status"], "NÃO DISPONÍVEL")
        self.assertTrue(any("estrutural" in r for r in cyp2d6["diplotype"]["reasons"]))


class RegistryValidationTest(unittest.TestCase):
    def test_a_registry_without_a_cited_source_is_refused(self):
        bad = json.loads(json.dumps(REGISTRY))
        del bad["source"]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "r.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(PgxRegistryError) as ctx:
                load_pgx_registry(path)
        self.assertIn("source", str(ctx.exception))

    def test_an_allele_without_defining_positions_is_refused(self):
        bad = json.loads(json.dumps(REGISTRY))
        bad["genes"]["BCHE"]["alleles"]["BCHE*2"]["defining"] = []
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "r.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(PgxRegistryError):
                load_pgx_registry(path)

    def test_a_wrong_schema_is_refused(self):
        bad = json.loads(json.dumps(REGISTRY))
        bad["schema"] = "something-else"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "r.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(PgxRegistryError):
                load_pgx_registry(path)


class AnesthesiaCardTest(unittest.TestCase):
    def test_the_card_is_unavailable_without_a_declared_relevance_list(self):
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), CLEAN_ROWS)
        card = passport["anesthesia_card"]
        self.assertEqual(card["status"], "NÃO DISPONÍVEL")
        self.assertEqual(card["observations"], [])
        self.assertIn("não foi declarada", card["reason"])

    def test_the_card_reports_observations_and_never_clears_anaesthesia(self):
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), CLEAN_ROWS, registry=REGISTRY)
        card = passport["anesthesia_card"]
        self.assertEqual(card["genes"], ["BCHE"])
        self.assertEqual({o["rsid"] for o in card["observations"]}, {"rs1799807", "rs1803274"})
        self.assertIn("não libera nem contraindica", card["clearance_policy"])
        self.assertIn("ausência de achado", card["clearance_policy"])

    def test_the_card_is_unavailable_when_no_relevant_locus_is_interpretable(self):
        rows = (
            "rs1799807,3,165548529,--,consensus,--,--,GM\n"
            "rs1803274,3,165551201,--,consensus,--,--,GM\n"
            "rs4244285,10,96541616,GG,consensus,GG,GG,GM\n"
            "rs4986893,10,96540410,GG,consensus,GG,GG,GM\n"
            "rs6025,1,169519049,GG,consensus,GG,GG,GM\n"
        )
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), rows, registry=REGISTRY)
        self.assertEqual(passport["anesthesia_card"]["status"], "NÃO DISPONÍVEL")


class ReportIntegrationTest(unittest.TestCase):
    def _payload(self, root: Path, rows: str = CLEAN_ROWS, registry: dict | None = REGISTRY):
        from scripts.build_pharmacogenomic_report import build_payload

        matrix_path, passport, _ = _artifacts(root, rows, registry=registry)
        passport_path = write_passport(passport, root / "passport.json")
        return build_payload(passport_path, matrix_path), passport

    def test_the_compiled_payload_passes_the_provenance_gate(self):
        from reporting.provenance import provenance_blockers

        with tempfile.TemporaryDirectory() as td:
            payload, _ = self._payload(Path(td))
        self.assertEqual(provenance_blockers(payload), [])

    def test_the_report_renders_and_states_the_refusals_on_the_page(self):
        from reporting.engine import render_document

        with tempfile.TemporaryDirectory() as td:
            payload, _ = self._payload(Path(td))
            markdown = render_document("06", payload, mode="FINAL")["markdown"]

        self.assertIn("Fenótipos emitidos: 0", markdown)
        self.assertIn("PGX-BCHE", markdown)
        self.assertIn("PGX-CYP2C19", markdown)
        self.assertIn("não libera nem contraindica", markdown)
        self.assertIn("diplótipo NÃO DISPONÍVEL", markdown)

    def test_a_hand_written_phenotype_is_refused_at_render_time(self):
        from reporting.engine import ReportReleaseError, render_document

        with tempfile.TemporaryDirectory() as td:
            payload, _ = self._payload(Path(td))
            payload["sections"]["Resumo farmacogenômico"] = (
                "CYP2C19 *1/*1 — metabolizador normal. Clopidogrel sem restrição."
            )
            with self.assertRaises(ReportReleaseError) as ctx:
                render_document("06", payload, mode="FINAL")
        self.assertIn("provenance:mismatch", str(ctx.exception))

    def test_the_printer_withholds_a_genotype_from_a_non_interpretable_locus(self):
        """Defence in depth: the printer decides too, not only the upstream matrix."""
        from scripts.build_pharmacogenomic_report import _anesthesia_text, _gene_layer

        genes = [{
            "gene": "HFE", "interrogated_loci": 0, "total_loci": 1,
            "loci": [{
                "rsid": "rs1800562", "genotype": "AG",
                "classification": "NÃO REPORTÁVEL", "interpretable": False, "evidence": [],
            }],
            "diplotype": {"status": "NÃO DISPONÍVEL"},
            "phenotype": {"status": "NÃO DISPONÍVEL"},
        }]
        layer = _gene_layer(genes)
        self.assertIn("rs1800562=NÃO REPORTÁVEL", layer)
        self.assertNotIn("rs1800562=AG", layer)

        card = {
            "status": "VERIFICADO", "clearance_policy": "P.",
            "observations": [{
                "gene": "HFE", "rsid": "rs1800562", "genotype": "AG",
                "classification": "NÃO REPORTÁVEL", "interpretable": False,
            }],
        }
        text = _anesthesia_text(card)
        self.assertIn("rs1800562=NÃO REPORTÁVEL", text)
        self.assertNotIn("AG", text)

    def test_the_sections_match_the_catalogue_for_report_06(self):
        from reporting.engine import load_catalog
        from scripts.build_pharmacogenomic_report import SECTIONS

        self.assertEqual(tuple(load_catalog()["06"]["sections"]), SECTIONS)


if __name__ == "__main__":
    unittest.main()
