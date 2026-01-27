import unittest
import os
import tempfile
import shutil
import sqlite3
import zipfile
import pandas as pd
from datetime import datetime
import sys
from unittest.mock import patch, Mock

from pymaude import MaudeDatabase
from pymaude.processors import _identify_date_columns, _parse_dates_flexible


class TestMaudeDatabase(unittest.TestCase):
    """Unit tests for MaudeDatabase class"""
    
    def setUp(self):
        """Set up test fixtures before each test"""
        # Create temporary directory for test data
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, 'test_maude.db')
        self.test_data_dir = os.path.join(self.test_dir, 'maude_data')
        os.makedirs(self.test_data_dir)
        
        # Create sample test data files
        self._create_test_files()
        
    def tearDown(self):
        """Clean up after each test"""
        shutil.rmtree(self.test_dir)
    
    def _create_test_files(self):
        """Create sample MAUDE data files for testing"""
        # Sample master file (cumulative pattern: mdrfoithru2020.txt) - using uppercase column names like real FDA data
        # Include multiple date formats to test flexible parsing
        # EVENT_KEY is needed for deduplication in search_by_device_names()
        master_data = """MDR_REPORT_KEY|EVENT_KEY|DATE_RECEIVED|EVENT_TYPE|MANUFACTURER_NAME|DATE_REPORT|DATE_OF_EVENT|PMA_PMN_NUM
1234567|EVT001|01/15/2020|Injury|Test Manufacturer|2020/01/10|2020-01-05|P180037
1234568|EVT002|02/20/2020|Death|Another Manufacturer|2020/02/15|2020-02-10|K123456
1234569|EVT003|03/10/2020|Malfunction|Test Manufacturer|2020/03/05|2020-03-01|
1234570|EVT004|04/15/2020|Death|Test Manufacturer|2020/04/10|2020-04-05|P180037
1234571|EVT005|05/20/2020|Injury|Another Manufacturer|2020/05/15|2020-05-10|"""

        with open(f'{self.test_data_dir}/mdrfoithru2020.txt', 'w') as f:
            f.write(master_data)

        # Sample device file (yearly pattern: device2020.txt for year >= 2000) - using uppercase column names like real FDA data
        # Device table should have MANUFACTURER_D_NAME, not DATE_RECEIVED (DATE_RECEIVED is in master)
        device_data = """MDR_REPORT_KEY|DEVICE_REPORT_PRODUCT_CODE|GENERIC_NAME|BRAND_NAME|MANUFACTURER_D_NAME|EXPIRATION_DATE_OF_DEVICE
1234567|NIQ|Thrombectomy Device|DeviceX|Acme Corp|12/31/2025
1234568|NIQ|Thrombectomy Device|DeviceY|Beta Inc|
1234569|ABC|Other Device|DeviceZ|Gamma LLC|2025-12-31
1234570|NIQ|Thrombectomy Device|DeviceW|Acme Corp|12/31/2025
1234571|ABC|Other Device|DeviceV|Beta Inc|"""

        with open(f'{self.test_data_dir}/device2020.txt', 'w') as f:
            f.write(device_data)

        # Sample patient file (cumulative pattern: patientthru2020.txt) - using uppercase column names like real FDA data
        # SEQUENCE_NUMBER_OUTCOME contains semicolon-separated outcome codes (D=Death, H=Hospitalization, etc.)
        # Test cases:
        # 1234567: Single injury outcome (H=Hospitalization)
        # 1234568: Single death outcome (D=Death)
        # 1234569: No patient record (device malfunction with no patient impact)
        # 1234570: Multiple outcomes including death (D;L = Death + Life threatening)
        # 1234571: Multiple patients for same report, one with injury
        patient_data = """MDR_REPORT_KEY|PATIENT_SEQUENCE_NUMBER|DATE_OF_EVENT|SEQUENCE_NUMBER_OUTCOME
1234567|1|2020-01-10|H
1234568|1|2020-02-15|D
1234570|1|2020-04-10|D;L
1234571|1|2020-05-15|S
1234571|2|2020-05-15|"""

        with open(f'{self.test_data_dir}/patientthru2020.txt', 'w') as f:
            f.write(patient_data)

        # Sample text file (yearly pattern: foitext2020.txt) - using uppercase column names like real FDA data
        text_data = """MDR_REPORT_KEY|MDR_TEXT_KEY|TEXT_TYPE_CODE|FOI_TEXT
1234567|1|D|Patient experienced adverse event with device
1234568|2|D|Fatal incident reported"""

        with open(f'{self.test_data_dir}/foitext2020.txt', 'w') as f:
            f.write(text_data)
    
    # ========== Initialization Tests ==========
    
    def test_init_creates_database(self):
        """Test that __init__ creates a database file"""
        db = MaudeDatabase(self.test_db, verbose=False)
        self.assertTrue(os.path.exists(self.test_db))
        db.close()
    
    def test_init_connects_to_existing(self):
        """Test that __init__ can connect to existing database"""
        # Create database
        db1 = MaudeDatabase(self.test_db, verbose=False)
        db1.close()
        
        # Reconnect
        db2 = MaudeDatabase(self.test_db, verbose=False)
        self.assertIsNotNone(db2.conn)
        db2.close()
    
    def test_context_manager(self):
        """Test that context manager works properly"""
        with MaudeDatabase(self.test_db, verbose=False) as db:
            self.assertIsNotNone(db.conn)
        
        # Connection should be closed after context
        with self.assertRaises(sqlite3.ProgrammingError):
            db.conn.execute("SELECT 1")
    
    # ========== Year Parsing Tests ==========
    
    def test_parse_year_range_single_int(self):
        """Test parsing single integer year"""
        db = MaudeDatabase(self.test_db, verbose=False)
        result = db._parse_year_range(2020)
        self.assertEqual(result, [2020])
        db.close()
    
    def test_parse_year_range_list(self):
        """Test parsing list of years"""
        db = MaudeDatabase(self.test_db, verbose=False)
        result = db._parse_year_range([2018, 2019, 2020])
        self.assertEqual(result, [2018, 2019, 2020])
        db.close()
    
    def test_parse_year_range_string_range(self):
        """Test parsing year range string"""
        db = MaudeDatabase(self.test_db, verbose=False)
        result = db._parse_year_range('2018-2020')
        self.assertEqual(list(result), [2018, 2019, 2020])
        db.close()
    
    def test_parse_year_range_latest(self):
        """Test parsing 'latest' keyword"""
        db = MaudeDatabase(self.test_db, verbose=False)
        result = db._parse_year_range('latest')
        expected = datetime.now().year - 1
        self.assertEqual(result, [expected])
        db.close()
    
    def test_parse_year_range_all(self):
        """Test parsing 'all' keyword"""
        db = MaudeDatabase(self.test_db, verbose=False)
        result = list(db._parse_year_range('all'))
        self.assertEqual(result[0], 1991)
        self.assertGreater(len(result), 30)
        db.close()
    
    # ========== File Path Tests ==========

    def test_make_file_path_lowercase(self):
        """Test finding cumulative file paths (master table)"""
        db = MaudeDatabase(self.test_db, verbose=False)
        path = db._make_file_path('master', 2020, self.test_data_dir)
        self.assertTrue(path.endswith('mdrfoithru2020.txt'))
        db.close()

    def test_make_file_path_uppercase(self):
        """Test finding uppercase cumulative file paths"""
        # Create uppercase cumulative file for current year - 1
        current_year = datetime.now().year
        cumulative_year = current_year - 1

        with open(f'{self.test_data_dir}/MDRFOITHRU{cumulative_year}.txt', 'w') as f:
            f.write('test')

        db = MaudeDatabase(self.test_db, verbose=False)
        path = db._make_file_path('master', cumulative_year, self.test_data_dir)
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith(f'MDRFOITHRU{cumulative_year}.txt'))
        db.close()

    def test_make_file_path_missing(self):
        """Test that missing files return False"""
        db = MaudeDatabase(self.test_db, verbose=False)
        # Use 'text' (yearly pattern) instead of 'master' (cumulative pattern)
        # Year 1999 has no foitext1999.txt file, so should return False
        path = db._make_file_path('text', 1999, self.test_data_dir)
        self.assertFalse(path)
        db.close()
    
    # ========== Add Years Tests ==========
    
    def test_add_years_basic(self):
        """Test basic add_years functionality"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)
        
        # Check that data was added (now have 5 test records)
        df = db.query("SELECT COUNT(*) as count FROM master")
        self.assertEqual(df['count'][0], 5)

        df = db.query("SELECT COUNT(*) as count FROM device")
        self.assertEqual(df['count'][0], 5)
        
        db.close()
    
    def test_add_years_strict_mode_failure(self):
        """Test that strict mode raises error on invalid year/table combination"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Use 'text' table for year 1999, which is before text data availability (2000+)
        # This should raise ValueError during validation, not FileNotFoundError
        with self.assertRaises(ValueError):
            db.add_years(1999, tables=['text'], download=False, strict=True, data_dir=self.test_data_dir, interactive=False)

        db.close()
    
    def test_add_years_non_strict_mode(self):
        """Test that non-strict mode skips missing files"""
        db = MaudeDatabase(self.test_db, verbose=False)
        
        # Should not raise error
        db.add_years(1999, tables=['master'], download=False, strict=False, data_dir=self.test_data_dir, interactive=False)
        
        db.close()
    
    def test_add_years_creates_indexes(self):
        """Test that indexes are created"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)
        
        # Check indexes exist
        indexes = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='index'",
            db.conn
        )['name'].tolist()
        
        self.assertIn('idx_master_key', indexes)
        self.assertIn('idx_device_code', indexes)
        
        db.close()
    
    # ========== Query Tests ==========
    
    def test_query_raw_sql(self):
        """Test raw SQL query execution"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir, interactive=False)

        df = db.query("SELECT * FROM master WHERE EVENT_TYPE = 'Death'")
        self.assertEqual(len(df), 2)  # 1234568 and 1234570 both have EVENT_TYPE='Death'
        self.assertIn(1234568, df['MDR_REPORT_KEY'].values)
        self.assertIn(1234570, df['MDR_REPORT_KEY'].values)

        db.close()

    def test_query_with_params(self):
        """Test parameterized queries"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir, interactive=False)

        df = db.query(
            "SELECT * FROM master WHERE EVENT_TYPE = :type",
            params={'type': 'Injury'}
        )
        self.assertEqual(len(df), 2)  # 1234567 and 1234571 have EVENT_TYPE='Injury'

        db.close()
    
    def test_query_device_by_name(self):
        """Test query_device with generic name filter (new exact-match API)"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)

        # Use exact match on generic_name
        df = db.query_device(generic_name='Thrombectomy Device')
        self.assertEqual(len(df), 3)  # 1234567, 1234568, 1234570

        db.close()

    def test_query_device_by_product_code(self):
        """Test query_device with product code filter"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)

        df = db.query_device(product_code='NIQ')
        self.assertEqual(len(df), 3)  # 1234567, 1234568, 1234570

        db.close()

    def test_query_device_by_date_range(self):
        """Test query_device with date filters (requires search parameter)"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)

        # Query with product code and date filters
        df = db.query_device(product_code='NIQ', start_date='2020-02-01', end_date='2020-12-31')
        self.assertEqual(len(df), 2)  # 1234568 (NIQ, 02/20), 1234570 (NIQ, 04/15)

        db.close()

    def test_query_device_multiple_filters(self):
        """Test query_device with multiple filters (new exact-match API)"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)

        df = db.query_device(
            generic_name='Thrombectomy Device',
            start_date='2020-02-01'
        )
        self.assertEqual(len(df), 2)  # 1234568 (02/20), 1234570 (04/15)

        db.close()

    def test_query_device_by_pma_pmn(self):
        """Test query_device with PMA/PMN number filter (master table column)"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)

        # Query by PMA number (should find 1234567 and 1234570)
        df = db.query_device(pma_pmn='P180037')
        self.assertEqual(len(df), 2)  # 1234567, 1234570
        self.assertTrue(all(df['PMA_PMN_NUM'] == 'P180037'))

        # Query by K number (should find 1234568)
        df_k = db.query_device(pma_pmn='K123456')
        self.assertEqual(len(df_k), 1)  # 1234568
        self.assertEqual(df_k.iloc[0]['PMA_PMN_NUM'], 'K123456')

        # Case insensitive matching
        df_lower = db.query_device(pma_pmn='p180037')
        self.assertEqual(len(df_lower), 2)

        db.close()

    def test_get_trends_by_year(self):
        """Test get_trends_by_year functionality - DataFrame-only method"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)

        # Create search index for search_by_device_names
        db.create_search_index()

        # Get all results using search_by_device_names (search for "device" to match all)
        results = db.search_by_device_names('device')  # Should match all devices in test data

        # Get trends from DataFrame
        trends = db.get_trends_by_year(results)

        # Check structure
        self.assertIn('year', trends.columns)
        self.assertIn('event_count', trends.columns)

        # Check that we have results for 2020
        self.assertEqual(len(trends), 1)
        self.assertEqual(trends.iloc[0]['year'], 2020)  # Year is now int, not string
        self.assertEqual(trends.iloc[0]['event_count'], 5)  # 5 total reports

        db.close()
    
    def test_get_trends_by_product_code(self):
        """Test get_trends_by_year with product code filter - DataFrame-only method"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)

        # Query by product code using exact-match query
        results = db.query_device(product_code='NIQ')

        # Get trends from DataFrame
        trends = db.get_trends_by_year(results)

        # NIQ reports: 1234567 (H), 1234568 (D), 1234570 (D;L) = 3 reports
        self.assertEqual(trends.iloc[0]['event_count'], 3)
        self.assertEqual(trends.iloc[0]['year'], 2020)

        db.close()
    
    def test_get_narratives(self):
        """Test get_narratives functionality"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['text'], download=False, data_dir=self.test_data_dir, interactive=False)
        
        df = db.get_narratives(['1234567', '1234568'])
        self.assertEqual(len(df), 2)
        self.assertIn('adverse event', df.iloc[0]['FOI_TEXT'])
        
        db.close()
    
    # ========== Export Tests ==========
    
    def test_export_subset(self):
        """Test export_subset functionality (new exact-match API)"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)

        output_file = os.path.join(self.test_dir, 'export.csv')
        db.export_subset(output_file, generic_name='Thrombectomy Device')

        self.assertTrue(os.path.exists(output_file))

        df = pd.read_csv(output_file)
        self.assertEqual(len(df), 3)  # 3 Thrombectomy devices

        db.close()
    
    # ========== Info Tests ==========
    
    def test_info_empty_database(self):
        """Test info on empty database"""
        db = MaudeDatabase(self.test_db, verbose=False)
        # Should not raise error
        db.info()
        db.close()
    
    def test_info_populated_database(self):
        """Test info on populated database"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir, interactive=False)
        # Should not raise error
        db.info()
        db.close()
    
    # ========== Years in DB Tests ==========
    
    def test_get_years_in_db_empty(self):
        """Test getting years from empty database"""
        db = MaudeDatabase(self.test_db, verbose=False)
        years = db._get_years_in_db()
        self.assertEqual(years, [])
        db.close()
    
    def test_get_years_in_db_populated(self):
        """Test getting years from populated database"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir, interactive=False)
        
        years = db._get_years_in_db()
        self.assertIn(2020, years)
        
        db.close()
    
    # ========== Update Tests ==========

    def test_update_empty_database(self):
        """Test update on empty database"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Should return early with message for empty database
        db.update(add_new_years=False, download=False)

        # Database should still be empty
        years = db._get_years_in_db()
        self.assertEqual(years, [])

        db.close()

    def test_update_refresh_only(self):
        """Test update with add_new_years=False (refresh only)"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir, interactive=False)

        # Update should re-check existing years
        db.update(add_new_years=False, download=False)

        # Should still only have 2020 data
        years = db._get_years_in_db()
        self.assertEqual(years, [2020])

        df = db.query("SELECT COUNT(*) as count FROM master")
        self.assertEqual(df['count'][0], 5)  # Still only 5 records

        db.close()

    def test_update_with_new_years(self):
        """Test update with add_new_years=True"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir, interactive=False)

        # Add 2021 data file for testing
        # (In real scenario, this would download new years)
        # For now, just verify it attempts to add years
        initial_years = db._get_years_in_db()
        self.assertEqual(initial_years, [2020])

        # This will attempt to add years 2021-2026 (current year)
        # Since we don't have those files in test data, they'll be skipped
        db.update(add_new_years=True, download=False)

        db.close()

    def test_update_checksum_tracking(self):
        """Test that update uses checksum tracking (doesn't use force_refresh)"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir, interactive=False)

        # Get initial metadata
        metadata_before = db._get_loaded_file_info('master', 2020)
        self.assertIsNotNone(metadata_before)

        # Update without changes - checksum should prevent reprocessing
        db.update(add_new_years=False, download=False)

        # Metadata should still exist and be the same
        metadata_after = db._get_loaded_file_info('master', 2020)
        self.assertEqual(metadata_before['file_checksum'], metadata_after['file_checksum'])

        db.close()
    
    # ========== Edge Cases ==========
    
    def test_empty_table_list(self):
        """Test add_years with empty table list"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=[], download=False, data_dir=self.test_data_dir, interactive=False)

        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'",
            db.conn
        )['name'].tolist()

        # Should have no data tables (only internal metadata table _maude_load_metadata)
        self.assertEqual(len(tables), 0)
        db.close()
    
    def test_duplicate_year_addition(self):
        """Test adding same year twice - checksum tracking prevents duplicates"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir, interactive=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir, interactive=False)

        # With checksum tracking, should NOT have duplicate rows
        df = db.query("SELECT COUNT(*) as count FROM master")
        self.assertEqual(df['count'][0], 5)  # 5 records (no duplicates)

        db.close()
    
    def test_close(self):
        """Test close method"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.close()

        with self.assertRaises(sqlite3.ProgrammingError):
            db.conn.execute("SELECT 1")

    # ========== Date Parsing Tests ==========

    def test_identify_date_columns(self):
        """Test that date columns are identified correctly"""
        df = pd.DataFrame({
            'DATE_RECEIVED': ['01/01/2024'],
            'DATE_REPORT': ['02/01/2024'],
            'DEVICE_NAME': ['Test Device']
        })

        result = _identify_date_columns(df)

        self.assertIn('DATE_RECEIVED', result)
        self.assertIn('DATE_REPORT', result)
        self.assertNotIn('DEVICE_NAME', result)
        self.assertEqual(len(result), 2)

    def test_parse_dates_flexible_multiple_formats(self):
        """Test flexible date parsing handles MM/DD/YYYY format"""
        df = pd.DataFrame({
            'DATE_RECEIVED': ['01/15/2024', '02/20/2024', '12/31/2023']
        })

        result = _parse_dates_flexible(df, ['DATE_RECEIVED'])

        self.assertTrue(pd.api.types.is_datetime64_any_dtype(result['DATE_RECEIVED']))
        self.assertEqual(result['DATE_RECEIVED'].iloc[0], pd.Timestamp('2024-01-15'))
        self.assertEqual(result['DATE_RECEIVED'].iloc[1], pd.Timestamp('2024-02-20'))
        self.assertEqual(result['DATE_RECEIVED'].iloc[2], pd.Timestamp('2023-12-31'))

    def test_parse_dates_handles_invalid_gracefully(self):
        """Test that invalid dates are converted to NaT"""
        df = pd.DataFrame({
            'DATE_RECEIVED': ['01/15/2024', 'INVALID', '']
        })

        result = _parse_dates_flexible(df, ['DATE_RECEIVED'])

        self.assertEqual(result['DATE_RECEIVED'].iloc[0], pd.Timestamp('2024-01-15'))
        self.assertTrue(pd.isna(result['DATE_RECEIVED'].iloc[1]))
        self.assertTrue(pd.isna(result['DATE_RECEIVED'].iloc[2]))

    def test_dates_stored_as_timestamps_in_sqlite(self):
        """Test that dates are stored as TIMESTAMP type in SQLite"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        # Check master table schema
        cursor = db.conn.execute("PRAGMA table_info(master)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        self.assertEqual(columns['DATE_RECEIVED'], 'TIMESTAMP')
        self.assertEqual(columns['DATE_REPORT'], 'TIMESTAMP')
        self.assertEqual(columns['DATE_OF_EVENT'], 'TIMESTAMP')

        # Check device table schema (device table should NOT have DATE_RECEIVED - only master table has it)
        cursor = db.conn.execute("PRAGMA table_info(device)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        # Device table only has EXPIRATION_DATE_OF_DEVICE date column
        self.assertEqual(columns['EXPIRATION_DATE_OF_DEVICE'], 'TIMESTAMP')
        # Verify DATE_RECEIVED is NOT in device table (prevents duplicate columns)
        self.assertNotIn('DATE_RECEIVED', columns)

        db.close()

    def test_date_filtering_works_in_sql(self):
        """Test that date filtering works with SQL WHERE clauses"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        # Query using date filtering
        result = db.query("""
            SELECT COUNT(*) as count FROM master
            WHERE DATE_RECEIVED >= '2020-02-01'
        """)

        self.assertEqual(result['count'][0], 4)  # 1234568 (02/20), 1234569 (03/10), 1234570 (04/15), 1234571 (05/20)

        db.close()

    def test_date_extraction_with_strftime(self):
        """Test that SQL date functions work on stored dates"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        # Use strftime to extract year
        result = db.query("""
            SELECT strftime('%Y', DATE_RECEIVED) as year, COUNT(*) as count
            FROM master
            GROUP BY year
        """)

        self.assertEqual(result['year'].iloc[0], '2020')
        self.assertEqual(result['count'].iloc[0], 5)

        db.close()

    # ========== URL Existence Check Tests ==========

    @patch('requests.head')
    def test_check_url_exists_valid_url(self, mock_head):
        """Test that _check_url_exists returns True for valid URLs"""
        # Mock a successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_head.return_value = mock_response

        db = MaudeDatabase(self.test_db, verbose=False)
        result = db._check_url_exists('https://www.fda.gov/')
        self.assertTrue(result)

        # Verify the request was made with correct parameters
        mock_head.assert_called_once_with(
            'https://www.fda.gov/',
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=5,
            allow_redirects=True
        )

        db.close()

    @patch('requests.head')
    def test_check_url_exists_invalid_url(self, mock_head):
        """Test that _check_url_exists returns False for invalid URLs"""
        # Mock a 404 response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_head.return_value = mock_response

        db = MaudeDatabase(self.test_db, verbose=False)
        result = db._check_url_exists('https://www.fda.gov/nonexistent-file-12345.zip')
        self.assertFalse(result)

        db.close()

    @patch('requests.head')
    def test_check_url_exists_handles_redirects(self, mock_head):
        """Test that _check_url_exists follows redirects correctly"""
        # Mock a successful response after redirect (allow_redirects=True means final response)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_head.return_value = mock_response

        db = MaudeDatabase(self.test_db, verbose=False)
        result = db._check_url_exists('http://www.fda.gov/')
        self.assertTrue(result)

        # Verify allow_redirects was set to True
        call_kwargs = mock_head.call_args[1]
        self.assertTrue(call_kwargs['allow_redirects'])

        db.close()

    @patch('requests.head')
    def test_check_url_exists_handles_timeout(self, mock_head):
        """Test that _check_url_exists handles timeouts gracefully"""
        # Mock a timeout exception
        import requests
        mock_head.side_effect = requests.exceptions.Timeout()

        db = MaudeDatabase(self.test_db, verbose=False)
        result = db._check_url_exists('http://192.0.2.1/test.zip')
        self.assertFalse(result)

        db.close()

    # ========== Cumulative File Fallback Tests ==========

    def test_construct_file_url_cumulative_fallback_logic(self):
        """Test that cumulative file URL construction has fallback logic"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Test for master table (cumulative pattern)
        # The function should try multiple years if files don't exist
        # We'll check that it attempts the fallback by mocking _check_url_exists

        # Store original method
        original_check = db._check_url_exists

        # Track which URLs were checked
        checked_urls = []

        def mock_check(url):
            checked_urls.append(url)
            # Simulate: 2025 doesn't exist, 2024 exists
            if '2025' in url:
                return False
            elif '2024' in url:
                return True
            return original_check(url)

        # Replace method temporarily
        db._check_url_exists = mock_check

        # Request a historical year (which should use cumulative file)
        url, filename = db._construct_file_url('master', 2023)

        # Should have checked multiple years as fallback
        self.assertGreater(len(checked_urls), 0)

        # Should have selected 2024 file (first available)
        self.assertIn('2024', filename)

        # Restore original method
        db._check_url_exists = original_check
        db.close()

    def test_construct_file_url_cumulative_uses_first_available(self):
        """Test that cumulative file construction uses first available file"""
        db = MaudeDatabase(self.test_db, verbose=False)

        original_check = db._check_url_exists

        def mock_check(url):
            # Simulate: 2025 and 2024 don't exist, 2023 exists
            if '2025' in url or '2024' in url:
                return False
            elif '2023' in url:
                return True
            return False

        db._check_url_exists = mock_check

        url, filename = db._construct_file_url('master', 2020)

        # Should fall back to 2023 file
        self.assertIn('2023', filename)

        db._check_url_exists = original_check
        db.close()

    def test_construct_file_url_cumulative_handles_all_missing(self):
        """Test that cumulative file construction handles case when all fallbacks missing"""
        db = MaudeDatabase(self.test_db, verbose=False)

        original_check = db._check_url_exists

        def mock_check(url):
            # Simulate: all files missing
            return False

        db._check_url_exists = mock_check

        url, filename = db._construct_file_url('master', 2020)

        # Should still return a URL (will be handled by download error later)
        self.assertIsNotNone(url)
        self.assertIsNotNone(filename)

        db._check_url_exists = original_check
        db.close()

    def test_construct_file_url_yearly_not_affected(self):
        """Test that yearly pattern files are not affected by fallback logic"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Device table uses yearly pattern for recent years
        url, filename = db._construct_file_url('device', 2020)

        # Should have exact year in filename (no fallback)
        self.assertEqual(filename, 'device2020.zip')
        self.assertIn('device2020.zip', url)

        db.close()

    # ========== Force Download Tests ==========

    @patch('requests.get')
    def test_download_uses_disk_cache_by_default(self, mock_get):
        """Test that _download_file uses cached zip file by default (force_download=False)"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Create a fake zip file on disk
        data_dir = tempfile.mkdtemp()
        zip_path = f"{data_dir}/device2020.zip"

        # Create a minimal valid zip file
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('device2020.txt', 'fake data')

        try:
            # Call _download_file with default force_download=False
            result = db._download_file(2020, 'device', data_dir=data_dir, force_download=False)

            # Should return True (success)
            self.assertTrue(result)

            # Should NOT have called requests.get (used disk cache)
            mock_get.assert_not_called()

        finally:
            shutil.rmtree(data_dir)
            db.close()

    @patch('requests.get')
    def test_force_download_bypasses_disk_cache(self, mock_get):
        """Test that force_download=True bypasses disk cache and re-downloads"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Create a fake OLD zip file on disk
        data_dir = tempfile.mkdtemp()
        zip_path = f"{data_dir}/device2020.zip"

        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('device2020.txt', 'old data')

        # Mock requests.get to return a new zip file
        mock_response = Mock()
        mock_response.content = self._create_minimal_zip_content('device2020.txt', 'new data')
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        try:
            # Call _download_file with force_download=True
            result = db._download_file(2020, 'device', data_dir=data_dir, force_download=True)

            # Should return True (success)
            self.assertTrue(result)

            # Should have called requests.get (bypassed disk cache)
            mock_get.assert_called_once()

            # Verify it downloaded the correct URL
            call_args = mock_get.call_args[0]
            self.assertIn('device2020.zip', call_args[0])

        finally:
            shutil.rmtree(data_dir)
            db.close()

    def _create_minimal_zip_content(self, filename, content):
        """Helper to create minimal zip file content in memory"""
        import io
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr(filename, content)
        return zip_buffer.getvalue()

    @patch('requests.get')
    def test_force_download_bypasses_session_cache(self, mock_get):
        """Test that force_download=True bypasses session cache too"""
        db = MaudeDatabase(self.test_db, verbose=False)

        data_dir = tempfile.mkdtemp()

        # Mock requests.get to return valid zip
        mock_response = Mock()
        mock_response.content = self._create_minimal_zip_content('device2020.txt', 'data')
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        try:
            # First call with force_download=True
            result1 = db._download_file(2020, 'device', data_dir=data_dir, force_download=True)
            self.assertTrue(result1)

            # Second call with force_download=True (same session)
            result2 = db._download_file(2020, 'device', data_dir=data_dir, force_download=True)
            self.assertTrue(result2)

            # Should have called requests.get TWICE (bypassed session cache)
            self.assertEqual(mock_get.call_count, 2)

        finally:
            shutil.rmtree(data_dir)
            db.close()

    @patch.object(MaudeDatabase, '_download_file')
    def test_add_years_force_download_parameter(self, mock_download):
        """Test that add_years passes force_download to _download_file"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Mock _download_file to return True (success)
        mock_download.return_value = True

        # Create test data directory with files so processing can happen
        data_dir = tempfile.mkdtemp()

        # Create minimal test files
        with open(f"{data_dir}/mdrfoithru2023.txt", 'w', encoding='latin-1') as f:
            f.write('MDR_REPORT_KEY|DATE_RECEIVED|EVENT_TYPE|EVENT_KEY\n')
            f.write('12345|01/15/2020|IN|EVT001\n')

        with open(f"{data_dir}/device2020.txt", 'w', encoding='latin-1') as f:
            f.write('MDR_REPORT_KEY|BRAND_NAME|GENERIC_NAME|DEVICE_REPORT_PRODUCT_CODE\n')
            f.write('12345|TestDevice|Generic Name|ABC\n')

        try:
            # Call add_years with force_download=True
            db.add_years(2020, tables=['device'], download=True,
                        force_download=True, data_dir=data_dir, interactive=False)

            # Verify _download_file was called with force_download=True
            mock_download.assert_called()

            # Check that at least one call had force_download=True
            calls = mock_download.call_args_list
            found_force_download = False
            for call in calls:
                if 'force_download' in call[1] and call[1]['force_download'] == True:
                    found_force_download = True
                    break

            self.assertTrue(found_force_download,
                          "Expected _download_file to be called with force_download=True")

        finally:
            shutil.rmtree(data_dir)
            db.close()

    def test_update_force_download_parameter(self):
        """Test that update passes force_download to add_years"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Add some initial data so update has something to work with
        with open(f"{self.test_data_dir}/mdrfoithru2023.txt", 'w', encoding='latin-1') as f:
            f.write('MDR_REPORT_KEY|DATE_RECEIVED|EVENT_TYPE|EVENT_KEY\n')
            f.write('12345|01/15/2020|IN|EVT001\n')

        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        # Now patch add_years for the update call
        with patch.object(db, 'add_years') as mock_add_years:
            # Call update with force_download=True
            db.update(add_new_years=False, download=True, force_download=True)

            # Verify add_years was called with force_download=True
            mock_add_years.assert_called_once()
            call_kwargs = mock_add_years.call_args[1]
            self.assertTrue(call_kwargs.get('force_download', False),
                           "Expected add_years to be called with force_download=True")

        db.close()

    @patch('requests.get')
    def test_force_download_no_effect_when_download_false(self, mock_get):
        """Test that force_download has no effect when download=False"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Create test file
        with open(f"{self.test_data_dir}/device2020.txt", 'w', encoding='latin-1') as f:
            f.write('MDR_REPORT_KEY|BRAND_NAME|GENERIC_NAME|DEVICE_REPORT_PRODUCT_CODE\n')
            f.write('12345|TestDevice|Generic Name|ABC\n')

        # Call add_years with download=False but force_download=True
        db.add_years(2020, tables=['device'], download=False,
                    force_download=True, data_dir=self.test_data_dir, interactive=False)

        # Should NOT have called requests.get (download=False)
        mock_get.assert_not_called()

        db.close()


if __name__ == '__main__':
    unittest.main()