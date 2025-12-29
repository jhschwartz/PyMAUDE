import unittest
import os
import tempfile
import shutil
import sqlite3
import pandas as pd
from datetime import datetime
import sys

from maude_db import MaudeDatabase


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
        # Sample master file (mdrfoi)
        master_data = """mdr_report_key|date_received|event_type|manufacturer_name
1234567|2020-01-15|Injury|Test Manufacturer
1234568|2020-02-20|Death|Another Manufacturer
1234569|2020-03-10|Malfunction|Test Manufacturer"""
        
        with open(f'{self.test_data_dir}/mdrfoi2020.txt', 'w') as f:
            f.write(master_data)
        
        # Sample device file (foidev) - using uppercase column names like real FDA data
        device_data = """MDR_REPORT_KEY|DEVICE_REPORT_PRODUCT_CODE|GENERIC_NAME|BRAND_NAME
1234567|NIQ|Thrombectomy Device|DeviceX
1234568|NIQ|Thrombectomy Device|DeviceY
1234569|ABC|Other Device|DeviceZ"""
        
        with open(f'{self.test_data_dir}/foidev2020.txt', 'w') as f:
            f.write(device_data)
        
        # Sample patient file
        patient_data = """mdr_report_key|patient_sequence_number|date_of_event
1234567|1|2020-01-10
1234568|1|2020-02-15"""
        
        with open(f'{self.test_data_dir}/patient2020.txt', 'w') as f:
            f.write(patient_data)
        
        # Sample text file - using uppercase column names like real FDA data
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
        """Test finding lowercase file paths"""
        db = MaudeDatabase(self.test_db, verbose=False)
        path = db._make_file_path('master', 2020, self.test_data_dir)
        self.assertTrue(path.endswith('mdrfoi2020.txt'))
        db.close()
    
    def test_make_file_path_uppercase(self):
        """Test finding uppercase file paths"""
        # Create uppercase file
        with open(f'{self.test_data_dir}/MDRFOI2021.txt', 'w') as f:
            f.write('test')

        db = MaudeDatabase(self.test_db, verbose=False)
        path = db._make_file_path('master', 2021, self.test_data_dir)
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith('MDRFOI2021.txt'))
        db.close()
    
    def test_make_file_path_missing(self):
        """Test that missing files return False"""
        db = MaudeDatabase(self.test_db, verbose=False)
        path = db._make_file_path('master', 1999, self.test_data_dir)
        self.assertFalse(path)
        db.close()
    
    # ========== Add Years Tests ==========
    
    def test_add_years_basic(self):
        """Test basic add_years functionality"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
        
        # Check that data was added
        df = db.query("SELECT COUNT(*) as count FROM master")
        self.assertEqual(df['count'][0], 3)
        
        df = db.query("SELECT COUNT(*) as count FROM device")
        self.assertEqual(df['count'][0], 3)
        
        db.close()
    
    def test_add_years_strict_mode_failure(self):
        """Test that strict mode raises error on missing file"""
        db = MaudeDatabase(self.test_db, verbose=False)
        
        with self.assertRaises(FileNotFoundError):
            db.add_years(1999, tables=['master'], download=False, strict=True, data_dir=self.test_data_dir)
        
        db.close()
    
    def test_add_years_non_strict_mode(self):
        """Test that non-strict mode skips missing files"""
        db = MaudeDatabase(self.test_db, verbose=False)
        
        # Should not raise error
        db.add_years(1999, tables=['master'], download=False, strict=False, data_dir=self.test_data_dir)
        
        db.close()
    
    def test_add_years_creates_indexes(self):
        """Test that indexes are created"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
        
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
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir)

        df = db.query("SELECT * FROM master WHERE event_type = 'Death'")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['mdr_report_key'], 1234568)

        db.close()
    
    def test_query_with_params(self):
        """Test parameterized queries"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir)
        
        df = db.query(
            "SELECT * FROM master WHERE event_type = :type",
            params={'type': 'Injury'}
        )
        self.assertEqual(len(df), 1)
        
        db.close()
    
    def test_query_device_by_name(self):
        """Test query_device with device name filter"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
        
        df = db.query_device(device_name='Thrombectomy')
        self.assertEqual(len(df), 2)
        
        db.close()
    
    def test_query_device_by_product_code(self):
        """Test query_device with product code filter"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
        
        df = db.query_device(product_code='NIQ')
        self.assertEqual(len(df), 2)
        
        db.close()
    
    def test_query_device_by_date_range(self):
        """Test query_device with date filters"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
        
        df = db.query_device(start_date='2020-02-01', end_date='2020-12-31')
        self.assertEqual(len(df), 2)
        
        db.close()
    
    def test_query_device_multiple_filters(self):
        """Test query_device with multiple filters"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
        
        df = db.query_device(
            device_name='Thrombectomy',
            start_date='2020-02-01'
        )
        self.assertEqual(len(df), 1)
        
        db.close()
    
    def test_get_trends_by_year(self):
        """Test get_trends_by_year functionality"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
        
        df = db.get_trends_by_year()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['year'], '2020')
        self.assertEqual(df.iloc[0]['event_count'], 3)
        self.assertEqual(df.iloc[0]['deaths'], 1)
        self.assertEqual(df.iloc[0]['injuries'], 1)
        
        db.close()
    
    def test_get_trends_by_product_code(self):
        """Test get_trends_by_year with product code filter"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
        
        df = db.get_trends_by_year(product_code='NIQ')
        self.assertEqual(df.iloc[0]['event_count'], 2)
        
        db.close()
    
    def test_get_narratives(self):
        """Test get_narratives functionality"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['text'], download=False, data_dir=self.test_data_dir)
        
        df = db.get_narratives(['1234567', '1234568'])
        self.assertEqual(len(df), 2)
        self.assertIn('adverse event', df.iloc[0]['FOI_TEXT'])
        
        db.close()
    
    # ========== Export Tests ==========
    
    def test_export_subset(self):
        """Test export_subset functionality"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
        
        output_file = os.path.join(self.test_dir, 'export.csv')
        db.export_subset(output_file, device_name='Thrombectomy')
        
        self.assertTrue(os.path.exists(output_file))
        
        df = pd.read_csv(output_file)
        self.assertEqual(len(df), 2)
        
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
        db.add_years(2020, tables=['master', 'device'], download=False, data_dir=self.test_data_dir)
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
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir)
        
        years = db._get_years_in_db()
        self.assertIn(2020, years)
        
        db.close()
    
    # ========== Update Tests ==========
    
    def test_update_when_up_to_date(self):
        """Test update when database is current"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir)
        
        # Mock _get_latest_available_year to return 2020
        original_method = db._get_latest_available_year
        db._get_latest_available_year = lambda: 2020
        
        # Should not add duplicate data
        db.update()
        
        df = db.query("SELECT COUNT(*) as count FROM master")
        self.assertEqual(df['count'][0], 3)  # Still only 3 records
        
        db._get_latest_available_year = original_method
        db.close()
    
    # ========== Edge Cases ==========
    
    def test_empty_table_list(self):
        """Test add_years with empty table list"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=[], download=False, data_dir=self.test_data_dir)
        
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'",
            db.conn
        )['name'].tolist()
        
        self.assertEqual(len(tables), 0)
        db.close()
    
    def test_duplicate_year_addition(self):
        """Test adding same year twice"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir)
        db.add_years(2020, tables=['master'], download=False, data_dir=self.test_data_dir)
        
        # Should have duplicate rows
        df = db.query("SELECT COUNT(*) as count FROM master")
        self.assertEqual(df['count'][0], 6)  # 3 records x 2
        
        db.close()
    
    def test_close(self):
        """Test close method"""
        db = MaudeDatabase(self.test_db, verbose=False)
        db.close()
        
        with self.assertRaises(sqlite3.ProgrammingError):
            db.conn.execute("SELECT 1")


if __name__ == '__main__':
    unittest.main()