#!/usr/bin/env python3
"""
Tests for exact-match query_device functionality.

Tests cover:
- Exact brand name matching (case-insensitive)
- Exact generic name matching (case-insensitive)
- Exact manufacturer matching (case-insensitive)
- Exact device_name_concat matching
- Product code matching
- AND logic for multiple parameters
- Date filtering
- Validation requiring at least one search parameter
- No duplicate columns in results
- Integration with deduplication

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

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymaude import MaudeDatabase


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary database file path."""
    return str(tmp_path / "test_query_device.db")


@pytest.fixture
def db_with_test_data(temp_db_path):
    """Create a real database with test data for exact-match query testing."""
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

    # Insert test data - various device combinations with exact names
    master_data = [
        (2001, 'EVT001', '2022-01-15', 'M'),
        (2002, 'EVT002', '2022-02-20', 'IN'),
        (2003, 'EVT003', '2022-03-10', 'D'),
        (2004, 'EVT004', '2022-04-05', 'M'),
        (2005, 'EVT005', '2022-05-12', 'IN'),
        (2006, 'EVT006', '2022-06-18', 'M'),
        (2007, 'EVT007', '2022-07-22', 'M'),
        (2008, 'EVT008', '2022-08-30', 'D'),
        (2009, 'EVT009', '2022-09-15', 'M'),
        (2010, 'EVT010', '2022-10-01', 'IN'),
    ]

    device_data = [
        # Exact brand: "Venovo"
        (2001, 'Venovo', 'Venous Stent', 'BD BARD INC', 'NIQ'),
        (2002, 'Venovo', 'Venous Stent', 'BD BARD INC', 'NIQ'),
        # Different case: "VENOVO"
        (2003, 'VENOVO', 'Venous Stent', 'BD BARD INC', 'NIQ'),
        # Partial match should NOT match: "Venovo XL"
        (2004, 'Venovo XL', 'Venous Stent', 'BD BARD INC', 'NIQ'),
        # Different brand, same generic
        (2005, 'Zilver Vena', 'Venous Stent', 'COOK MEDICAL INC', 'NIQ'),
        # Different generic, similar brand name
        (2006, 'Veno Plus', 'Catheter', 'OTHER MANUFACTURER', 'DQY'),
        # Exact manufacturer test
        (2007, 'Product A', 'Device Type A', 'Medtronic', 'ABC'),
        (2008, 'Product B', 'Device Type B', 'MEDTRONIC', 'DEF'),
        # Exact generic test
        (2009, 'Brand X', 'Thrombectomy Catheter', 'Company X', 'XYZ'),
        (2010, 'Brand Y', 'Thrombectomy Catheter', 'Company Y', 'XYZ'),
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

    # Return a MaudeDatabase instance
    db = MaudeDatabase(temp_db_path, verbose=False)
    return db


# ==================== Validation Tests ====================

class TestParameterValidation:
    """Tests for parameter validation."""

    def test_no_parameters_raises_error(self, db_with_test_data):
        """Test that calling with no search parameters raises ValueError."""
        with pytest.raises(ValueError, match="At least one search parameter required"):
            db_with_test_data.query_device()

    def test_only_date_parameters_raises_error(self, db_with_test_data):
        """Test that date parameters alone don't satisfy requirement."""
        with pytest.raises(ValueError, match="At least one search parameter required"):
            db_with_test_data.query_device(start_date='2022-01-01')


# ==================== Exact Brand Name Tests ====================

class TestExactBrandName:
    """Tests for exact brand name matching."""

    def test_exact_brand_match(self, db_with_test_data):
        """Test exact brand name matching."""
        results = db_with_test_data.query_device(brand_name='Venovo')

        # Should match 2001, 2002, 2003 (case-insensitive)
        # Should NOT match 2004 (Venovo XL - not exact)
        assert len(results) == 3
        assert set(results['MDR_REPORT_KEY']) == {2001, 2002, 2003}

    def test_brand_name_case_insensitive(self, db_with_test_data):
        """Test that brand name matching is case-insensitive."""
        # Test lowercase
        results_lower = db_with_test_data.query_device(brand_name='venovo')
        # Test uppercase
        results_upper = db_with_test_data.query_device(brand_name='VENOVO')
        # Test mixed case
        results_mixed = db_with_test_data.query_device(brand_name='VeNoVo')

        # All should return same results
        assert len(results_lower) == 3
        assert len(results_upper) == 3
        assert len(results_mixed) == 3
        assert set(results_lower['MDR_REPORT_KEY']) == {2001, 2002, 2003}
        assert set(results_upper['MDR_REPORT_KEY']) == {2001, 2002, 2003}
        assert set(results_mixed['MDR_REPORT_KEY']) == {2001, 2002, 2003}

    def test_partial_match_not_included(self, db_with_test_data):
        """Test that partial matches are NOT included (exact match only)."""
        results = db_with_test_data.query_device(brand_name='Venovo')

        # "Venovo XL" should NOT be in results (2004)
        assert 2004 not in results['MDR_REPORT_KEY'].values

    def test_no_match_returns_empty(self, db_with_test_data):
        """Test that no match returns empty DataFrame."""
        results = db_with_test_data.query_device(brand_name='NonexistentBrand')

        assert len(results) == 0
        assert isinstance(results, pd.DataFrame)


# ==================== Exact Generic Name Tests ====================

class TestExactGenericName:
    """Tests for exact generic name matching."""

    def test_exact_generic_match(self, db_with_test_data):
        """Test exact generic name matching."""
        results = db_with_test_data.query_device(generic_name='Venous Stent')

        # Should match 2001-2005 (all with "Venous Stent")
        assert len(results) == 5
        assert set(results['MDR_REPORT_KEY']) == {2001, 2002, 2003, 2004, 2005}

    def test_generic_name_case_insensitive(self, db_with_test_data):
        """Test that generic name matching is case-insensitive."""
        results_lower = db_with_test_data.query_device(generic_name='venous stent')
        results_upper = db_with_test_data.query_device(generic_name='VENOUS STENT')

        assert len(results_lower) == 5
        assert len(results_upper) == 5
        assert set(results_lower['MDR_REPORT_KEY']) == {2001, 2002, 2003, 2004, 2005}

    def test_generic_thrombectomy_catheter(self, db_with_test_data):
        """Test exact match on Thrombectomy Catheter."""
        results = db_with_test_data.query_device(generic_name='Thrombectomy Catheter')

        # Should match 2009, 2010
        assert len(results) == 2
        assert set(results['MDR_REPORT_KEY']) == {2009, 2010}


# ==================== Exact Manufacturer Tests ====================

class TestExactManufacturer:
    """Tests for exact manufacturer matching."""

    def test_exact_manufacturer_match(self, db_with_test_data):
        """Test exact manufacturer matching."""
        results = db_with_test_data.query_device(manufacturer_name='BD BARD INC')

        # Should match 2001, 2002, 2003, 2004
        assert len(results) == 4
        assert set(results['MDR_REPORT_KEY']) == {2001, 2002, 2003, 2004}

    def test_manufacturer_case_insensitive(self, db_with_test_data):
        """Test that manufacturer matching is case-insensitive."""
        results_lower = db_with_test_data.query_device(manufacturer_name='medtronic')
        results_upper = db_with_test_data.query_device(manufacturer_name='MEDTRONIC')
        results_mixed = db_with_test_data.query_device(manufacturer_name='Medtronic')

        # All should match 2007, 2008
        assert len(results_lower) == 2
        assert len(results_upper) == 2
        assert len(results_mixed) == 2
        assert set(results_lower['MDR_REPORT_KEY']) == {2007, 2008}


# ==================== Product Code Tests ====================

class TestProductCode:
    """Tests for product code matching."""

    def test_exact_product_code(self, db_with_test_data):
        """Test exact product code matching."""
        results = db_with_test_data.query_device(product_code='NIQ')

        # Should match 2001-2005 (all NIQ)
        assert len(results) == 5
        assert set(results['MDR_REPORT_KEY']) == {2001, 2002, 2003, 2004, 2005}

    def test_product_code_xyz(self, db_with_test_data):
        """Test product code XYZ."""
        results = db_with_test_data.query_device(product_code='XYZ')

        # Should match 2009, 2010
        assert len(results) == 2
        assert set(results['MDR_REPORT_KEY']) == {2009, 2010}


# ==================== Multiple Parameters (AND Logic) ====================

class TestMultipleParameters:
    """Tests for combining multiple search parameters with AND logic."""

    def test_brand_and_generic(self, db_with_test_data):
        """Test brand AND generic name."""
        results = db_with_test_data.query_device(
            brand_name='Venovo',
            generic_name='Venous Stent'
        )

        # Should match 2001, 2002, 2003 (all have both)
        assert len(results) == 3
        assert set(results['MDR_REPORT_KEY']) == {2001, 2002, 2003}

    def test_brand_and_manufacturer(self, db_with_test_data):
        """Test brand AND manufacturer."""
        results = db_with_test_data.query_device(
            brand_name='Venovo',
            manufacturer_name='BD BARD INC'
        )

        # Should match 2001, 2002, 2003
        assert len(results) == 3
        assert set(results['MDR_REPORT_KEY']) == {2001, 2002, 2003}

    def test_generic_and_product_code(self, db_with_test_data):
        """Test generic AND product code."""
        results = db_with_test_data.query_device(
            generic_name='Venous Stent',
            product_code='NIQ'
        )

        # Should match 2001-2005
        assert len(results) == 5
        assert set(results['MDR_REPORT_KEY']) == {2001, 2002, 2003, 2004, 2005}

    def test_all_three_parameters(self, db_with_test_data):
        """Test brand AND generic AND manufacturer."""
        results = db_with_test_data.query_device(
            brand_name='Venovo',
            generic_name='Venous Stent',
            manufacturer_name='BD BARD INC'
        )

        # Should match 2001, 2002, 2003
        assert len(results) == 3
        assert set(results['MDR_REPORT_KEY']) == {2001, 2002, 2003}

    def test_no_match_with_multiple_params(self, db_with_test_data):
        """Test that conflicting parameters return no results."""
        results = db_with_test_data.query_device(
            brand_name='Venovo',
            manufacturer_name='COOK MEDICAL INC'  # Wrong manufacturer for Venovo
        )

        # Should return empty (no device matches both)
        assert len(results) == 0


# ==================== Date Filtering Tests ====================

class TestDateFiltering:
    """Tests for date filtering with exact-match queries."""

    def test_start_date_filter(self, db_with_test_data):
        """Test start_date filtering."""
        results = db_with_test_data.query_device(
            product_code='NIQ',
            start_date='2022-03-01'
        )

        # Should match 2003, 2004, 2005 (March and later)
        assert len(results) == 3
        assert set(results['MDR_REPORT_KEY']) == {2003, 2004, 2005}

    def test_end_date_filter(self, db_with_test_data):
        """Test end_date filtering."""
        results = db_with_test_data.query_device(
            product_code='NIQ',
            end_date='2022-03-31'
        )

        # Should match 2001, 2002, 2003 (up to March)
        assert len(results) == 3
        assert set(results['MDR_REPORT_KEY']) == {2001, 2002, 2003}

    def test_date_range(self, db_with_test_data):
        """Test both start and end date."""
        results = db_with_test_data.query_device(
            product_code='NIQ',
            start_date='2022-02-01',
            end_date='2022-04-30'
        )

        # Should match 2002, 2003, 2004 (Feb-Apr)
        assert len(results) == 3
        assert set(results['MDR_REPORT_KEY']) == {2002, 2003, 2004}


# ==================== No Duplicate Columns Tests ====================

class TestNoDuplicateColumns:
    """Tests verifying no duplicate columns in results."""

    def test_no_duplicate_columns_with_dedup(self, db_with_test_data):
        """Test that results don't have duplicate columns (dedup enabled)."""
        results = db_with_test_data.query_device(brand_name='Venovo', deduplicate_events=True)

        # Check for duplicate columns
        assert not results.columns.duplicated().any(), \
            f"Duplicate columns found: {results.columns[results.columns.duplicated()].tolist()}"

        # Verify common columns appear only once
        assert results.columns.tolist().count('MDR_REPORT_KEY') == 1
        assert results.columns.tolist().count('DATE_RECEIVED') == 1
        assert results.columns.tolist().count('EVENT_TYPE') == 1

    def test_no_duplicate_columns_without_dedup(self, db_with_test_data):
        """Test that results don't have duplicate columns (dedup disabled)."""
        results = db_with_test_data.query_device(brand_name='Venovo', deduplicate_events=False)

        # Check for duplicate columns
        assert not results.columns.duplicated().any(), \
            f"Duplicate columns found: {results.columns[results.columns.duplicated()].tolist()}"


# ==================== Column Content Tests ====================

class TestColumnContent:
    """Tests for expected columns and content in results."""

    def test_expected_columns_present(self, db_with_test_data):
        """Test that all expected columns are present."""
        results = db_with_test_data.query_device(brand_name='Venovo')

        # Should have columns from both master and device tables
        assert 'MDR_REPORT_KEY' in results.columns
        assert 'EVENT_KEY' in results.columns
        assert 'DATE_RECEIVED' in results.columns
        assert 'EVENT_TYPE' in results.columns
        assert 'BRAND_NAME' in results.columns
        assert 'GENERIC_NAME' in results.columns
        assert 'MANUFACTURER_D_NAME' in results.columns
        assert 'DEVICE_REPORT_PRODUCT_CODE' in results.columns

    def test_results_contain_correct_data(self, db_with_test_data):
        """Test that results contain the correct data."""
        results = db_with_test_data.query_device(brand_name='Venovo')

        # All results should have brand name matching "Venovo" (case-insensitive)
        for brand in results['BRAND_NAME']:
            assert brand.upper() == 'VENOVO'


# ==================== Deduplication Tests ====================

class TestDeduplication:
    """Tests for EVENT_KEY deduplication."""

    def test_deduplication_enabled(self, db_with_test_data):
        """Test that deduplication is enabled by default."""
        results = db_with_test_data.query_device(brand_name='Venovo')

        # Each EVENT_KEY should appear only once
        event_counts = results['EVENT_KEY'].value_counts()
        assert all(event_counts == 1)

    def test_deduplication_disabled(self, db_with_test_data):
        """Test that deduplication can be disabled."""
        results = db_with_test_data.query_device(
            brand_name='Venovo',
            deduplicate_events=False
        )

        # Should return results (may or may not have duplicates depending on test data)
        assert len(results) >= 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
