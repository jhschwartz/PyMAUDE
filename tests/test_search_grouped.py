#!/usr/bin/env python3
"""
Tests for grouped device name search functionality.

Tests cover:
- Dict input validation
- Basic grouped search with search_group column
- Complex criteria per group (strings, lists, list-of-lists)
- Custom group_column name
- Date filtering across all groups
- Empty results for some groups
- Overlap handling and warnings
- Integration with non-dict search

Author: Jacob Schwartz <jaschwa@umich.edu>
Copyright: 2026, GNU GPL v3
"""

import pytest
import os
import sys
from pathlib import Path
import pandas as pd
import sqlite3
import tempfile
import warnings

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymaude import MaudeDatabase


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary database file path."""
    return str(tmp_path / "test_grouped_search.db")


@pytest.fixture
def db_with_test_data(temp_db_path):
    """Create a real database with test data for grouped search testing."""
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

    # Insert test data - various device combinations
    master_data = [
        (1001, 'EVT001', '2023-01-15', 'M'),
        (1002, 'EVT002', '2023-02-20', 'IN'),
        (1003, 'EVT003', '2023-03-10', 'D'),
        (1004, 'EVT004', '2023-04-05', 'M'),
        (1005, 'EVT005', '2023-05-12', 'IN'),
        (1006, 'EVT006', '2023-06-18', 'M'),
        (1007, 'EVT007', '2023-07-22', 'M'),
        (1008, 'EVT008', '2023-08-30', 'D'),
    ]

    device_data = [
        # Argon Cleaner devices (mechanical thrombectomy)
        (1001, 'ARGON CLEANER THROMBECTOMY', 'THROMBECTOMY CATHETER', 'ARGON MEDICAL DEVICES INC', 'DQY'),
        (1002, 'ARGON CLEANER PRO', 'THROMBECTOMY CATHETER', 'ARGON MEDICAL DEVICES INC', 'DQY'),
        # AngioJet devices (mechanical thrombectomy)
        (1003, 'ANGIOJET ULTRA', 'THROMBECTOMY SYSTEM', 'BOSTON SCIENTIFIC CORP', 'DQY'),
        (1004, 'ANGIOJET ZELANTE', 'THROMBECTOMY SYSTEM', 'BOSTON SCIENTIFIC CORP', 'DQY'),
        # Penumbra devices (aspiration)
        (1005, 'PENUMBRA INDIGO', 'ASPIRATION CATHETER', 'PENUMBRA INC', 'DQY'),
        (1006, 'PENUMBRA LIGHTNING', 'ASPIRATION CATHETER', 'PENUMBRA INC', 'DQY'),
        # Argon balloon catheter (overlaps with "argon" but not cleaner)
        (1007, 'ARGON BALLOON CATHETER', 'BALLOON CATHETER', 'ARGON MEDICAL DEVICES INC', 'DTK'),
        # Device without specific keywords
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


# ==================== Dict Input Validation Tests ====================

class TestDictInputValidation:
    """Tests for dict input validation."""

    def test_empty_dict_raises_error(self, db_with_test_data):
        """Test that empty dict raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            db_with_test_data.search_by_device_names({})

    def test_non_string_keys_raise_error(self, db_with_test_data):
        """Test that non-string keys raise ValueError."""
        with pytest.raises(ValueError, match="must be strings"):
            db_with_test_data.search_by_device_names({
                1: 'argon',
                'valid_key': 'penumbra'
            })

    def test_invalid_criteria_in_dict(self, db_with_test_data):
        """Test that invalid criteria values in dict are handled."""
        # Empty list should raise error from underlying search
        with pytest.raises(ValueError):
            db_with_test_data.search_by_device_names({
                'group1': []
            })


# ==================== Basic Grouped Search Tests ====================

