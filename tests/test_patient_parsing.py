"""
Tests for patient OUTCOME/TREATMENT concatenation handling.
"""
import unittest
import tempfile
import os
import pandas as pd
from src.pymaude import analysis_helpers


class TestPatientConcatenation(unittest.TestCase):
    """Test patient OUTCOME/TREATMENT concatenation detection and handling."""

    def setUp(self):
        """Create test data with multi-patient concatenation scenarios."""
        # Create patient data demonstrating concatenation issue
        # Pattern: Patient 1: D, Patient 2: D;H, Patient 3: D;H;L
        self.test_data = pd.DataFrame({
            'MDR_REPORT_KEY': ['1111111', '1111111', '1111111', '2222222', '3333333', '3333333'],
            'PATIENT_SEQUENCE_NUMBER': [1, 2, 3, 1, 1, 2],
            'SEQUENCE_NUMBER_OUTCOME': ['D', 'D;H', 'D;H;L', 'H', 'S', 'S;R'],
            'SEQUENCE_NUMBER_TREATMENT': ['1', '1;2', '1;2;3', '1', '1', '1;2']
        })

    def test_detect_multi_patient_reports_basic(self):
        """Test detection of reports with multiple patients."""
        result = analysis_helpers.detect_multi_patient_reports(self.test_data)

        self.assertEqual(result['total_reports'], 3)
        self.assertEqual(result['multi_patient_reports'], 2)  # 1111111 and 3333333
        self.assertAlmostEqual(result['affected_percentage'], 66.7, places=1)
        self.assertIn('1111111', result['affected_mdr_keys'])
        self.assertIn('3333333', result['affected_mdr_keys'])

    def test_detect_multi_patient_reports_empty(self):
        """Test with empty DataFrame."""
        empty_df = pd.DataFrame()
        result = analysis_helpers.detect_multi_patient_reports(empty_df)

        self.assertEqual(result['total_reports'], 0)
        self.assertEqual(result['multi_patient_reports'], 0)
        self.assertEqual(result['affected_percentage'], 0.0)

    def test_detect_multi_patient_reports_single_patients(self):
        """Test with only single-patient reports."""
        single_patient_df = self.test_data[self.test_data['MDR_REPORT_KEY'] == '2222222'].copy()
        result = analysis_helpers.detect_multi_patient_reports(single_patient_df)

        self.assertEqual(result['total_reports'], 1)
        self.assertEqual(result['multi_patient_reports'], 0)
        self.assertEqual(result['affected_percentage'], 0.0)

    def test_count_unique_outcomes_per_report(self):
        """Test accurate outcome counting despite concatenation."""
        result = analysis_helpers.count_unique_outcomes_per_report(self.test_data)

        # Report 1111111 should have 3 unique outcomes: D, H, L
        report1 = result[result['MDR_REPORT_KEY'] == '1111111']
        self.assertEqual(report1.iloc[0]['patient_count'], 3)
        self.assertEqual(set(report1.iloc[0]['unique_outcomes']), {'D', 'H', 'L'})
        self.assertEqual(report1.iloc[0]['outcome_counts']['D'], 1)
        self.assertEqual(report1.iloc[0]['outcome_counts']['H'], 1)
        self.assertEqual(report1.iloc[0]['outcome_counts']['L'], 1)

        # Report 2222222 should have 1 outcome: H
        report2 = result[result['MDR_REPORT_KEY'] == '2222222']
        self.assertEqual(report2.iloc[0]['patient_count'], 1)
        self.assertEqual(set(report2.iloc[0]['unique_outcomes']), {'H'})

        # Report 3333333 should have 2 outcomes: S, R
        report3 = result[result['MDR_REPORT_KEY'] == '3333333']
        self.assertEqual(report3.iloc[0]['patient_count'], 2)
        self.assertEqual(set(report3.iloc[0]['unique_outcomes']), {'S', 'R'})

    def test_count_unique_outcomes_empty(self):
        """Test with empty DataFrame."""
        empty_df = pd.DataFrame()
        result = analysis_helpers.count_unique_outcomes_per_report(empty_df)

        self.assertTrue(result.empty)

    def test_count_unique_outcomes_missing_column(self):
        """Test handling of missing SEQUENCE_NUMBER_OUTCOME column."""
        df_no_outcome = self.test_data.drop(columns=['SEQUENCE_NUMBER_OUTCOME'])

        with self.assertRaises(ValueError):
            analysis_helpers.count_unique_outcomes_per_report(df_no_outcome)

    def test_outcome_counting_inflation_prevented(self):
        """Test that concatenation doesn't inflate outcome counts."""
        # WRONG way - naive counting (would count D three times for report 1111111)
        naive_df = self.test_data.copy()
        naive_df['outcome_list'] = naive_df['SEQUENCE_NUMBER_OUTCOME'].apply(
            lambda x: [c.strip() for c in str(x).split(';') if c.strip()]
        )
        naive_death_count = sum(
            'D' in outcomes for outcomes in naive_df['outcome_list']
        )

        # CORRECT way - unique per report
        outcome_summary = analysis_helpers.count_unique_outcomes_per_report(self.test_data)
        correct_death_count = sum(
            'D' in outcomes for outcomes in outcome_summary['unique_outcomes']
        )

        # Naive method should overcount
        self.assertGreater(naive_death_count, correct_death_count)
        self.assertEqual(correct_death_count, 1)  # Only report 1111111 has death
        self.assertEqual(naive_death_count, 3)  # Naive counts D three times

    def test_multiple_outcomes_same_patient(self):
        """Test handling of multiple outcomes for same patient (not concatenation)."""
        # Some reports may have genuine multiple outcomes per patient
        test_data = pd.DataFrame({
            'MDR_REPORT_KEY': ['4444444'],
            'PATIENT_SEQUENCE_NUMBER': [1],
            'SEQUENCE_NUMBER_OUTCOME': ['D;H;L']  # One patient with 3 outcomes
        })

        result = analysis_helpers.count_unique_outcomes_per_report(test_data)

        report = result.iloc[0]
        self.assertEqual(report['patient_count'], 1)
        self.assertEqual(set(report['unique_outcomes']), {'D', 'H', 'L'})

    def test_null_outcomes(self):
        """Test handling of null/empty outcome values."""
        test_data = pd.DataFrame({
            'MDR_REPORT_KEY': ['5555555', '5555555', '6666666'],
            'PATIENT_SEQUENCE_NUMBER': [1, 2, 1],
            'SEQUENCE_NUMBER_OUTCOME': ['D', '', None]
        })

        result = analysis_helpers.count_unique_outcomes_per_report(test_data)

        # Report 5555555 should only count 'D' (empty string ignored)
        report1 = result[result['MDR_REPORT_KEY'] == '5555555']
        self.assertEqual(set(report1.iloc[0]['unique_outcomes']), {'D'})

        # Report 6666666 with None should have empty list
        report2 = result[result['MDR_REPORT_KEY'] == '6666666']
        self.assertEqual(len(report2.iloc[0]['unique_outcomes']), 0)

    def test_whitespace_handling(self):
        """Test proper handling of whitespace in outcome codes."""
        test_data = pd.DataFrame({
            'MDR_REPORT_KEY': ['7777777'],
            'PATIENT_SEQUENCE_NUMBER': [1],
            'SEQUENCE_NUMBER_OUTCOME': ['D ; H ; L']  # Spaces around semicolons
        })

        result = analysis_helpers.count_unique_outcomes_per_report(test_data)

        report = result.iloc[0]
        # Should strip whitespace and get clean codes
        self.assertEqual(set(report['unique_outcomes']), {'D', 'H', 'L'})


if __name__ == '__main__':
    unittest.main()
