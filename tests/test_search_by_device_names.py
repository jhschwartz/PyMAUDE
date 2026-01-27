#!/usr/bin/env python3
"""
Tests for device search functionality (create_search_index and search_by_device_names).

Tests cover:
- Search index creation and idempotency
- Boolean search logic (AND/OR combinations)
- Search with and without concat column
- Date filtering integration
- EVENT_KEY deduplication
- Input validation and error handling
"""

import pytest
import os
import sys
from pathlib import Path
import pandas as pd
import sqlite3
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymaude import MaudeDatabase


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary database file path."""
    return str(tmp_path / "test_search.db")


@pytest.fixture
def db_with_test_data(temp_db_path):
    """Create a real database with test data for search testing."""
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
        (1009, 'EVT009', '2023-09-14', 'M'),
        (1010, 'EVT010', '2023-10-25', 'IN'),
    ]

    device_data = [
        # Argon Cleaner devices
        (1001, 'ARGON CLEANER THROMBECTOMY', 'THROMBECTOMY CATHETER', 'ARGON MEDICAL DEVICES INC', 'DQY'),
        (1002, 'ARGON CLEANER PRO', 'THROMBECTOMY CATHETER', 'ARGON MEDICAL DEVICES INC', 'DQY'),
        # AngioJet devices
        (1003, 'ANGIOJET ULTRA', 'THROMBECTOMY SYSTEM', 'BOSTON SCIENTIFIC CORP', 'DQY'),
        (1004, 'ANGIOJET ZELANTE', 'THROMBECTOMY SYSTEM', 'BOSTON SCIENTIFIC CORP', 'DQY'),
        # Penumbra devices
        (1005, 'PENUMBRA INDIGO', 'ASPIRATION CATHETER', 'PENUMBRA INC', 'DQY'),
        (1006, 'PENUMBRA LIGHTNING', 'ASPIRATION CATHETER', 'PENUMBRA INC', 'DQY'),
        # Argon non-cleaner device (should not match 'argon AND cleaner')
        (1007, 'ARGON BALLOON CATHETER', 'BALLOON CATHETER', 'ARGON MEDICAL DEVICES INC', 'DTK'),
        # Boston device without specific keywords
        (1008, 'BOSTON SCIENTIFIC STENT', 'CORONARY STENT', 'BOSTON SCIENTIFIC CORP', 'NIQ'),
        # Device with NULL fields
        (1009, None, 'CATHETER', 'GENERIC MANUFACTURER', 'DQY'),
        # Device matching only manufacturer
        (1010, 'SOME DEVICE', 'SOME CATEGORY', 'ARGON MEDICAL DEVICES INC', 'BWD'),
    ]

    cursor.executemany(
        'INSERT INTO master VALUES (?, ?, ?, ?, NULL)',
        master_data
    )
    cursor.executemany(
        'INSERT INTO device VALUES (?, ?, ?, ?, ?, NULL)',
        device_data
    )

    # Create ROWIDs (SQLite auto-assigns these, but we set them explicitly for testing)
    conn.execute("UPDATE master SET ROWID = MDR_REPORT_KEY")
    conn.execute("UPDATE device SET ROWID = MDR_REPORT_KEY")

    conn.commit()
    conn.close()

    # Return a MaudeDatabase instance
    return MaudeDatabase(temp_db_path, verbose=False)


@pytest.fixture
def db_with_search_index(db_with_test_data):
    """Database with search index already created."""
    db_with_test_data.create_search_index()
    return db_with_test_data


# ==================== Search Index Creation Tests ====================

class TestSearchIndexCreation:
    """Tests for create_search_index() method."""

    def test_create_index_success(self, db_with_test_data):
        """Test successful search index creation."""
        result = db_with_test_data.create_search_index()

        assert result['created'] is True
        assert result['rows_updated'] == 10  # We inserted 10 device rows
        assert result['time_seconds'] >= 0

    def test_index_idempotent(self, db_with_search_index):
        """Test that calling create_search_index twice is safe."""
        # Index already exists from fixture
        result = db_with_search_index.create_search_index()

        assert result['created'] is False
        assert result['rows_updated'] == 0

    def test_concat_column_populated(self, db_with_search_index):
        """Test that DEVICE_NAME_CONCAT column is correctly populated."""
        cursor = db_with_search_index.conn.execute("""
            SELECT BRAND_NAME, GENERIC_NAME, MANUFACTURER_D_NAME, DEVICE_NAME_CONCAT
            FROM device
            WHERE MDR_REPORT_KEY = 1001
        """)
        row = cursor.fetchone()

        brand, generic, mfr, concat = row
        expected = f"{brand.upper()} | {generic.upper()} | {mfr.upper()}"

        assert concat == expected

    def test_concat_column_handles_nulls(self, db_with_search_index):
        """Test that NULL values are handled in concatenation."""
        cursor = db_with_search_index.conn.execute("""
            SELECT DEVICE_NAME_CONCAT
            FROM device
            WHERE MDR_REPORT_KEY = 1009
        """)
        concat = cursor.fetchone()[0]

        # Should handle None/NULL brand name gracefully
        assert ' | CATHETER | ' in concat
        assert concat.startswith(' | ')  # Empty brand at start

    def test_index_exists(self, db_with_search_index):
        """Test that the index was actually created."""
        cursor = db_with_search_index.conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_device_name_concat'
        """)
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == 'idx_device_name_concat'


