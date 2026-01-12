"""
Tests for EVENT_KEY deduplication functionality.
"""
import unittest
import tempfile
import os
import pandas as pd
from src.pymaude import analysis_helpers


class TestEventKeyFunctions(unittest.TestCase):
    """Test EVENT_KEY utility functions."""

    def setUp(self):
        """Create test data with EVENT_KEY scenarios."""
        # Create test data with duplicated EVENT_KEYs
        self.test_data = pd.DataFrame({
            'MDR_REPORT_KEY': ['1', '2', '3', '4', '5', '6'],
            'EVENT_KEY': ['EVT001', 'EVT001', 'EVT002', 'EVT003', 'EVT003', 'EVT003'],
            'DATE_RECEIVED': pd.to_datetime([
                '2020-01-15', '2020-01-16', '2020-02-20',
                '2020-03-15', '2020-03-16', '2020-03-17'
            ]),
            'EVENT_TYPE': ['Injury', 'Injury', 'Malfunction', 'Death', 'Death', 'Death'],
            'MANUFACTURER_NAME': ['Test Mfg A', 'Test Mfg A', 'Test Mfg B',
                                 'Test Mfg C', 'Test Mfg C', 'Test Mfg C']
        })

    def test_count_unique_events_basic(self):
        """Test basic event counting with duplicates."""
        counts = analysis_helpers.count_unique_events(self.test_data)

        self.assertEqual(counts['total_reports'], 6)
        self.assertEqual(counts['unique_events'], 3)
        self.assertAlmostEqual(counts['duplication_rate'], 50.0, places=1)
        self.assertEqual(len(counts['multi_report_events']), 2)  # EVT001 and EVT003

    def test_count_unique_events_empty(self):
        """Test with empty DataFrame."""
        empty_df = pd.DataFrame()
        counts = analysis_helpers.count_unique_events(empty_df)

        self.assertEqual(counts['total_reports'], 0)
        self.assertEqual(counts['unique_events'], 0)
        self.assertEqual(counts['duplication_rate'], 0.0)

    def test_detect_multi_report_events(self):
        """Test detection of events with multiple reports."""
        multi_reports = analysis_helpers.detect_multi_report_events(self.test_data)

        self.assertEqual(len(multi_reports), 2)  # EVT001 and EVT003

        # Check EVT003 (has 3 reports)
        evt003 = multi_reports[multi_reports['EVENT_KEY'] == 'EVT003']
        self.assertEqual(evt003.iloc[0]['report_count'], 3)
        self.assertEqual(len(evt003.iloc[0]['mdr_report_keys']), 3)

    def test_select_primary_report_first_received(self):
        """Test selecting earliest report for each event."""
        deduplicated = analysis_helpers.select_primary_report(
            self.test_data, strategy='first_received'
        )

        self.assertEqual(len(deduplicated), 3)  # 3 unique events

        # Verify EVT001 kept earliest (MDR_REPORT_KEY='1')
        evt001 = deduplicated[deduplicated['EVENT_KEY'] == 'EVT001']
        self.assertEqual(evt001.iloc[0]['MDR_REPORT_KEY'], '1')

    def test_select_primary_report_most_complete(self):
        """Test selecting report with most non-null fields."""
        # Add some nulls to test completeness
        test_data = self.test_data.copy()
        test_data.loc[4, 'MANUFACTURER_NAME'] = None  # Make one report less complete

        deduplicated = analysis_helpers.select_primary_report(
            test_data, strategy='most_complete'
        )

        self.assertEqual(len(deduplicated), 3)

    def test_compare_report_vs_event_counts(self):
        """Test report vs event comparison."""
        comparison = analysis_helpers.compare_report_vs_event_counts(self.test_data)

        self.assertEqual(comparison['report_count'].iloc[0], 6)
        self.assertEqual(comparison['event_count'].iloc[0], 3)
        self.assertAlmostEqual(comparison['inflation_pct'].iloc[0], 100.0, places=1)

    def test_compare_report_vs_event_counts_grouped(self):
        """Test report vs event comparison with grouping."""
        # Add year column
        test_data = self.test_data.copy()
        test_data['year'] = test_data['DATE_RECEIVED'].dt.year

        comparison = analysis_helpers.compare_report_vs_event_counts(
            test_data, group_by='year'
        )

        self.assertEqual(len(comparison), 1)  # Only 2020
        self.assertIn('year', comparison.columns)


if __name__ == '__main__':
    unittest.main()
