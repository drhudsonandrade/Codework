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
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.targets import load_target_manifest, read_manifest_text


def _load(name: str):
    """Load one of the scripts/ builders as a module, since they are not importable packages."""
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    # Checked before `module_from_spec`, not after. `module_from_spec(None)` reads
    # `spec.loader` itself, so a `None` spec died there with an `AttributeError` naming
    # nothing useful and this guard never ran — it only ever caught the loaderless case.
    # Raised rather than asserted, because `assert` is stripped under `python -O`.
    if spec is None or spec.loader is None:
        raise ImportError(f"no loader for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXPAND = _load("expand_clinvar_targets")
MERGE = _load("merge_target_manifests")
TRAITS = _load("build_trait_targets")
CURATE = _load("curate_assessed_alleles")

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
    """One ClinVar row that passes every filter, with keyword overrides for the negative controls.

    The base row is the real HFE p.Cys282Tyr record. Building the negative controls by changing
    one field of a known-good row is what makes each of them a control: the only difference
    between accepted and rejected is the field under test.
    """
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
    """Write the given rows into a gzipped variant_summary with the real column header."""
    directory = Path(tempfile.mkdtemp())
    path = directory / "variant_summary.txt.gz"
    body = "\t".join(COLUMNS) + "\n" + "\n".join(rows) + "\n"
    path.write_bytes(gzip.compress(body.encode("utf-8")))
    return path


def _scan(rows: list[str]):
    """Scan a bulk file built from these rows and return the scanner's three outputs."""
    return EXPAND.scan_clinvar(_bulk(rows))


class ScriptLoaderTest(unittest.TestCase):
    """`_load` refuses a file it cannot import, with an error that names the file."""

    def test_a_spec_that_cannot_be_built_raises_import_error_not_attribute_error(self):
        """Raised in review: the guard sat below `module_from_spec`, which reads `spec.loader`.

        `spec_from_file_location` returns `None` for a path Python has no loader for — a
        directory, or a file with an unrecognised suffix. `module_from_spec(None)` then failed
        with `AttributeError: 'NoneType' object has no attribute 'loader'` before this
        module's own check could run, so the check only ever covered the loaderless spec and
        the diagnosis named nothing.
        """
        with patch.object(importlib.util, "spec_from_file_location", return_value=None):
            with self.assertRaises(ImportError) as caught:
                _load("expand_clinvar_targets")
        self.assertIn("expand_clinvar_targets.py", str(caught.exception))
        self.assertNotIsInstance(caught.exception, AttributeError)

    def test_a_spec_without_a_loader_is_also_refused(self):
        """The other half of the condition, which the original guard did reach."""
        with patch.object(
            importlib.util,
            "spec_from_file_location",
            return_value=SimpleNamespace(loader=None),
        ):
            with self.assertRaises(ImportError):
                _load("expand_clinvar_targets")


class ClinVarFilterTest(unittest.TestCase):
    """Which ClinVar rows the scanner accepts as targets, and which it refuses."""
    def test_a_qualifying_row_is_kept(self):
        """A row that passes every filter is kept, indexed by rsid, and counted for its gene."""
        by_rsid, stats, counts = _scan([_row()])
        self.assertEqual(stats["kept"], 1)
        self.assertIn("rs1800562", by_rsid)
        self.assertEqual(counts["HFE"]["pathogenic_any"], 1)

    def test_each_filter_rejects_on_its_own(self):
        """Every filter refuses on its own, with the others satisfied."""
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
        """'Conflicting classifications of pathogenicity' contains 'athogenic' and must still be refused."""
        # The substring trap: this string contains "athogenic" and asserts the opposite.
        _by_rsid, stats, _counts = _scan(
            [_row(ClinicalSignificance="Conflicting classifications of pathogenicity")]
        )
        self.assertEqual(stats.get("kept", 0), 0)

    def test_benign_is_not_pathogenic(self):
        """Benign, likely benign and uncertain significance are not pathogenic."""
        for classification in ("Benign", "Likely benign", "Uncertain significance"):
            with self.subTest(classification=classification):
                _b, stats, _c = _scan([_row(ClinicalSignificance=classification)])
                self.assertEqual(stats.get("kept", 0), 0)

    def test_a_trailing_qualifier_does_not_block_a_pathogenic_row(self):
        """A trailing qualifier ('Pathogenic; risk factor') does not disqualify a pathogenic row."""
        _by, stats, _c = _scan([_row(ClinicalSignificance="Pathogenic; risk factor")])
        self.assertEqual(stats["kept"], 1)

    def test_the_gene_denominator_counts_the_whole_catalogue_not_the_kept_rows(self):
        """The per-gene denominator counts the gene's whole pathogenic catalogue, not only the kept rows."""
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
    """What a built target asserts about the variant behind it."""
    def test_one_alternate_yields_an_assessed_allele(self):
        """A single alternate allele becomes the target's assessed allele."""
        by_rsid, _s, _c = _scan([_row()])
        targets, stats = EXPAND.build_targets(by_rsid)
        self.assertEqual(targets[0]["assessed_allele"], "A")
        self.assertEqual(stats["with_assessed_allele"], 1)

    def test_two_alternates_at_one_position_yield_none(self):
        """Two alternates at one coordinate yield no assessed allele, and both are recorded."""
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
        """An rsid the release places at two coordinates is dropped rather than guessed at."""
        by_rsid, _s, _c = _scan([_row(), _row(PositionVCF="99999999", VariationID="10")])
        targets, stats = EXPAND.build_targets(by_rsid)
        self.assertEqual(targets, [])
        self.assertEqual(stats["ambiguous_position"], 1)

    def test_the_target_carries_the_coordinate_so_a_consumer_can_check_it(self):
        """The target carries its own GRCh38 coordinate and accession, so a consumer can re-check it."""
        by_rsid, _s, _c = _scan([_row()])
        target = EXPAND.build_targets(by_rsid)[0][0]
        self.assertEqual(target["grch38"], {
            "chromosome": "6", "position": 26092913, "reference_accession": "NC_000006.12"
        })

    def test_conditions_keep_their_mondo_cross_reference(self):
        """A condition keeps the MONDO cross-reference the release gave it."""
        by_rsid, _s, _c = _scan([_row()])
        conditions = by_rsid["rs1800562"][0]["conditions"]
        self.assertEqual(conditions[0]["name"], "Hemochromatosis type 1")
        self.assertEqual(conditions[0]["xrefs"]["MONDO"], "MONDO:0021001")

    def test_misaligned_condition_columns_drop_the_ids_not_the_names(self):
        """When names and cross-references are misaligned, the ids are dropped and the names kept."""
        # Names and cross-references are positionally aligned; where they are not, a
        # condition matched to the wrong MONDO id is worse than one with no id.
        by_rsid, _s, _c = _scan(
            [_row(PhenotypeList="A|B|C", PhenotypeIDS="MONDO:MONDO:0000001")]
        )
        conditions = by_rsid["rs1800562"][0]["conditions"]
        self.assertEqual([c["name"] for c in conditions], ["A", "B", "C"])
        self.assertTrue(all(not c["xrefs"] for c in conditions))

    def test_placeholder_conditions_are_dropped(self):
        """ClinVar's 'not provided' / 'not specified' placeholders are not conditions."""
        by_rsid, _s, _c = _scan([_row(PhenotypeList="not provided|not specified")])
        self.assertEqual(by_rsid["rs1800562"][0]["conditions"], [])


class GzipManifestTest(unittest.TestCase):
    """Reading a target manifest that is stored compressed."""
    def test_a_gzipped_manifest_loads(self):
        """A gzipped manifest loads and yields the same targets as an uncompressed one."""
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
        """Compression is detected from the file's magic bytes, not from its name."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "no-extension.json"
            path.write_bytes(gzip.compress(b'{"a": 1}'))
            self.assertEqual(json.loads(read_manifest_text(path)), {"a": 1})


def _manifest(identifier: str, targets: list[dict]) -> dict:
    """A minimal valid manifest wrapper around the given targets."""
    return {
        "schema": "genoma-partial-genome-targets-v1",
        "id": identifier,
        "version": "1",
        "targets": targets,
    }


def _write(payload: dict, directory: Path, name: str) -> Path:
    """Write a payload as JSON into a directory and return the path."""
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class MergeTest(unittest.TestCase):
    """How two target registries combine, and what the merge refuses to decide on its own."""
    def _merge(self, *manifests):
        """Merge these manifests through the real script, via temporary files."""
        with tempfile.TemporaryDirectory() as td:
            paths = [
                _write(m, Path(td), f"m{i}.json") for i, m in enumerate(manifests)
            ]
            return MERGE.merge(paths)

    def test_agreeing_registries_merge_and_keep_the_allele(self):
        """Registries that agree merge to one target and keep the allele they agree on."""
        target = {"rsid": "rs1", "scope": "CLINICO", "label": "a",
                  "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "A"}
        result = self._merge(_manifest("A", [target]), _manifest("B", [dict(target)]))
        self.assertEqual(result["totals"]["targets"], 1)
        self.assertEqual(result["targets"][0]["assessed_allele"], "A")
        self.assertEqual(result["totals"]["assessed_allele_conflicts"], 0)

    def test_a_disagreement_removes_the_allele_rather_than_choosing(self):
        """Registries that disagree on the allele lose it: the merge records a conflict, not a winner."""
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

    def test_reference_conflict_removes_assessed_allele_and_its_evidence(self):
        """A reference-allele conflict removes the assessed allele and the provenance that supported it."""
        first = {
            "rsid": "rs1",
            "scope": "CLINICO",
            "label": "a",
            "queries": {"clinvar": {"term": "rs1"}},
            "reference_allele": "A",
            "assessed_allele": "G",
            "assessed_allele_source": "fixture",
            "assessed_allele_status": "VERIFICADO",
            "assessed_allele_evidence": "evidence.json",
            "assessed_allele_references": {"clinvar": ["VCV9"]},
            "references": {"clinvar": ["VCV1"]},
        }
        second = {
            **first,
            "label": "b",
            "reference_allele": "C",
        }
        merged = self._merge(_manifest("A", [first]), _manifest("B", [second]))[
            "targets"
        ][0]
        self.assertNotIn("reference_allele", merged)
        self.assertNotIn("assessed_allele", merged)
        self.assertNotIn("assessed_allele_source", merged)
        self.assertNotIn("assessed_allele_evidence", merged)
        self.assertNotIn("assessed_allele_status", merged)
        # Allele-scoped references go with the allele: they are the records cited *for* a
        # scoring that no longer stands.
        self.assertNotIn("assessed_allele_references", merged)
        self.assertIn("alelo de referência", merged["assessed_allele_reason"])
        # Locus-scoped `references` deliberately survives, asserted on purpose rather than
        # left to omission. It records which registry entries were consulted for rs1, not
        # which allele they supported; the locus is still in the manifest, refused and
        # carrying `identity_conflict`, and an auditor has to be able to see which records
        # disagreed. Dropping it would strip provenance from exactly the target that most
        # needs it. Note the retention is structural, not incidental: the field sits outside
        # the `assessed_allele_` namespace, so even a `pop` in the clearing branch is undone
        # by the generic carry-over below it. Removing it would take a deliberate change to
        # both, which is the point — this assertion says that change is not wanted.
        self.assertEqual(merged["references"], {"clinvar": ["VCV1"]})
        self.assertEqual(merged["identity_conflict"], ["reference_allele"])

    def test_a_third_registry_cannot_restore_an_allele_refused_for_reference_conflict(self):
        """The refusal has to outlive the registry that caused it.

        Clearing on a reference_allele conflict removes every `assessed_allele*` key, and
        the sentinel `assessed_allele_conflict` lives in that namespace, so it was cleared
        too. A third registry then saw a locus with no allele and no conflict marker —
        indistinguishable from one never assessed — and copied its own allele in. The locus
        was refused for disagreeing about which base is the reference and still came out of
        the merge carrying an arbitrated allele.
        """
        first = {"rsid": "rs1", "scope": "CLINICO", "label": "a",
                 "queries": {"clinvar": {"term": "rs1"}},
                 "reference_allele": "A", "assessed_allele": "G"}
        second = {**first, "label": "b", "reference_allele": "C"}
        third = {"rsid": "rs1", "scope": "CLINICO", "label": "c",
                 "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "T"}
        merged = self._merge(
            _manifest("A", [first]),
            _manifest("B", [second]),
            _manifest("C", [third]),
        )["targets"][0]
        self.assertNotIn("assessed_allele", merged)
        self.assertIn("reference_allele", merged["identity_conflict"])
        self.assertIn("alelo de referência", merged["assessed_allele_reason"])

    def test_silence_is_not_disagreement(self):
        """A registry that says nothing about the allele is not disagreeing with one that does."""
        result = self._merge(
            _manifest("A", [{"rsid": "rs1", "scope": "CLINICO", "label": "a",
                             "queries": {"clinvar": {"term": "rs1"}}}]),
            _manifest("B", [{"rsid": "rs1", "scope": "CLINICO", "label": "b",
                             "queries": {"clinvar": {"term": "rs1"}}, "assessed_allele": "G"}]),
        )
        self.assertEqual(result["targets"][0]["assessed_allele"], "G")

    def test_a_locus_keeps_the_stronger_scope(self):
        """The strongest declared scope wins, so merging never demotes a clinical locus."""
        result = self._merge(
            _manifest("A", [{"rsid": "rs1", "scope": "CURIOSIDADE", "label": "a",
                             "queries": {"clinvar": {"term": "rs1"}}}]),
            _manifest("B", [{"rsid": "rs1", "scope": "CLINICO", "label": "b",
                             "queries": {"clinvar": {"term": "rs1"}}}]),
        )
        self.assertEqual(result["targets"][0]["scope"], "CLINICO")

    def test_a_conflict_is_not_undone_by_a_third_registry(self):
        """A third registry agreeing with one side does not resolve an existing conflict by majority."""
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
    """How trait scopes are validated against the GWAS catalogue."""
    def test_a_declared_term_with_no_significant_association_is_a_hard_error(self):
        """A declared term with no genome-wide-significant association is an error, not an empty scope."""
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
        """A scope name outside the known vocabulary is refused instead of being ignored."""
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
        """Scan one association row carrying this trait label and URI."""
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
        """A comma inside a trait label must not shift the locus onto another trait's name."""
        # MAPPED_TRAIT and MAPPED_TRAIT_URI are comma-separated and positionally aligned, so a
        # label containing a comma breaks the alignment. Zipping them anyway printed another
        # trait's name on this locus. Where the lengths disagree the declared label is used.
        by_rsid, stats = self._scan(
            "lactase persistence, adult type", "http://x/EFO_0801753"
        )
        self.assertEqual(stats["misaligned_trait_columns"], 1)
        self.assertEqual(by_rsid["rs4988235"][0]["term_label"], "persistência da lactase")

    def test_a_misaligned_row_still_matches_every_term_it_declares(self):
        """A misaligned row still matches every term it declares, instead of being truncated by zip."""
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
        """Aligned columns keep the catalogue's own label."""
        by_rsid, stats = self._scan("lactase persistence", "http://x/EFO_0801753")
        self.assertEqual(stats.get("misaligned_trait_columns", 0), 0)
        self.assertEqual(by_rsid["rs4988235"][0]["term_label"], "lactase persistence")

    def test_the_risk_allele_parser_refuses_what_it_cannot_read(self):
        """The risk-allele parser returns None for anything it cannot read, never a guess."""
        self.assertEqual(TRAITS._risk_allele("rs738409-G", "rs738409"), "G")
        for unreadable in ("rs738409-?", "rs738409", "", "rs738409-NR"):
            self.assertIsNone(TRAITS._risk_allele(unreadable, "rs738409"), unreadable)


class ShippedRegistryTest(unittest.TestCase):
    """The registries committed to the repository must load and be internally consistent."""

    def _registries(self):
        """The registries actually shipped in config/, whichever of them exist."""
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
        """The registry list is not silently empty: at least four are shipped."""
        self.assertGreaterEqual(len(self._registries()), 4)

    def test_every_shipped_registry_loads(self):
        """Every shipped registry parses and contains targets."""
        for path in self._registries():
            with self.subTest(registry=path.name):
                manifest = load_target_manifest(path)
                self.assertTrue(manifest["targets"])

    def test_every_shipped_registry_cites_a_source(self):
        """Every shipped registry declares where it came from."""
        for path in self._registries():
            with self.subTest(registry=path.name):
                manifest = load_target_manifest(path)
                self.assertTrue(
                    manifest.get("sources") or manifest.get("description") or manifest.get("merged_from"),
                    f"{path.name} declares no provenance",
                )

    def test_a_target_with_an_assessed_allele_names_where_it_came_from(self):
        """A shipped target that carries an assessed allele also names the source that assessed it."""
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


class AssessedAlleleApplicationTest(unittest.TestCase):
    """How a re-assessment is applied to a target that already carried an allele."""
    def test_refusal_clears_stale_allele_and_provenance(self):
        """A refusal clears the stale allele and every provenance field that supported it."""
        target = {
            "rsid": "rs1",
            "assessed_allele": "A",
            "assessed_allele_status": "VERIFICADO",
            "assessed_allele_source": "old",
            "assessed_allele_evidence": "old.json",
            "assessed_allele_references": ["old"],
            "references": {"clinvar": ["old"]},
        }
        CURATE._apply_target_assessment(
            target,
            {
                "assessed_allele": None,
                "status": "NÃO DISPONÍVEL",
                "reason": "fixture refusal",
            },
            "new.json",
        )
        self.assertNotIn("assessed_allele", target)
        self.assertNotIn("assessed_allele_source", target)
        self.assertNotIn("assessed_allele_evidence", target)
        self.assertNotIn("assessed_allele_references", target)
        self.assertNotIn("references", target)
        self.assertEqual(target["assessed_allele_status"], "NÃO DISPONÍVEL")
        self.assertEqual(target["assessed_allele_reason"], "fixture refusal")


class ReviewStarTierTest(unittest.TestCase):
    """Admitting one-star variants only helps if every one of them stays labelled as such."""

    def test_the_ladder_scores_the_statuses_clinvar_actually_writes(self):
        """The star ladder scores each review status ClinVar actually writes."""
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
        """An unrecognised review status scores zero, so a new NCBI status cannot fail open."""
        # The fail-open shape this guards against: a status NCBI adds later defaulting to a
        # number that clears the threshold would admit it silently.
        for status in ("", None, "reviewed by a friend", "criteria provided, whatever"):
            with self.subTest(status=status):
                self.assertEqual(EXPAND.review_stars(status), 0)
                self.assertLess(EXPAND.review_stars(status), 2)

    def test_the_default_threshold_still_rejects_a_single_submitter(self):
        """At the default threshold a single-submitter assertion is refused and counted as such."""
        _by, stats, _counts = _scan([_row(ReviewStatus="criteria provided, single submitter")])
        self.assertEqual(stats.get("kept", 0), 0)
        self.assertEqual(stats["below_review_threshold"], 1)

    def test_lowering_the_threshold_admits_it_and_records_one_star(self):
        """Lowering the threshold admits it and records it as one star, not as unqualified."""
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
        """A one-star target carries its own star level, so a stricter consumer can still refuse it."""
        by_rsid, _stats, _counts = EXPAND.scan_clinvar(
            _bulk([_row(ReviewStatus="criteria provided, single submitter")]),
            min_review_stars=1,
        )
        targets, _tstats = EXPAND.build_targets(by_rsid)
        self.assertEqual(targets[0]["clinvar_review_stars"], 1)
        self.assertIn("1★", targets[0]["assessed_allele_source"])

    def test_a_locus_asserted_at_two_levels_reports_both_ends(self):
        """A locus asserted at two review levels reports both ends rather than only the best."""
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
    """A PanelApp index built from the given gene records."""
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
        """A green gene establishes validity and names PanelApp as the registry that did it."""
        block = EXPAND.gene_validity("HFE", {}, {}, _panelapp(HFE=self.GREEN))
        self.assertEqual(block["established_by"], ["PanelApp"])
        self.assertTrue(block["established"])
        self.assertEqual(block["modes_of_inheritance"], ["AR"])

    def test_an_amber_only_gene_does_not_establish(self):
        """Amber is not evidence: a gene the curators declined to endorse does not establish."""
        # The failure this guards against: reading amber as evidence would report a gene the
        # curators explicitly declined to endorse.
        block = EXPAND.gene_validity("HFE", {}, {}, _panelapp(HFE=self.AMBER_ONLY))
        self.assertEqual(block["established_by"], [])
        self.assertFalse(block["panelapp"]["established"])
        self.assertEqual(block["panelapp"]["status"], "NÃO DISPONÍVEL")

    def test_a_gene_absent_from_panelapp_says_so_rather_than_failing_open(self):
        """A gene absent from PanelApp is recorded as absent, not as refuted."""
        block = EXPAND.gene_validity("HFE", {}, {}, _panelapp(CFTR=self.GREEN))
        self.assertFalse(block["panelapp"]["established"])
        self.assertIn("não aparece como gene verde", block["panelapp"]["reason"])

    def test_no_panelapp_file_is_reported_as_missing_input_not_as_a_negative(self):
        """No PanelApp file at all is a missing input, distinct from a gene PanelApp rejected."""
        block = EXPAND.gene_validity("HFE", {}, {}, None)
        self.assertIn("não fornecida", block["panelapp"]["reason"])

    def test_the_gencc_overlap_is_flagged_rather_than_counted_twice(self):
        """A gene established in both GenCC and PanelApp is flagged as overlapping, not counted twice."""
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
        """A PanelApp mode of inheritance with no disease anchor is listed as such."""
        block = EXPAND.gene_validity("HFE", {}, {}, _panelapp(HFE=self.GREEN))
        self.assertEqual(block["modes_without_disease_anchor"], ["AR"])

    def test_the_curation_schema_is_checked_before_it_is_trusted(self):
        """A curation file whose schema is not the expected one is refused before it is read."""
        directory = Path(tempfile.mkdtemp())
        path = directory / "panelapp.json"
        path.write_text(json.dumps({"schema": "something-else", "genes": {}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            EXPAND.read_panelapp(path)

    def test_a_missing_file_is_an_error_not_an_empty_registry(self):
        """A missing curation file raises, rather than being read as a registry with no genes."""
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
        """A haploinsufficiency score of 3 establishes the gene and reads as dominant."""
        table = EXPAND.read_clingen_dosage(_dosage_file([("HFE", "3", "0")]))
        self.assertTrue(table["HFE"]["established"])
        self.assertEqual(table["HFE"]["modes_of_inheritance"], ["AD"])
        block = EXPAND.gene_validity("HFE", {}, {}, {}, table)
        self.assertEqual(block["established_by"], ["ClinGen Dosage"])

    def test_score_thirty_records_recessive_inheritance_without_establishing(self):
        """Score 30 records recessive inheritance without establishing: it is a code, not a stronger 3."""
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
        """Haploinsufficiency on the X chromosome is X-linked, not autosomal dominant."""
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
        """The recessive dosage code on X stays X-linked too."""
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
        """Score 40 neither establishes nor contributes a mode of inheritance."""
        table = EXPAND.read_clingen_dosage(_dosage_file([("HFE", "40", "0")]))
        self.assertFalse(table["HFE"]["established"])
        self.assertEqual(table["HFE"]["modes_of_inheritance"], [])

    def test_the_partial_scores_do_not_establish(self):
        """The partial scores (0, 1, 2) do not establish."""
        for score in ("0", "1", "2"):
            with self.subTest(score=score):
                table = EXPAND.read_clingen_dosage(_dosage_file([("HFE", score, "0")]))
                self.assertFalse(table["HFE"]["established"])

    def test_triplosensitivity_alone_can_establish(self):
        """Triplosensitivity on its own can establish, without any haploinsufficiency score."""
        table = EXPAND.read_clingen_dosage(_dosage_file([("HFE", "0", "3")]))
        self.assertTrue(table["HFE"]["established"])

    def test_a_gene_absent_from_the_list_says_so(self):
        """A gene absent from the dosage list is recorded as absent, not as scored zero."""
        table = EXPAND.read_clingen_dosage(_dosage_file([("CFTR", "3", "0")]))
        block = EXPAND.gene_validity("HFE", {}, {}, {}, table)
        self.assertIn("não consta", block["clingen_dosage"]["reason"])

    def test_a_file_with_no_recognisable_header_is_refused(self):
        """A dosage file with no recognisable header is refused instead of parsed as empty."""
        path = Path(tempfile.mkdtemp()) / "broken.tsv"
        path.write_text("#comment only\nHFE\t1\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            EXPAND.read_clingen_dosage(path)


CONSTRAINT_COLUMNS = [
    "gene", "gene_id", "transcript", "canonical", "mane_select",
    "lof.pLI", "lof.oe", "lof.oe_ci.upper", "mis.z_score", "constraint_flags",
]


def _constraint_file(rows: list[dict[str, str]]) -> Path:
    """Write a gnomAD constraint TSV containing exactly these rows."""
    path = Path(tempfile.mkdtemp()) / "constraint.tsv"
    lines = ["\t".join(CONSTRAINT_COLUMNS)]
    for row in rows:
        lines.append("\t".join(str(row.get(c, "")) for c in CONSTRAINT_COLUMNS))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class GnomadConstraintTest(unittest.TestCase):
    """Constraint is carried, displayed, and never allowed to establish anything."""

    def test_the_mane_select_transcript_wins_over_the_canonical_one(self):
        """The MANE Select transcript is preferred over the merely canonical one."""
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
        """When both rows claim MANE and canonical, the Ensembl-keyed row breaks the tie."""
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
        """A transcript that is neither MANE nor canonical is skipped, however extreme its metrics."""
        table = EXPAND.read_gnomad_constraint(
            _constraint_file(
                [{"gene": "HFE", "gene_id": "ENSG1", "transcript": "ENST_ALT",
                  "canonical": "false", "mane_select": "false", "lof.pLI": "0.99"}]
            )
        )
        self.assertEqual(table, {})

    def test_an_unparseable_metric_becomes_absent_not_zero(self):
        """A metric that does not parse becomes absent, never zero."""
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
        """Constraint never establishes gene-disease validity, however extreme the metrics are."""
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


class ClinvarCitationRetrievalTest(unittest.TestCase):
    """A failed citation lookup must not be published as "no publications exist".

    `clinvar_citations` caught `CurationError` and returned `[]`. The curated target still
    carried `status: VERIFICADO`, because the allele assignment comes from CPIC's definition
    rather than from the citations — so an empty `clinvar_pubmed` asserted an absence of
    supporting literature that a failed request had never established. The two facts now
    look different in the record.
    """

    def test_a_failed_lookup_is_recorded_rather_than_read_as_absence(self):
        """A failed citation lookup is recorded as a failure, not as 'this variant has no citations'."""
        from scripts import curate_assessed_alleles as curate

        with patch.object(
            curate, "_get", side_effect=curate.CurationError("eutils unreachable")
        ):
            result = curate.clinvar_citations(["1", "2"])
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertEqual(result["pmids"], [])
        self.assertIn("falhou", result["reason"])

    def test_a_successful_lookup_reports_executed(self):
        """A successful lookup reports EXECUTADO and de-duplicates the returned links."""
        from scripts import curate_assessed_alleles as curate

        payload = {
            "linksets": [
                {"linksetdbs": [{"linkname": "clinvar_pubmed", "links": ["11", "22", "11"]}]}
            ]
        }
        with patch.object(curate, "_get", return_value=payload):
            result = curate.clinvar_citations(["1"])
        self.assertEqual(result["status"], "EXECUTADO")
        self.assertEqual(result["pmids"], ["11", "22"])
        self.assertIsNone(result["reason"])

    def test_no_uids_is_executed_not_a_failure(self):
        """A lookup with no uids is EXECUTADO with an empty result, which is not a failure."""
        from scripts import curate_assessed_alleles as curate

        result = curate.clinvar_citations([])
        self.assertEqual(result["status"], "EXECUTADO")
        self.assertEqual(result["pmids"], [])


class MergeCarriesWhatItPublishesTest(unittest.TestCase):
    """Three ways the merge published something it could not support.

    The refusal logic is careful about *which allele*; these are about everything travelling
    beside it — the evidence for the allele, the digest naming what was merged, and the scope
    the loader accepted in one spelling and the ranking rejected in another.
    """

    def _merge(self, *manifests):
        """Merge these manifests through the real script, via temporary files."""
        with tempfile.TemporaryDirectory() as td:
            paths = [
                _write(m, Path(td), f"m{i}.json") for i, m in enumerate(manifests)
            ]
            return MERGE.merge(paths)

    def test_an_allele_arriving_second_brings_its_evidence_with_it(self):
        """An allele without its provenance is a claim this project does not make.

        When the first registry declares no allele and the second does, the "silence is not
        disagreement" branch copies the allele in. It copied four keys by name —
        `assessed_allele`, `_source`, `_status`, `_reason` — and `assessed_allele_evidence`
        and `assessed_allele_references` were not among them. The generic carry-over below it
        then skips everything in `ASSESSED_ALLELE_FIELDS` and everything prefixed
        `assessed_allele_`, deliberately, so those two had no other way in. The merged panel
        scored the locus against an allele while naming nothing that supported it.
        """
        first = {"rsid": "rs1", "scope": "CLINICO", "label": "a",
                 "queries": {"clinvar": {"term": "rs1"}}}
        second = {"rsid": "rs1", "scope": "CLINICO", "label": "b",
                  "queries": {"clinvar": {"term": "rs1"}},
                  "assessed_allele": "G",
                  "assessed_allele_source": "clinvar",
                  "assessed_allele_status": "VERIFICADO",
                  "assessed_allele_evidence": {"review_status": "criteria provided"},
                  "assessed_allele_references": {"clinvar": ["VCV1"]}}
        merged = self._merge(_manifest("A", [first]), _manifest("B", [second]))["targets"][0]
        self.assertEqual("G", merged["assessed_allele"])
        self.assertEqual({"review_status": "criteria provided"},
                         merged["assessed_allele_evidence"])
        self.assertEqual({"clinvar": ["VCV1"]}, merged["assessed_allele_references"])

    def test_a_refused_allele_does_not_drag_its_evidence_back_in(self):
        """The carry must not become a second door around the refusal it sits beside."""
        first = {"rsid": "rs1", "scope": "CLINICO", "label": "a",
                 "queries": {"clinvar": {"term": "rs1"}},
                 "assessed_allele": "T", "reference_allele": "A",
                 "assessed_allele_evidence": {"from": "A"}}
        second = {"rsid": "rs1", "scope": "CLINICO", "label": "b",
                  "queries": {"clinvar": {"term": "rs1"}},
                  "assessed_allele": "G", "reference_allele": "C",
                  "assessed_allele_evidence": {"from": "B"}}
        merged = self._merge(_manifest("A", [first]), _manifest("B", [second]))["targets"][0]
        self.assertNotIn("assessed_allele", merged)
        self.assertNotIn("assessed_allele_evidence", merged)
        self.assertIn("reference_allele", merged["identity_conflict"])

    def test_a_manifest_whose_declared_digest_is_wrong_is_refused(self):
        """`merge_basis` and `merged_from` published `sha256` without ever checking it.

        The panel's own version string is derived from `merge_basis`, so a manifest declaring
        someone else's digest — or a typo — produced a panel whose provenance named content
        that was not what got merged. The digest is a claim about bytes; it is now computed
        from them.
        """
        target = {"rsid": "rs1", "scope": "CLINICO", "label": "a",
                  "queries": {"clinvar": {"term": "rs1"}}}
        manifest = _manifest("A", [target])
        manifest["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "sha256"):
            self._merge(manifest)

    def test_a_manifest_declaring_its_real_digest_is_accepted(self):
        """The accepting case, so the refusal above is a check and not a ban on the field."""
        target = {"rsid": "rs1", "scope": "CLINICO", "label": "a",
                  "queries": {"clinvar": {"term": "rs1"}}}
        manifest = _manifest("A", [target])
        manifest["sha256"] = MERGE.sha256_json(
            {k: v for k, v in manifest.items() if k != "sha256"}
        )
        result = self._merge(manifest)
        self.assertEqual(manifest["sha256"], result["merged_from"][0]["sha256"])

    def test_a_scope_the_loader_accepts_is_a_scope_the_merge_can_rank(self):
        """`load_target_manifest` validates `scope.upper()` and returns the original.

        So `"clinico"` passed validation and then reached `_scope_rank`, which compares
        against the canonical uppercase tuple and raised `ValueError` — on a manifest the
        loader had just accepted. Loader and ranking must agree about what a scope is.
        """
        for spelling in ("clinico", "Clinico", "CLINICO", "predisposicao"):
            with self.subTest(scope=spelling):
                target = {"rsid": "rs1", "scope": spelling, "label": "a",
                          "queries": {"clinvar": {"term": "rs1"}}}
                merged = self._merge(_manifest("A", [target]))["targets"][0]
                self.assertEqual(spelling.upper(), merged["scope"])

    def test_the_stronger_scope_still_wins_across_spellings(self):
        """Normalising must not flatten the ranking it exists to make possible."""
        weak = {"rsid": "rs1", "scope": "curiosidade", "label": "a",
                "queries": {"clinvar": {"term": "rs1"}}}
        strong = {"rsid": "rs1", "scope": "CLINICO", "label": "b",
                  "queries": {"clinvar": {"term": "rs1"}}}
        merged = self._merge(_manifest("A", [weak]), _manifest("B", [strong]))["targets"][0]
        self.assertEqual("CLINICO", merged["scope"])


class StrictReferenceDecodingTest(unittest.TestCase):
    """Curated reference inputs fail closed rather than replacing malformed UTF-8."""

    def test_gwas_associations_reject_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "associations.tsv"
        path.write_bytes(b"SNPS\tDISEASE/TRAIT\nrs1\tbad\xff\n")
        with self.assertRaises(UnicodeDecodeError):
            with TRAITS._open_associations(path) as handle:
                handle.read()

    def test_gwas_ancestry_rejects_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "ancestries.tsv"
        path.write_bytes(
            b"STUDY ACCESSION\tBROAD ANCESTRAL CATEGORY\tSTAGE\tNUMBER OF INDIVIDUALS\tINITIAL SAMPLE DESCRIPTION\n"
            b"GCST1\tEuropean\tinitial\t10\tbad\xff\n"
        )
        with self.assertRaises(UnicodeDecodeError):
            TRAITS.read_ancestries(path)

    def test_clinvar_bulk_rejects_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "variant_summary.txt.gz"
        raw = ("\t".join(COLUMNS) + "\n").encode("utf-8") + b"bad\xff\n"
        path.write_bytes(gzip.compress(raw))
        with self.assertRaises(UnicodeDecodeError):
            EXPAND.scan_clinvar(path)

    def test_clingen_dosage_rejects_invalid_utf8(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "dosage.tsv"
        path.write_bytes(DOSAGE_HEADER.encode("utf-8") + b"\nHFE\t1\tbad\xff\n")
        with self.assertRaises(UnicodeDecodeError):
            EXPAND.read_clingen_dosage(path)

if __name__ == "__main__":
    unittest.main()