# ==================== Search Logic Tests ====================

class TestSearchLogic:
    """Tests for search_by_device_names() boolean logic."""

    def test_simple_string_search(self, db_with_search_index):
        """Test single string search."""
        results = db_with_search_index.search_by_device_names('argon')

        # Should match all Argon devices (1001, 1002, 1007, 1010)
        assert len(results) == 4
        assert set(results['MDR_REPORT_KEY']) == {1001, 1002, 1007, 1010}

    def test_or_search_list(self, db_with_search_index):
        """Test OR search with list of strings."""
        results = db_with_search_index.search_by_device_names(['argon', 'penumbra'])

        # Should match Argon (4) + Penumbra (2) = 6 devices
        assert len(results) == 6
        assert set(results['MDR_REPORT_KEY']) == {1001, 1002, 1005, 1006, 1007, 1010}

    def test_and_search_single_group(self, db_with_search_index):
        """Test AND search with single group."""
        results = db_with_search_index.search_by_device_names([['argon', 'cleaner']])

        # Should match only Argon Cleaner devices (1001, 1002), not balloon (1007)
        assert len(results) == 2
        assert set(results['MDR_REPORT_KEY']) == {1001, 1002}

    def test_complex_and_or_search(self, db_with_search_index):
        """Test (A AND B) OR C logic."""
        results = db_with_search_index.search_by_device_names([
            ['argon', 'cleaner'],  # Argon Cleaner devices
            ['angiojet']            # OR AngioJet devices
        ])

        # Should match Argon Cleaner (2) + AngioJet (2) = 4 devices
        assert len(results) == 4
        assert set(results['MDR_REPORT_KEY']) == {1001, 1002, 1003, 1004}

    def test_three_way_or(self, db_with_search_index):
        """Test (A AND B) OR C OR D logic."""
        results = db_with_search_index.search_by_device_names([
            ['argon', 'cleaner'],  # Argon Cleaner
            ['angiojet'],           # OR AngioJet
            ['penumbra']            # OR Penumbra
        ])

        # Should match Argon Cleaner (2) + AngioJet (2) + Penumbra (2) = 6
        assert len(results) == 6
        assert set(results['MDR_REPORT_KEY']) == {1001, 1002, 1003, 1004, 1005, 1006}

    def test_mixed_list_syntax(self, db_with_search_index):
        """Test mixed list syntax: [['A', 'B'], 'C'] for (A AND B) OR C."""
        # Mixed syntax: list of strings AND string in same list
        results = db_with_search_index.search_by_device_names([
            ['argon', 'cleaner'],  # Argon Cleaner (AND)
            'angiojet'              # OR AngioJet (string not wrapped in list)
        ])

        # Should match Argon Cleaner (2) + AngioJet (2) = 4 devices
        assert len(results) == 4
        assert set(results['MDR_REPORT_KEY']) == {1001, 1002, 1003, 1004}

    def test_mixed_list_complex(self, db_with_search_index):
        """Test complex mixed list: ['A', ['B', 'C'], 'D'] for A OR (B AND C) OR D."""
        results = db_with_search_index.search_by_device_names([
            'balloon',               # Single string (matches 1007)
            ['argon', 'cleaner'],   # AND group (matches 1001, 1002)
            'stent'                  # Single string (matches 1008)
        ])

        # Should match balloon (1007) + Argon Cleaner (1001, 1002) + stent (1008)
        assert len(results) == 4
        assert set(results['MDR_REPORT_KEY']) == {1001, 1002, 1007, 1008}

    def test_search_case_insensitive(self, db_with_search_index):
        """Test that search is case-insensitive."""
        results_upper = db_with_search_index.search_by_device_names('ARGON')
        results_lower = db_with_search_index.search_by_device_names('argon')
        results_mixed = db_with_search_index.search_by_device_names('ArGoN')

        assert len(results_upper) == len(results_lower) == len(results_mixed) == 4

    def test_search_partial_match(self, db_with_search_index):
        """Test that search does partial/substring matching."""
        results = db_with_search_index.search_by_device_names('throm')

        # Should match all thrombectomy devices (1001-1004)
        assert len(results) >= 4

    def test_search_without_concat_column(self, db_with_test_data):
        """Test search fallback when concat column doesn't exist."""
        # Don't create index, use individual column search
        results = db_with_test_data.search_by_device_names(
            ['argon', 'penumbra'],
            use_concat_column=False
        )

        # Should still work, matching Argon (4) + Penumbra (2) = 6
        assert len(results) == 6

    def test_empty_results(self, db_with_search_index):
        """Test search that returns no results."""
        results = db_with_search_index.search_by_device_names('nonexistent_device_xyz')

        assert len(results) == 0
        assert isinstance(results, pd.DataFrame)


