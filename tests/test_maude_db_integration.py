"""
Integration tests for MaudeDatabase that test actual FDA data downloads.

These tests download real data from FDA servers and are slower than unit tests.
Run with: pytest -m integration

To skip integration tests during normal testing:
pytest -m "not integration"
"""

import unittest
import os
import tempfile
import shutil
import pytest
from maude_db import MaudeDatabase


@pytest.mark.integration
class TestMaudeDatabaseIntegration(unittest.TestCase):
    """Integration tests that download real data from FDA servers"""

    @classmethod
    def setUpClass(cls):
        """Set up once for all tests - create temp directory"""
        cls.test_dir = tempfile.mkdtemp()
        cls.test_db = os.path.join(cls.test_dir, 'integration_test.db')
        cls.test_data_dir = os.path.join(cls.test_dir, 'maude_data')
        os.makedirs(cls.test_data_dir, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)

    def setUp(self):
        """Reset database before each test"""
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
            

    def test_download_single_year_device(self):
        """Test downloading device (foidev) data from FDA"""
        db = MaudeDatabase(self.test_db, verbose=True)

        # Use 1998 - earliest available individual year file for foidev
        db.add_years(
            years=1998,
            tables=['device'],
            download=True,
            data_dir=self.test_data_dir
        )

        # Verify data was loaded
        result = db.query("SELECT COUNT(*) as count FROM device")
        count = result['count'][0]

        self.assertGreater(count, 0, "Should have downloaded and loaded some device records")

        db.close()
        print(f"✓ Successfully downloaded and loaded {count:,} device records from 1998")

    def test_download_single_year_text(self):
        """Test downloading narrative text (foitext) data from FDA"""
        db = MaudeDatabase(self.test_db, verbose=True)

        # Use 1996 - earliest year according to FDA website for foitext
        db.add_years(
            years=1996,
            tables=['text'],
            download=True,
            data_dir=self.test_data_dir
        )

        # Verify data was loaded
        result = db.query("SELECT COUNT(*) as count FROM text")
        count = result['count'][0]

        self.assertGreater(count, 0, "Should have downloaded and loaded some text records")

        db.close()
        print(f"✓ Successfully downloaded and loaded {count:,} text records from 1996")

    def test_download_multiple_tables_same_year(self):
        """Test downloading multiple table types for the same year"""
        db = MaudeDatabase(self.test_db, verbose=True)

        # Download device and text for 1998 (both have individual year files)
        db.add_years(
            years=1998,
            tables=['device', 'text'],
            download=True,
            data_dir=self.test_data_dir
        )

        # Verify both tables have data
        device_count = db.query("SELECT COUNT(*) as count FROM device")['count'][0]
        text_count = db.query("SELECT COUNT(*) as count FROM text")['count'][0]

        self.assertGreater(device_count, 0, "Device table should have records")
        self.assertGreater(text_count, 0, "Text table should have records")

        # Verify we can join the tables
        joined = db.query("""
            SELECT COUNT(*) as count
            FROM device d
            JOIN text t ON d.mdr_report_key = t.mdr_report_key
        """)
        joined_count = joined['count'][0]

        self.assertGreater(joined_count, 0, "Should be able to join device and text tables")

        db.close()
        print(f"✓ Successfully downloaded device ({device_count:,}) and text ({text_count:,}) records")
        print(f"✓ Successfully joined {joined_count:,} records")

    def test_download_uses_cached_files(self):
        """Test that re-downloading uses cached ZIP files"""
        db = MaudeDatabase(self.test_db, verbose=True)

        # First download - use 1998 device file
        db.add_years(
            years=1998,
            tables=['device'],
            download=True,
            data_dir=self.test_data_dir
        )

        # Check that ZIP file was saved
        zip_path = f"{self.test_data_dir}/foidev1998.zip"
        self.assertTrue(os.path.exists(zip_path), "ZIP file should be cached")

        # Get ZIP file modification time
        first_mtime = os.path.getmtime(zip_path)

        # Close and recreate database
        db.close()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

        # Second download should use cached ZIP
        db2 = MaudeDatabase(self.test_db, verbose=True)
        db2.add_years(
            years=1998,
            tables=['device'],
            download=True,
            data_dir=self.test_data_dir
        )

        # ZIP file should not have been re-downloaded (same modification time)
        second_mtime = os.path.getmtime(zip_path)
        self.assertEqual(first_mtime, second_mtime, "Should use cached ZIP file")

        db2.close()
        print("✓ Successfully used cached ZIP file on second download")

    def test_check_file_exists_on_server(self):
        """Test that _check_file_exists correctly identifies available files"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # 1998 foidev should exist
        exists_1998 = db._check_file_exists(1998, 'foidev')
        self.assertTrue(exists_1998, "1998 device file should exist on FDA server")

        # 1980 probably doesn't exist (too old)
        exists_1980 = db._check_file_exists(1980, 'foidev')
        self.assertFalse(exists_1980, "1980 device file should not exist on FDA server")

        # 2050 definitely doesn't exist (future)
        exists_2050 = db._check_file_exists(2050, 'foidev')
        self.assertFalse(exists_2050, "2050 device file should not exist on FDA server")

        db.close()
        print("✓ File existence checks working correctly")

    def test_download_gracefully_handles_missing_year(self):
        """Test that download handles missing years gracefully in non-strict mode"""
        db = MaudeDatabase(self.test_db, verbose=True)

        # Try to download a year that doesn't exist, should skip without error
        db.add_years(
            years=1980,  # Doesn't exist (before 1991 start year)
            tables=['master'],
            download=True,
            strict=False,  # Don't raise error
            data_dir=self.test_data_dir,
            interactive=False  # Don't prompt in tests
        )

        # Database should still be functional even though no data was loaded
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")

        # Should either have no tables or empty tables
        db.close()
        print("✓ Gracefully handled missing year without crashing")

    def test_download_strict_mode_raises_on_missing(self):
        """Test that strict mode raises error on missing files"""
        db = MaudeDatabase(self.test_db, verbose=False)

        # Should raise ValueError for invalid year (before start year)
        # Note: Year 1980 is before the master table start year of 1991, so this
        # triggers validation error rather than file not found error
        with self.assertRaises(ValueError):
            db.add_years(
                years=1980,  # Before 1991 start year
                tables=['master'],
                download=True,
                strict=True,  # Should raise error
                data_dir=self.test_data_dir,
                interactive=False  # Don't prompt in tests
            )

        db.close()
        print("✓ Strict mode correctly raises error on invalid year")

    def test_real_query_workflow(self):
        """Test a realistic end-to-end workflow with real data"""
        db = MaudeDatabase(self.test_db, verbose=True)

        # Download 1998 device data
        db.add_years(
            years=1998,
            tables=['device'],
            download=True,
            data_dir=self.test_data_dir
        )

        # Get database info
        print("\n" + "="*60)
        db.info()
        print("="*60)

        # Query for device types
        all_devices = db.query("""
            SELECT DISTINCT d.generic_name, COUNT(*) as count
            FROM device d
            GROUP BY d.generic_name
            ORDER BY count DESC
            LIMIT 10
        """)

        self.assertGreater(len(all_devices), 0, "Should have some device types")
        print(f"\n✓ Found {len(all_devices)} device types in 1998 data")
        print("\nTop devices:")
        print(all_devices.to_string(index=False))

        db.close()

    def test_device_table_columns_match_source_file(self):
        """Test that device table in SQLite has exactly the same columns as the source text file"""
        db = MaudeDatabase(self.test_db, verbose=True)

        # Download 1998 device data
        db.add_years(
            years=1998,
            tables=['device'],
            download=True,
            data_dir=self.test_data_dir
        )

        # Read the source file to get expected columns
        device_file = f"{self.test_data_dir}/foidev1998.txt"
        self.assertTrue(os.path.exists(device_file),
                       f"Device file not found: {device_file}")

        # Read first line (header) from source file
        with open(device_file, 'r', encoding='latin1') as f:
            header = f.readline().strip()
            expected_columns = set(header.split('|'))

        print(f"\n✓ Source file has {len(expected_columns)} columns")

        # Get actual columns from SQLite database
        cursor = db.conn.execute("PRAGMA table_info(device)")
        actual_columns = {row[1] for row in cursor.fetchall()}

        print(f"✓ SQLite table has {len(actual_columns)} columns")

        # Verify no extra columns were added by our processing
        extra_columns = actual_columns - expected_columns
        self.assertEqual(len(extra_columns), 0,
                        f"Unexpected columns in device table: {extra_columns}")

        # Verify no columns were lost during processing
        missing_columns = expected_columns - actual_columns
        self.assertEqual(len(missing_columns), 0,
                        f"Missing columns in device table: {missing_columns}")

        # Verify exact match
        self.assertEqual(actual_columns, expected_columns,
                        "Device table columns should exactly match source file")

        print(f"✓ Device table columns match source file exactly")

        db.close()


if __name__ == '__main__':
    # Run only integration tests
    pytest.main([__file__, '-v', '-m', 'integration'])