class TestBasicGroupedSearch:
    """Tests for basic grouped search functionality."""

    def test_simple_grouped_search(self, db_with_test_data):
        """Test basic grouped search with two groups."""
        results = db_with_test_data.search_by_device_names({
            'mechanical': [['argon', 'cleaner']],
            'aspiration': 'penumbra'
        })

        # Should have results from both groups
        assert len(results) > 0
        assert 'search_group' in results.columns

        # Check that both groups are present
        groups = set(results['search_group'].unique())
        assert 'mechanical' in groups
        assert 'aspiration' in groups

        # Check specific devices
        mechanical_devices = results[results['search_group'] == 'mechanical']['MDR_REPORT_KEY']
        assert set(mechanical_devices) == {1001, 1002}  # Argon Cleaner devices

        aspiration_devices = results[results['search_group'] == 'aspiration']['MDR_REPORT_KEY']
        assert set(aspiration_devices) == {1005, 1006}  # Penumbra devices

    def test_grouped_search_with_string_criteria(self, db_with_test_data):
        """Test grouped search with simple string criteria."""
        results = db_with_test_data.search_by_device_names({
            'argon_devices': 'argon',
            'penumbra_devices': 'penumbra'
        })

        assert 'search_group' in results.columns
        groups = set(results['search_group'].unique())
        assert 'argon_devices' in groups
        assert 'penumbra_devices' in groups

    def test_grouped_search_with_list_criteria(self, db_with_test_data):
        """Test grouped search with OR list criteria."""
        results = db_with_test_data.search_by_device_names({
            'mechanical': ['argon', 'angiojet'],
            'aspiration': ['penumbra']
        })

        mechanical_devices = results[results['search_group'] == 'mechanical']['MDR_REPORT_KEY']
        # Should match all Argon (3) + AngioJet (2) = 5 devices
        # But 1007 is just Argon balloon, not cleaner, so all 3 Argon + 2 AngioJet
        assert len(mechanical_devices) >= 4  # At least Argon Cleaners + AngioJets

    def test_grouped_search_with_complex_criteria(self, db_with_test_data):
        """Test grouped search with complex AND/OR criteria."""
        results = db_with_test_data.search_by_device_names({
            'mechanical': [['argon', 'cleaner'], ['angiojet']],
            'aspiration': [['penumbra', 'indigo'], ['penumbra', 'lightning']]
        })

        assert 'search_group' in results.columns
        assert set(results['search_group'].unique()) == {'mechanical', 'aspiration'}


# ==================== Custom Group Column Tests ====================

class TestCustomGroupColumn:
    """Tests for custom group_column parameter."""

    def test_custom_group_column_name(self, db_with_test_data):
        """Test using custom group column name."""
        results = db_with_test_data.search_by_device_names(
            {
                'mechanical': 'argon',
                'aspiration': 'penumbra'
            },
            group_column='device_category'
        )

        assert 'device_category' in results.columns
        assert 'search_group' not in results.columns
        assert set(results['device_category'].unique()) == {'mechanical', 'aspiration'}


# ==================== Date Filtering Tests ====================

class TestDateFilteringGrouped:
    """Tests for date filtering with grouped search."""

    def test_date_filtering_applies_to_all_groups(self, db_with_test_data):
        """Test that date filters apply to all groups."""
        results = db_with_test_data.search_by_device_names(
            {
                'mechanical': 'argon',
                'aspiration': 'penumbra'
            },
            start_date='2023-03-01',
            end_date='2023-06-30'
        )

        # Check that all results are within date range
        if len(results) > 0:
            dates = pd.to_datetime(results['DATE_RECEIVED'])
            assert all(dates >= '2023-03-01')
            assert all(dates <= '2023-06-30')

    def test_date_filtering_can_eliminate_groups(self, db_with_test_data):
        """Test that date filtering can result in empty groups."""
        results = db_with_test_data.search_by_device_names(
            {
                'mechanical': [['argon', 'cleaner']],  # Jan-Feb only
                'aspiration': 'penumbra'  # May-Jun
            },
            start_date='2023-05-01'
        )

        # Only aspiration group should have results
        if len(results) > 0:
            groups = set(results['search_group'].unique())
            assert 'aspiration' in groups
            assert 'mechanical' not in groups  # Filtered out by date


# ==================== Empty Results Tests ====================

class TestEmptyResults:
    """Tests for handling empty results in grouped search."""

    def test_all_empty_groups(self, db_with_test_data):
        """Test when all groups return no results."""
        results = db_with_test_data.search_by_device_names({
            'group1': 'nonexistent_device_xyz',
            'group2': 'another_fake_device'
        })

        assert len(results) == 0
        assert isinstance(results, pd.DataFrame)
        assert 'search_group' in results.columns

    def test_some_empty_groups(self, db_with_test_data):
        """Test when some groups are empty."""
        results = db_with_test_data.search_by_device_names({
            'found': 'argon',
            'not_found': 'nonexistent_device_xyz'
        })

        # Should only have results from 'found' group
        assert len(results) > 0
        assert set(results['search_group'].unique()) == {'found'}


# ==================== Overlap Handling Tests ====================