# ==================== Date Filtering Tests ====================

class TestDateFiltering:
    """Tests for date filtering integration with search."""

    def test_search_with_start_date(self, db_with_search_index):
        """Test search with start_date filter."""
        results = db_with_search_index.search_by_device_names(
            'argon',
            start_date='2023-04-01'
        )

        # Argon devices: 1001 (Jan), 1002 (Feb), 1007 (Jul), 1010 (Oct)
        # After Apr 1: 1007, 1010
        assert len(results) == 2
        assert set(results['MDR_REPORT_KEY']) == {1007, 1010}

    def test_search_with_end_date(self, db_with_search_index):
        """Test search with end_date filter."""
        results = db_with_search_index.search_by_device_names(
            'argon',
            end_date='2023-03-31'
        )

        # Argon devices before Mar 31: 1001 (Jan), 1002 (Feb)
        assert len(results) == 2
        assert set(results['MDR_REPORT_KEY']) == {1001, 1002}

    def test_search_with_date_range(self, db_with_search_index):
        """Test search with both start and end dates."""
        results = db_with_search_index.search_by_device_names(
            ['argon', 'penumbra'],
            start_date='2023-02-01',
            end_date='2023-06-30'
        )

        # Feb-Jun: 1002 (Feb), 1005 (May), 1006 (Jun)
        assert len(results) == 3
        assert set(results['MDR_REPORT_KEY']) == {1002, 1005, 1006}


# ==================== Deduplication Tests ====================

class TestDeduplication:
    """Tests for EVENT_KEY deduplication integration."""

    def test_deduplicate_events_default(self, db_with_search_index):
        """Test that deduplication is on by default."""
        results = db_with_search_index.search_by_device_names('thrombectomy')

        # With deduplication, should have unique EVENT_KEYs
        event_keys = results['EVENT_KEY'].tolist()
        assert len(event_keys) == len(set(event_keys))  # All unique

    def test_no_deduplication(self, db_with_search_index):
        """Test with deduplication disabled."""
        # This test assumes normal operation - our test data has unique events
        # so result count should be the same either way
        results_dedup = db_with_search_index.search_by_device_names(
            'thrombectomy',
            deduplicate_events=True
        )
        results_no_dedup = db_with_search_index.search_by_device_names(
            'thrombectomy',
            deduplicate_events=False
        )

        # Should return same results (no duplicate events in test data)
        assert len(results_dedup) == len(results_no_dedup)


# ==================== Input Validation Tests ====================

