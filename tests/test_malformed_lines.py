"""
Unit tests for malformed line handling in MAUDE data processing.

These tests ensure that the processor correctly handles lines with:
- Extra pipe delimiters in text fields
- Missing fields
- Embedded special characters
- Date parsing edge cases

The fix uses Python engine instead of C engine to handle malformed lines.
"""

import unittest
import os
import tempfile
import sqlite3
from io import StringIO
import sys
import warnings
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from maude_db import processors


class TestMalformedLineHandling(unittest.TestCase):
    """Test that processors correctly handle malformed MAUDE data lines"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.temp_dir, 'test.db')
        self.conn = sqlite3.connect(self.test_db)

        # Create a test table
        self.conn.execute("""
            CREATE TABLE test_master (
                MDR_REPORT_KEY TEXT,
                EVENT_KEY REAL,
                REPORT_NUMBER TEXT,
                DATE_RECEIVED TIMESTAMP,
                ADVERSE_EVENT_FLAG TEXT,
                PRODUCT_PROBLEM_FLAG TEXT,
                MANUFACTURER_NAME TEXT
            )
        """)
        self.conn.commit()

    def tearDown(self):
        """Clean up test database"""
        self.conn.close()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)

    def _create_test_file(self, content):
        """Helper to create a temporary test data file"""
        test_file = os.path.join(self.temp_dir, 'test_data.txt')
        with open(test_file, 'w', encoding='latin1') as f:
            f.write(content)
        return test_file

    def test_normal_lines_are_processed(self):
        """Test that normal, well-formed lines are processed correctly"""
        content = """MDR_REPORT_KEY|EVENT_KEY|REPORT_NUMBER|DATE_RECEIVED|ADVERSE_EVENT_FLAG|PRODUCT_PROBLEM_FLAG|MANUFACTURER_NAME
12345||REP-2018-001|01/15/2018|Y|Y|Test Manufacturer
67890||REP-2019-002|03/20/2019|N|Y|Another Manufacturer
11111||REP-2020-003|05/10/2020|Y|N|Third Manufacturer
"""
        test_file = self._create_test_file(content)

        # Process the file
        processors.process_file(
            filepath=test_file,
            table_name='test_master',
            conn=self.conn,
            chunk_size=100,
            verbose=False
        )

        # Verify all rows were inserted
        cursor = self.conn.execute("SELECT COUNT(*) FROM test_master")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 3, "Should process all 3 normal lines")

    def test_extra_pipe_in_text_field(self):
        """Test that lines with extra pipes in text fields are handled"""
        # This simulates the real-world issue where manufacturer names
        # or other text fields contain pipe characters
        content = """MDR_REPORT_KEY|EVENT_KEY|REPORT_NUMBER|DATE_RECEIVED|ADVERSE_EVENT_FLAG|PRODUCT_PROBLEM_FLAG|MANUFACTURER_NAME
12345||REP-2018-001|01/15/2018|Y|Y|Normal Manufacturer
67890||REP-2019-002|03/20/2019|N|Y|Manufacturer with | pipe
11111||REP-2020-003|05/10/2020|Y|N|Another Normal One
"""
        test_file = self._create_test_file(content)

        # Process the file - with python engine, this should handle the extra pipe
        # Note: The line with extra pipe will be skipped with a warning,
        # but processing continues
        # Suppress the expected ParserWarning for this test
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=pd.errors.ParserWarning)
            processors.process_file(
                filepath=test_file,
                table_name='test_master',
                conn=self.conn,
                chunk_size=100,
                verbose=False
            )

        # Verify that at least the good lines were processed
        cursor = self.conn.execute("SELECT COUNT(*) FROM test_master")
        count = cursor.fetchone()[0]
        self.assertGreaterEqual(count, 2,
            "Should process at least the 2 well-formed lines")

    def test_batch_processing_with_year_filtering(self):
        """Test batch processing correctly filters by year despite malformed lines"""
        content = """MDR_REPORT_KEY|EVENT_KEY|REPORT_NUMBER|DATE_RECEIVED|ADVERSE_EVENT_FLAG|PRODUCT_PROBLEM_FLAG|MANUFACTURER_NAME
