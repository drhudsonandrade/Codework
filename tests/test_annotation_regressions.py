from __future__ import annotations

import unittest

from array_pipeline.annotation import _observation_status, check_coordinate


class AnnotationRegressionTest(unittest.TestCase):
    """One orientation implementation, and the structured refusals built on it."""
    def test_orientation_is_shared_by_qc_annotation_and_completeness(self):
        """QC, annotation and completeness share the same orientation function, not three copies."""
        from array_pipeline import annotation, completeness, qc

        self.assertIs(annotation._orientation, qc._orientation)
        self.assertIs(completeness._orientation, qc._orientation)

    def test_determinate_orientation_refusal_is_not_promoted_to_inferred(self):
        """A determinate orientation refusal is not promoted to INFERIDO."""
        self.assertEqual(
            _observation_status([{
                "orientation_operational_status": "NÃO DISPONÍVEL",
                "coordinate_operational_status": "VERIFICADO",
                "coordinate_reason_code": "COORDINATE_MATCH",
            }]),
            "NÃO DISPONÍVEL",
        )

    def test_missing_expected_position_is_a_domain_refusal_not_an_exception(self):
        """A missing expected position is a domain refusal, not an exception escaping the check."""
        result = check_coordinate(
            {"chromosome": "1", "position": "100"},
            {
                "rsid": "rs1",
                "coordinates": {
                    "status": "VERIFICADO",
                    "GRCh37": {"chromosome": "1"},
                },
            },
            "GRCh37",
        )
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertEqual(result["code"], "EXPECTED_POSITION_INVALID")

    def test_missing_expected_chromosome_is_not_blamed_on_the_patient_file(self):
        """A gap in our registry must not be published as a claim about the sample.

        With no chromosome in the registry the expected value collapsed to "", the
        comparison below failed, and the locus came back COORDINATE_MISMATCH — whose basis
        tells the reader the file is on another assembly or had its coordinate column
        rewritten. That is a causal statement about the patient's data, asserted from our
        own incomplete reference.
        """
        result = check_coordinate(
            {"chromosome": "7", "position": "99672916"},
            {
                "rsid": "rs776746",
                "coordinates": {
                    "status": "VERIFICADO",
                    "GRCh38": {"position": 99672916},
                },
            },
            "GRCh38",
        )
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertEqual(result["code"], "EXPECTED_CHROMOSOME_INVALID")
        self.assertNotIn("outra montagem", result["basis"])

    def test_registry_chromosome_prefix_is_normalized(self):
        """A 'chr' prefix in the registry coordinate is normalised before comparison."""
        result = check_coordinate(
            {"chromosome": "3", "position": "100"},
            {
                "rsid": "rs1",
                "coordinates": {
                    "status": "VERIFICADO",
                    "GRCh37": {"chromosome": "chr3", "position": 100},
                },
            },
            "GRCh37",
        )
        self.assertEqual(result["code"], "COORDINATE_MATCH")

    def test_ambiguous_registry_coordinate_is_inferred(self):
        """An ambiguous registry coordinate is INFERIDO."""
        self.assertEqual(
            _observation_status([{
                "orientation_operational_status": "VERIFICADO",
                "coordinate_operational_status": "NÃO DISPONÍVEL",
                "coordinate_reason_code": "AMBIGUOUS_COORDINATE",
            }]),
            "INFERIDO",
        )

    def test_missing_and_divergent_coordinates_have_distinct_structured_outcomes(self):
        """A missing coordinate and a divergent one produce distinct structured outcomes."""
        missing = _observation_status([{
            "orientation_operational_status": "VERIFICADO",
            "coordinate_operational_status": "NÃO DISPONÍVEL",
            "coordinate_reason_code": "BUILD_COORDINATE_MISSING",
        }])
        divergent = _observation_status([{
            "orientation_operational_status": "VERIFICADO",
            "coordinate_operational_status": "NÃO DISPONÍVEL",
            "coordinate_reason_code": "COORDINATE_MISMATCH",
        }])
        self.assertEqual(missing, "INFERIDO")
        self.assertEqual(divergent, "NÃO DISPONÍVEL")

    def test_a_registry_gap_grades_inferido_not_unavailable(self):
        """A gap in our reference data is not a finding against the patient's file.

        `EXPECTED_CHROMOSOME_INVALID` was added so that a registry with no chromosome would
        stop being published as a mismatch blamed on the patient's file. It was not added to
        the set of reason codes that grade INFERIDO, so it fell through to NÃO DISPONÍVEL —
        while its twin `EXPECTED_POSITION_INVALID` graded INFERIDO. The same gap in our own
        reference data produced two different verdicts about the sample, decided only by
        which field the registry happened to be missing.
        """
        for code in (
            "EXPECTED_POSITION_INVALID",
            "EXPECTED_CHROMOSOME_INVALID",
            # No verified build means no canonical block to compare against, so the file has
            # not been contradicted — same category, and it graded NÃO DISPONÍVEL alongside
            # COORDINATE_MISMATCH, which *is* a finding against the file.
            "BUILD_UNVERIFIED",
        ):
            with self.subTest(code=code):
                self.assertEqual(
                    _observation_status([{
                        "orientation_operational_status": "VERIFICADO",
                        "coordinate_operational_status": "NÃO DISPONÍVEL",
                        "coordinate_reason_code": code,
                    }]),
                    "INFERIDO",
                )


if __name__ == "__main__":
    unittest.main()
