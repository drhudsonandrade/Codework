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
    evidence = lambda asserted: json.dumps({
        "status": "VERIFICADO", "decision": "SATISFIED", "asserted_value": asserted,
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
                       build_evidence=evidence("GRCh37"), strand_evidence=evidence("forward"))
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
            evidence = lambda asserted: json.dumps({
                "status": "VERIFICADO", "decision": "SATISFIED", "asserted_value": asserted,
                "justification": "fixture", "evidence_refs": ["x"],
                "trace": {"attestation_id": "a", "created_at": "2026-08-18T00:00:00Z",
                          "actor_type": "SOFTWARE", "actor_id": "t", "method": "m", "run_id": "r",
                          "input_sha256": [sha], "output_sha256": [], "tool_versions": {"t": "1"}},
            })
            qc = inspect_array(array, case_id="SYN-PGX", build="GRCh37", strand="forward",
                               build_evidence=evidence("GRCh37"), strand_evidence=evidence("forward"))
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


class CpicRegistryTest(unittest.TestCase):
    """The shipped registry must be CPIC's data, not a hand-written table."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "config/pgx_allele_definitions.json"
        cls.registry = load_pgx_registry(path)

    def test_the_registry_cites_cpic_and_its_retrieval_date(self):
        self.assertIn("CPIC", self.registry["source"])
        self.assertIn("api.cpicpgx.org", self.registry["source"])
        self.assertIn("build_pgx_registry.py", self.registry["source"])
        self.assertRegex(self.registry["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T")

    def test_complete_panel_is_scoped_to_cpic_not_claimed_absolute(self):
        """An allele CPIC has not catalogued stays indistinguishable from reference."""
        self.assertIn("não biologicamente exaustivo", self.registry["scope_note"])
        for gene, spec in self.registry["genes"].items():
            with self.subTest(gene=gene):
                if spec.get("complete_panel"):
                    self.assertEqual(spec["complete_panel_scope"], "CPIC")

    def test_every_defining_position_carries_an_rsid_and_a_single_base(self):
        for gene, spec in self.registry["genes"].items():
            for allele, definition in spec["alleles"].items():
                for position in definition["defining"]:
                    with self.subTest(allele=allele):
                        self.assertRegex(position["rsid"], r"^rs\d+$")
                        self.assertIn(position["allele"], set("ACGT"))

    def test_a_gene_cpic_does_not_define_records_why(self):
        """BCHE: CPIC publishes no allele table and PharmVar needs credentials.

        The variants themselves now come from ClinVar with cited accessions, so the gap is
        narrower than it was — but it is still a gap, and the reason must survive. ClinVar
        catalogues variants, not haplotypes, so no diplotype follows from it.
        """
        bche = self.registry["genes"]["BCHE"]
        self.assertTrue(bche["alleles"], "the ClinVar fallback should supply the variants")
        self.assertFalse(bche["complete_panel"])
        self.assertIn("ClinVar", bche["complete_panel_scope"])
        self.assertIn("CPIC não publica", bche["definitions_unavailable"])
        self.assertIn("PharmVar", bche["definitions_unavailable"])
        self.assertEqual(bche["phenotype_map"], {})

    def test_structural_alleles_are_excluded_and_listed(self):
        """An array cannot genotype a duplication; excluding it silently would hide that."""
        excluded = {a for s in self.registry["genes"].values() for a in s["structural_alleles_excluded"]}
        self.assertTrue(excluded, "CPIC marks some alleles structural; none were recorded")
        for gene, spec in self.registry["genes"].items():
            for allele in spec["structural_alleles_excluded"]:
                with self.subTest(allele=allele):
                    self.assertNotIn(allele, spec["alleles"])

    def test_allele_labels_are_not_blindly_concatenated(self):
        """VKORC1's alleles are named descriptively; `VKORC1rs9923231 variant (T)` is wrong."""
        for gene, spec in self.registry["genes"].items():
            for allele in spec["alleles"]:
                with self.subTest(allele=allele):
                    remainder = allele[len(gene):]
                    self.assertTrue(
                        remainder.startswith("*") or remainder.startswith(" "),
                        f"{allele!r} concatenates the symbol onto a descriptive name",
                    )

    def test_a_gene_with_no_phenotype_table_does_not_get_a_phenotype(self):
        """CPIC has no metabolizer phenotype for VKORC1; none must be invented."""
        from array_pipeline.pharmacogenomics import _phenotype_for

        spec = self.registry["genes"]["VKORC1"]
        self.assertEqual(spec["phenotype_map"], {})
        result = _phenotype_for("VKORC1", spec, {"status": "INFERIDO", "value": "A/B"})
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIn("não fornece tabela", result["reason"])

    def test_a_diplotype_absent_from_the_table_yields_no_nearest_match(self):
        from array_pipeline.pharmacogenomics import _phenotype_for

        spec = self.registry["genes"]["CYP2C19"]
        self.assertTrue(spec["phenotype_map"])
        result = _phenotype_for(
            "CYP2C19", spec, {"status": "INFERIDO", "value": "CYP2C19*999/CYP2C19*998"}
        )
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIn("não consta", result["reason"])

    def test_a_listed_diplotype_is_translated_and_marked_inferido(self):
        from array_pipeline.pharmacogenomics import _phenotype_for

        spec = self.registry["genes"]["CYP2C19"]
        key = next(k for k in spec["phenotype_map"] if k.count("/") == 1)
        value = "/".join(f"CYP2C19{part}" for part in key.split("/"))
        result = _phenotype_for("CYP2C19", spec, {"status": "INFERIDO", "value": value})
        self.assertEqual(result["status"], "INFERIDO")
        self.assertEqual(result["value"], spec["phenotype_map"][key]["phenotype"])
        self.assertIn("CPIC", result["source"])
        # Never EXECUTADO: the diplotype behind it is inferred from genotypes.
        self.assertNotEqual(result["status"], "EXECUTADO")


class PanelMatrixTest(unittest.TestCase):
    """Coverage must be measured against the array, not against this pipeline's target list.

    Joining CPIC's defining positions to a twenty-nine-locus matrix made every other position
    NÃO TESTADO by construction, so the passport's coverage figure described the target
    registry rather than the chip. The panel matrix is what turns that back into a
    measurement, and its absence has to be visible rather than equivalent to full coverage.
    """

    def test_a_passport_without_a_panel_matrix_says_so_on_its_face(self):
        with tempfile.TemporaryDirectory() as td:
            _matrix, passport, _root = _artifacts(Path(td), CLEAN_ROWS, registry=REGISTRY)
        self.assertEqual(passport["panel_matrix"]["status"], "NÃO DISPONÍVEL")
        self.assertIn("NÃO TESTADO por construção", passport["panel_matrix"]["reason"])

    def test_a_panel_matrix_from_a_different_input_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            matrix_path, _passport, _root = _artifacts(root, CLEAN_ROWS, registry=REGISTRY)

            other = root / "other"
            other.mkdir()
            other_matrix, _p, _r = _artifacts(other, CLEAN_ROWS.replace("rs6025,1,169519049,GG", "rs6025,1,169519049,AG"))
            with self.assertRaises(ValueError) as raised:
                build_pharmacogenomic_passport(
                    matrix_path,
                    root / "targets.json",
                    pgx_registry_path=root / "pgx-registry.json",
                    panel_matrix_path=other_matrix,
                )
        self.assertIn("different inputs", str(raised.exception))

    def test_a_panel_matrix_raises_the_measured_defining_position_coverage(self):
        # rs1234567 defines an allele the curated target list never mentions. Without the
        # panel matrix it can only read as NÃO TESTADO; with it, the array is actually asked.
        registry = json.loads(json.dumps(REGISTRY))
        registry["genes"]["CYP2C19"]["alleles"]["CYP2C19*17"] = {
            "defining": [{"rsid": "rs1234567", "allele": "T", "position": 1, "chromosome": "chr10"}],
            "cpic_clinical_function": "Increased function",
            "cpic_frequency": {"European": 0.21},
        }
        panel_targets = {
            "schema": "genoma-partial-genome-targets-v1",
            "id": "TEST-PANEL",
            "version": "test.1",
            "targets": [
                {"rsid": "rs1234567", "gene": "CYP2C19", "scope": "CLINICO", "label": "CYP2C19*17",
                 "queries": {"cpic": {"path": "data/gene"}}, "assessed_allele": "T"},
            ],
        }
        rows = CLEAN_ROWS + "rs1234567,10,94761900,CC,consensus,CC,CC,GM\n"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            matrix_path, without, _root = _artifacts(root, rows, registry=registry)
            panel_path = root / "panel-targets.json"
            panel_path.write_text(json.dumps(panel_targets), encoding="utf-8")
            panel_matrix = build_completeness_matrix(
                root / "array.csv.gz", root / "qc.json", panel_path
            )
            panel_matrix_path = write_matrix(panel_matrix, root / "panel-matrix.json")
            with_panel = build_pharmacogenomic_passport(
                matrix_path,
                root / "targets.json",
                pgx_registry_path=root / "pgx-registry.json",
                panel_matrix_path=panel_matrix_path,
            )

        before = without["totals"]["defining_positions_interpretable"]
        after = with_panel["totals"]["defining_positions_interpretable"]
        self.assertEqual(after, before + 1)
        self.assertEqual(with_panel["panel_matrix"]["target_manifest"]["id"], "TEST-PANEL")
        # And the newly-read position actually changes what could be excluded.
        cyp = next(g for g in with_panel["genes"] if g["gene"] == "CYP2C19")
        self.assertIn("CYP2C19*17", cyp["discrimination"]["discriminable_alleles"])


class NoCallIsNotHomozygousTest(unittest.TestCase):
    """A position that was not read cannot stand as evidence of the reference haplotype.

    Zygosity was read as `len(set(genotype)) > 1` over any locus with a truthy genotype. The
    no-call string "--" has a set of size one, so an uninterrogated position counted as
    homozygous. That went wrong twice: it removed the position from the heterozygous count,
    so a gene with two het positions and one no-call could drop to one and stop raising phase
    ambiguity, and it let an unknown genotype pass as the reference base — the closed-world
    claim a diplotype must never make silently. A gene whose panel positions were all
    no-calls returned `INFERIDO *1/*1` alongside the words "todas as posições definidoras
    interpretáveis".
    """

    SPEC = {
        "complete_panel": True,
        "reference_allele": "*1",
        "alleles": {
            "*2": {"cpic_clinical_function": "No function", "defining": [{"rsid": "rs1", "allele": "T"}]}
        },
    }

    def _diplotype(self, loci):
        from array_pipeline.pharmacogenomics import _diplotype_for

        return _diplotype_for("TEST", self.SPEC, loci, [], gaps=[])

    def _locus(self, rsid, genotype, interpretable):
        return {"rsid": rsid, "genotype": genotype, "interpretable": interpretable}

    def test_a_gene_of_nothing_but_no_calls_yields_no_diplotype(self):
        result = self._diplotype([
            self._locus("rs2", "--", False), self._locus("rs3", None, False),
        ])
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIsNone(result["value"])

    def test_the_refusal_names_the_uncalled_positions(self):
        result = self._diplotype([self._locus("rs9", "--", False)])
        self.assertIn("rs9", " ".join(result["reasons"]))
        self.assertIn("mundo fechado", " ".join(result["reasons"]))

    def test_one_no_call_beside_called_positions_still_withholds(self):
        result = self._diplotype([
            self._locus("rs1", "AG", True), self._locus("rs2", "--", False),
        ])
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")

    def test_fully_called_positions_still_produce_a_diplotype(self):
        # Negative control: the refusal must not have made every diplotype impossible.
        result = self._diplotype([self._locus("rs1", "AA", True)])
        self.assertEqual(result["status"], "INFERIDO")
        self.assertEqual(result["value"], "*1/*1")

    def test_a_no_call_no_longer_masks_phase_ambiguity(self):
        # Two heterozygous positions must raise phase ambiguity whether or not an uncalled
        # position sits between them.
        result = self._diplotype([
            self._locus("rs1", "AG", True), self._locus("rs4", "CT", True),
        ])
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertIn("fase não resolvida", " ".join(result["reasons"]))

    def test_the_call_predicate_separates_reads_from_placeholders(self):
        from array_pipeline.pharmacogenomics import _is_called_genotype

        for value in ("AG", "AA", "ID", "cc"):
            with self.subTest(called=value):
                self.assertTrue(_is_called_genotype(value))
        for value in ("--", "-", "", None, "NA", "N/A", "NULL", ".", "00", "A-", "??"):
            with self.subTest(uncalled=value):
                self.assertFalse(_is_called_genotype(value))


if __name__ == "__main__":
    unittest.main()
