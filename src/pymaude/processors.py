# processors.py - MAUDE Database Data Processors
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
Data processing utilities for MAUDE database files.

Handles reading, parsing, and loading MAUDE data files into SQLite database.
"""

import pandas as pd
import csv
import sys

# Increase CSV field size limit for large text fields
# Set to maximum possible value on the system
csv.field_size_limit(sys.maxsize)

# SQLite has a maximum string/blob size limit. Set to 100MB to be safe.
MAX_TEXT_LENGTH = 100 * 1024 * 1024  # 100 MB


def _identify_date_columns(df):
    """
    Identify columns that contain 'DATE' in their name.

    Args:
        df: DataFrame to analyze

    Returns:
        List of column names that appear to be date columns
    """
    date_columns = [col for col in df.columns if 'DATE' in col.upper()]
    return date_columns


def _parse_dates_flexible(df, date_columns):
    """
    Parse date columns with flexible format detection.

    Handles multiple date formats commonly found in MAUDE data:
    - MM/DD/YYYY
    - YYYY/MM/DD
    - MM-DD-YYYY
    - YYYY-MM-DD
    - And other variations

    Args:
        df: DataFrame to process
        date_columns: List of column names to parse as dates

    Returns:
        DataFrame with date columns converted to datetime objects
    """
    df_copy = df.copy()

    for col in date_columns:
        if col in df_copy.columns:
            # Use pandas to_datetime with flexible parsing
            # errors='coerce' converts unparseable dates to NaT (Not a Time)
            # format='mixed' suppresses the warning about mixed formats
            df_copy[col] = pd.to_datetime(
                df_copy[col],
                errors='coerce',
                format='mixed'
            )

    return df_copy


def _truncate_large_text_columns(df, max_length=MAX_TEXT_LENGTH):
    """
    Truncate text columns that exceed SQLite's maximum string/blob size.

    Args:
        df: DataFrame to process
        max_length: Maximum length for text fields (default: 100MB)

    Returns:
        DataFrame with truncated text columns
    """
    df_copy = df.copy()

    for col in df_copy.columns:
        # Check if column contains string data
        if df_copy[col].dtype == 'object':
            # Truncate strings that are too long
            df_copy[col] = df_copy[col].apply(
                lambda x: x[:max_length] if isinstance(x, str) and len(x) > max_length else x
            )

    return df_copy


def process_file(filepath, table_name, conn, chunk_size, verbose=False):
    """
    Read MAUDE text file and insert into SQLite database.

    Args:
        filepath: Path to pipe-delimited text file
        table_name: Name of table to insert into
        conn: SQLite database connection
        chunk_size: Number of rows to process at once
        verbose: Whether to print progress messages
    """
    # Set PRAGMA optimizations for bulk loading
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -64000")  # 64MB cache

    total_rows = 0
    date_columns = None

    for i, chunk in enumerate(pd.read_csv(
        filepath,
        sep='|',
        encoding='latin1',
        on_bad_lines='warn',  # Changed from 'skip' to 'warn' - still skips but warns
        chunksize=chunk_size,
        engine='python',  # Python engine is more lenient with malformed lines
        quoting=3  # QUOTE_NONE - don't use special quoting
    )):
        # Identify date columns on first chunk
        if i == 0:
            date_columns = _identify_date_columns(chunk)
            if verbose and date_columns:
                print(f'    Identified date columns: {", ".join(date_columns)}')

        # Parse date columns with flexible format detection
        if date_columns:
            chunk = _parse_dates_flexible(chunk, date_columns)

        # Truncate text columns that might exceed SQLite's max length
        chunk = _truncate_large_text_columns(chunk)
        chunk.to_sql(table_name, conn, if_exists='append', index=False)
        total_rows += len(chunk)

        if verbose and i % 10 == 0 and i > 0:
            print(f'    Processed {total_rows:,} rows...')

    # Restore default PRAGMA settings
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.commit()

    if verbose:
        print(f'    Total: {total_rows:,} rows')


def process_cumulative_file(filepath, table_name, year, metadata, conn, chunk_size, verbose=False):
    """
    Read cumulative MAUDE file and insert only specified year into database.

    For tables like master and patient that are distributed as cumulative files,
    this filters to only include records from the specified year.

    Args:
        filepath: Path to pipe-delimited text file
        table_name: Name of table to insert into
        year: Year to filter for
        metadata: Table metadata dict containing date_column info
        conn: SQLite database connection
        chunk_size: Number of rows to process at once
        verbose: Whether to print progress messages
    """
    # Fallback to regular processing if no date column defined
    if 'date_column' not in metadata:
        return process_file(filepath, table_name, conn, chunk_size, verbose)

    # Set PRAGMA optimizations for bulk loading
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -64000")  # 64MB cache

    total_rows = 0
    filtered_rows = 0
    date_columns = None

    date_col = metadata['date_column']

    if verbose:
        print(f'    Processing cumulative file, filtering for year {year}...')

    for i, chunk in enumerate(pd.read_csv(
        filepath,
        sep='|',
        encoding='latin1',
        on_bad_lines='warn',  # Changed from 'skip' to 'warn' - still skips but warns
        chunksize=chunk_size,
        engine='python',  # Python engine is more lenient with malformed lines
        quoting=3  # QUOTE_NONE - don't use special quoting
    )):
        # Identify date columns on first chunk
        if i == 0:
            date_columns = _identify_date_columns(chunk)
            if verbose and date_columns:
                print(f'    Identified date columns: {", ".join(date_columns)}')

        # Parse date columns with flexible format detection
        if date_columns:
            chunk = _parse_dates_flexible(chunk, date_columns)

        total_rows += len(chunk)

        # Filter to specified year
        if date_col in chunk.columns:
            # Extract year from date column (already parsed as datetime)
            chunk['_year'] = chunk[date_col].dt.year
            chunk_filtered = chunk[chunk['_year'] == year]
            chunk_filtered = chunk_filtered.drop(columns=['_year'])
        else:
            if verbose and i == 0:
                print(f'    Warning: Date column {date_col} not found, loading all data')
            chunk_filtered = chunk

        if len(chunk_filtered) > 0:
            # Truncate text columns that might exceed SQLite's max length
            chunk_filtered = _truncate_large_text_columns(chunk_filtered)
            chunk_filtered.to_sql(table_name, conn, if_exists='append', index=False)
            filtered_rows += len(chunk_filtered)

        if verbose and i % 10 == 0 and i > 0:
            print(f'    Scanned {total_rows:,} rows, kept {filtered_rows:,}...')

    # Restore default PRAGMA settings
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.commit()

    if verbose:
        print(f'    Total: Scanned {total_rows:,} rows, loaded {filtered_rows:,} rows for year {year}')


def process_cumulative_file_batch(filepath, table_name, years_list, metadata, conn, chunk_size, verbose=False):
    """
    Process cumulative file once for multiple years (batch optimization).

    This is a performance optimization that reads a cumulative file once and filters
    for multiple years simultaneously, instead of reading the same file multiple times.

    Args:
        filepath: Path to pipe-delimited text file
        table_name: Name of table to insert into
        years_list: List of years to extract (e.g., [1996, 1997, ..., 2024])
        metadata: Table metadata dict containing date_column info
        conn: SQLite database connection
        chunk_size: Number of rows to process at once
        verbose: Whether to print progress messages
    """
    if not years_list:
        return

    # Fallback to regular processing if no date column defined
    if 'date_column' not in metadata:
        return process_file(filepath, table_name, conn, chunk_size, verbose)

    # Set PRAGMA optimizations for bulk loading
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -64000")  # 64MB cache

    total_rows = 0
    year_counts = {year: 0 for year in years_list}
    years_set = set(years_list)
    date_columns = None

    date_col = metadata['date_column']

    if verbose:
        year_range = f"{min(years_list)}-{max(years_list)}" if len(years_list) > 1 else str(years_list[0])
        print(f'    Processing cumulative file for years {year_range} (batch mode)...')

    for i, chunk in enumerate(pd.read_csv(
        filepath,
        sep='|',
        encoding='latin1',
        on_bad_lines='warn',  # Changed from 'skip' to 'warn' - still skips but warns
        chunksize=chunk_size,
        engine='python',  # Python engine is more lenient with malformed lines
        quoting=3  # QUOTE_NONE - don't use special quoting
    )):
        # Identify date columns on first chunk
        if i == 0:
            date_columns = _identify_date_columns(chunk)
            if verbose and date_columns:
                print(f'    Identified date columns: {", ".join(date_columns)}')

        # Parse date columns with flexible format detection
        if date_columns:
            chunk = _parse_dates_flexible(chunk, date_columns)

        total_rows += len(chunk)

        # Filter to ANY requested year
        if date_col in chunk.columns:
            # Extract year from date column (already parsed as datetime)
            chunk['_year'] = chunk[date_col].dt.year

            # Filter for any year in the requested set
            chunk_filtered = chunk[chunk['_year'].isin(years_set)]

            # Track per-year counts
            for year in chunk_filtered['_year'].unique():
                if year in year_counts:
                    year_counts[year] += sum(chunk_filtered['_year'] == year)

            chunk_filtered = chunk_filtered.drop(columns=['_year'])
        else:
            if verbose and i == 0:
                print(f'    Warning: Date column {date_col} not found, loading all data')
            chunk_filtered = chunk

        if len(chunk_filtered) > 0:
            # Truncate text columns that might exceed SQLite's max length
            chunk_filtered = _truncate_large_text_columns(chunk_filtered)
            chunk_filtered.to_sql(table_name, conn, if_exists='append', index=False)

        if verbose and i % 10 == 0 and i > 0:
            total_kept = sum(year_counts.values())
            print(f'    Scanned {total_rows:,} rows, kept {total_kept:,}...')

    # Restore default PRAGMA settings
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.commit()

    if verbose:
        total_kept = sum(year_counts.values())
        print(f'    Total: Scanned {total_rows:,} rows, loaded {total_kept:,} rows for {len(years_list)} years')

        # Show per-year breakdown if verbose
        if len(years_list) > 1:
            print(f'    Per-year breakdown:')
            for year in sorted(year_counts.keys()):
                if year_counts[year] > 0:
                    print(f'      {year}: {year_counts[year]:,} rows')


def create_indexes(conn, tables, verbose=False):
    """
    Create indexes on commonly queried fields for performance.
    Only creates indexes if the table actually exists.

    Args:
        conn: SQLite database connection
        tables: List of tables that were added
        verbose: Whether to print progress messages
    """
    if verbose:
        print('\nCreating indexes...')

    # Get list of existing tables
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    existing_tables = {row[0] for row in cursor.fetchall()}

    if 'master' in tables and 'master' in existing_tables:
        conn.execute('CREATE INDEX IF NOT EXISTS idx_master_key ON master(MDR_REPORT_KEY)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_master_date ON master(DATE_RECEIVED)')

    if 'device' in tables and 'device' in existing_tables:
        conn.execute('CREATE INDEX IF NOT EXISTS idx_device_key ON device(MDR_REPORT_KEY)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_device_code ON device(DEVICE_REPORT_PRODUCT_CODE)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_device_generic ON device(GENERIC_NAME)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_device_brand ON device(BRAND_NAME)')



    if 'patient' in tables and 'patient' in existing_tables:
        conn.execute('CREATE INDEX IF NOT EXISTS idx_patient_key ON patient(MDR_REPORT_KEY)')

    if 'text' in tables and 'text' in existing_tables:
        conn.execute('CREATE INDEX IF NOT EXISTS idx_text_key ON text(MDR_REPORT_KEY)')

    conn.commit()