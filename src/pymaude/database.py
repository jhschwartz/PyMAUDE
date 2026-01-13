# database.py - FDA MAUDE Database Interface
# Copyright (C) 2026 Jacob Schwartz <jaschwa@umich.edu>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Main MaudeDatabase class for interfacing with FDA MAUDE data.

This module provides the primary interface for downloading, managing, and querying
FDA MAUDE (Manufacturer and User Facility Device Experience) database.
"""

import pandas as pd
import sqlite3
import os
from datetime import datetime
import requests
import zipfile
from collections import defaultdict
import hashlib

from .metadata import TABLE_METADATA, FDA_BASE_URL
from . import processors
from . import analysis_helpers


class MaudeDatabase:
    """
    Interface to FDA MAUDE database - handles download, parsing, and querying.

    Usage:
        # Connect to existing database
        db = MaudeDatabase('maude.db')

        # Add data
        db.add_years('2015-2024', tables=['master', 'device'], download=True)

        # Query
        results = db.query_device(device_name='thrombectomy')

        # Update existing years and add new ones
        db.update(add_new_years=True)

        # Or just refresh existing years
        db.update(add_new_years=False)
    """

    def __init__(self, db_path, verbose=True):
        """
        Initialize connection to MAUDE database.
        Creates new database if doesn't exist, connects to existing if it does.

        Args:
            db_path: Path to SQLite database file
            verbose: Whether to print progress messages
        """
        self.db_path = db_path
        self.verbose = verbose
        self.conn = sqlite3.connect(self.db_path)

        # Increase SQLite's maximum string/blob size limit to 1GB
        # This helps handle large text fields in MAUDE data
        self.conn.execute("PRAGMA max_length = 1073741824")  # 1GB

        self._download_cache = set()  # Track downloaded files to avoid re-downloading
        self.TABLE_METADATA = TABLE_METADATA
        self.base_url = FDA_BASE_URL

        # Initialize metadata tracking table
        self._init_metadata_table()


    def __enter__(self):
        """Context manager entry - allows 'with MaudeDatabase() as db:' syntax"""
        return self


    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up connection"""
        self.conn.close()


    def _init_metadata_table(self):
        """
        Initialize metadata table to track loaded files and their checksums.

        This table helps avoid reprocessing unchanged files and detects when
        FDA updates their source data.
        """
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS _maude_load_metadata (
                table_name TEXT NOT NULL,
                year INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                file_checksum TEXT NOT NULL,
                loaded_at TIMESTAMP NOT NULL,
                row_count INTEGER,
                PRIMARY KEY (table_name, year)
            )
        """)
        self.conn.commit()


    def _compute_file_checksum(self, filepath):
        """
        Compute SHA256 checksum of a file.

        Args:
            filepath: Path to file

        Returns:
            Hexadecimal checksum string, or None if file doesn't exist
        """
        if not os.path.exists(filepath):
            return None

        sha256_hash = hashlib.sha256()

        # Read file in chunks to handle large files efficiently
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096 * 1024), b''):  # 4MB chunks
                sha256_hash.update(chunk)

        return sha256_hash.hexdigest()


    def _get_loaded_file_info(self, table_name, year):
        """
        Get metadata about a previously loaded file.

        Args:
            table_name: Table name
            year: Year

        Returns:
            Dict with file_checksum, loaded_at, row_count, or None if not found
        """
        cursor = self.conn.execute("""
            SELECT file_checksum, loaded_at, row_count
            FROM _maude_load_metadata
            WHERE table_name = ? AND year = ?
        """, (table_name, year))

        row = cursor.fetchone()
        if row:
            return {
                'file_checksum': row[0],
                'loaded_at': row[1],
                'row_count': row[2]
            }
        return None


    def _record_file_load(self, table_name, year, filepath, file_checksum, row_count):
        """
        Record that a file has been loaded into the database.

        Args:
            table_name: Table name
            year: Year
            filepath: Path to source file
            file_checksum: SHA256 checksum of file
            row_count: Number of rows loaded
        """
        self.conn.execute("""
            INSERT OR REPLACE INTO _maude_load_metadata
            (table_name, year, file_path, file_checksum, loaded_at, row_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (table_name, year, filepath, file_checksum, datetime.now().isoformat(), row_count))
        self.conn.commit()


    def _delete_year_data(self, table_name, year):
        """
        Delete all data for a specific year from a table.

        Used when refreshing data due to changed source files.

        Args:
            table_name: Table name
            year: Year to delete
        """
        # Check if table exists first
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        if not cursor.fetchone():
            return  # Table doesn't exist, nothing to delete

        metadata = self.TABLE_METADATA.get(table_name, {})
        date_column = metadata.get('date_column')

        if not date_column:
            if self.verbose:
                print(f'  Warning: Cannot delete year {year} from {table_name} - no date column defined')
            return

        # Delete rows for this year
        self.conn.execute(f"""
            DELETE FROM {table_name}
            WHERE strftime('%Y', {date_column}) = ?
        """, (str(year),))
        self.conn.commit()


    def _count_table_rows(self, table_name):
        """
        Count rows in a table.

        Args:
            table_name: Table name

        Returns:
            Row count as integer, or 0 if table doesn't exist
        """
        # Check if table exists first
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        if not cursor.fetchone():
            return 0

        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]


    def add_years(self, years, tables=None, download=False, strict=False, chunk_size=100000, data_dir='./maude_data', interactive=True, force_refresh=False):
        """
        Add MAUDE data for specified years to database.

        Uses intelligent checksum tracking to avoid reprocessing unchanged files.
        When a year/table has already been loaded, the source file checksum is
        compared to detect FDA updates. Only changed files are reprocessed.

        For cumulative files (master/patient), all years from that file share the
        same checksum. If the file hasn't changed, all years are skipped together.

        Args:
            years: Year or years to add. Can be:
                   - Single int: 2024
                   - List: [2020, 2021, 2022]
                   - String range: '2015-2024'
                   - String: 'all', 'latest', 'current'
            tables: List of tables to include (default: all main tables)
            download: Whether to download files from FDA
            strict: If True, raise error on missing files. If False, skip with warning.
            chunk_size: Rows to process at once (for memory efficiency)
            data_dir: Directory containing data files
            interactive: If True, prompt user for validation issues (default: True)
            force_refresh: If True, reload all years even if unchanged (default: False)
        """
        years_list = self._parse_year_range(years)

        if tables is None:
            tables = ['master', 'device', 'patient', 'text']

        # Validate year/table compatibility
        validation_result = self._validate_year_table_compatibility(years_list, tables)

        # Handle interactive validation
        if interactive and (validation_result['invalid'] or validation_result['warnings']):
            proceed, valid_combinations = self._prompt_user_for_validation_resolution(validation_result)
            if not proceed:
                if self.verbose:
                    print("\nOperation cancelled by user.")
                return
        else:
            # Non-interactive mode: use only valid combinations
            valid_combinations = validation_result['valid']

            # In strict mode, raise error if any invalid combinations
            if strict and validation_result['invalid']:
                invalid_msgs = [f"{t} {y}: {r}" for y, t, r in validation_result['invalid']]
                raise ValueError(f"Invalid year/table combinations:\n" + "\n".join(invalid_msgs))

        # Extract just the years and tables from valid combinations
        years_set = sorted(set(year for year, table in valid_combinations))
        tables_set = sorted(set(table for year, table in valid_combinations))

        # Track which tables were actually loaded
        loaded_tables = set()
        current_year = datetime.now().year

        # OPTIMIZATION: Group years by file for batch processing
        if self.verbose:
            print(f'\nGrouping years by file for optimization...')

        file_groups = self._group_years_by_file(years_set, tables_set, data_dir)

        # Download files first (with deduplication built into _download_file)
        if download:
            if self.verbose:
                print(f'\nDownloading files...')

            for (table, filepath, pattern_type), years_for_file in file_groups.items():
                # Download for the first year in the group (others use same file)
                year_to_download = years_for_file[0]

                if not self._download_file(year_to_download, table, data_dir):
                    # Try fallback for current year
                    if year_to_download == current_year:
                        if self.verbose:
                            print(f'  Current year file not found for {table}, trying previous year...')
                        if not self._download_file(year_to_download - 1, table, data_dir):
                            if strict:
                                raise FileNotFoundError(f'Could not download {table} for {year_to_download} or {year_to_download-1}')
                            if self.verbose:
                                print(f'  Skipping {table} - download failed')
                            continue
                    else:
                        if strict:
                            raise FileNotFoundError(f'Could not download {table} for {year_to_download}')
                        if self.verbose:
                            print(f'  Skipping {table} - download failed')
                        continue

        # Process files with batch optimization and checksum tracking
        if self.verbose:
            print(f'\nProcessing data files...')

        for (table, filepath, pattern_type), years_for_file in file_groups.items():
            # Re-check file path in case download changed it
            path = self._make_file_path(table, years_for_file[0], data_dir)

            if not path:
                if strict:
                    raise FileNotFoundError(f'No file found for table={table}')
                if self.verbose:
                    print(f'  Skipping {table} - file not found')
                continue

            # CHECKSUM TRACKING: Check if we need to process this file
            current_checksum = self._compute_file_checksum(path)
            if not current_checksum:
                if self.verbose:
                    print(f'  Warning: Could not compute checksum for {path}')
                continue

            # Check if all years from this file have been loaded with the same checksum
            needs_processing = force_refresh
            years_needing_refresh = []
            years_already_loaded = []

            if force_refresh:
                # Force refresh: need to delete and reload all years
                years_needing_refresh = list(years_for_file)
            else:
                # Check each year for changes
                for year in years_for_file:
                    loaded_info = self._get_loaded_file_info(table, year)
                    if not loaded_info:
                        # Never loaded before
                        needs_processing = True
                    elif loaded_info['file_checksum'] != current_checksum:
                        # Checksum changed - FDA updated the file
                        needs_processing = True
                        years_needing_refresh.append(year)
                    else:
                        # Already loaded with same checksum
                        years_already_loaded.append(year)

                # If we need to process (for new/changed years), we must delete
                # any years that were already loaded from this same file to avoid duplicates
                if needs_processing and years_already_loaded:
                    years_needing_refresh.extend(years_already_loaded)

            if not needs_processing:
                # All years already loaded and file unchanged
                if self.verbose:
                    if len(years_for_file) > 1:
                        year_range = f"{min(years_for_file)}-{max(years_for_file)}"
                        print(f'\n{table} for years {year_range} already loaded and unchanged, skipping')
                    else:
                        print(f'\n{table} for year {years_for_file[0]} already loaded and unchanged, skipping')
                continue

            # File needs processing
            if self.verbose:
                if len(years_for_file) > 1:
                    year_range = f"{min(years_for_file)}-{max(years_for_file)}"
                    print(f'\nLoading {table} for years {year_range}...')
                else:
                    print(f'\nLoading {table} for year {years_for_file[0]}...')

                if years_needing_refresh:
                    print(f'  File changed, refreshing years: {years_needing_refresh}')

            # Delete old data for years that need refresh
            if years_needing_refresh:
                for year in years_needing_refresh:
                    if self.verbose:
                        print(f'  Deleting old data for {table} year {year}...')
                    self._delete_year_data(table, year)

            # Get metadata for this table
            metadata = self.TABLE_METADATA.get(table, {})

            # Track rows loaded for metadata
            rows_before = self._count_table_rows(table)

            # BATCH PROCESSING OPTIMIZATION: Use batch method for cumulative files with multiple years
            if pattern_type == 'cumulative' and len(years_for_file) > 1:
                # Batch mode: process file once for all years
                processors.process_cumulative_file_batch(
                    path, table, years_for_file, metadata, self.conn, chunk_size, self.verbose
                )
            elif pattern_type == 'cumulative':
                # Single year cumulative: use standard single-year method
                processors.process_cumulative_file(
                    path, table, years_for_file[0], metadata, self.conn, chunk_size, self.verbose
                )
            else:
                # Yearly files: process each year separately
                for year in years_for_file:
                    year_path = self._make_file_path(table, year, data_dir)
                    if year_path:
                        if self.verbose and len(years_for_file) > 1:
                            print(f'  Processing year {year}...')
                        processors.process_file(year_path, table, self.conn, chunk_size, self.verbose)

            # Record successful load for all years from this file
            rows_after = self._count_table_rows(table)
            rows_loaded = rows_after - rows_before

            for year in years_for_file:
                self._record_file_load(table, year, path, current_checksum, rows_loaded)

            loaded_tables.add(table)

        # Only create indexes for tables that were actually loaded
        processors.create_indexes(self.conn, list(loaded_tables), self.verbose)

        if self.verbose:
            print('\nDatabase update complete')


    def _predict_file_path(self, table, year, data_dir='./maude_data'):
        """
        Predict what file path will exist for a table/year after download.
        Unlike _make_file_path, this doesn't check if the file currently exists.

        Args:
            table: Table name (e.g., 'master', 'device')
            year: Year as integer
            data_dir: Directory containing data files

        Returns:
            Predicted file path as string, or False if invalid table
        """
        if table not in self.TABLE_METADATA:
            return False

        metadata = self.TABLE_METADATA[table]
        file_prefix = metadata['file_prefix']
        pattern_type = metadata['pattern_type']
        current_year = datetime.now().year

        if pattern_type == 'yearly':
            # Special case: device table uses device{year}.txt naming (from 2000+)
            if table == 'device':
                # Device: device2020.txt (lowercase from zip)
                return f"{data_dir}/device{year}.txt"
            else:
                # Standard yearly pattern: foitext2020.txt (lowercase from zip)
                return f"{data_dir}/{file_prefix}{year}.txt"

        elif pattern_type == 'cumulative':
            # Cumulative files use latest available thru file
            # After download, they'll be lowercase (from zip extraction)
            if year == current_year:
                return f"{data_dir}/{metadata['current_year_prefix']}.txt"
            else:
                # Use previous year's cumulative file for historical years
                cumulative_year = current_year - 1
                return f"{data_dir}/{file_prefix}thru{cumulative_year}.txt"

        return False

    def _group_years_by_file(self, years_list, tables, data_dir):
        """
        Group years that will use the same file for processing.

        This enables batch processing optimization: when multiple years map to the same
        cumulative file (e.g., mdrfoithru2024.txt), we can process the file once instead
        of reading it separately for each year.

        Args:
            years_list: List of year integers
            tables: List of table names
            data_dir: Directory containing data files

        Returns:
            dict: Mapping of (table, filepath) -> list of years
                  e.g., {('master', './maude_data/mdrfoithru2024.txt'): [1996, 1997, ..., 2024]}
        """
        file_groups = defaultdict(list)
        current_year = datetime.now().year

        for table in tables:
            if table not in self.TABLE_METADATA:
                continue

            metadata = self.TABLE_METADATA[table]
            pattern_type = metadata['pattern_type']

            for year in years_list:
                # First try to find existing file
                file_path = self._make_file_path(table, year, data_dir)

                # If no existing file, predict what the path will be after download
                if not file_path:
                    file_path = self._predict_file_path(table, year, data_dir)

                if file_path:
                    # Group by (table, filepath, pattern_type)
                    key = (table, file_path, pattern_type)
                    file_groups[key].append(year)

        return file_groups


    def _construct_file_url(self, table, year):
        """
        Construct download URL based on table type and year.

        Args:
            table: Table name (e.g., 'master', 'device')
            year: Year as integer

        Returns:
            tuple: (url, filename) or (None, None) if invalid
        """
        if table not in self.TABLE_METADATA:
            return None, None

        metadata = self.TABLE_METADATA[table]
        pattern_type = metadata['pattern_type']
        file_prefix = metadata['file_prefix']
        current_year = datetime.now().year

        # Current year files (no year suffix)
        if year == current_year:
            filename = f"{metadata['current_year_prefix']}.zip"
            url = f"{self.base_url}/{filename}"
            return url, filename

        # Historical files
        if pattern_type == 'yearly':
            # Special case: device table uses device{year}.zip naming (from 2000+)
            if table == 'device':
                # Device: device2020.zip (years 2000+ only, due to schema change)
                filename = f"device{year}.zip"
            else:
                # Standard yearly pattern: foitext2020.zip
                filename = f"{file_prefix}{year}.zip"

            url = f"{self.base_url}/{filename}"
            return url, filename

        elif pattern_type == 'cumulative':
            # Cumulative files: use latest cumulative through previous year for historical data
            # For current year, use current year file
            # Historical: mdrfoithru2024.zip, patientthru2024.zip
            # Current year: mdrfoi.zip, patient.zip

            # Try to find the most recent available cumulative file
            # FDA may not have updated to current_year-1 yet (e.g., in early January)
            # Try current_year-1, current_year-2, current_year-3 as fallbacks
            expected_year = current_year - 1
            for offset in [1, 2, 3]:
                cumulative_year = current_year - offset
                filename = f"{file_prefix}thru{cumulative_year}.zip"
                url = f"{self.base_url}/{filename}"

                # Check if this file exists on FDA server
                if self._check_url_exists(url):
                    if offset > 1 and self.verbose:
                        # Warn when falling back if verbose mode is enabled
                        expected_filename = f"{file_prefix}thru{expected_year}.zip"
                        print(f'  WARNING: Expected file {expected_filename} not available.')
                        print(f'  Using {filename} instead (latest available cumulative file).')
                    return url, filename

            # If none found, return the expected file and let download handle the error
            cumulative_year = current_year - 1
            filename = f"{file_prefix}thru{cumulative_year}.zip"
            url = f"{self.base_url}/{filename}"
            return url, filename

        return None, None

    def _parse_year_range(self, year_str):
        """
        Convert year string to list of year integers.

        Args:
            year_str: String like '2015-2024', 'all', 'latest', 'current', or single year '2024'

        Returns:
            List of year integers
        """
        if isinstance(year_str, int):
            return [year_str]

        if isinstance(year_str, list):
            return year_str

        if year_str == 'all':
            return list(range(1991, datetime.now().year + 1))
        elif year_str == 'latest':
            return [datetime.now().year - 1]
        elif year_str == 'current':
            return [datetime.now().year]
        elif '-' in year_str:
            start, end = year_str.split('-')
            return list(range(int(start), int(end) + 1))

        return [int(year_str)]

    def _validate_year_table_compatibility(self, years, tables):
        """
        Validate that requested years are valid for requested tables.

        Args:
            years: List of year integers
            tables: List of table names

        Returns:
            dict: {
                'valid': [(year, table), ...],
                'invalid': [(year, table, reason), ...],
                'warnings': [(year, table, warning_msg), ...]
            }
        """
        valid = []
        invalid = []
        warnings = []
        current_year = datetime.now().year

        for year in years:
            for table in tables:
                if table not in self.TABLE_METADATA:
                    invalid.append((year, table, f"Unknown table '{table}'"))
                    continue

                metadata = self.TABLE_METADATA[table]
                start_year = metadata['start_year']

                # Check if year is too old
                if year < start_year:
                    invalid.append((
                        year,
                        table,
                        f"{metadata['description']} only available from {start_year} onwards"
                    ))
                    continue

                # Check if year is in the future
                if year > current_year:
                    invalid.append((
                        year,
                        table,
                        f"Year {year} is in the future"
                    ))
                    continue

                # Check if current year file might not exist yet (year transition)
                if year == current_year:
                    # Check if it's early in the year (before February)
                    if datetime.now().month < 2:
                        warnings.append((
                            year,
                            table,
                            f"Current year ({current_year}) files may not be available yet. Will attempt download with fallback."
                        ))

                # Add size warnings for patient table
                if table == 'patient' and 'size_warning' in metadata:
                    # Only warn once per patient table request, not per year
                    patient_warning = (
                        year,
                        table,
                        metadata['size_warning']
                    )
                    if patient_warning not in warnings:
                        warnings.append(patient_warning)

                valid.append((year, table))

        return {
            'valid': valid,
            'invalid': invalid,
            'warnings': warnings
        }

    def _prompt_user_for_validation_resolution(self, validation_result):
        """
        Interactively prompt user to resolve validation issues.

        Args:
            validation_result: Output from _validate_year_table_compatibility

        Returns:
            tuple: (proceed: bool, filtered_valid: list of (year, table) tuples)
        """
        invalid = validation_result['invalid']
        warnings = validation_result['warnings']
        valid = validation_result['valid']

        if not invalid and not warnings:
            return True, valid

        print("\n" + "="*60)
        print("DATA AVAILABILITY VALIDATION")
        print("="*60)

        # Show invalid combinations
        if invalid:
            print("\nINVALID YEAR/TABLE COMBINATIONS:")
            print("-" * 60)
            for year, table, reason in invalid:
                print(f"  X {table} {year}: {reason}")

            print("\nThese combinations will be skipped.")
            print("\nOptions:")
            print("  1. Continue with valid combinations only")
            print("  2. Abort and adjust your request")

            while True:
                choice = input("\nYour choice (1 or 2): ").strip()
                if choice == '1':
                    break
                elif choice == '2':
                    return False, []
                else:
                    print("  Invalid choice. Please enter 1 or 2.")

        # Show warnings
        if warnings:
            print("\nWARNINGS:")
            print("-" * 60)

            # Group warnings by type
            patient_warnings = [(y, t, w) for y, t, w in warnings if 'patient' in t.lower() and 'large file' in w.lower()]
            other_warnings = [(y, t, w) for y, t, w in warnings if not ('patient' in t.lower() and 'large file' in w.lower())]

            # Patient size warnings
            if patient_warnings:
                print("\nPATIENT TABLE SIZE WARNING:")
                print(patient_warnings[0][2])  # Show warning message
                print("\nDo you want to proceed with patient table download?")

                while True:
                    choice = input("Proceed? (y/n): ").strip().lower()
                    if choice in ['y', 'yes']:
                        break
                    elif choice in ['n', 'no']:
                        # Remove patient from valid list
                        valid = [(y, t) for y, t in valid if t != 'patient']
                        print("  Patient table removed from download list.")
                        break
                    else:
                        print("  Invalid choice. Please enter y or n.")

            # Other warnings
            if other_warnings:
                for year, table, warning in other_warnings:
                    print(f"  ! {table} {year}: {warning}")
                print("\nProceed despite warnings?")

                while True:
                    choice = input("(y/n): ").strip().lower()
                    if choice in ['y', 'yes']:
                        break
                    elif choice in ['n', 'no']:
                        return False, []
                    else:
                        print("  Invalid choice. Please enter y or n.")

        return True, valid


    def _make_file_path(self, table, year, data_dir='./maude_data'):
        """
        Create a path for the MAUDE datafile, checking all possible naming patterns.

        Args:
            table: Table name (e.g., 'master', 'device')
            year: Year as integer
            data_dir: Directory containing data files

        Returns:
            path if it exists
            Otherwise returns False
        """
        if table not in self.TABLE_METADATA:
            return False

        metadata = self.TABLE_METADATA[table]
        file_prefix = metadata['file_prefix']
        pattern_type = metadata['pattern_type']
        current_year = datetime.now().year

        if not os.path.exists(data_dir):
            return False

        files_in_dir = os.listdir(data_dir)

        # Patterns to check (both lowercase and uppercase)
        patterns = []

        if year == current_year:
            # Current year pattern: device.txt or DEVICE.txt
            current_prefix = metadata['current_year_prefix']
            patterns.extend([
                f"{current_prefix}.txt",
                f"{current_prefix.upper()}.txt"
            ])

        if pattern_type == 'yearly':
            # Special case: device table uses device{year}.txt naming (from 2000+)
            if table == 'device':
                # Device: device2020.txt or DEVICE2020.txt (2000+ only)
                patterns.extend([
                    f"device{year}.txt",
                    f"DEVICE{year}.txt"
                ])
            else:
                # Yearly pattern: foitext2020.txt
                patterns.extend([
                    f"{file_prefix}{year}.txt",
                    f"{file_prefix.upper()}{year}.txt"
                ])

        elif pattern_type == 'cumulative':
            # Cumulative files: check for cumulative file
            # For historical years, look for any cumulative file (e.g., mdrfoithru2024.txt, patientthru2020.txt)
            # Try current year - 1 first, then search for any cumulative file
            if year != current_year:
                cumulative_year = current_year - 1
                patterns.extend([
                    f"{file_prefix}thru{cumulative_year}.txt",
                    f"{file_prefix.upper()}thru{cumulative_year}.txt",
                    f"{file_prefix.upper()}THRU{cumulative_year}.txt",
                    f"{file_prefix}Thru{cumulative_year}.txt"
                ])

        # Check each pattern
        for pattern in patterns:
            if pattern in files_in_dir:
                return f"{data_dir}/{pattern}"

        # For cumulative files, if we didn't find the expected year, search for ANY cumulative file
        if pattern_type == 'cumulative' and year != current_year:
            # Search for any file matching the cumulative pattern
            for filename in files_in_dir:
                lower_filename = filename.lower()
                if (lower_filename.startswith(file_prefix) and
                    'thru' in lower_filename and
                    filename.endswith('.txt')):
                    return f"{data_dir}/{filename}"

        return False


    def _download_file(self, year, table, data_dir='./maude_data'):
        """
        Download and extract a MAUDE file from FDA.

        Args:
            year: Year to download
            table: Table name (e.g., 'master', 'device')
            data_dir: Directory to save files

        Returns:
            True if successful, False otherwise
        """
        os.makedirs(data_dir, exist_ok=True)

        url, filename = self._construct_file_url(table, year)
        if not url:
            if self.verbose:
                print(f'  Cannot construct URL for {table} year {year}')
            return False

        # Check download cache to avoid redundant downloads
        cache_key = (table, filename, data_dir)
        if cache_key in self._download_cache:
            if self.verbose:
                print(f'  Already downloaded {filename} in this session')
            return True

        zip_path = f"{data_dir}/{filename}"

        if os.path.exists(zip_path):
            if self.verbose:
                print(f'  Using cached {filename}')
            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(data_dir)
                self._download_cache.add(cache_key)  # Mark as downloaded
                return True
            except:
                os.remove(zip_path)

        try:
            if self.verbose:
                print(f'  Downloading {filename}...')

            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            with open(zip_path, 'wb') as f:
                f.write(response.content)

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(data_dir)

            self._download_cache.add(cache_key)  # Mark as downloaded
            return True

        except Exception as e:
            if self.verbose:
                print(f'  Error downloading {year}: {e}')
            return False


    def _check_url_exists(self, url):
        """
        Check if a URL exists without downloading.

        Args:
            url: Full URL to check

        Returns:
            True if file exists (2xx status), False otherwise
        """
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.head(url, headers=headers, timeout=5, allow_redirects=True)
            # Accept any 2xx status code (200-299)
            return 200 <= response.status_code < 300
        except:
            return False


    def _check_file_exists(self, year, file_prefix):
        """
        Check if a file exists on FDA server without downloading.

        Args:
            year: Year to check
            file_prefix: File type to check

        Returns:
            True if file exists (2xx status), False otherwise
        """
        url = f"{self.base_url}/{file_prefix}{year}.zip"
        return self._check_url_exists(url)


    def update(self, *, add_new_years, download=True):
        """
        Update existing years in database with latest FDA data.

        Checks all years currently in the database and re-downloads them to catch
        any corrections or updates from the FDA. Uses checksum tracking to skip
        files that haven't changed, so unchanged data won't be reprocessed.

        Args:
            add_new_years: If True, also adds any missing years since the most
                          recent year in database. If False, only refreshes
                          existing years.
            download: If True, download files from FDA. If False, use local files
                     (default: True)

        Example:
            # Refresh existing data only
            db.update(add_new_years=False)

            # Refresh existing + add new years
            db.update(add_new_years=True)

            # Update from local files without downloading
            db.update(add_new_years=False, download=False)
        """
        existing = self._get_years_in_db()

        if not existing:
            if self.verbose:
                print('Database is empty. Use add_years() to populate.')
            return

        years_to_process = existing.copy()

        if add_new_years:
            max_existing = max(existing)
            current_year = datetime.now().year
            new_years = list(range(max_existing + 1, current_year + 1))

            if new_years:
                years_to_process.extend(new_years)
                if self.verbose:
                    print(f'Will refresh {len(existing)} existing years and add {len(new_years)} new years')
            else:
                if self.verbose:
                    print(f'Will refresh {len(existing)} existing years (no new years available)')
        else:
            if self.verbose:
                print(f'Will refresh {len(existing)} existing years')

        # Determine which tables exist in the database
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'")
        existing_tables = [row[0] for row in cursor.fetchall()]

        # Only update tables that exist
        tables_to_update = [t for t in ['master', 'device', 'patient', 'text'] if t in existing_tables]

        if not tables_to_update:
            if self.verbose:
                print('No data tables found in database.')
            return

        # Use force_refresh=False to let checksum tracking decide what needs updating
        # This ensures only changed files are reprocessed
        self.add_years(years_to_process, tables=tables_to_update, download=download, force_refresh=False, interactive=False)


    def _get_latest_available_year(self):
        """
        Find the most recent year available on FDA server.

        Returns:
            Most recent year as integer
        """
        current_year = datetime.now().year

        for year in range(current_year, 1990, -1):
            if self._check_file_exists(year, 'mdrfoi'):
                return year

        return current_year - 1


    def _get_years_in_db(self):
        """
        Get list of years currently in the database.

        Returns:
            List of years (as integers)
        """
        try:
            df = pd.read_sql_query(
                "SELECT DISTINCT strftime('%Y', DATE_RECEIVED) as year FROM master",
                self.conn
            )
            return [int(y) for y in df['year'].tolist() if y]
        except:
            return []


    def query(self, sql, params=None):
        """
        Execute raw SQL query and return results as DataFrame.

        Args:
            sql: SQL query string
            params: Optional parameters for query (for safety)

        Returns:
            pandas DataFrame with results
        """
        return pd.read_sql_query(sql, self.conn, params=params)


    def query_device(self, device_name=None, product_code=None,
                     start_date=None, end_date=None, deduplicate_events=True):
        """
        Query device events with optional filters.

        By default, returns one row per unique EVENT (EVENT_KEY). When multiple reports
        exist for the same event (e.g., manufacturer + hospital reports), only the first
        report is included. When an event/report involves multiple devices, only the
        first device record is included.

        Args:
            device_name: Filter by generic_name or brand_name (partial match)
            product_code: Filter by exact product code
            start_date: Only events on/after this date
            end_date: Only events on/before this date
            deduplicate_events: If True (default), return one row per EVENT_KEY.
                               If False, return all reports (may include multiple
                               reports for the same event). Set to False only if you
                               specifically need report-level data.

        Returns:
            DataFrame with matching records from master + device tables.
            By default, one row per unique event (EVENT_KEY). Approximately 8% of
            reports share EVENT_KEY with other reports (same event, different sources).

        Note:
            This method now deduplicates by EVENT_KEY by default (changed from
            MDR_REPORT_KEY). This ensures accurate event counts for epidemiological
            analysis. Use deduplicate_events=False to get report-level data for
            reporting compliance analysis.
        """
        # Check if EVENT_KEY column exists in master table
        cursor = self.conn.execute("PRAGMA table_info(master)")
        columns = {row[1] for row in cursor.fetchall()}
        has_event_key = 'EVENT_KEY' in columns

        # If EVENT_KEY doesn't exist, fall back to non-deduplication mode
        if deduplicate_events and not has_event_key:
            deduplicate_events = False

        # Build WHERE conditions for device filters
        device_conditions = []
        params = {}

        if device_name:
            device_conditions.append("(UPPER(d.GENERIC_NAME) LIKE UPPER(:device) OR UPPER(d.BRAND_NAME) LIKE UPPER(:device))")
            params['device'] = f'%{device_name}%'

        if product_code:
            device_conditions.append("d.DEVICE_REPORT_PRODUCT_CODE = :code")
            params['code'] = product_code

        device_where = " AND ".join(device_conditions) if device_conditions else "1=1"

        # Build WHERE conditions for date filters (applied to master table)
        date_conditions = []

        if start_date:
            date_conditions.append("m.DATE_RECEIVED >= :start")
            params['start'] = start_date

        if end_date:
            date_conditions.append("m.DATE_RECEIVED < date(:end, '+1 day')")
            params['end'] = end_date

        date_where = " AND ".join(date_conditions) if date_conditions else "1=1"

        if deduplicate_events:
            # Fast CTE-based deduplication by EVENT_KEY
            # Performance: O(N+M) complexity vs O(N*M) for correlated subquery
            # CRITICAL: Must filter by device FIRST, then deduplicate by EVENT_KEY
            # FIX: Store device_rowid in Step 1 to preserve filter through deduplication
            sql = f"""
                WITH matching_reports AS (
                    -- Step 1: Find all reports with matching devices and date filters
                    -- FIX: Store device_rowid to preserve which device matched the filter
                    SELECT DISTINCT
                        m.MDR_REPORT_KEY,
                        m.EVENT_KEY,
                        m.ROWID as master_rowid,
                        d.ROWID as device_rowid
                    FROM master m
                    JOIN device d ON d.MDR_REPORT_KEY = m.MDR_REPORT_KEY
                    WHERE {device_where} AND {date_where}
                ),
                first_report_per_event AS (
                    -- Step 2: For each EVENT_KEY, select first report and device
                    -- FIX: Keep device_rowid from Step 1 to use in final join
                    -- FIX: Use MDR_REPORT_KEY as fallback when EVENT_KEY is NULL
                    SELECT
                        EVENT_KEY,
                        MDR_REPORT_KEY,
                        MIN(master_rowid) as first_master_rowid,
                        MIN(device_rowid) as first_device_rowid
                    FROM matching_reports
                    GROUP BY COALESCE(EVENT_KEY, MDR_REPORT_KEY)
                )
                -- Step 3: Final join using preserved device_rowid
                -- FIX: Removed intermediate CTE that joined to ALL devices (was the bug!)
                SELECT m.*, d.*
                FROM first_report_per_event frpe
                JOIN master m ON m.ROWID = frpe.first_master_rowid
                JOIN device d ON d.ROWID = frpe.first_device_rowid
            """
        else:
            # No deduplication - return all matching reports and devices
            # Still use CTE for consistent performance
            sql = f"""
                WITH matching_devices AS (
                    SELECT d.MDR_REPORT_KEY, d.ROWID as device_rowid
                    FROM device d
                    WHERE {device_where}
                )
                SELECT m.*, d.*
                FROM master m
                JOIN matching_devices md ON md.MDR_REPORT_KEY = m.MDR_REPORT_KEY
                JOIN device d ON d.ROWID = md.device_rowid
                WHERE {date_where}
            """

        return pd.read_sql_query(sql, self.conn, params=params)


    def get_trends_by_year(self, product_code=None, device_name=None):
        """
        Get yearly event counts and breakdown by patient outcomes.

        Uses patient_outcome table for accurate death/injury counts.

        Args:
            product_code: Optional filter by product code
            device_name: Optional filter by device name

        Returns:
            DataFrame with columns: year, event_count, deaths, injuries, no_patient_record
            - deaths: Reports with OUTCOME_CODE = 'D'
            - injuries: Reports with serious outcomes (L, H, S, C, R, O)
            - no_patient_record: Reports with no patient table record
        """
        condition = "1=1"
        params = {}

        if product_code:
            condition = "d.DEVICE_REPORT_PRODUCT_CODE = :code"
            params['code'] = product_code
        elif device_name:
            condition = "(UPPER(d.GENERIC_NAME) LIKE UPPER(:name) OR UPPER(d.BRAND_NAME) LIKE UPPER(:name))"
            params['name'] = f'%{device_name}%'

        # Count patient outcomes from patient table (SEQUENCE_NUMBER_OUTCOME contains semicolon-separated codes)
        # Outcome codes: D=Death, L=Life threatening, H=Hospitalization, S=Disability, C=Congenital Anomaly, R=Required Intervention, O=Other
        # Multiple outcomes can exist per patient, separated by semicolons with spaces (e.g., "D; L")
        # Match codes at start, middle, or end of semicolon-separated list
        # Events without patient records may still be deaths/injuries (incomplete data entry)
        sql = f"""
            SELECT
                strftime('%Y', m.DATE_RECEIVED) as year,
                COUNT(DISTINCT m.MDR_REPORT_KEY) as event_count,
                COUNT(DISTINCT CASE WHEN p.SEQUENCE_NUMBER_OUTCOME LIKE '%D%' THEN m.MDR_REPORT_KEY END) as deaths,
                COUNT(DISTINCT CASE WHEN (p.SEQUENCE_NUMBER_OUTCOME LIKE '%L%'
                                       OR p.SEQUENCE_NUMBER_OUTCOME LIKE '%H%'
                                       OR p.SEQUENCE_NUMBER_OUTCOME LIKE '%S%'
                                       OR p.SEQUENCE_NUMBER_OUTCOME LIKE '%C%'
                                       OR p.SEQUENCE_NUMBER_OUTCOME LIKE '%R%'
                                       OR p.SEQUENCE_NUMBER_OUTCOME = 'O'
                                       OR p.SEQUENCE_NUMBER_OUTCOME LIKE 'O; %'
                                       OR p.SEQUENCE_NUMBER_OUTCOME LIKE '%; O'
                                       OR p.SEQUENCE_NUMBER_OUTCOME LIKE '%; O; %') THEN m.MDR_REPORT_KEY END) as injuries,
                COUNT(DISTINCT CASE WHEN p.MDR_REPORT_KEY IS NULL THEN m.MDR_REPORT_KEY END) as no_patient_record
            FROM master m
            JOIN device d ON m.MDR_REPORT_KEY = d.MDR_REPORT_KEY
            LEFT JOIN patient p ON m.MDR_REPORT_KEY = p.MDR_REPORT_KEY
            WHERE {condition}
            GROUP BY year
            ORDER BY year
        """

        return pd.read_sql_query(sql, self.conn, params=params)


    def get_narratives(self, mdr_report_keys):
        """
        Get text narratives for specific report keys.

        Args:
            mdr_report_keys: List of MDR report keys

        Returns:
            DataFrame with mdr_report_key and narrative text
        """
        placeholders = ','.join('?' * len(mdr_report_keys))

        sql = f"""
            SELECT MDR_REPORT_KEY, FOI_TEXT
            FROM text
            WHERE MDR_REPORT_KEY IN ({placeholders})
        """

        return pd.read_sql_query(sql, self.conn, params=mdr_report_keys)


    def export_subset(self, output_file, **filters):
        """
        Export filtered data to CSV file.

        Args:
            output_file: Path for output CSV
            **filters: Keyword arguments passed to query_device()
        """
        df = self.query_device(**filters)
        df.to_csv(output_file, index=False)

        if self.verbose:
            print(f'Exported {len(df):,} records to {output_file}')


    # ==================== Helper Query Methods (Delegated to analysis_helpers) ====================

    def get_narratives_for(self, results_df):
        """Get narratives for query results. See analysis_helpers module."""
        return analysis_helpers.get_narratives_for(self, results_df)

    def trends_for(self, results_df):
        """Get yearly trends. See analysis_helpers module."""
        return analysis_helpers.trends_for(results_df)

    def event_type_breakdown_for(self, results_df):
        """Get event type breakdown. See analysis_helpers module."""
        return analysis_helpers.event_type_breakdown_for(results_df)

    def top_manufacturers_for(self, results_df, n=10):
        """Get top manufacturers. See analysis_helpers module."""
        return analysis_helpers.top_manufacturers_for(results_df, n)

    def date_range_summary_for(self, results_df):
        """Get date range summary. See analysis_helpers module."""
        return analysis_helpers.date_range_summary_for(results_df)

    # ==================== New Analysis Helper Methods ====================

    def query_multiple_devices(self, device_names, start_date=None, end_date=None,
                              deduplicate=True, brand_column='query_brand'):
        """Query multiple devices. See analysis_helpers module."""
        return analysis_helpers.query_multiple_devices(
            self, device_names, start_date, end_date, deduplicate, brand_column
        )

    def query_device_catalog(self, device_catalog, start_date=None, end_date=None):
        """Query devices from a catalog. See analysis_helpers module."""
        return analysis_helpers.query_device_catalog(
            self, device_catalog, start_date, end_date
        )

    def enrich_with_problems(self, results_df):
        """Join device problem codes. See analysis_helpers module."""
        return analysis_helpers.enrich_with_problems(self, results_df)

    def enrich_with_patient_data(self, results_df):
        """Join patient outcome data. See analysis_helpers module."""
        return analysis_helpers.enrich_with_patient_data(self, results_df)

    def enrich_with_narratives(self, results_df):
        """Join event narratives. See analysis_helpers module."""
        return analysis_helpers.enrich_with_narratives(self, results_df)

    def summarize_by_brand(self, results_df, group_column='standard_brand', include_temporal=True):
        """Generate summary statistics by brand. See analysis_helpers module."""
        return analysis_helpers.summarize_by_brand(results_df, group_column, include_temporal)

    def find_brand_variations(self, search_terms, max_results=50):
        """Find brand name variations. See analysis_helpers module."""
        return analysis_helpers.find_brand_variations(self, search_terms, max_results)

    def standardize_brand_names(self, results_df, mapping_dict,
                               source_col='BRAND_NAME', target_col='standard_brand'):
        """Standardize brand names. See analysis_helpers module."""
        return analysis_helpers.standardize_brand_names(
            results_df, mapping_dict, source_col, target_col
        )

    def create_contingency_table(self, results_df, row_var, col_var, normalize=False):
        """Create contingency table. See analysis_helpers module."""
        return analysis_helpers.create_contingency_table(results_df, row_var, col_var, normalize)

    def chi_square_test(self, results_df, row_var, col_var, exclude_cols=None):
        """Perform chi-square test. See analysis_helpers module."""
        return analysis_helpers.chi_square_test(results_df, row_var, col_var, exclude_cols)

    def event_type_comparison(self, results_df, group_var='standard_brand'):
        """Compare event type distributions. See analysis_helpers module."""
        return analysis_helpers.event_type_comparison(results_df, group_var)

    def plot_temporal_trends(self, summary_dict, output_file=None, figsize=(12, 6), **kwargs):
        """Generate temporal trend figure. See analysis_helpers module."""
        return analysis_helpers.plot_temporal_trends(summary_dict, output_file, figsize, **kwargs)

    def plot_problem_distribution(self, contingency_table, output_file=None, stacked=True, **kwargs):
        """Generate problem distribution chart. See analysis_helpers module."""
        return analysis_helpers.plot_problem_distribution(contingency_table, output_file, stacked, **kwargs)

    def export_publication_figures(self, results_df, output_dir, prefix='figure',
                                   formats=['png', 'pdf'], **kwargs):
        """Batch export publication figures. See analysis_helpers module."""
        return analysis_helpers.export_publication_figures(
            self, results_df, output_dir, prefix, formats, **kwargs
        )

    # ==================== EVENT_KEY Deduplication Methods ====================

    def count_unique_events(self, results_df, event_key_col='EVENT_KEY'):
        """Count unique events vs reports. See analysis_helpers module."""
        return analysis_helpers.count_unique_events(results_df, event_key_col)

    def detect_multi_report_events(self, results_df, event_key_col='EVENT_KEY'):
        """Identify events with multiple reports. See analysis_helpers module."""
        return analysis_helpers.detect_multi_report_events(results_df, event_key_col)

    def select_primary_report(self, results_df, event_key_col='EVENT_KEY',
                             strategy='first_received'):
        """Select primary report for each event. See analysis_helpers module."""
        return analysis_helpers.select_primary_report(results_df, event_key_col, strategy)

    def compare_report_vs_event_counts(self, results_df, event_key_col='EVENT_KEY',
                                       group_by=None):
        """Compare report vs event counts. See analysis_helpers module."""
        return analysis_helpers.compare_report_vs_event_counts(results_df, event_key_col, group_by)

    # ==================== Patient OUTCOME Concatenation Methods ====================

    def detect_multi_patient_reports(self, patient_df):
        """Detect reports with multiple patients. See analysis_helpers module."""
        return analysis_helpers.detect_multi_patient_reports(patient_df)

    def count_unique_outcomes_per_report(self, patient_df, outcome_col='SEQUENCE_NUMBER_OUTCOME'):
        """Count unique outcomes per report. See analysis_helpers module."""
        return analysis_helpers.count_unique_outcomes_per_report(patient_df, outcome_col)


    # ==================== Database Info Methods ====================

    def info(self):
        """
        Print summary statistics about the database.
        Displays: tables present, record counts, date range
        """
        print(f"\nDatabase: {self.db_path}")
        print("=" * 60)

        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'",
            self.conn
        )['name'].tolist()

        if not tables:
            print("Database is empty")
            return

        for table in tables:
            count = pd.read_sql_query(
                f"SELECT COUNT(*) as count FROM {table}",
                self.conn
            )['count'][0]
            print(f"{table:15} {count:,} records")

        if 'master' in tables:
            date_info = pd.read_sql_query(
                "SELECT MIN(DATE_RECEIVED) as first, MAX(DATE_RECEIVED) as last FROM master",
                self.conn
            ).iloc[0]
            print(f"\nDate range: {date_info['first']} to {date_info['last']}")

        db_size = os.path.getsize(self.db_path) / (1024**3)
        print(f"Database size: {db_size:.2f} GB")


    def close(self):
        """Close database connection."""
        self.conn.close()