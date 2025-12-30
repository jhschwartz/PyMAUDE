import unittest
import os
import tempfile
import shutil
import sqlite3
from datetime import datetime

from maude_db import MaudeDatabase


class TestChecksumTracking(unittest.TestCase):
    """Unit tests for checksum tracking functionality"""

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
        # Sample master file (cumulative pattern)
        master_data = """MDR_REPORT_KEY|DATE_RECEIVED|EVENT_TYPE
1234567|01/15/2020|Injury
1234568|02/20/2020|Death"""

        self.master_file = f'{self.test_data_dir}/mdrfoithru2020.txt'
        with open(self.master_file, 'w') as f:
            f.write(master_data)

        # Sample text file (yearly pattern)
        text_data = """MDR_REPORT_KEY|FOI_TEXT
1234567|Test report 1
1234568|Test report 2"""

        self.text_file = f'{self.test_data_dir}/foitext2020.txt'
        with open(self.text_file, 'w') as f:
            f.write(text_data)

    # ========== Metadata Table Tests ==========

    def test_metadata_table_created_on_init(self):
        """Test that metadata table is created when database is initialized"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Check table exists
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_maude_load_metadata'"
        )
        result = cursor.fetchone()

        self.assertIsNotNone(result)
        db.close()

    def test_metadata_table_schema(self):
        """Test that metadata table has correct schema"""
        db = MaudeDatabase(self.test_db, verbose=False)

        cursor = db.conn.execute('PRAGMA table_info(_maude_load_metadata)')
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        expected_columns = {
            'table_name': 'TEXT',
            'year': 'INTEGER',
            'file_path': 'TEXT',
            'file_checksum': 'TEXT',
            'loaded_at': 'TIMESTAMP',
            'row_count': 'INTEGER'
        }

        for col_name, col_type in expected_columns.items():
            self.assertIn(col_name, columns)
            self.assertEqual(columns[col_name], col_type)

        db.close()

    def test_metadata_table_primary_key(self):
        """Test that primary key constraint works"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Insert first record
        db._record_file_load('test_table', 2020, '/path/to/file', 'checksum1', 100)

        # Insert duplicate (should replace due to INSERT OR REPLACE)
        db._record_file_load('test_table', 2020, '/path/to/file2', 'checksum2', 200)

        # Verify only one record exists
        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM _maude_load_metadata WHERE table_name='test_table' AND year=2020"
        )
        count = cursor.fetchone()[0]

        self.assertEqual(count, 1)

        # Verify it's the second one (replacement worked)
        info = db._get_loaded_file_info('test_table', 2020)
        self.assertEqual(info['file_checksum'], 'checksum2')

        db.close()

    # ========== Checksum Computation Tests ==========

    def test_compute_checksum_valid_file(self):
        """Test checksum computation for valid file"""
        db = MaudeDatabase(self.test_db, verbose=False)

        checksum = db._compute_file_checksum(self.master_file)

        self.assertIsNotNone(checksum)
        self.assertEqual(len(checksum), 64)  # SHA256 produces 64 hex chars
        self.assertTrue(all(c in '0123456789abcdef' for c in checksum))

        db.close()

    def test_compute_checksum_nonexistent_file(self):
        """Test checksum computation for nonexistent file"""
        db = MaudeDatabase(self.test_db, verbose=False)

        checksum = db._compute_file_checksum('/nonexistent/file.txt')

        self.assertIsNone(checksum)
        db.close()

    def test_compute_checksum_deterministic(self):
        """Test that same file produces same checksum"""
        db = MaudeDatabase(self.test_db, verbose=False)

        checksum1 = db._compute_file_checksum(self.master_file)
        checksum2 = db._compute_file_checksum(self.master_file)

        self.assertEqual(checksum1, checksum2)
        db.close()

    def test_compute_checksum_different_for_modified_file(self):
        """Test that modified file produces different checksum"""
        db = MaudeDatabase(self.test_db, verbose=False)

        checksum1 = db._compute_file_checksum(self.master_file)

        # Modify file
        with open(self.master_file, 'a') as f:
            f.write('\n1234569|03/10/2020|Malfunction')

        checksum2 = db._compute_file_checksum(self.master_file)

        self.assertNotEqual(checksum1, checksum2)
        db.close()

    # ========== File Load Recording Tests ==========

    def test_record_file_load(self):
        """Test recording a file load"""
        db = MaudeDatabase(self.test_db, verbose=False)

        db._record_file_load('master', 2020, self.master_file, 'abc123', 1000)

        cursor = db.conn.execute(
            "SELECT * FROM _maude_load_metadata WHERE table_name='master' AND year=2020"
        )
        row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'master')  # table_name
        self.assertEqual(row[1], 2020)  # year
        self.assertEqual(row[3], 'abc123')  # file_checksum
        self.assertEqual(row[5], 1000)  # row_count

        db.close()

    def test_record_file_load_updates_timestamp(self):
        """Test that recording updates the loaded_at timestamp"""
        db = MaudeDatabase(self.test_db, verbose=False)

        db._record_file_load('master', 2020, self.master_file, 'abc123', 1000)
        info1 = db._get_loaded_file_info('master', 2020)

        # Wait a tiny bit (not necessary but conceptually shows time passing)
        import time
        time.sleep(0.01)

        db._record_file_load('master', 2020, self.master_file, 'xyz789', 2000)
        info2 = db._get_loaded_file_info('master', 2020)

        self.assertNotEqual(info1['loaded_at'], info2['loaded_at'])
        self.assertEqual(info2['file_checksum'], 'xyz789')

        db.close()

    def test_get_loaded_file_info_exists(self):
        """Test retrieving info for existing file"""
        db = MaudeDatabase(self.test_db, verbose=False)

        db._record_file_load('master', 2020, self.master_file, 'abc123', 1000)
        info = db._get_loaded_file_info('master', 2020)

        self.assertIsNotNone(info)
        self.assertEqual(info['file_checksum'], 'abc123')
        self.assertEqual(info['row_count'], 1000)
        self.assertIsNotNone(info['loaded_at'])

        db.close()

    def test_get_loaded_file_info_not_exists(self):
        """Test retrieving info for non-existent file"""
        db = MaudeDatabase(self.test_db, verbose=False)

        info = db._get_loaded_file_info('master', 2020)

        self.assertIsNone(info)
        db.close()

    # ========== Year Data Deletion Tests ==========

    def test_delete_year_data(self):
        """Test deleting year data from table"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Load data first
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        # Verify data exists
        count_before = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_before, 2)

        # Delete year data
        db._delete_year_data('master', 2020)

        # Verify data deleted
        count_after = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_after, 0)

        db.close()

    def test_delete_year_data_nonexistent_table(self):
        """Test deleting from non-existent table doesn't error"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Should not raise error
        db._delete_year_data('nonexistent_table', 2020)

        db.close()

    def test_delete_year_data_no_date_column(self):
        """Test deleting from table without date column"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Create a table without date column
        db.conn.execute("CREATE TABLE test_table (id INTEGER, name TEXT)")
        db.conn.commit()

        # Should not raise error, just skip
        db._delete_year_data('test_table', 2020)

        db.close()

    # ========== Count Table Rows Tests ==========

    def test_count_table_rows(self):
        """Test counting rows in table"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Load data
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        count = db._count_table_rows('master')
        self.assertEqual(count, 2)

        db.close()

    def test_count_table_rows_empty_table(self):
        """Test counting rows in empty table"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Create empty table
        db.conn.execute("CREATE TABLE empty_table (id INTEGER)")
        db.conn.commit()

        count = db._count_table_rows('empty_table')
        self.assertEqual(count, 0)

        db.close()

    def test_count_table_rows_nonexistent(self):
        """Test counting rows in non-existent table"""
        db = MaudeDatabase(self.test_db, verbose=False)

        count = db._count_table_rows('nonexistent_table')
        self.assertEqual(count, 0)

        db.close()

    # ========== Integration Tests: Skip Unchanged Files ==========

    def test_add_years_first_load_processes_file(self):
        """Test that first load processes the file"""
        db = MaudeDatabase(self.test_db, verbose=False)

        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        # Verify data was loaded
        count = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count, 2)

        # Verify metadata was recorded
        info = db._get_loaded_file_info('master', 2020)
        self.assertIsNotNone(info)

        db.close()

    def test_add_years_second_load_skips_unchanged_file(self):
        """Test that second load with unchanged file skips processing"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # First load
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        count_after_first = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_after_first, 2)

        # Second load - should skip
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        count_after_second = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_after_second, 2)  # No duplicates!

        db.close()

    def test_add_years_changed_file_reprocesses(self):
        """Test that changed file is detected and reprocessed"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # First load
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        count_after_first = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_after_first, 2)

        # Modify the file
        with open(self.master_file, 'a') as f:
            f.write('\n1234569|03/10/2020|Malfunction')

        # Second load - should detect change and reprocess
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        count_after_second = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_after_second, 3)  # Updated data

        db.close()

    def test_add_years_force_refresh_always_processes(self):
        """Test that force_refresh ignores checksums"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # First load
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        count_after_first = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_after_first, 2)

        # Second load with force_refresh - should process even though unchanged
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False,
                    force_refresh=True)

        count_after_second = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_after_second, 2)  # Replaced, not duplicated

        db.close()

    # ========== Integration Tests: Cumulative Files ==========

    def test_cumulative_file_multiple_years_same_checksum(self):
        """Test that multiple years from same cumulative file share checksum"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Load multiple years from same cumulative file
        db.add_years([2019, 2020], tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        # Both years should have same checksum
        info_2019 = db._get_loaded_file_info('master', 2019)
        info_2020 = db._get_loaded_file_info('master', 2020)

        self.assertIsNotNone(info_2019)
        self.assertIsNotNone(info_2020)
        self.assertEqual(info_2019['file_checksum'], info_2020['file_checksum'])

        db.close()

    def test_cumulative_file_all_years_skipped_when_unchanged(self):
        """Test that all years are skipped when cumulative file unchanged"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # First load - multiple years
        db.add_years([2019, 2020], tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        count_first = db.query("SELECT COUNT(*) as count FROM master")['count'][0]

        # Second load - should skip both years
        db.add_years([2019, 2020], tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        count_second = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_first, count_second)  # No duplicates

        db.close()

    # ========== Edge Cases ==========

    def test_add_years_partial_years_already_loaded(self):
        """Test adding years when some are already loaded"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Load 2020 first
        db.add_years(2020, tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        count_first = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_first, 2)

        # Now load 2019-2020 (2020 already exists with same checksum)
        # Because they come from same cumulative file, both should be skipped
        db.add_years([2019, 2020], tables=['master'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        # Should not have duplicates - data should be unchanged
        count_second = db.query("SELECT COUNT(*) as count FROM master")['count'][0]
        self.assertEqual(count_second, 2)  # No duplicates

        db.close()

    def test_multiple_tables_independent_checksums(self):
        """Test that different tables track checksums independently"""
        db = MaudeDatabase(self.test_db, verbose=False)

        db.add_years(2020, tables=['master', 'text'], download=False,
                    data_dir=self.test_data_dir, interactive=False)

        info_master = db._get_loaded_file_info('master', 2020)
        info_text = db._get_loaded_file_info('text', 2020)

        self.assertIsNotNone(info_master)
        self.assertIsNotNone(info_text)
        # Different files = different checksums
        self.assertNotEqual(info_master['file_checksum'], info_text['file_checksum'])

        db.close()


if __name__ == '__main__':
    unittest.main()
