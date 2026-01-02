#!/usr/bin/env python3
"""
Tests for helper query methods that operate on DataFrames.
"""

import pytest
import pandas as pd
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maude_db import MaudeDatabase


@pytest.fixture
def sample_results_df():
    """Create a sample DataFrame that mimics query_device() output."""
    return pd.DataFrame({
        'MDR_REPORT_KEY': [1001, 1002, 1003, 1004, 1005],
        'DATE_RECEIVED': ['2020-01-15', '2020-03-20', '2021-05-10', '2021-08-12', '2022-02-01'],
        'EVENT_TYPE': ['Death', 'Injury', 'Malfunction', 'Injury;Death', 'Malfunction'],
        'MANUFACTURER_D_NAME': ['Company A', 'Company B', 'Company A', 'Company A', 'Company C'],
        'GENERIC_NAME': ['Device X', 'Device Y', 'Device X', 'Device Z', 'Device Y'],
        'BRAND_NAME': ['Brand 1', 'Brand 2', 'Brand 1', 'Brand 3', 'Brand 2']
    })


class TestHelperMethods:
    """Test suite for DataFrame helper methods."""

    def test_event_type_breakdown_for(self, sample_results_df):
        """Test event type breakdown calculation."""
        db = MaudeDatabase(':memory:', verbose=False)

        breakdown = db.event_type_breakdown_for(sample_results_df)

        assert breakdown['total'] == 5
        assert breakdown['deaths'] >= 1  # At least 1 death
        assert breakdown['injuries'] >= 1  # At least 1 injury
        assert breakdown['malfunctions'] >= 1  # At least 1 malfunction
        assert all(isinstance(v, int) for v in breakdown.values())

        db.close()

    def test_event_type_breakdown_missing_column(self):
        """Test that missing EVENT_TYPE column raises error."""
        db = MaudeDatabase(':memory:', verbose=False)
        df = pd.DataFrame({'MDR_REPORT_KEY': [1, 2, 3]})

        with pytest.raises(ValueError, match="must contain 'EVENT_TYPE'"):
            db.event_type_breakdown_for(df)

        db.close()

    def test_trends_for(self, sample_results_df):
        """Test yearly trends calculation."""
        db = MaudeDatabase(':memory:', verbose=False)

        trends = db.trends_for(sample_results_df)

        # Should have 3 years (2020, 2021, 2022)
        assert len(trends) == 3
        assert 'year' in trends.columns
        assert 'event_count' in trends.columns
        assert 'deaths' in trends.columns
        assert 'injuries' in trends.columns
        assert 'malfunctions' in trends.columns

        # Check 2020 has 2 events
        year_2020 = trends[trends['year'] == 2020]
        assert len(year_2020) == 1
        assert year_2020.iloc[0]['event_count'] == 2

        db.close()

    def test_trends_for_missing_columns(self):
        """Test that missing required columns raises error."""
        db = MaudeDatabase(':memory:', verbose=False)
        df = pd.DataFrame({'MDR_REPORT_KEY': [1, 2, 3]})

        with pytest.raises(ValueError, match="missing required columns"):
            db.trends_for(df)

        db.close()

    def test_top_manufacturers_for(self, sample_results_df):
        """Test top manufacturers extraction."""
        db = MaudeDatabase(':memory:', verbose=False)

        top_mfg = db.top_manufacturers_for(sample_results_df, n=2)

        assert len(top_mfg) == 2
        assert 'manufacturer' in top_mfg.columns
        assert 'event_count' in top_mfg.columns

        # Company A should be first (3 events)
        assert top_mfg.iloc[0]['manufacturer'] == 'Company A'
        assert top_mfg.iloc[0]['event_count'] == 3

        db.close()

    def test_top_manufacturers_for_missing_column(self):
        """Test that missing MANUFACTURER_D_NAME column raises error."""
        db = MaudeDatabase(':memory:', verbose=False)
        df = pd.DataFrame({'MDR_REPORT_KEY': [1, 2, 3]})

        with pytest.raises(ValueError, match="must contain 'MANUFACTURER_D_NAME'"):
            db.top_manufacturers_for(df)

        db.close()

    def test_date_range_summary_for(self, sample_results_df):
        """Test date range summary calculation."""
        db = MaudeDatabase(':memory:', verbose=False)

        summary = db.date_range_summary_for(sample_results_df)

        assert 'first_date' in summary
        assert 'last_date' in summary
        assert 'total_days' in summary
        assert 'total_records' in summary

        assert summary['first_date'] == '2020-01-15'
        assert summary['last_date'] == '2022-02-01'
        assert summary['total_records'] == 5
        assert summary['total_days'] > 0

        db.close()

    def test_date_range_summary_missing_column(self):
        """Test that missing DATE_RECEIVED column raises error."""
        db = MaudeDatabase(':memory:', verbose=False)
        df = pd.DataFrame({'MDR_REPORT_KEY': [1, 2, 3]})

        with pytest.raises(ValueError, match="must contain 'DATE_RECEIVED'"):
            db.date_range_summary_for(df)

        db.close()

    def test_get_narratives_for_missing_column(self):
        """Test that missing MDR_REPORT_KEY column raises error."""
        db = MaudeDatabase(':memory:', verbose=False)
        df = pd.DataFrame({'SOME_OTHER_COLUMN': [1, 2, 3]})

        with pytest.raises(ValueError, match="must contain 'MDR_REPORT_KEY'"):
            db.get_narratives_for(df)

        db.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
