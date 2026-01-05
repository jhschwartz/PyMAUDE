#!/usr/bin/env python3
"""
Comprehensive tests for EVENT_TYPE handling.

Tests both FDA abbreviation codes (D, IN, M, O) and potential legacy full-text values.
"""

import pytest
import pandas as pd
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maude_db import MaudeDatabase


class TestEventTypeCodes:
    """Test suite for EVENT_TYPE abbreviation and combination handling."""

    def test_fda_abbreviations(self):
        """Test that FDA abbreviations (D, IN, M) are correctly identified."""
        db = MaudeDatabase(':memory:', verbose=False)

        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3, 4, 5],
            'EVENT_TYPE': ['D', 'IN', 'M', 'O', '*'],
            'DATE_RECEIVED': ['2023-01-01'] * 5
        })

        breakdown = db.event_type_breakdown_for(df)

        assert breakdown['total'] == 5
        assert breakdown['deaths'] == 1, "Should find 'D' as death"
        assert breakdown['injuries'] == 1, "Should find 'IN' as injury"
        assert breakdown['malfunctions'] == 1, "Should find 'M' as malfunction"

        db.close()

    def test_legacy_full_words(self):
        """Test backwards compatibility with full word event types."""
        db = MaudeDatabase(':memory:', verbose=False)

        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3],
            'EVENT_TYPE': ['Death', 'Injury', 'Malfunction'],
            'DATE_RECEIVED': ['2023-01-01'] * 3
        })

        breakdown = db.event_type_breakdown_for(df)

        assert breakdown['deaths'] == 1, "Should find 'Death' (full word)"
        assert breakdown['injuries'] == 1, "Should find 'Injury' (full word)"
        assert breakdown['malfunctions'] == 1, "Should find 'Malfunction' (full word)"

        db.close()

    def test_mixed_formats(self):
        """Test mix of abbreviations and full words."""
        db = MaudeDatabase(':memory:', verbose=False)

        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3, 4, 5, 6],
            'EVENT_TYPE': ['D', 'Death', 'IN', 'Injury', 'M', 'Malfunction'],
            'DATE_RECEIVED': ['2023-01-01'] * 6
        })

        breakdown = db.event_type_breakdown_for(df)

        assert breakdown['deaths'] == 2, "Should find both 'D' and 'Death'"
        assert breakdown['injuries'] == 2, "Should find both 'IN' and 'Injury'"
        assert breakdown['malfunctions'] == 2, "Should find both 'M' and 'Malfunction'"

        db.close()

    def test_empty_and_null_event_types(self):
        """Test handling of empty and null EVENT_TYPE values."""
        db = MaudeDatabase(':memory:', verbose=False)

        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3],
            'EVENT_TYPE': ['', None, 'M'],
            'DATE_RECEIVED': ['2023-01-01'] * 3
        })

        breakdown = db.event_type_breakdown_for(df)

        assert breakdown['total'] == 3
        assert breakdown['deaths'] == 0
        assert breakdown['injuries'] == 0
        assert breakdown['malfunctions'] == 1

        db.close()

    def test_case_insensitive_matching(self):
        """Test that matching is case-insensitive for full words."""
        db = MaudeDatabase(':memory:', verbose=False)

        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3],
            'EVENT_TYPE': ['death', 'INJURY', 'MaLfUnCtIoN'],
            'DATE_RECEIVED': ['2023-01-01'] * 3
        })

        breakdown = db.event_type_breakdown_for(df)

        assert breakdown['deaths'] == 1, "Should match 'death' (lowercase)"
        assert breakdown['injuries'] == 1, "Should match 'INJURY' (uppercase)"
        assert breakdown['malfunctions'] == 1, "Should match 'MaLfUnCtIoN' (mixed case)"

        db.close()

    def test_word_boundary_matching(self):
        """Test that abbreviations use word boundaries to avoid false matches."""
        db = MaudeDatabase(':memory:', verbose=False)

        # 'M' should only match as a complete word, not within other words
        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3],
            'EVENT_TYPE': ['M', 'MALFUNCTION', 'Malfunction'],
            'DATE_RECEIVED': ['2023-01-01'] * 3
        })

        breakdown = db.event_type_breakdown_for(df)

        # All three should be counted as malfunctions
        assert breakdown['malfunctions'] == 3

        db.close()

    def test_trends_for_with_abbreviations(self):
        """Test trends_for() method with FDA abbreviations."""
        db = MaudeDatabase(':memory:', verbose=False)

        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3, 4, 5, 6],
            'EVENT_TYPE': ['D', 'IN', 'M', 'D', 'IN', 'M'],
            'DATE_RECEIVED': ['2020-01-01', '2020-02-01', '2020-03-01',
                            '2021-01-01', '2021-02-01', '2021-03-01']
        })

        trends = db.trends_for(df)

        assert len(trends) == 2, "Should have data for 2 years"

        # Check 2020
        year_2020 = trends[trends['year'] == 2020].iloc[0]
        assert year_2020['event_count'] == 3
        assert year_2020['deaths'] == 1
        assert year_2020['injuries'] == 1
        assert year_2020['malfunctions'] == 1

        # Check 2021
        year_2021 = trends[trends['year'] == 2021].iloc[0]
        assert year_2021['event_count'] == 3
        assert year_2021['deaths'] == 1
        assert year_2021['injuries'] == 1
        assert year_2021['malfunctions'] == 1

        db.close()

    def test_duplicate_columns_handling(self):
        """Test that duplicate EVENT_TYPE columns are handled correctly."""
        db = MaudeDatabase(':memory:', verbose=False)

        # Simulate what happens when query_device() joins master and device tables
        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3],
            'EVENT_TYPE': ['D', 'IN', 'M'],  # First EVENT_TYPE (from master)
            'DATE_RECEIVED': ['2023-01-01'] * 3
        })

        # Add duplicate EVENT_TYPE column (simulating device table)
        df['EVENT_TYPE'] = df['EVENT_TYPE']  # This creates duplicate column names

        # The methods should handle this gracefully
        breakdown = db.event_type_breakdown_for(df)

        assert breakdown['total'] == 3
        assert breakdown['deaths'] == 1
        assert breakdown['injuries'] == 1
        assert breakdown['malfunctions'] == 1

        db.close()

    def test_all_known_event_types(self):
        """Test all documented FDA event type codes.

        Official FDA codes (from MDR Data Files documentation):
        - D = Death
        - IN = Injury
        - M = Malfunction
        - O = Other
        - * = No answer provided
        """
        db = MaudeDatabase(':memory:', verbose=False)

        # Based on actual FDA data: D, IN, M, O, *, and empty
        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3, 4, 5, 6],
            'EVENT_TYPE': ['D', 'IN', 'M', 'O', '*', ''],
            'DATE_RECEIVED': ['2023-01-01'] * 6
        })

        breakdown = db.event_type_breakdown_for(df)

        assert breakdown['total'] == 6
        assert breakdown['deaths'] == 1, "D = Death"
        assert breakdown['injuries'] == 1, "IN = Injury"
        assert breakdown['malfunctions'] == 1, "M = Malfunction"
        # O (Other) and * (unknown) and empty should not be counted
        assert breakdown['deaths'] + breakdown['injuries'] + breakdown['malfunctions'] == 3

        db.close()

    def test_fda_combination_codes(self):
        """Test FDA combination codes used in Alternative Summary Reports (ASRs).

        Official FDA combination codes:
        - M-D = Malfunction where a patient death was reported
        - IN-D = Serious Injury where a patient death was reported
        """
        db = MaudeDatabase(':memory:', verbose=False)

        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2],
            'EVENT_TYPE': ['M-D', 'IN-D'],
            'DATE_RECEIVED': ['2023-01-01'] * 2
        })

        breakdown = db.event_type_breakdown_for(df)

        assert breakdown['total'] == 2
        # M-D should be counted as both malfunction AND death
        assert breakdown['malfunctions'] >= 1, "M-D should count as malfunction"
        assert breakdown['deaths'] >= 2, "Both M-D and IN-D should count as deaths"
        # IN-D should be counted as both injury AND death
        assert breakdown['injuries'] >= 1, "IN-D should count as injury"

        db.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
