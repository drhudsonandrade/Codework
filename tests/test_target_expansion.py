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

    def test_unknown_scope_is_a_domain_error(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            associations = directory / "a.tsv"
            ancestry = directory / "ancestry.tsv"
            scopes = directory / "scopes.json"
            associations.write_text("", encoding="utf-8")
            ancestry.write_text("", encoding="utf-8")
            scopes.write_text(
                json.dumps(
                    {
                        "schema": "genoma-trait-scopes-v1",
                        "scopes": {"DESCONHECIDO": {"terms": []}},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TRAITS.TraitScopeError, "DESCONHECIDO"):
                TRAITS.build(associations, ancestry, scopes)

    TRAIT_HEADER = "\t".join(
        ["SNPS", "P-VALUE", "MAPPED_TRAIT", "MAPPED_TRAIT_URI", "CHR_ID", "CHR_POS",
         "STRONGEST SNP-RISK ALLELE", "RISK ALLELE FREQUENCY", "OR or BETA",
         "95% CI (TEXT)", "STUDY ACCESSION", "PUBMEDID", "MAPPED_GENE",
         "REPORTED GENE(S)", "INITIAL SAMPLE SIZE"]
    )

    def _scan(self, mapped_trait, mapped_uri):
        row = "\t".join(
            ["rs4988235", "1e-20", mapped_trait, mapped_uri, "2", "136608646",
             "rs4988235-T", "0.3", "1.5", "[1-2]", "GCST1", "1", "MCM6", "MCM6",
             "1000 European"]
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "a.tsv"
            path.write_text(self.TRAIT_HEADER + "\n" + row + "\n", encoding="utf-8")
            return TRAITS.scan(
                path, {"EFO_0801753": ("PREDISPOSICAO", "persistência da lactase")}, 5e-8
            )

    def test_a_comma_inside_a_trait_label_does_not_misname_the_locus(self):
        # MAPPED_TRAIT and MAPPED_TRAIT_URI are comma-separated and positionally aligned, so a
        # label containing a comma breaks the alignment. Zipping them anyway printed another
        # trait's name on this locus. Where the lengths disagree the declared label is used.
        by_rsid, stats = self._scan(
            "lactase persistence, adult type", "http://x/EFO_0801753"
        )
        self.assertEqual(stats["misaligned_trait_columns"], 1)
        self.assertEqual(by_rsid["rs4988235"][0]["term_label"], "persistência da lactase")

    def test_a_misaligned_row_still_matches_every_term_it_declares(self):
        # The other half of the failure: with fewer labels than URIs, zip truncates and the
        # trailing terms are never checked against the declared scope, so their targets
        # silently vanish.
        by_rsid, stats = self._scan(
            "one label only", "http://x/EFO_9999999,http://x/EFO_0801753"
        )
        self.assertEqual(stats["misaligned_trait_columns"], 1)
        self.assertIn("rs4988235", by_rsid)
        self.assertEqual(by_rsid["rs4988235"][0]["term_id"], "EFO_0801753")

    def test_aligned_columns_keep_the_catalogue_label(self):
        by_rsid, stats = self._scan("lactase persistence", "http://x/EFO_0801753")
        self.assertEqual(stats.get("misaligned_trait_columns", 0), 0)
        self.assertEqual(by_rsid["rs4988235"][0]["term_label"], "lactase persistence")

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

        # The assessed-allele curator writes the versioned partial-genome registry. Its
        # success branch must clear any older refusal metadata and explicitly attest the
        # allele it just wrote; unrelated legacy registries have separate producers.
        path = ROOT / "config/partial_genome_annotation_targets.json"
        manifest = load_target_manifest(path)
        contradictory = [
            t["rsid"]
            for t in manifest["targets"]
            if t.get("assessed_allele")
            and (
                t.get("assessed_allele_status") != "VERIFICADO"
                or t.get("assessed_allele_reason")
            )
        ]
        self.assertEqual(
            contradictory[:5],
            [],
            f"{path.name}: assessed allele lacks a clean VERIFICADO attestation",
        )


class ReviewStarTierTest(unittest.TestCase):
    """Admitting one-star variants only helps if every one of them stays labelled as such."""

    def test_the_ladder_scores_the_statuses_clinvar_actually_writes(self):
        for status, expected in (
            ("practice guideline", 4),
            ("reviewed by expert panel", 3),
            ("criteria provided, multiple submitters, no conflicts", 2),
            ("criteria provided, single submitter", 1),
            ("no assertion criteria provided", 0),
        ):
            with self.subTest(status=status):
                self.assertEqual(EXPAND.review_stars(status), expected)

    def test_an_unrecognised_status_scores_zero_rather_than_passing(self):
        # The fail-open shape this guards against: a status NCBI adds later defaulting to a
        # number that clears the threshold would admit it silently.
        for status in ("", None, "reviewed by a friend", "criteria provided, whatever"):
            with self.subTest(status=status):
                self.assertEqual(EXPAND.review_stars(status), 0)
                self.assertLess(EXPAND.review_stars(status), 2)

    def test_the_default_threshold_still_rejects_a_single_submitter(self):
        _by, stats, _counts = _scan([_row(ReviewStatus="criteria provided, single submitter")])
        self.assertEqual(stats.get("kept", 0), 0)
        self.assertEqual(stats["below_review_threshold"], 1)

    def test_lowering_the_threshold_admits_it_and_records_one_star(self):
        by_rsid, stats, counts = EXPAND.scan_clinvar(
            _bulk([_row(ReviewStatus="criteria provided, single submitter")]),
            min_review_stars=1,
        )
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(by_rsid["rs1800562"][0]["review_stars"], 1)
        # Admitted into the registry, still absent from the two-star denominator.
        self.assertEqual(counts["HFE"]["pathogenic_at_threshold_snv_rsid"], 1)
        self.assertEqual(counts["HFE"]["pathogenic_two_star_snv_rsid"], 0)

    def test_a_one_star_target_carries_its_star_level(self):
        by_rsid, _stats, _counts = EXPAND.scan_clinvar(
            _bulk([_row(ReviewStatus="criteria provided, single submitter")]),
            min_review_stars=1,
        )
        targets, _tstats = EXPAND.build_targets(by_rsid)
        self.assertEqual(targets[0]["clinvar_review_stars"], 1)
        self.assertIn("1★", targets[0]["assessed_allele_source"])

    def test_a_locus_asserted_at_two_levels_reports_both_ends(self):
        by_rsid, _stats, _counts = EXPAND.scan_clinvar(
            _bulk(
                [
                    _row(ReviewStatus="criteria provided, single submitter", VariationID="9"),
                    _row(ReviewStatus="reviewed by expert panel", VariationID="10"),
                ]
            ),
            min_review_stars=1,
        )
        targets, _tstats = EXPAND.build_targets(by_rsid)
        self.assertEqual(targets[0]["clinvar_review_stars"], 3)
        self.assertEqual(targets[0]["clinvar_review_stars_min"], 1)


def _panelapp(**genes):
    return {gene: record for gene, record in genes.items()}


class PanelAppRegistryTest(unittest.TestCase):
    """PanelApp is a third registry, not a third way of saying the same thing."""

    GREEN = {
        "established": True,
        "established_by": ["Genomics England PanelApp"],
        "green_panel_count": 3,
        "modes_of_inheritance": ["AR"],
        "phenotypes": ["Hemochromatosis"],
        "publications": ["10000001"],
    }
    AMBER_ONLY = {
        "established": False,
        "established_by": [],
        "green_panel_count": 0,
        "modes_of_inheritance": [],
    }

    def test_a_green_gene_establishes_and_says_which_registry_did(self):
        block = EXPAND.gene_validity("HFE", {}, {}, _panelapp(HFE=self.GREEN))
        self.assertEqual(block["established_by"], ["PanelApp"])
        self.assertTrue(block["established"])
        self.assertEqual(block["modes_of_inheritance"], ["AR"])

    def test_an_amber_only_gene_does_not_establish(self):
        # The failure this guards against: reading amber as evidence would report a gene the
        # curators explicitly declined to endorse.
        block = EXPAND.gene_validity("HFE", {}, {}, _panelapp(HFE=self.AMBER_ONLY))
        self.assertEqual(block["established_by"], [])
        self.assertFalse(block["panelapp"]["established"])
        self.assertEqual(block["panelapp"]["status"], "NÃO DISPONÍVEL")

    def test_a_gene_absent_from_panelapp_says_so_rather_than_failing_open(self):
        block = EXPAND.gene_validity("HFE", {}, {}, _panelapp(CFTR=self.GREEN))
        self.assertFalse(block["panelapp"]["established"])
        self.assertIn("não aparece como gene verde", block["panelapp"]["reason"])

    def test_no_panelapp_file_is_reported_as_missing_input_not_as_a_negative(self):
        block = EXPAND.gene_validity("HFE", {}, {}, None)
        self.assertIn("não fornecida", block["panelapp"]["reason"])

    def test_the_gencc_overlap_is_flagged_rather_than_counted_twice(self):
        gencc = {
            "HFE": [
                {
                    "disease": "hemochromatosis type 1",
                    "disease_curie": "MONDO:0021001",
                    "mode_of_inheritance": "AR",
                    "mode_of_inheritance_reported": "Autosomal recessive",
                    "classification": "Definitive",
                    "submitter": submitter,
                }
                for submitter in ("Ambry", "Labcorp")
            ]
        }
        block = EXPAND.gene_validity("HFE", {}, gencc, _panelapp(HFE=self.GREEN))
        self.assertEqual(block["established_by"], ["GenCC", "PanelApp"])
        self.assertTrue(
            block["panelapp_overlaps_gencc"],
            "GenCC aggregates the PanelApp submissions; two names here is one body of curation",
        )

    def test_a_panelapp_mode_with_no_disease_anchor_is_listed_as_such(self):
        block = EXPAND.gene_validity("HFE", {}, {}, _panelapp(HFE=self.GREEN))
        self.assertEqual(block["modes_without_disease_anchor"], ["AR"])

    def test_the_curation_schema_is_checked_before_it_is_trusted(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "panelapp.json"
        path.write_text(json.dumps({"schema": "something-else", "genes": {}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            EXPAND.read_panelapp(path)

    def test_a_missing_file_is_an_error_not_an_empty_registry(self):
        with self.assertRaises(FileNotFoundError):
            EXPAND.read_panelapp(Path(tempfile.mkdtemp()) / "absent.json.gz")


DOSAGE_HEADER = (
    "#Gene Symbol\tGene ID\tcytoBand\tGenomic Location\tHaploinsufficiency Score\t"
    "Haploinsufficiency Description\tHaploinsufficiency PMID1\tHaploinsufficiency PMID2\t"
    "Haploinsufficiency PMID3\tHaploinsufficiency PMID4\tHaploinsufficiency PMID5\t"
    "Haploinsufficiency PMID6\tTriplosensitivity Score\tTriplosensitivity Description\t"
    "Triplosensitivity PMID1\tTriplosensitivity PMID2\tTriplosensitivity PMID3\t"
    "Triplosensitivity PMID4\tTriplosensitivity PMID5\tTriplosensitivity PMID6\t"
    "Date Last Evaluated\tHaploinsufficiency Disease ID\tTriplosensitivity Disease ID"
)


def _dosage_file(
    rows: list[tuple[str, str, str]],
    *,
    cytoband: str = "1q1",
    location: str = "chr1:1-2",
) -> Path:
    """Rows of (gene, haploinsufficiency score, triplosensitivity score)."""
    path = Path(tempfile.mkdtemp()) / "dosage.tsv"
    lines = ["#ClinGen Gene Curation Results", "#19 Aug,2026", DOSAGE_HEADER]
    for gene, haplo, triplo in rows:
        cells = [gene, "1", cytoband, location, haplo, "desc"] + [""] * 6
        cells += [triplo, "desc"] + [""] * 6 + ["2026-01-01", "MONDO:0000001", ""]
        lines.append("\t".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class ClinGenDosageTest(unittest.TestCase):
    """ClinGen's dosage scores are labels, not a ranking — 30 is not more than 3."""

    def test_a_haploinsufficiency_score_of_three_establishes_and_reads_dominant(self):
        table = EXPAND.read_clingen_dosage(_dosage_file([("HFE", "3", "0")]))
        self.assertTrue(table["HFE"]["established"])
        self.assertEqual(table["HFE"]["modes_of_inheritance"], ["AD"])
        block = EXPAND.gene_validity("HFE", {}, {}, {}, table)
        self.assertEqual(block["established_by"], ["ClinGen Dosage"])

    def test_score_thirty_records_recessive_inheritance_without_establishing(self):
        # The trap: 30 sorts above 3 as a number and reads as "even more evidence". It is not
        # a score at all — it is the curators writing "this gene's phenotype is recessive"
        # instead of scoring dosage, and treating it as establishment would report hundreds
        # of genes ClinGen never asserted a dosage mechanism for.
        table = EXPAND.read_clingen_dosage(_dosage_file([("HFE", "30", "0")]))
        self.assertFalse(table["HFE"]["established"])
        self.assertEqual(table["HFE"]["modes_of_inheritance"], ["AR"])
        block = EXPAND.gene_validity("HFE", {}, {}, {}, table)
        self.assertEqual(block["established_by"], [])
        self.assertEqual(block["modes_of_inheritance"], ["AR"])

    def test_haploinsufficiency_on_x_is_x_linked_not_autosomal_dominant(self):
        table = EXPAND.read_clingen_dosage(
            _dosage_file(
                [("BTK", "3", "0")],
                cytoband="Xq22",
                location="chrX:100-200",
            )
        )
        self.assertEqual(table["BTK"]["modes_of_inheritance"], ["XL"])
        self.assertNotIn("AD", table["BTK"]["modes_of_inheritance"])

    def test_recessive_dosage_code_on_x_remains_x_linked(self):
        table = EXPAND.read_clingen_dosage(
            _dosage_file(
                [("BTK", "30", "0")],
                cytoband="Xq22",
                location="chrX:100-200",
            )
        )
        self.assertEqual(table["BTK"]["modes_of_inheritance"], ["XL"])
        self.assertNotIn("AR", table["BTK"]["modes_of_inheritance"])

    def test_score_forty_neither_establishes_nor_contributes_a_mode(self):
        table = EXPAND.read_clingen_dosage(_dosage_file([("HFE", "40", "0")]))
        self.assertFalse(table["HFE"]["established"])
        self.assertEqual(table["HFE"]["modes_of_inheritance"], [])

    def test_the_partial_scores_do_not_establish(self):
        for score in ("0", "1", "2"):
            with self.subTest(score=score):
                table = EXPAND.read_clingen_dosage(_dosage_file([("HFE", score, "0")]))
                self.assertFalse(table["HFE"]["established"])

    def test_triplosensitivity_alone_can_establish(self):
        table = EXPAND.read_clingen_dosage(_dosage_file([("HFE", "0", "3")]))
        self.assertTrue(table["HFE"]["established"])

    def test_a_gene_absent_from_the_list_says_so(self):
        table = EXPAND.read_clingen_dosage(_dosage_file([("CFTR", "3", "0")]))
        block = EXPAND.gene_validity("HFE", {}, {}, {}, table)
        self.assertIn("não consta", block["clingen_dosage"]["reason"])

    def test_a_file_with_no_recognisable_header_is_refused(self):
        path = Path(tempfile.mkdtemp()) / "broken.tsv"
        path.write_text("#comment only\nHFE\t1\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            EXPAND.read_clingen_dosage(path)


CONSTRAINT_COLUMNS = [
    "gene", "gene_id", "transcript", "canonical", "mane_select",
    "lof.pLI", "lof.oe", "lof.oe_ci.upper", "mis.z_score", "constraint_flags",
]


def _constraint_file(rows: list[dict[str, str]]) -> Path:
    path = Path(tempfile.mkdtemp()) / "constraint.tsv"
    lines = ["\t".join(CONSTRAINT_COLUMNS)]
    for row in rows:
        lines.append("\t".join(str(row.get(c, "")) for c in CONSTRAINT_COLUMNS))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class GnomadConstraintTest(unittest.TestCase):
    """Constraint is carried, displayed, and never allowed to establish anything."""

    def test_the_mane_select_transcript_wins_over_the_canonical_one(self):
        table = EXPAND.read_gnomad_constraint(
            _constraint_file(
                [
                    {"gene": "HFE", "gene_id": "ENSG1", "transcript": "ENST_CANON",
                     "canonical": "true", "mane_select": "false", "lof.pLI": "0.10"},
                    {"gene": "HFE", "gene_id": "ENSG1", "transcript": "ENST_MANE",
                     "canonical": "false", "mane_select": "true", "lof.pLI": "0.90"},
                ]
            )
        )
        self.assertEqual(table["HFE"]["transcript"], "ENST_MANE")
        self.assertEqual(table["HFE"]["transcript_basis"], "MANE Select")

    def test_the_ensembl_keyed_row_wins_the_tie(self):
        table = EXPAND.read_gnomad_constraint(
            _constraint_file(
                [
                    {"gene": "HFE", "gene_id": "3077", "transcript": "NM_000410.4",
                     "canonical": "true", "mane_select": "true", "lof.pLI": "0.5"},
                    {"gene": "HFE", "gene_id": "ENSG00000010704", "transcript": "ENST00000357618",
                     "canonical": "true", "mane_select": "true", "lof.pLI": "0.5"},
                ]
            )
        )
        self.assertEqual(table["HFE"]["transcript"], "ENST00000357618")

    def test_a_row_that_is_neither_mane_nor_canonical_is_skipped(self):
        table = EXPAND.read_gnomad_constraint(
            _constraint_file(
                [{"gene": "HFE", "gene_id": "ENSG1", "transcript": "ENST_ALT",
                  "canonical": "false", "mane_select": "false", "lof.pLI": "0.99"}]
            )
        )
        self.assertEqual(table, {})

    def test_an_unparseable_metric_becomes_absent_not_zero(self):
        # A pLI of NaN read as 0.0 would say "tolerant of loss of function" about a gene the
        # release declined to score, which is a claim rather than a gap.
        table = EXPAND.read_gnomad_constraint(
            _constraint_file(
                [{"gene": "HFE", "gene_id": "ENSG1", "transcript": "T", "canonical": "true",
                  "mane_select": "true", "lof.pLI": "NaN", "lof.oe_ci.upper": ""}]
            )
        )
        self.assertIsNone(table["HFE"]["pli"])
        self.assertIsNone(table["HFE"]["loeuf"])

    def test_constraint_never_appears_in_established_by(self):
        constraint = {
            "HFE": {
                "status": "VERIFICADO",
                "source": "fixture gnomAD",
                "pli": 1.0,
                "loeuf": 0.05,
            }
        }
        block = EXPAND.gene_validity_with_constraint(
            "HFE", {}, {}, {}, {}, constraint
        )
        self.assertEqual(block["established_by"], [])
        self.assertFalse(block["established"])
        self.assertEqual(block["gnomad_constraint"]["pli"], 1.0)
        self.assertEqual(block["gnomad_constraint"]["loeuf"], 0.05)


if __name__ == "__main__":
    unittest.main()