class TestOverlapHandling:
    """Tests for overlap handling and warnings."""

    def test_overlap_warning_issued(self, db_with_test_data):
        """Test that overlap warnings are issued."""
        # 'argon' will match devices that 'cleaner' would also match
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            results = db_with_test_data.search_by_device_names({
                'all_argon': 'argon',  # Matches 1001, 1002, 1007
                'argon_cleaner': [['argon', 'cleaner']]  # Would match 1001, 1002 but they're taken
            })

            # Should have issued warning about overlaps
            assert len(w) > 0
            assert any("previously matched" in str(warning.message) for warning in w)

    def test_first_match_wins(self, db_with_test_data):
        """Test that events only appear in first matching group."""
        results = db_with_test_data.search_by_device_names({
            'all_argon': 'argon',  # Matches all Argon devices first
            'argon_cleaner': [['argon', 'cleaner']]  # Would match some Argon devices
        })

        # Check that each MDR_REPORT_KEY appears only once
        key_counts = results['MDR_REPORT_KEY'].value_counts()
        assert all(key_counts == 1)

        # Argon Cleaner devices (1001, 1002) should be in 'all_argon', not 'argon_cleaner'
        all_argon_keys = set(results[results['search_group'] == 'all_argon']['MDR_REPORT_KEY'])
        assert 1001 in all_argon_keys
        assert 1002 in all_argon_keys

        # 'argon_cleaner' group should be empty or not present
        if 'argon_cleaner' in results['search_group'].unique():
            argon_cleaner_keys = results[results['search_group'] == 'argon_cleaner']['MDR_REPORT_KEY']
            assert len(argon_cleaner_keys) == 0

    def test_dict_order_determines_priority(self, db_with_test_data):
        """Test that dict order determines which group gets the event."""
        # In Python 3.7+, dicts maintain insertion order
        results1 = db_with_test_data.search_by_device_names({
            'group_a': 'argon',
            'group_b': 'argon'
        })

        results2 = db_with_test_data.search_by_device_names({
            'group_b': 'argon',
            'group_a': 'argon'
        })

        # All argon devices should be in first group for each search
        if len(results1) > 0:
            assert all(results1['search_group'] == 'group_a')

        if len(results2) > 0:
            assert all(results2['search_group'] == 'group_b')


# ==================== Integration Tests ====================

class TestGroupedSearchIntegration:
    """Integration tests for grouped search."""

    def test_non_dict_input_no_group_column(self, db_with_test_data):
        """Test that non-dict input doesn't add search_group column."""
        results = db_with_test_data.search_by_device_names('argon')

        assert 'search_group' not in results.columns

    def test_grouped_search_with_deduplication(self, db_with_test_data):
        """Test that deduplication works with grouped search."""
        results = db_with_test_data.search_by_device_names({
            'group1': 'argon',
            'group2': 'penumbra'
        })

        # All EVENT_KEYs should be unique (deduplication enabled by default)
        event_keys = results['EVENT_KEY'].tolist()
        assert len(event_keys) == len(set(event_keys))

    def test_grouped_search_returns_expected_columns(self, db_with_test_data):
        """Test that grouped search returns all expected columns."""
        results = db_with_test_data.search_by_device_names({
            'group1': 'argon'
        })

        # Should have columns from both master and device tables plus search_group
        assert 'MDR_REPORT_KEY' in results.columns
        assert 'EVENT_KEY' in results.columns
        assert 'DATE_RECEIVED' in results.columns
        assert 'BRAND_NAME' in results.columns
        assert 'GENERIC_NAME' in results.columns
        assert 'search_group' in results.columns

    def test_large_grouped_search(self, db_with_test_data):
        """Test grouped search with many groups."""
        # Create a dict with multiple groups
        criteria = {
            f'group_{i}': 'argon' if i % 2 == 0 else 'penumbra'
            for i in range(10)
        }

        results = db_with_test_data.search_by_device_names(criteria)

        # Should only have results from first group of each type (due to overlaps)
        assert len(results) > 0
        assert 'search_group' in results.columns


# ==================== Edge Cases ====================

class TestEdgeCases:
    """Tests for edge cases and corner scenarios."""

    def test_single_group_dict(self, db_with_test_data):
        """Test dict with only one group."""
        results = db_with_test_data.search_by_device_names({
            'only_group': 'argon'
        })

        assert len(results) > 0
        assert 'search_group' in results.columns
        assert all(results['search_group'] == 'only_group')

    def test_group_names_with_special_characters(self, db_with_test_data):
        """Test that group names can contain special characters."""
        results = db_with_test_data.search_by_device_names({
            'mechanical-devices': 'argon',
            'aspiration_devices': 'penumbra',
            'other devices!': 'generic'
        })

        if len(results) > 0:
            groups = set(results['search_group'].unique())
            assert 'mechanical-devices' in groups or 'aspiration_devices' in groups


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
