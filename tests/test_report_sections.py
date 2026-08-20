"""Every builder's section titles must equal the catalogue's, character for character.

`reporting.engine` prints sections by looking each one up under its catalogue title. A
builder that anchors text under a paraphrase therefore renders an *empty* section while the
anchored content sits unreachable under a key nobody reads — the document silently loses a
page and nothing raises. That has happened twice in this project, and both times it survived
until someone opened the PDF and read it.

This test makes the drift impossible to ship. Builders may keep a literal `SECTIONS` tuple
for readability; they may not disagree with `reporting/catalog.json`.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.catalog import load_catalog, report_ids, section_titles


def _load(module_path: Path):
    spec = importlib.util.spec_from_file_location(f"_builder_{module_path.stem}", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _builders() -> list[tuple[str, Path]]:
    """Every script that declares both a REPORT_ID and a SECTIONS tuple.

    Discovered rather than listed: a hand-kept list would omit the next builder someone adds,
    which is exactly the one most likely to carry a typo.
    """
    found: list[tuple[str, Path]] = []
    for path in sorted((ROOT / "scripts").glob("build_*.py")):
        text = path.read_text(encoding="utf-8")
        if "\nSECTIONS" not in text or "\nREPORT_ID" not in text:
            continue
        found.append((path.stem, path))
    return found


class BuilderSectionTitlesTest(unittest.TestCase):
    def test_builders_were_discovered(self):
        # Negative control for the discovery itself: a test that found nothing to check
        # would pass silently and prove nothing, which is the vacuous pass this project
        # keeps finding elsewhere.
        self.assertGreaterEqual(len(_builders()), 6, _builders())

    def test_every_builder_matches_the_catalogue(self):
        for name, path in _builders():
            with self.subTest(builder=name):
                module = _load(path)
                report_id = getattr(module, "REPORT_ID")
                sections = tuple(getattr(module, "SECTIONS"))
                self.assertEqual(
                    sections,
                    section_titles(report_id),
                    f"{name} declares section titles that differ from reporting/catalog.json "
                    f"for report {report_id}; the engine prints by catalogue title, so the "
                    "mismatched sections would render empty",
                )


class CatalogShapeTest(unittest.TestCase):
    def test_every_report_declares_sections(self):
        for report_id in report_ids():
            with self.subTest(report=report_id):
                self.assertTrue(section_titles(report_id))

    def test_section_titles_are_unique_within_a_report(self):
        # Two sections with the same title collapse into one key in the payload, so the
        # second silently overwrites the first.
        for report_id in report_ids():
            titles = section_titles(report_id)
            with self.subTest(report=report_id):
                self.assertEqual(len(titles), len(set(titles)))

    def test_an_unknown_report_raises_rather_than_returning_empty(self):
        from reporting.catalog import CatalogError

        with self.assertRaises(CatalogError):
            section_titles("99")

    def test_the_catalogue_covers_the_declared_suite(self):
        self.assertEqual(len(load_catalog()), 11)



class AssociationSectionRolesTest(unittest.TestCase):
    """The association reports do not order their sections alike.

    Mapping them by position put report 08's trait matrix under "Sentidos, fisiologia e
    preferências" and its refusal under "Cartões de traços", and nothing errored. The roles
    are now named, and this checks they still name real catalogue sections.
    """

    def test_every_role_names_a_real_middle_section(self):
        module = _load(ROOT / "scripts" / "build_association_report.py")
        for report_id, roles in module.SECTION_ROLES.items():
            with self.subTest(report=report_id):
                middle = section_titles(report_id)[1:-1]
                self.assertEqual(sorted(roles), sorted(middle))

    def test_each_report_maps_exactly_one_section_to_the_association_matrix(self):
        module = _load(ROOT / "scripts" / "build_association_report.py")
        for report_id, roles in module.SECTION_ROLES.items():
            with self.subTest(report=report_id):
                self.assertEqual(
                    sum(1 for role in roles.values() if role == "associations"), 1
                )


class CarrierDenominatorTest(unittest.TestCase):
    """The carrier-screening denominator must count the registry, not the sample."""

    def _detection(self, registry_recessive):
        import importlib.util

        path = ROOT / "scripts" / "build_reproductive_report.py"
        spec = importlib.util.spec_from_file_location("_rep", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        payload = {
            "registry": {"recessive_genes_established": registry_recessive},
            "findings": [
                {
                    "gene": gene,
                    "coverage_class": "OBSERVADO",
                    "validity": {
                        "established": True,
                        "modes_of_inheritance": ["AR"],
                        "clinvar_variant_counts": {
                            "pathogenic": 100, "representable_in_registry": 10
                        },
                    },
                }
                for gene in ("HFE", "CFTR", "PAH")
            ],
        }
        return module._detection(payload)

    def test_the_denominator_is_the_registry_not_the_genes_reached(self):
        # The defect this guards against: the denominator used to be len(by_gene), which is
        # built only from findings that carry a validity block — and only interrogated loci
        # do. It therefore always equalled the numerator and printed "N of N", which reads as
        # complete gene coverage.
        detection = self._detection(1939)
        self.assertEqual(detection["genes_interrogated"], 3)
        self.assertEqual(detection["genes_total"], 1939)
        self.assertNotEqual(
            detection["genes_total"],
            detection["genes_interrogated"],
            "denominator collapsed back onto the numerator",
        )

    def test_a_missing_registry_block_yields_no_denominator_rather_than_a_wrong_one(self):
        detection = self._detection(None)
        self.assertIsNone(detection["genes_total"])


class UnqueriedLocusTest(unittest.TestCase):
    """A locus nobody looked up must never be reported as having no association."""

    def _module(self):
        import importlib.util

        path = ROOT / "scripts" / "build_association_report.py"
        spec = importlib.util.spec_from_file_location("_assoc", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    #: A locus from the bulk ClinVar route: no GWAS block at all.
    NEVER_QUERIED = {"rsid": "rs1", "gene": "BRCA1", "coverage_class": "OBSERVADO"}
    #: A locus from the curated route where the catalogue was consulted and returned nothing.
    QUERIED_EMPTY = {
        "rsid": "rs2", "gene": "MTHFR", "coverage_class": "OBSERVADO",
        "gwas": {"status": "VERIFICADO", "traits": []},
    }
    #: The bulk route's explicit marker.
    BULK_MARKED = {
        "rsid": "rs3", "gene": "TTN", "coverage_class": "OBSERVADO",
        "gwas": {"status": "NÃO DISPONÍVEL", "traits": [],
                 "reason": "não consultado nesta rota em massa"},
    }

    def test_the_two_kinds_of_silence_are_told_apart(self):
        module = self._module()
        self.assertFalse(module._gwas_queried(self.NEVER_QUERIED))
        self.assertFalse(module._gwas_queried(self.BULK_MARKED))
        self.assertTrue(module._gwas_queried(self.QUERIED_EMPTY))

    def test_an_unqueried_locus_is_not_reported_as_having_no_association(self):
        # The defect this guards against: the matrix printed "nenhuma associação com
        # significância genômica no GWAS Catalog" once per locus, for 124,357 loci the
        # catalogue was never asked about — a negative finding nobody looked for.
        module = self._module()
        text = module._trait_matrix([self.NEVER_QUERIED, self.BULK_MARKED])
        self.assertIn("não foram consultados", text)
        self.assertIn("ninguém procurou", text)
        self.assertNotIn("nenhuma associação com significância genômica no GWAS Catalog", text)

    def test_a_queried_locus_with_nothing_significant_is_counted_as_such(self):
        module = self._module()
        text = module._trait_matrix([self.QUERIED_EMPTY])
        self.assertIn("foram consultados no GWAS Catalog e não têm", text)

    def test_the_matrix_is_bounded_and_counts_the_remainder(self):
        module = self._module()
        many = [dict(self.NEVER_QUERIED, rsid=f"rs{i}") for i in range(5000)]
        text = module._trait_matrix(many)
        self.assertLess(len(text), 4000, "the matrix grew with the registry again")
        self.assertIn("5000", text)

    def test_the_evidence_tier_refuses_to_grade_an_unqueried_scope(self):
        module = self._module()
        text = module._evidence_tier([self.NEVER_QUERIED, self.BULK_MARKED])
        self.assertIn("foi consultado no GWAS Catalog", text)
        self.assertIn("a ausência dela não é resultado", text)

    def test_the_protective_line_counts_only_what_was_consulted(self):
        module = self._module()
        text = module._protective_line([self.NEVER_QUERIED, self.QUERIED_EMPTY])
        self.assertIn("efetivamente consultados", text)
        self.assertIn("não foram consultados", text)


class ClinicalSectionBoundsTest(unittest.TestCase):
    """Report 01's negative lists must not grow with the registry."""

    def _module(self):
        import importlib.util

        path = ROOT / "scripts" / "build_clinical_report.py"
        spec = importlib.util.spec_from_file_location("_clin", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def _payload(self, untested: int):
        from array_pipeline.clinical_findings import NAO_INTERROGADO

        return {
            "negative_statement_policy": "política",
            "findings": [
                {
                    "rsid": f"rs{i}", "gene": "GENE", "interpretation": NAO_INTERROGADO,
                    "genotype": None, "clinvar": {"conditions": []},
                }
                for i in range(untested)
            ],
        }

    def test_the_untested_list_is_capped_and_the_remainder_counted(self):
        # The defect: naming all 124,546 loci the array never carried produced a 2.3 MB
        # section. The count was already in the label, so the list added nothing.
        module = self._module()
        text = module._predisposition_text(self._payload(5000))
        self.assertIn("Não interrogados (5000)", text)
        self.assertIn("não listados individualmente", text)
        self.assertLess(len(text), 6000, "the section grew with the registry again")

    def test_a_short_list_is_named_in_full(self):
        module = self._module()
        text = module._predisposition_text(self._payload(3))
        self.assertIn("Não interrogados (3)", text)
        self.assertNotIn("não listados individualmente", text)

    def test_the_one_star_tier_is_named_rather_than_folded_in(self):
        # The wider default registry is only safe because the report says which findings rest
        # on a single submitter.
        from array_pipeline.clinical_findings import ACHADO_PRELIMINAR

        module = self._module()
        payload = self._payload(0)
        payload["findings"].append(
            {
                "rsid": "rs99", "gene": "CAV3", "interpretation": ACHADO_PRELIMINAR,
                "genotype": "AG", "clinvar": {"conditions": []},
            }
        )
        text = module._predisposition_text(payload)
        self.assertIn("Achados preliminares, revisão de uma estrela (1)", text)
        self.assertIn("rs99", text)


class ReportableFindingBoundsTest(unittest.TestCase):
    """The positive findings had no bound at all, and they grow with the case.

    The negative lists were capped; the reportable ones were not. On a representative array
    that produced 4,065 described loci and a 28 MB payload — a document in which the findings
    that matter were indistinguishable from the ones that did not. The cap must never reach
    the actionable class, whose omission would be the worst outcome this pipeline could
    produce, and whatever it does omit has to be stated as a count.
    """

    def _module(self):
        import importlib.util

        path = ROOT / "scripts" / "build_clinical_report.py"
        spec = importlib.util.spec_from_file_location("_clin_bounds", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def _findings(self, module, counts: dict[str, int]):
        out = []
        n = 0
        for kind, count in counts.items():
            for _ in range(count):
                n += 1
                out.append({
                    "rsid": f"rs{n}", "gene": f"GENE{n}", "interpretation": kind,
                    "genotype": "AA", "clinvar": {"conditions": ["condição"]},
                })
        return out

    def test_actionable_findings_are_never_truncated(self):
        module = self._module()
        from array_pipeline.clinical_findings import ACIONAVEL

        over = module.MAX_FINDINGS_DETAILED_PER_CLASS * 5
        detailed, omitted = module._split_reportable(
            self._findings(module, {ACIONAVEL: over})
        )
        self.assertEqual(len(detailed), over)
        self.assertEqual(omitted, [])

    def test_the_lower_tiers_are_capped_per_class(self):
        module = self._module()
        from array_pipeline.clinical_findings import GENOTIPO_DE_RISCO, PORTADOR

        cap = module.MAX_FINDINGS_DETAILED_PER_CLASS
        detailed, omitted = module._split_reportable(
            self._findings(module, {PORTADOR: cap + 11, GENOTIPO_DE_RISCO: cap + 7})
        )
        self.assertEqual(len(detailed), cap * 2)
        self.assertEqual(len(omitted), 18)

    def test_every_omitted_locus_is_counted_in_the_section_text(self):
        module = self._module()
        from array_pipeline.clinical_findings import ACIONAVEL, PORTADOR

        cap = module.MAX_FINDINGS_DETAILED_PER_CLASS
        payload = {"findings": self._findings(module, {ACIONAVEL: 3, PORTADOR: cap + 42})}
        text = module._findings_text(payload)
        self.assertIn("42 em", text)
        self.assertIn(str(cap), text)
        self.assertIn(ACIONAVEL, text)

    def test_nothing_is_said_about_omission_when_nothing_was_omitted(self):
        module = self._module()
        from array_pipeline.clinical_findings import PORTADOR

        text = module._findings_text({"findings": self._findings(module, {PORTADOR: 5})})
        self.assertNotIn("não são detalhados", text)

    def test_the_detailed_and_omitted_sets_partition_the_reportable_ones(self):
        # No locus may be dropped by the split itself, and none may be described twice.
        module = self._module()
        from array_pipeline.clinical_findings import ACIONAVEL, GENOTIPO_DE_RISCO, PORTADOR

        cap = module.MAX_FINDINGS_DETAILED_PER_CLASS
        findings = self._findings(
            module, {ACIONAVEL: 9, PORTADOR: cap + 5, GENOTIPO_DE_RISCO: cap + 3}
        )
        detailed, omitted = module._split_reportable(findings)
        rsids = [f["rsid"] for f in detailed] + [f["rsid"] for f in omitted]
        self.assertEqual(len(rsids), len(set(rsids)), "um locus foi descrito duas vezes")
        self.assertEqual(set(rsids), {f["rsid"] for f in findings})

    def test_non_reportable_classes_are_left_out_of_both_sets(self):
        module = self._module()
        from array_pipeline.clinical_findings import ACIONAVEL, NAO_INTERROGADO, NEGATIVO

        findings = self._findings(
            module, {ACIONAVEL: 2, NEGATIVO: 30, NAO_INTERROGADO: 40}
        )
        detailed, omitted = module._split_reportable(findings)
        self.assertEqual(len(detailed), 2)
        self.assertEqual(omitted, [])

    def test_the_split_is_stable_across_calls(self):
        # The aggregate's counts are recomputed by the compiler's transform from the same
        # artifact. If the split were not deterministic the prose and the aggregate could
        # disagree about how many loci were omitted.
        module = self._module()
        from array_pipeline.clinical_findings import PORTADOR

        findings = self._findings(
            module, {PORTADOR: module.MAX_FINDINGS_DETAILED_PER_CLASS + 17}
        )
        first = [f["rsid"] for f in module._split_reportable(findings)[0]]
        second = [f["rsid"] for f in module._split_reportable(findings)[0]]
        self.assertEqual(first, second)
        self.assertIn("17", module._omitted_breakdown(findings))


class ReproductiveSectionBoundsTest(unittest.TestCase):
    """Report 03's carrier list grew with the registry, exactly like report 01's findings.

    2,111 carrier loci described one by one produced a 1.0 MB section in which no individual
    result could be found. The count was already in reach; the list was what made it
    unreadable.
    """

    def _module(self):
        import importlib.util

        path = ROOT / "scripts" / "build_reproductive_report.py"
        spec = importlib.util.spec_from_file_location("_repro_bounds", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def _payload(self, module, carriers: int):
        from array_pipeline.clinical_findings import PORTADOR

        return {
            "findings": [
                {
                    "rsid": f"rs{i}", "gene": f"GENE{i}", "genotype": "AG",
                    "interpretation": PORTADOR,
                    "validity": {
                        "recessive_diseases": ["condição"], "established_by": ["ClinGen"],
                    },
                }
                for i in range(carriers)
            ]
        }

    def test_the_carrier_list_is_capped_and_the_remainder_counted(self):
        module = self._module()
        cap = module.MAX_LOCI_DESCRIBED
        text = module._carrier_text(self._payload(module, cap + 33))
        self.assertIn(f"Portador ({cap + 33})", text)
        self.assertIn("+33", text)
        self.assertIn("não descritos individualmente", text)

    def test_a_short_list_is_described_in_full_with_no_omission_notice(self):
        module = self._module()
        text = module._carrier_text(self._payload(module, 4))
        self.assertIn("Portador (4)", text)
        self.assertNotIn("não descritos individualmente", text)
        for i in range(4):
            self.assertIn(f"rs{i}", text)

    def test_the_total_is_stated_even_when_the_list_is_cut(self):
        # The cap must never make a large case look like a small one.
        module = self._module()
        cap = module.MAX_LOCI_DESCRIBED
        text = module._carrier_text(self._payload(module, cap * 4))
        self.assertIn(str(cap * 4), text)


if __name__ == "__main__":
    unittest.main()
