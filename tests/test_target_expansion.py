"""Fifty thousand targets is fifty thousand chances to admit one that was never sourced.

The expansion turns a hand-curated registry of twenty-nine loci into one derived from bulk
releases, which removes the human who used to check each entry. Every filter that replaced
that person is pinned here with a negative control — a row that must be rejected — so a
passing test proves the filter works rather than proving the fixture was easy.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.targets import load_target_manifest, read_manifest_bytes


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


EXPAND = _load("expand_clinvar_targets")
MERGE = _load("merge_target_manifests")
TRAITS = _load("build_trait_targets")

COLUMNS = [
    "#AlleleID", "Type", "Name", "GeneID", "GeneSymbol", "HGNC_ID", "ClinicalSignificance",
    "ClinSigSimple", "LastEvaluated", "RS# (dbSNP)", "nsv/esv (dbVar)", "RCVaccession",
    "PhenotypeIDS", "PhenotypeList", "Origin", "OriginSimple", "Assembly",
    "ChromosomeAccession", "Chromosome", "Start", "Stop", "ReferenceAllele", "AlternateAllele",
    "Cytogenetic", "ReviewStatus", "NumberSubmitters", "Guidelines", "TestedInGTR", "OtherIDs",
    "SubmitterCategories", "VariationID", "PositionVCF", "ReferenceAlleleVCF",
    "AlternateAlleleVCF",
]

TWO_STAR = "criteria provided, multiple submitters, no conflicts"


def _row(**overrides):
    base = {
        "Type": "single nucleotide variant",
        "Name": "NM_000410.4(HFE):c.845G>A (p.Cys282Tyr)",
        "GeneSymbol": "HFE",
        "ClinicalSignificance": "Pathogenic",
        "RS# (dbSNP)": "1800562",
        "PhenotypeIDS": "MONDO:MONDO:0021001,MedGen:C3469186",
        "PhenotypeList": "Hemochromatosis type 1",
        "Assembly": "GRCh38",
        "ChromosomeAccession": "NC_000006.12",
        "Chromosome": "6",
        "ReviewStatus": TWO_STAR,
        "NumberSubmitters": "12",
        "VariationID": "9",
        "PositionVCF": "26092913",
        "ReferenceAlleleVCF": "G",
        "AlternateAlleleVCF": "A",
        "LastEvaluated": "Jan 1, 2026",
    }
    base.update(overrides)
    return "\t".join(str(base.get(column, "-")) for column in COLUMNS)


def _bulk(rows: list[str]) -> Path:
    directory = Path(tempfile.mkdtemp())
    path = directory / "variant_summary.txt.gz"
    body = "\t".join(COLUMNS) + "\n" + "\n".join(rows) + "\n"
    path.write_bytes(gzip.compress(body.encode("utf-8")))
    return path


def _scan(rows: list[str]):
    return EXPAND.scan_clinvar(_bulk(rows))


class ClinVarFilterTest(unittest.TestCase):
    def test_a_qualifying_row_is_kept(self):
        by_rsid, stats, counts = _scan([_row()])
        self.assertEqual(stats["kept"], 1)
        self.assertIn("rs1800562", by_rsid)
        self.assertEqual(counts["HFE"]["pathogenic_any"], 1)

    def test_each_filter_rejects_on_its_own(self):
        # Negative controls, one per filter. Each row differs from the accepted one in
        # exactly one field, so a filter that stopped working would show up here alone.
        for label, row in (
            ("GRCh37", _row(Assembly="GRCh37")),
            ("indel", _row(Type="Indel")),
            ("one submitter", _row(ReviewStatus="criteria provided, single submitter")),
            ("no assertion", _row(ReviewStatus="no assertion criteria provided")),
            ("no rsid", _row(**{"RS# (dbSNP)": "-"})),
            ("multi-base alt", _row(AlternateAlleleVCF="AT")),
            ("non-ACGT", _row(AlternateAlleleVCF="N")),
        ):
            with self.subTest(filter=label):
                _by_rsid, stats, _counts = _scan([row])
                self.assertEqual(stats.get("kept", 0), 0)

    def test_conflicting_classifications_are_not_read_as_pathogenic(self):
        # The substring trap: this string contains "athogenic" and asserts the opposite.
        _by_rsid, stats, _counts = _scan(
            [_row(ClinicalSignificance="Conflicting classifications of pathogenicity")]
        )
        self.assertEqual(stats.get("kept", 0), 0)

    def test_benign_is_not_pathogenic(self):
        for classification in ("Benign", "Likely benign", "Uncertain significance"):
            with self.subTest(classification=classification):
                _b, stats, _c = _scan([_row(ClinicalSignificance=classification)])
                self.assertEqual(stats.get("kept", 0), 0)

    def test_a_trailing_qualifier_does_not_block_a_pathogenic_row(self):
        _by, stats, _c = _scan([_row(ClinicalSignificance="Pathogenic; risk factor")])
        self.assertEqual(stats["kept"], 1)

    def test_the_gene_denominator_counts_the_whole_catalogue_not_the_kept_rows(self):
        # An indel and a one-star variant belong in the denominator — they are part of the
        # gene's pathogenic catalogue even though this registry cannot represent them. A
        # denominator that counted only what was kept would make coverage look complete.
        _by, _stats, counts = _scan(
            [
                _row(),
                _row(Type="Indel", VariationID="10", **{"RS# (dbSNP)": "2"}),
                _row(ReviewStatus="criteria provided, single submitter", VariationID="11",
                     **{"RS# (dbSNP)": "3"}),
            ]
        )
        self.assertEqual(counts["HFE"]["pathogenic_any"], 3)
        self.assertEqual(counts["HFE"]["pathogenic_two_star"], 2)
        self.assertEqual(counts["HFE"]["pathogenic_two_star_snv_rsid"], 1)


class TargetShapeTest(unittest.TestCase):
    def test_one_alternate_yields_an_assessed_allele(self):
        by_rsid, _s, _c = _scan([_row()])
        targets, stats = EXPAND.build_targets(by_rsid)
        self.assertEqual(targets[0]["assessed_allele"], "A")
        self.assertEqual(stats["with_assessed_allele"], 1)

    def test_two_alternates_at_one_position_yield_none(self):
        # rs3918290 is the real case: C>T is DPYD*2A and C>G is a different pathogenic
        # variant at the same coordinate. Picking one would score the genotype against the
        # wrong base.
        by_rsid, _s, _c = _scan(
            [_row(), _row(AlternateAlleleVCF="T", VariationID="10")]
        )
        targets, stats = EXPAND.build_targets(by_rsid)
        self.assertNotIn("assessed_allele", targets[0])
        self.assertEqual(targets[0]["clinvar_alternate_alleles"], ["A", "T"])
        self.assertEqual(stats["multi_allelic"], 1)

    def test_one_rsid_at_two_coordinates_is_dropped(self):
        by_rsid, _s, _c = _scan([_row(), _row(PositionVCF="99999999", VariationID="10")])
        targets, stats = EXPAND.build_targets(by_rsid)
        self.assertEqual(targets, [])
        self.assertEqual(stats["ambiguous_position"], 1)

    def test_the_target_carries_the_coordinate_so_a_consumer_can_check_it(self):
        by_rsid, _s, _c = _scan([_row()])
        target = EXPAND.build_targets(by_rsid)[0][0]
        self.assertEqual(target["grch38"], {
            "chromosome": "6", "position": 26092913, "reference_accession": "NC_000006.12"
        })

    def test_conditions_keep_their_mondo_cross_reference(self):
        by_rsid, _s, _c = _scan([_row()])
        conditions = by_rsid["rs1800562"][0]["conditions"]
        self.assertEqual(conditions[0]["name"], "Hemochromatosis type 1")
        self.assertEqual(conditions[0]["xrefs"]["MONDO"], "MONDO:0021001")

    def test_misaligned_condition_columns_drop_the_ids_not_the_names(self):
        # Names and cross-references are positionally aligned; where they are not, a
        # condition matched to the wrong MONDO id is worse than one with no id.
        by_rsid, _s, _c = _scan(
            [_row(PhenotypeList="A|B|C", PhenotypeIDS="MONDO:MONDO:0000001")]
        )
        conditions = by_rsid["rs1800562"][0]["conditions"]
        self.assertEqual([c["name"] for c in conditions], ["A", "B", "C"])
        self.assertTrue(all(not c["xrefs"] for c in conditions))

    def test_placeholder_conditions_are_dropped(self):
        by_rsid, _s, _c = _scan([_row(PhenotypeList="not provided|not specified")])
        self.assertEqual(by_rsid["rs1800562"][0]["conditions"], [])


class GzipManifestTest(unittest.TestCase):
    def test_a_gzipped_manifest_loads(self):
        manifest = {
            "schema": "genoma-partial-genome-targets-v1",
            "id": "T", "version": "1",
            "targets": [{"rsid": "rs1", "scope": "CLINICO", "label": "x",
                         "queries": {"clinvar": {"term": "rs1"}}}],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "t.json.gz"
            path.write_bytes(gzip.compress(json.dumps(manifest).encode("utf-8")))
            self.assertEqual(load_target_manifest(path)["id"], "T")

    def test_compression_is_detected_by_content_not_by_extension(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "no-extension.json"
            path.write_bytes(gzip.compress(b'{"a": 1}'))
            self.assertEqual(json.loads(read_manifest_bytes(path)), {"a": 1})


def _manifest(identifier: str, targets: list[dict]) -> dict:
    return {
        "schema": "genoma-partial-genome-targets-v1",
        "id": identifier,
        "version": "1",
        "targets": targets,
    }


def _write(payload: dict, directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class MergeTest(unittest.TestCase):
    def _merge(self, *manifests):
        with tempfile.TemporaryDirectory() as td:
            paths = [
                _write(m, Path(td), f"m{i}.json") for i, m in enumerate(manifests)
            ]
            return MERGE.merge(paths)

    def test_agreeing_registries_merge_and_keep_the_allele(self):
        target = {"rsid": "rs1", "scope": "CLINICO", "label": "a",
                  "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "A"}
        result = self._merge(_manifest("A", [target]), _manifest("B", [dict(target)]))
        self.assertEqual(result["totals"]["targets"], 1)
        self.assertEqual(result["targets"][0]["assessed_allele"], "A")
        self.assertEqual(result["totals"]["assessed_allele_conflicts"], 0)

    def test_a_disagreement_removes_the_allele_rather_than_choosing(self):
        result = self._merge(
            _manifest("A", [{"rsid": "rs1", "scope": "CLINICO", "label": "a",
                             "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "T"}]),
            _manifest("B", [{"rsid": "rs1", "scope": "CLINICO", "label": "b",
                             "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "G"}]),
        )
        merged = result["targets"][0]
        self.assertNotIn("assessed_allele", merged)
        self.assertEqual(merged["assessed_allele_conflict"], ["G", "T"])
        self.assertEqual(result["totals"]["assessed_allele_conflicts"], 1)

    def test_silence_is_not_disagreement(self):
        result = self._merge(
            _manifest("A", [{"rsid": "rs1", "scope": "CLINICO", "label": "a",
                             "queries": {"clinvar": {"term": "rs1"}}}]),
            _manifest("B", [{"rsid": "rs1", "scope": "CLINICO", "label": "b",
                             "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "G"}]),
        )
        self.assertEqual(result["targets"][0]["assessed_allele"], "G")

    def test_a_locus_keeps_the_stronger_scope(self):
        result = self._merge(
            _manifest("A", [{"rsid": "rs1", "scope": "CURIOSIDADE", "label": "a",
                             "queries": {"clinvar": {"term": "rs1"}}}]),
            _manifest("B", [{"rsid": "rs1", "scope": "CLINICO", "label": "b",
                             "queries": {"clinvar": {"term": "rs1"}}}]),
        )
        self.assertEqual(result["targets"][0]["scope"], "CLINICO")

    def test_a_conflict_is_not_undone_by_a_third_registry(self):
        result = self._merge(
            _manifest("A", [{"rsid": "rs1", "scope": "CLINICO", "label": "a",
                             "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "T"}]),
            _manifest("B", [{"rsid": "rs1", "scope": "CLINICO", "label": "b",
                             "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "G"}]),
            _manifest("C", [{"rsid": "rs1", "scope": "CLINICO", "label": "c",
                             "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "T"}]),
        )
        self.assertNotIn("assessed_allele", result["targets"][0])


class TraitScopeTest(unittest.TestCase):
    def test_a_declared_term_with_no_significant_association_is_a_hard_error(self):
        # The guard that caught two real terms: sweet-taste perception, whose best p-value in
        # the catalogue is 4e-07, and lactose intolerance, which has no mapped association at
        # all. A scope that silently covered neither would claim more than it delivers.
        header = "\t".join(
            ["SNPS", "P-VALUE", "MAPPED_TRAIT", "MAPPED_TRAIT_URI", "CHR_ID", "CHR_POS",
             "STRONGEST SNP-RISK ALLELE", "RISK ALLELE FREQUENCY", "OR or BETA",
             "95% CI (TEXT)", "STUDY ACCESSION", "PUBMEDID", "MAPPED_GENE",
             "REPORTED GENE(S)", "INITIAL SAMPLE SIZE"]
        )
        row = "\t".join(
            ["rs1", "4e-07", "sweet", "http://x/GO_0050916", "1", "100", "rs1-A", "0.2",
             "1.1", "[1-2]", "GCST1", "1", "GENE", "GENE", "1000 European"]
        )
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            associations = directory / "a.tsv"
            associations.write_text(header + "\n" + row + "\n", encoding="utf-8")
            ancestry = directory / "anc.tsv"
            ancestry.write_text(
                "STUDY ACCESSION\tBROAD ANCESTRAL CATEGORY\tSTAGE\tNUMBER OF INDIVIDUALS\t"
                "INITIAL SAMPLE DESCRIPTION\nGCST1\tEuropean\tinitial\t1000\tdesc\n",
                encoding="utf-8",
            )
            scopes = directory / "scopes.json"
            scopes.write_text(json.dumps({
                "schema": "genoma-trait-scopes-v1",
                "version": "t",
                "significance_threshold": 5e-8,
                "max_loci_per_term": 5,
                "scopes": {"CURIOSIDADE": {"terms": [{"id": "GO_0050916", "label": "sweet"}]}},
            }), encoding="utf-8")
            with self.assertRaises(TRAITS.TraitScopeError) as raised:
                TRAITS.build(associations, ancestry, scopes)
        self.assertIn("GO_0050916", str(raised.exception))

    def test_the_risk_allele_parser_refuses_what_it_cannot_read(self):
        self.assertEqual(TRAITS._risk_allele("rs738409-G", "rs738409"), "G")
        for unreadable in ("rs738409-?", "rs738409", "", "rs738409-NR"):
            self.assertIsNone(TRAITS._risk_allele(unreadable, "rs738409"), unreadable)


class ShippedRegistryTest(unittest.TestCase):
    """The registries committed to the repository must load and be internally consistent."""

    def _registries(self):
        return [
            p
            for p in (
                ROOT / "config/partial_genome_annotation_targets.json",
                ROOT / "config/pgx_panel_targets.json",
                ROOT / "config/targets_clinvar_plp.json.gz",
                ROOT / "config/targets_gwas_traits.json",
                ROOT / "config/targets_merged_panel.json.gz",
            )
            if p.is_file()
        ]

    def test_registries_were_found(self):
        self.assertGreaterEqual(len(self._registries()), 4)

    def test_every_shipped_registry_loads(self):
        for path in self._registries():
            with self.subTest(registry=path.name):
                manifest = load_target_manifest(path)
                self.assertTrue(manifest["targets"])

    def test_every_shipped_registry_cites_a_source(self):
        for path in self._registries():
            with self.subTest(registry=path.name):
                manifest = load_target_manifest(path)
                self.assertTrue(
                    manifest.get("sources") or manifest.get("description") or manifest.get("merged_from"),
                    f"{path.name} declares no provenance",
                )

    def test_a_target_with_an_assessed_allele_names_where_it_came_from(self):
        for path in self._registries():
            manifest = load_target_manifest(path)
            with self.subTest(registry=path.name):
                unsourced = [
                    t["rsid"]
                    for t in manifest["targets"]
                    if t.get("assessed_allele") and not t.get("assessed_allele_source")
                ]
                self.assertEqual(unsourced[:5], [], f"{path.name}: assessed allele with no source")


if __name__ == "__main__":
    unittest.main()