12345||REP-2018-001|01/15/2018|Y|Y|Test Manufacturer
67890||REP-2019-002|03/20/2019|N|Y|Another Manufacturer
11111||REP-2020-003|05/10/2020|Y|N|Third Manufacturer
22222||REP-2015-004|06/01/2015|N|N|Old Record
33333||REP-2024-005|12/15/2024|Y|Y|Recent Record
"""
        test_file = self._create_test_file(content)

        metadata = {'date_column': 'DATE_RECEIVED'}
        years_list = [2018, 2019, 2020]

        # Process with year filtering
        processors.process_cumulative_file_batch(
            filepath=test_file,
            table_name='test_master',
            years_list=years_list,
            metadata=metadata,
            conn=self.conn,
            chunk_size=100,
            verbose=False
        )

        # Verify only 2018-2020 records were inserted
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM test_master
            WHERE STRFTIME('%Y', DATE_RECEIVED) IN ('2018', '2019', '2020')
        """)
        count = cursor.fetchone()[0]
        self.assertEqual(count, 3,
            "Should only include records from 2018-2020")

        # Verify total count excludes 2015 and 2024
        cursor = self.conn.execute("SELECT COUNT(*) FROM test_master")
        total = cursor.fetchone()[0]
        self.assertEqual(total, 3,
            "Should exclude records outside requested years")

    def test_year_extraction_from_dates(self):
        """Test that year extraction works correctly for date filtering"""
        content = """MDR_REPORT_KEY|EVENT_KEY|REPORT_NUMBER|DATE_RECEIVED|ADVERSE_EVENT_FLAG|PRODUCT_PROBLEM_FLAG|MANUFACTURER_NAME
12345||REP-2018-001|12/31/2018|Y|Y|End of Year 2018
67890||REP-2019-002|01/01/2019|N|Y|Start of Year 2019
11111||REP-2019-003|12/31/2019|Y|N|End of Year 2019
22222||REP-2020-004|01/01/2020|Y|Y|Start of Year 2020
"""
        test_file = self._create_test_file(content)

        metadata = {'date_column': 'DATE_RECEIVED'}

        # Process only 2019
        processors.process_cumulative_file_batch(
            filepath=test_file,
            table_name='test_master',
            years_list=[2019],
            metadata=metadata,
            conn=self.conn,
            chunk_size=100,
            verbose=False
        )

        # Verify exactly 2 records from 2019
        cursor = self.conn.execute("SELECT COUNT(*) FROM test_master")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 2, "Should have exactly 2 records from 2019")

        # Verify the dates are both 2019
        cursor = self.conn.execute("""
            SELECT STRFTIME('%Y', DATE_RECEIVED) as year, COUNT(*)
            FROM test_master
            GROUP BY year
        """)
        results = cursor.fetchall()
        self.assertEqual(len(results), 1, "Should only have one year")
        self.assertEqual(results[0][0], '2019', "Year should be 2019")
        self.assertEqual(results[0][1], 2, "Should have 2 records")

    def test_empty_fields_handled_correctly(self):
        """Test that empty fields (||) are handled correctly"""
        content = """MDR_REPORT_KEY|EVENT_KEY|REPORT_NUMBER|DATE_RECEIVED|ADVERSE_EVENT_FLAG|PRODUCT_PROBLEM_FLAG|MANUFACTURER_NAME
12345|||01/15/2018|Y|Y|Test Manufacturer
67890||REP-2019-002|03/20/2019||Y|
11111||||Y||Third Manufacturer
"""
        test_file = self._create_test_file(content)

        processors.process_file(
            filepath=test_file,
            table_name='test_master',
            conn=self.conn,
            chunk_size=100,
            verbose=False
        )

        # Verify records were processed despite empty fields
        cursor = self.conn.execute("SELECT COUNT(*) FROM test_master")
        count = cursor.fetchone()[0]
        self.assertGreater(count, 0, "Should process lines with empty fields")

    def test_special_characters_in_text_fields(self):
        """Test that special characters in text don't break parsing"""
        content = """MDR_REPORT_KEY|EVENT_KEY|REPORT_NUMBER|DATE_RECEIVED|ADVERSE_EVENT_FLAG|PRODUCT_PROBLEM_FLAG|MANUFACTURER_NAME
12345||REP-2018-001|01/15/2018|Y|Y|Manufacturer & Company
67890||REP-2019-002|03/20/2019|N|Y|Company's Product
11111||REP-2020-003|05/10/2020|Y|N|Test "Quoted" Name
"""
        test_file = self._create_test_file(content)

        processors.process_file(
            filepath=test_file,
            table_name='test_master',
            conn=self.conn,
            chunk_size=100,
            verbose=False
        )

        cursor = self.conn.execute("SELECT COUNT(*) FROM test_master")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 3,
            "Should handle special characters in text fields")

    def test_date_parsing_with_different_formats(self):
        """Test that various date formats are parsed correctly"""
        content = """MDR_REPORT_KEY|EVENT_KEY|REPORT_NUMBER|DATE_RECEIVED|ADVERSE_EVENT_FLAG|PRODUCT_PROBLEM_FLAG|MANUFACTURER_NAME
12345||REP-2018-001|01/15/2018|Y|Y|Test Manufacturer
67890||REP-2019-002|3/20/2019|N|Y|Single digit month
11111||REP-2020-003|12/5/2020|Y|N|Single digit day
"""
        test_file = self._create_test_file(content)

        metadata = {'date_column': 'DATE_RECEIVED'}

        processors.process_cumulative_file_batch(
            filepath=test_file,
            table_name='test_master',
            years_list=[2018, 2019, 2020],
            metadata=metadata,
            conn=self.conn,
            chunk_size=100,
            verbose=False
        )

        # Verify all dates were parsed
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM test_master
            WHERE DATE_RECEIVED IS NOT NULL
        """)
        count = cursor.fetchone()[0]
        self.assertEqual(count, 3,
            "Should parse all date format variations")

    def test_large_dataset_chunking(self):
        """Test that chunking works correctly with batch processing"""
        # Create a larger dataset that spans multiple chunks
        lines = ["MDR_REPORT_KEY|EVENT_KEY|REPORT_NUMBER|DATE_RECEIVED|ADVERSE_EVENT_FLAG|PRODUCT_PROBLEM_FLAG|MANUFACTURER_NAME"]

        # Add 250 records (will be processed in 3 chunks of 100)
        for i in range(250):
            year = 2018 + (i % 3)  # Distribute across 2018, 2019, 2020
            month = (i % 12) + 1
            day = (i % 28) + 1
            lines.append(
                f"{10000+i}||REP-{year}-{i:03d}|{month:02d}/{day:02d}/{year}|Y|Y|Manufacturer {i}"
            )

        content = '\n'.join(lines) + '\n'
        test_file = self._create_test_file(content)

        metadata = {'date_column': 'DATE_RECEIVED'}

        # Process with small chunk size to test chunking
        processors.process_cumulative_file_batch(
            filepath=test_file,
            table_name='test_master',
            years_list=[2018, 2019, 2020],
            metadata=metadata,
            conn=self.conn,
            chunk_size=100,  # Will need 3 chunks
            verbose=False
        )

        # Verify all records were processed
        cursor = self.conn.execute("SELECT COUNT(*) FROM test_master")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 250,
            "Should process all records across multiple chunks")

        # Verify year distribution
        cursor = self.conn.execute("""
            SELECT STRFTIME('%Y', DATE_RECEIVED) as year, COUNT(*)
            FROM test_master
            GROUP BY year
            ORDER BY year
        """)
        results = cursor.fetchall()

        # Should have roughly equal distribution across 3 years
        self.assertEqual(len(results), 3, "Should have 3 years")
        for year, count in results:
            self.assertGreater(count, 70,
                f"Year {year} should have reasonable number of records")


class TestPandasEngineConfiguration(unittest.TestCase):
    """Test that pandas is configured correctly to handle malformed lines"""

    def test_python_engine_is_used(self):
        """Verify that the processor uses Python engine for better malformed line handling"""
        import inspect

        # Get the source code of process_cumulative_file_batch
        source = inspect.getsource(processors.process_cumulative_file_batch)

        # Verify it uses python engine
        self.assertIn("engine='python'", source,
            "Should use Python engine for better malformed line handling")

        # Verify it uses on_bad_lines='warn'
        self.assertIn("on_bad_lines='warn'", source,
            "Should warn about bad lines instead of silently skipping")

    def test_quoting_configuration(self):
        """Verify quoting is set to QUOTE_NONE to avoid quote-related issues"""
        import inspect

        source = inspect.getsource(processors.process_cumulative_file_batch)

        # Verify quoting is set to 3 (QUOTE_NONE)
        self.assertIn("quoting=3", source,
            "Should use QUOTE_NONE (3) to avoid quote-related parsing issues")


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
