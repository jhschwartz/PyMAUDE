#!/usr/bin/env python3
"""
Tests for get_trends_by_year() DataFrame-only functionality.

Tests cover:
- Basic DataFrame input (no search_group)
- Grouped search results (with search_group column)
- Empty DataFrame handling
- Invalid input validation
- Missing DATE_RECEIVED column

Author: Jacob Schwartz <jaschwa@umich.edu>
Copyright: 2026, GNU GPL v3
"""

import pytest
import pandas as pd
import sqlite3
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymaude import MaudeDatabase


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary database file path."""
    return str(tmp_path / "test_trends.db")


@pytest.fixture
def db_with_test_data(temp_db_path):
    """Create a real database with test data for trends testing."""
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    # Create minimal master table
    cursor.execute('''
        CREATE TABLE master (
            MDR_REPORT_KEY INTEGER PRIMARY KEY,
            EVENT_KEY TEXT,
            DATE_RECEIVED TEXT,
            EVENT_TYPE TEXT,
            ROWID INTEGER
        )
    ''')

    # Create device table
    cursor.execute('''
        CREATE TABLE device (
            MDR_REPORT_KEY INTEGER,
            BRAND_NAME TEXT,
            GENERIC_NAME TEXT,
            MANUFACTURER_D_NAME TEXT,
            DEVICE_REPORT_PRODUCT_CODE TEXT,
            ROWID INTEGER
        )
    ''')

    # Insert test data - various years and devices
    master_data = [
        # 2020 data
        (1001, 'EVT001', '2020-01-15', 'M'),
        (1002, 'EVT002', '2020-06-20', 'IN'),
        (1003, 'EVT003', '2020-12-10', 'D'),
        # 2021 data
        (1004, 'EVT004', '2021-03-05', 'M'),
        (1005, 'EVT005', '2021-09-12', 'IN'),
        # 2022 data
        (1006, 'EVT006', '2022-02-18', 'M'),
        (1007, 'EVT007', '2022-07-22', 'M'),
        (1008, 'EVT008', '2022-11-30', 'D'),
    ]

    device_data = [
        # Argon devices
        (1001, 'ARGON CLEANER', 'THROMBECTOMY CATHETER', 'ARGON MEDICAL', 'DQY'),
        (1002, 'ARGON CLEANER PRO', 'THROMBECTOMY CATHETER', 'ARGON MEDICAL', 'DQY'),
        (1003, 'ARGON BALLOON', 'BALLOON CATHETER', 'ARGON MEDICAL', 'DTK'),
        # Penumbra devices
        (1004, 'PENUMBRA INDIGO', 'ASPIRATION CATHETER', 'PENUMBRA INC', 'DQY'),
        (1005, 'PENUMBRA LIGHTNING', 'ASPIRATION CATHETER', 'PENUMBRA INC', 'DQY'),
        # More Argon
        (1006, 'ARGON CLEANER XT', 'THROMBECTOMY CATHETER', 'ARGON MEDICAL', 'DQY'),
        (1007, 'ARGON CLEANER', 'THROMBECTOMY CATHETER', 'ARGON MEDICAL', 'DQY'),
        # Generic device
        (1008, 'GENERIC DEVICE', 'CATHETER', 'GENERIC MANUFACTURER', 'BWD'),
    ]

    cursor.executemany(
        'INSERT INTO master VALUES (?, ?, ?, ?, NULL)',
        master_data
    )
    cursor.executemany(
        'INSERT INTO device VALUES (?, ?, ?, ?, ?, NULL)',
        device_data
    )

    # Create ROWIDs
    conn.execute("UPDATE master SET ROWID = MDR_REPORT_KEY")
    conn.execute("UPDATE device SET ROWID = MDR_REPORT_KEY")

    conn.commit()
    conn.close()

    # Return a MaudeDatabase instance with search index
    db = MaudeDatabase(temp_db_path, verbose=False)
    db.create_search_index()
    return db


# ==================== Basic Functionality Tests ====================

class TestBasicTrends:
    """Tests for basic trends functionality."""

    def test_trends_from_search_results(self, db_with_test_data):
        """Test get_trends_by_year with search results (no grouping)."""
        # Get all Argon devices
        results = db_with_test_data.search_by_device_names('argon')
        trends = db_with_test_data.get_trends_by_year(results)

        # Should have trends for 2020 and 2022 (no Argon devices in 2021)
        assert len(trends) == 2
        assert 'year' in trends.columns
        assert 'event_count' in trends.columns
        assert 'search_group' not in trends.columns  # No grouping

        # Check specific years
        assert 2020 in trends['year'].values
        assert 2022 in trends['year'].values
        assert 2021 not in trends['year'].values  # No Argon devices in 2021

        # 2020: 3 Argon devices (1001, 1002, 1003)
        # 2021: 0 Argon devices (not in trends)
        # 2022: 2 Argon devices (1006, 1007)
        y2020 = trends[trends['year'] == 2020]['event_count'].iloc[0]
        y2022 = trends[trends['year'] == 2022]['event_count'].iloc[0]
        assert y2020 == 3  # All 3 Argon devices in 2020
        assert y2022 == 2  # 2 Argon devices in 2022

    def test_trends_from_exact_query(self, db_with_test_data):
        """Test get_trends_by_year with exact query results."""
        # Query by product code
        results = db_with_test_data.query_device(product_code='DQY')
        trends = db_with_test_data.get_trends_by_year(results)

        # DQY devices: 1001, 1002, 1004, 1005, 1006, 1007
        # 2020: 2 (1001, 1002)
        # 2021: 2 (1004, 1005)
        # 2022: 2 (1006, 1007)
        assert len(trends) == 3
        assert all(trends['event_count'] == 2)  # 2 events per year


# ==================== Grouped Search Tests ====================

class TestGroupedTrends:
    """Tests for trends with grouped search results."""

    def test_trends_with_search_group_column(self, db_with_test_data):
        """Test that trends respect search_group column."""
        # Grouped search
        results = db_with_test_data.search_by_device_names({
            'argon': 'argon',
            'penumbra': 'penumbra'
        })

        trends = db_with_test_data.get_trends_by_year(results)

        # Should have search_group column
        assert 'search_group' in trends.columns
        assert 'year' in trends.columns
        assert 'event_count' in trends.columns

        # Check that both groups appear
        groups = set(trends['search_group'].unique())
        assert 'argon' in groups
        assert 'penumbra' in groups

        # Check Argon trends
        argon_trends = trends[trends['search_group'] == 'argon']
        assert len(argon_trends) == 2  # 2020 and 2022 only (no Argon in 2021)
        assert 2020 in argon_trends['year'].values
        assert 2022 in argon_trends['year'].values
        assert 2021 not in argon_trends['year'].values  # No Argon devices in 2021

        # Check Penumbra trends
        penumbra_trends = trends[trends['search_group'] == 'penumbra']
        assert len(penumbra_trends) == 1  # Only 2021
        assert 2021 in penumbra_trends['year'].values
        assert penumbra_trends[penumbra_trends['year'] == 2021]['event_count'].iloc[0] == 2

    def test_trends_single_group_filtered(self, db_with_test_data):
        """Test trends for single group from grouped search."""
        # Grouped search
        results = db_with_test_data.search_by_device_names({
            'argon': 'argon',
            'penumbra': 'penumbra'
        })

        # Filter to just Argon group
        argon_only = results[results['search_group'] == 'argon']
        trends = db_with_test_data.get_trends_by_year(argon_only)

        # Should still have search_group column (from original DataFrame)
        assert 'search_group' in trends.columns
        assert all(trends['search_group'] == 'argon')


# ==================== Validation Tests ====================

class TestValidation:
    """Tests for input validation."""

    def test_non_dataframe_raises_error(self, db_with_test_data):
        """Test that non-DataFrame input raises TypeError."""
        with pytest.raises(TypeError, match="must be a pandas DataFrame"):
            db_with_test_data.get_trends_by_year("not a dataframe")

        with pytest.raises(TypeError, match="must be a pandas DataFrame"):
            db_with_test_data.get_trends_by_year([1, 2, 3])

    def test_missing_date_column_raises_error(self, db_with_test_data):
        """Test that DataFrame without DATE_RECEIVED raises ValueError."""
        # Create DataFrame without DATE_RECEIVED
        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3],
            'BRAND_NAME': ['A', 'B', 'C']
        })

        with pytest.raises(ValueError, match="must contain DATE_RECEIVED column"):
            db_with_test_data.get_trends_by_year(df)

    def test_empty_dataframe_returns_empty_trends(self, db_with_test_data):
        """Test that empty DataFrame returns empty trends with correct structure."""
        # Create empty DataFrame with DATE_RECEIVED column
        df = pd.DataFrame(columns=['DATE_RECEIVED', 'MDR_REPORT_KEY'])

        trends = db_with_test_data.get_trends_by_year(df)

        # Should return empty DataFrame with correct columns
        assert len(trends) == 0
        assert 'year' in trends.columns
        assert 'event_count' in trends.columns

    def test_empty_grouped_dataframe(self, db_with_test_data):
        """Test empty DataFrame with search_group column."""
        df = pd.DataFrame(columns=['DATE_RECEIVED', 'MDR_REPORT_KEY', 'search_group'])

        trends = db_with_test_data.get_trends_by_year(df)

        assert len(trends) == 0
        assert 'year' in trends.columns
        assert 'search_group' in trends.columns
        assert 'event_count' in trends.columns


# ==================== Edge Cases ====================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_trends_sorted_by_year(self, db_with_test_data):
        """Test that trends are sorted by year."""
        results = db_with_test_data.search_by_device_names('argon')
        trends = db_with_test_data.get_trends_by_year(results)

        # Check that years are in ascending order
        years = trends['year'].tolist()
        assert years == sorted(years)

    def test_trends_sorted_by_group_and_year(self, db_with_test_data):
        """Test that grouped trends are sorted correctly."""
        results = db_with_test_data.search_by_device_names({
            'zulu': 'penumbra',  # Z to test sorting
            'alpha': 'argon'     # A to test sorting
        })

        trends = db_with_test_data.get_trends_by_year(results)

        # Check that results are sorted by search_group, then year
        groups = trends['search_group'].tolist()
        # Should be alpha entries first, then zulu entries
        assert groups[0] == 'alpha'
        assert groups[-1] == 'zulu'

    def test_single_year_trends(self, db_with_test_data):
        """Test trends when all events are in same year."""
        # Query Penumbra devices (all in 2021)
        results = db_with_test_data.search_by_device_names('penumbra')
        trends = db_with_test_data.get_trends_by_year(results)

        assert len(trends) == 1
        assert trends.iloc[0]['year'] == 2021
        assert trends.iloc[0]['event_count'] == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