class TestInputValidation:
    """Tests for input validation and error handling."""

    def test_empty_criteria_raises_error(self, db_with_search_index):
        """Test that empty criteria raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            db_with_search_index.search_by_device_names([])

    def test_empty_group_raises_error(self, db_with_search_index):
        """Test that empty group in criteria raises ValueError."""
        with pytest.raises(ValueError, match="Empty group"):
            db_with_search_index.search_by_device_names([['argon'], []])

    def test_non_string_term_raises_error(self, db_with_search_index):
        """Test that non-string terms raise ValueError."""
        with pytest.raises(ValueError, match="must be a list"):
            db_with_search_index.search_by_device_names([123])

    def test_invalid_criteria_type_raises_error(self, db_with_search_index):
        """Test that invalid criteria type raises ValueError."""
        # Dict is now valid (for grouped search), so test with an integer
        with pytest.raises(ValueError, match="must be a string, list of strings, or list of lists"):
            db_with_search_index.search_by_device_names(12345)


# ==================== SQL Injection Protection Tests ====================

class TestSQLSafety:
    """Tests for SQL injection protection."""

    def test_special_characters_escaped(self, db_with_search_index):
        """Test that special SQL characters are properly escaped."""
        # These should not cause SQL errors
        try:
            results = db_with_search_index.search_by_device_names("device'; DROP TABLE device; --")
            assert isinstance(results, pd.DataFrame)
        except sqlite3.OperationalError:
            pytest.fail("SQL injection vulnerability detected")

    def test_like_wildcards_escaped(self, db_with_search_index):
        """Test that LIKE wildcards (% and _) are escaped."""
        # Insert a device with literal percent sign
        conn = db_with_search_index.conn

        # Get column count for device table (should include DEVICE_NAME_CONCAT after create_search_index)
        cursor = conn.execute("PRAGMA table_info(device)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'DEVICE_NAME_CONCAT' in columns:
            # Table has concat column
            conn.execute("""
                INSERT INTO device (MDR_REPORT_KEY, BRAND_NAME, GENERIC_NAME,
                                   MANUFACTURER_D_NAME, DEVICE_REPORT_PRODUCT_CODE, ROWID)
                VALUES (9999, '100% SAFE DEVICE', 'TEST', 'TEST INC', 'XXX', NULL)
            """)
        else:
            conn.execute("""
                INSERT INTO device VALUES
                (9999, '100% SAFE DEVICE', 'TEST', 'TEST INC', 'XXX', NULL)
            """)

        conn.execute("""
            INSERT INTO master VALUES
            (9999, 'EVT9999', '2023-12-01', 'M', NULL)
        """)
        conn.execute("UPDATE device SET ROWID = 9999 WHERE MDR_REPORT_KEY = 9999")
        conn.execute("UPDATE master SET ROWID = 9999 WHERE MDR_REPORT_KEY = 9999")
        conn.commit()

        # Update search index to include new device
        conn.execute("""
            UPDATE device
            SET DEVICE_NAME_CONCAT = UPPER(
                COALESCE(BRAND_NAME, '') || ' | ' ||
                COALESCE(GENERIC_NAME, '') || ' | ' ||
                COALESCE(MANUFACTURER_D_NAME, '')
            )
            WHERE MDR_REPORT_KEY = 9999
        """)
        conn.commit()

        # Search for literal % should be escaped and work
        results = db_with_search_index.search_by_device_names('100%')
        assert len(results) >= 1  # Should find the device


# ==================== Integration Tests ====================

class TestSearchIntegration:
    """Integration tests combining multiple features."""

    def test_complex_real_world_search(self, db_with_search_index):
        """Test realistic complex search scenario."""
        # Search for: (Argon Cleaner OR AngioJet) devices from Q1 2023
        results = db_with_search_index.search_by_device_names(
            [['argon', 'cleaner'], ['angiojet']],
            start_date='2023-01-01',
            end_date='2023-03-31'
        )

        # Q1: 1001 (Jan Argon Cleaner), 1002 (Feb Argon Cleaner), 1003 (Mar AngioJet)
        assert len(results) == 3
        assert set(results['MDR_REPORT_KEY']) == {1001, 1002, 1003}

    def test_search_returns_proper_columns(self, db_with_search_index):
        """Test that search returns all expected columns."""
        results = db_with_search_index.search_by_device_names('argon')

        # Should have columns from both master and device tables
        assert 'MDR_REPORT_KEY' in results.columns
        assert 'EVENT_KEY' in results.columns
        assert 'DATE_RECEIVED' in results.columns
        assert 'BRAND_NAME' in results.columns
        assert 'GENERIC_NAME' in results.columns
        assert 'MANUFACTURER_D_NAME' in results.columns


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
