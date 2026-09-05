# database.py - FDA MAUDE Database Interface (DuckDB backend)
# Copyright (C) 2026 Jacob Schwartz <jaschwa@umich.edu>
# MIT License

"""
MaudeDatabase: download, load, and query FDA MAUDE adverse event data.

Usage:
    db = MaudeDatabase('maude.duckdb', data_dir='./maude_data')
    db.add_years('2019-2024', tables=['master', 'device', 'text'], download=True)
    results = db.search_by_device_names([['argon', 'cleaner'], 'angiojet'])
    narratives = db.get_narratives(results['MDR_REPORT_KEY'])
    db.close()
"""

import os
import json
import shutil
import zipfile
import hashlib
from collections import defaultdict
from datetime import datetime

import duckdb
import pandas as pd
import requests

from .metadata import TABLE_METADATA, FDA_BASE_URL


class MaudeDatabase:
    """
    Interface to FDA MAUDE database via DuckDB.

    Data is stored in a persistent DuckDB file. Raw downloaded CSVs are kept
    in data_dir and can be deleted after loading if disk space is a concern.

    Args:
        db_path: Path to DuckDB database file (created if it doesn't exist).
        data_dir: Directory for downloaded/extracted MAUDE files.
        verbose: Print progress messages (default True).
        memory_limit: DuckDB memory cap (e.g. '4GB', '512MB'). When set,
            DuckDB spills intermediate data to disk instead of OOMing during
            large CSV loads. Defaults to None (DuckDB manages its own limit).
    """

    def __init__(self, db_path, data_dir='./maude_data', verbose=True, memory_limit=None):
        self.db_path = db_path
        self.data_dir = data_dir
        self.verbose = verbose
        self._download_cache = set()

        os.makedirs(data_dir, exist_ok=True)
        self.conn = duckdb.connect(db_path)
        if memory_limit is not None:
            self.conn.execute(f"SET memory_limit='{memory_limit}'")
        self._init_metadata_table()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── Public: data management ───────────────────────────────────────────────

    def add_years(self, years, tables=None, download=False,
                  force_download=False, force_reload=False, force_partial=False):
        """
        Load MAUDE data for the specified years into the database.

        Uses checksum tracking to skip files that haven't changed since last load.

        Args:
            years: Years to load. One of:
                   - int: 2024
                   - list: [2020, 2021, 2022]
                   - str range: '2019-2024'
                   - 'all', 'latest', 'current'
            tables: List of tables to load (default: ['master', 'device', 'text', 'patient']).
            download: If True, download files from FDA before loading.
            force_download: If True, re-download even if zip exists locally.
            force_reload: If True, reload into DB even if checksum is unchanged.
            force_partial: Cumulative tables (master, patient, problem) are fully
                replaced on every reload, so a request that doesn't cover years
                already loaded for one of them would silently drop those years.
                That's rejected by default — pass True to proceed anyway. Doesn't
                apply to yearly tables (device, text), which can't lose data this
                way since each year is an independent file.
        """
        years_list = self._parse_year_range(years)
        if tables is None:
            tables = ['master', 'device', 'text', 'patient']

        valid = self._validate(years_list, tables)
        if not valid:
            return

        years_by_table = defaultdict(list)
        for year, table in valid:
            years_by_table[table].append(year)

        if not force_partial:
            for table in sorted(years_by_table):
                meta = TABLE_METADATA[table]
                if meta['pattern_type'] != 'cumulative':
                    continue
                years_for_table = sorted(years_by_table[table])
                implied = self._implied_years(table, years_for_table, meta)
                missing = self._covered_years(table) - implied
                if missing:
                    raise ValueError(
                        f"add_years({years_for_table}, tables=['{table}']) would not "
                        f"cover years {sorted(missing)} that '{table}' already has "
                        f"loaded. '{table}' is fully replaced on every reload, so this "
                        f"would silently drop that data. Call update() to refresh "
                        f"everything '{table}' has, or pass force_partial=True to "
                        f"proceed and accept the loss."
                    )

        for table in sorted(years_by_table):
            meta = TABLE_METADATA[table]
            years_for_table = sorted(years_by_table[table])

            if meta['pattern_type'] == 'yearly':
                self._process_yearly_table(
                    table, years_for_table, download, force_download, force_reload
                )
            else:
                self._process_cumulative_table(
                    table, years_for_table, meta, download, force_download, force_reload
                )

        self._create_indexes()

    def update(self, download=True, force_download=True):
        """
        Refresh all currently-loaded years and add any new years since the last load.

        Args:
            download: If True, download updated files from FDA.
            force_download: If True, re-download even if zip files exist locally.
        """
        years = self._get_years_in_db()
        if not years:
            if self.verbose:
                print('Database is empty. Use add_years() to populate.')
            return

        all_years = list(range(min(years), datetime.now().year + 1))
        loaded_tables = self._get_loaded_tables()
        if self.verbose:
            print(f'Refreshing {len(loaded_tables)} tables, years {min(years)}–{datetime.now().year}')
        self.add_years(all_years, tables=loaded_tables, download=download,
                       force_download=force_download)

    # ── Public: queries ───────────────────────────────────────────────────────

    def query_device(self, brand_name=None, generic_name=None,
                     manufacturer_name=None, product_code=None,
                     start_date=None, end_date=None):
        """
        Query device events by exact field matching (case-insensitive).

        All provided parameters are combined with AND logic. At least one
        device field (brand_name, generic_name, manufacturer_name, product_code)
        is required.

        For partial/substring matching or boolean logic, use search_by_device_names().

        Args:
            brand_name: Exact BRAND_NAME match (e.g., 'Venovo').
            generic_name: Exact GENERIC_NAME match (e.g., 'Venous Stent').
            manufacturer_name: Exact MANUFACTURER_D_NAME match.
            product_code: Exact DEVICE_REPORT_PRODUCT_CODE (e.g., 'NIQ').
            start_date: Earliest DATE_RECEIVED to include (YYYY-MM-DD).
            end_date: Latest DATE_RECEIVED to include (YYYY-MM-DD).

        Returns:
            DataFrame joining master and device tables.
        """
        conditions, params = [], []

        if brand_name is not None:
            conditions.append("d.BRAND_NAME ILIKE ?")
            params.append(brand_name)
        if generic_name is not None:
            conditions.append("d.GENERIC_NAME ILIKE ?")
            params.append(generic_name)
        if manufacturer_name is not None:
            conditions.append("d.MANUFACTURER_D_NAME ILIKE ?")
            params.append(manufacturer_name)
        if product_code is not None:
            conditions.append("d.DEVICE_REPORT_PRODUCT_CODE = ?")
            params.append(product_code)

        if not conditions:
            raise ValueError(
                "At least one device field required: brand_name, generic_name, "
                "manufacturer_name, or product_code."
            )

        if start_date:
            conditions.append("m.DATE_RECEIVED >= ?::DATE")
            params.append(start_date)
        if end_date:
            conditions.append("m.DATE_RECEIVED <= ?::DATE")
            params.append(end_date)

        where = " AND ".join(conditions)
        sql = f"""
            SELECT m.*, d.* EXCLUDE (MDR_REPORT_KEY)
            FROM device d
            JOIN master m USING (MDR_REPORT_KEY)
            WHERE {where}
        """
        return self.conn.execute(sql, params).df()

    def search_by_device_names(self, criteria, start_date=None, end_date=None,
                               group_column='search_group'):
        """
        Substring search across DEVICE_NAME_CONCAT (BRAND_NAME|GENERIC_NAME|MANUFACTURER_D_NAME).

        Criteria formats:
            'term'                 — any record where any name field contains 'term'
            ['a', 'b']             — contains 'a' OR 'b'
            [['a', 'b'], 'c']      — (contains 'a' AND 'b') OR (contains 'c')
            {'group1': [...], ...} — grouped search; result includes search_group column.
                                     Use None as criteria to skip a group.

        All matching is case-insensitive substring matching.

        Args:
            criteria: Search terms in one of the formats above.
            start_date: Earliest DATE_RECEIVED to include (YYYY-MM-DD).
            end_date: Latest DATE_RECEIVED to include (YYYY-MM-DD).
            group_column: Column name for group label when using dict criteria.

        Returns:
            DataFrame joining master and device tables (plus group_column if dict input).
        """
        if isinstance(criteria, dict):
            parts = []
            for group_name, group_criteria in criteria.items():
                if group_criteria is None:
                    continue
                df = self.search_by_device_names(group_criteria, start_date, end_date)
                df[group_column] = group_name
                parts.append(df)
            if not parts:
                return pd.DataFrame()
            combined = pd.concat(parts, ignore_index=True)
            # Events matching multiple groups: keep first group assignment (dict order).
            return combined.drop_duplicates(subset=['MDR_REPORT_KEY'])

        normalized = self._normalize_criteria(criteria)
        params = []
        or_groups = []

        for and_group in normalized:
            and_parts = []
            for term in and_group:
                and_parts.append("d.DEVICE_NAME_CONCAT ILIKE ?")
                params.append(f'%{term}%')
            or_groups.append("(" + " AND ".join(and_parts) + ")")

        where = "(" + " OR ".join(or_groups) + ")"

        if start_date:
            where += " AND m.DATE_RECEIVED >= ?::DATE"
            params.append(start_date)
        if end_date:
            where += " AND m.DATE_RECEIVED <= ?::DATE"
            params.append(end_date)

        sql = f"""
            SELECT m.*, d.* EXCLUDE (MDR_REPORT_KEY)
            FROM device d
            JOIN master m USING (MDR_REPORT_KEY)
            WHERE {where}
        """
        return self.conn.execute(sql, params).df()

    def get_narratives(self, mdr_report_keys):
        """
        Fetch FOI_TEXT narratives for the given MDR report keys.

        Args:
            mdr_report_keys: List or Series of MDR_REPORT_KEY values.

        Returns:
            DataFrame with MDR_REPORT_KEY and FOI_TEXT columns.
        """
        keys = list(mdr_report_keys)
        if not keys:
            return pd.DataFrame(columns=['MDR_REPORT_KEY', 'FOI_TEXT'])
        placeholders = ', '.join(['?'] * len(keys))
        sql = f"SELECT MDR_REPORT_KEY, FOI_TEXT FROM text WHERE MDR_REPORT_KEY IN ({placeholders})"
        return self.conn.execute(sql, keys).df()

    def get_trends_by_year(self, results_df):
        """
        Count events per year from a results DataFrame.

        If results_df has a 'search_group' column (from grouped search), counts
        are broken out per group.

        Args:
            results_df: DataFrame with at least DATE_RECEIVED and MDR_REPORT_KEY columns.

        Returns:
            DataFrame with year, event_count (and search_group if present).
        """
        if not isinstance(results_df, pd.DataFrame):
            raise TypeError("results_df must be a pandas DataFrame")
        if len(results_df) == 0:
            cols = ['year', 'event_count']
            if 'search_group' in results_df.columns:
                cols.insert(0, 'search_group')
            return pd.DataFrame(columns=cols)
        if 'DATE_RECEIVED' not in results_df.columns:
            raise ValueError("results_df must contain DATE_RECEIVED column")

        df = results_df.copy()
        df['year'] = pd.to_datetime(df['DATE_RECEIVED'], errors='coerce').dt.year

        group_cols = ['year']
        if 'search_group' in df.columns:
            group_cols.insert(0, 'search_group')

        trends = df.groupby(group_cols, as_index=False).size()
        trends.rename(columns={'size': 'event_count'}, inplace=True)
        return trends.sort_values(group_cols)

    def enrich_with_patient_data(self, results_df):
        """
        Left-join patient outcome data onto a results DataFrame.

        Args:
            results_df: DataFrame with MDR_REPORT_KEY column.

        Returns:
            results_df with patient columns appended (suffixed '_patient' on collision).
        """
        keys = results_df['MDR_REPORT_KEY'].tolist()
        if not keys:
            return results_df
        placeholders = ', '.join(['?'] * len(keys))
        patient = self.conn.execute(
            f"SELECT * FROM patient WHERE MDR_REPORT_KEY IN ({placeholders})", keys
        ).df()
        return results_df.merge(patient, on='MDR_REPORT_KEY', how='left',
                                suffixes=('', '_patient'))

    def enrich_with_problems(self, results_df):
        """
        Left-join device problem codes onto a results DataFrame.

        Args:
            results_df: DataFrame with MDR_REPORT_KEY column.

        Returns:
            results_df with problem columns appended (suffixed '_problem' on collision).
        """
        keys = results_df['MDR_REPORT_KEY'].tolist()
        if not keys:
            return results_df
        placeholders = ', '.join(['?'] * len(keys))
        problems = self.conn.execute(
            f"SELECT * FROM problem WHERE MDR_REPORT_KEY IN ({placeholders})", keys
        ).df()
        return results_df.merge(problems, on='MDR_REPORT_KEY', how='left',
                                suffixes=('', '_problem'))

    def query(self, sql, params=None):
        """Execute a raw DuckDB SQL query and return a DataFrame."""
        return self.conn.execute(sql, params or []).df()

    def info(self):
        """Print a summary of loaded tables."""
        print(f"Database : {self.db_path}")
        print(f"Data dir : {self.data_dir}")
        for t in ['master', 'device', 'text', 'patient', 'problem']:
            if not self._table_exists(t):
                print(f"  {t:10s}: not loaded")
                continue
            count = self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            # Years the table *should* cover, per _load_metadata, rather than
            # deriving from the raw data — real MAUDE files have malformed
            # dates (e.g. a placeholder year like 1900) that would otherwise
            # make this range misleading.
            years = self._covered_years(t)
            if years:
                print(f"  {t:10s}: {count:>10,} rows  ({min(years)}–{max(years)})")
            else:
                print(f"  {t:10s}: {count:>10,} rows")

    def close(self):
        """Close the DuckDB connection."""
        self.conn.close()

    # ── Public: archiving ───────────────────────────────────────────────────────

    def archive(self, output_dir, include_raw=False):
        """
        Prepare a citable snapshot of this database (e.g. for Zenodo upload).

        Checkpoints and copies the DuckDB file, and writes a manifest.json
        recording, per loaded table/year: source file, SHA-256 checksum, row
        count, and load timestamp (from _load_metadata) — plus the DuckDB and
        pymaude versions used to build it, so the snapshot can be reproduced
        or verified later.

        Args:
            output_dir: Directory to write the archive into (created if missing).
            include_raw: If True, also copy the raw MAUDE source files referenced
                in _load_metadata (from data_dir) into an output_dir/raw/ subfolder.

        Returns:
            Path to the written manifest.json.
        """
        import pymaude

        os.makedirs(output_dir, exist_ok=True)
        self.conn.execute("CHECKPOINT")

        db_filename = os.path.basename(self.db_path)
        db_dest = os.path.join(output_dir, db_filename)
        shutil.copy2(self.db_path, db_dest)

        rows = self.conn.execute(
            "SELECT table_name, year, source_file, checksum, row_count, loaded_at "
            "FROM _load_metadata ORDER BY table_name, year"
        ).fetchall()

        tables = [
            {
                'table': r[0],
                'year': r[1],
                'source_file': r[2],
                'sha256': r[3],
                'row_count': r[4],
                'loaded_at': r[5].isoformat(),
            }
            for r in rows
        ]

        manifest = {
            'generated_at': datetime.now().isoformat(),
            'pymaude_version': pymaude.__version__,
            'duckdb_version': duckdb.__version__,
            'checksum_algorithm': 'sha256',
            'database': {
                'filename': db_filename,
                'sha256': self._checksum(db_dest),
                'size_bytes': os.path.getsize(db_dest),
            },
            'tables': tables,
        }

        if include_raw:
            raw_dir = os.path.join(output_dir, 'raw')
            os.makedirs(raw_dir, exist_ok=True)
            raw_files = []
            for source_file in sorted({r[2] for r in rows if r[2]}):
                src = os.path.join(self.data_dir, source_file)
                if not os.path.exists(src):
                    if self.verbose:
                        print(f'  Skipping raw file (not found): {source_file}')
                    continue
                dest = os.path.join(raw_dir, source_file)
                shutil.copy2(src, dest)
                raw_files.append({'filename': source_file, 'sha256': self._checksum(dest)})
            manifest['raw_files'] = raw_files

        manifest_path = os.path.join(output_dir, 'manifest.json')
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)

        if self.verbose:
            print(f'Archive written to {output_dir}')
            print(f'  Database : {db_filename} ({manifest["database"]["size_bytes"]:,} bytes)')
            print(f'  Tables   : {len(tables)} entries')
            if include_raw:
                print(f'  Raw files: {len(manifest["raw_files"])}')

        return manifest_path

    # ── Private: loading orchestration ───────────────────────────────────────

    def _process_yearly_table(self, table, years, download, force_download, force_reload):
        for year in years:
            if download:
                self._download_file(table, year, force_download)
            fp = self._make_file_path(table, year)
            if not fp:
                if self.verbose:
                    print(f'  Skipping {table} {year}: file not found in {self.data_dir}')
                continue
            cksum = self._checksum(fp)
            if not force_reload and self._get_stored_checksum(table, year) == cksum:
                if self.verbose:
                    print(f'  {table} {year}: up to date, skipping')
                continue
            rows = self._load_yearly(table, year, fp)
            self._record_load(table, year, os.path.basename(fp), cksum, rows)

    def _process_cumulative_table(self, table, years, meta, download, force_download, force_reload):
        """
        Load a cumulative table (master, patient, problem) from its two source
        files: a historical "thru{N}" file and the small current-year file.

        There's no way to know which specific rows inside a changed cumulative
        file were actually modified — FDA ships one monolithic file per group,
        not a diff. So rather than trying to scope a delete, any checksum
        change in either file triggers a full delete-and-reload of the whole
        table from both currently available source files.
        """
        current_year = datetime.now().year
        prior_years = sorted(y for y in years if y < current_year)
        curr_years  = sorted(y for y in years if y == current_year)
        date_column = meta.get('date_column')

        groups = []
        if prior_years:
            groups.append((max(prior_years), False))
        if curr_years:
            groups.append((current_year, True))
        if not groups:
            return

        fetched = []
        for anchor, is_current in groups:
            if download:
                self._download_file(table, anchor, force_download)
            fp = self._make_file_path(table, anchor)
            if not fp:
                if self.verbose:
                    label = 'current year' if is_current else f'thru {anchor}'
                    print(f'  Skipping {table} ({label}): file not found in {self.data_dir}')
                continue
            fetched.append((anchor, is_current, fp, self._checksum(fp)))

        if len(fetched) != len(groups):
            # Can't safely rebuild the whole table without every expected
            # source file — a partial reload could permanently drop the group
            # we couldn't fetch, since there's no scoped delete to fall back on.
            if self.verbose:
                print(f'  Skipping {table}: not all source files available, leaving table untouched')
            return

        any_changed = force_reload or any(
            self._get_stored_checksum(table, current_year if is_current else anchor) != cksum
            for anchor, is_current, fp, cksum in fetched
        )
        if not any_changed:
            if self.verbose:
                print(f'  {table}: up to date, skipping')
            return

        if self._table_exists(table):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute("DELETE FROM _load_metadata WHERE table_name = ?", [table])

        for i, (anchor, is_current, fp, cksum) in enumerate(fetched):
            rows = self._load_all(table, fp, date_column=date_column, dedup=(i > 0))
            source_file = os.path.basename(fp)
            if is_current:
                self._record_load(table, current_year, source_file, cksum, rows)
            else:
                if date_column:
                    # Record the years this file *actually* contains, rather
                    # than assuming it only covers up to the requested anchor —
                    # thru-file selection chases whatever's latest-available
                    # regardless of the specific year requested, so the real
                    # content can cover more than that (see _implied_years).
                    covered_rows = self.conn.execute(
                        f'SELECT year("{date_column}") AS y, COUNT(*) FROM {table} '
                        f"WHERE source_file = '{source_file}' GROUP BY y"
                    ).fetchall()
                    for y, c in covered_rows:
                        # Real MAUDE data has malformed dates that parse to
                        # implausible years (e.g. 1900) — _validate() clips
                        # every future request to start_year..current_year, so
                        # recording anything outside that range here would make
                        # the guard rail permanently unsatisfiable.
                        if y is not None and meta['start_year'] <= y <= current_year:
                            self._record_load(table, y, source_file, cksum, c)
                else:
                    # No date column to verify against (patient, problem) — the
                    # same latest-available fetch behavior applies, so assume
                    # the same full range _implied_years does.
                    for y in range(meta['start_year'], current_year):
                        self._record_load(table, y, source_file, cksum, rows)

        if self.verbose:
            total = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f'  {table}: {total:,} total rows')

    # ── Private: DuckDB loading ───────────────────────────────────────────────

    # DuckDB CSV read options shared across all load methods.
    # all_varchar=true prevents DuckDB from auto-inferring types, which would
    # cause TRY_STRPTIME to fail (it expects VARCHAR, not auto-detected DATE).
    # Types for key columns are handled explicitly in each SELECT.
    _CSV_OPTS = "sep='|', encoding='latin-1', quote='', ignore_errors=true, all_varchar=true, strict_mode=false"

    def _parse_date_expr(self, col):
        """Return a SQL expression that parses a VARCHAR date column to DATE."""
        return (
            f"coalesce("
            f"TRY_STRPTIME({col}, '%m/%d/%Y'), "
            f"TRY_STRPTIME({col}, '%Y-%m-%d'), "
            f"TRY_STRPTIME({col}, '%Y/%m/%d'))::DATE"
        )

    def _load_yearly(self, table, year, filepath):
        """Load one year's file into its table. Returns row count."""
        if self.verbose:
            print(f'  Loading {table} {year}...')

        fp = filepath.replace("'", "''")
        source_file = os.path.basename(filepath).replace("'", "''")

        if table == 'device':
            # Parse DATE_RECEIVED and add DEVICE_NAME_CONCAT in one CTE pass.
            date_expr = self._parse_date_expr('DATE_RECEIVED')
            select_sql = f"""
                WITH raw AS (
                    SELECT * FROM read_csv('{fp}', {self._CSV_OPTS})
                )
                SELECT * REPLACE ({date_expr} AS DATE_RECEIVED),
                    upper(coalesce(BRAND_NAME, '') || '|' ||
                          coalesce(GENERIC_NAME, '') || '|' ||
                          coalesce(MANUFACTURER_D_NAME, '')) AS DEVICE_NAME_CONCAT,
                    '{source_file}' AS source_file
                FROM raw
            """
        else:
            # text/problem: no date column that needs parsing.
            select_sql = f"""
                SELECT *, '{source_file}' AS source_file
                FROM read_csv('{fp}', {self._CSV_OPTS})
            """

        if self._table_exists(table):
            # Scope the delete to exactly this file's prior contribution.
            # Filename <-> year is fixed for life for yearly tables
            # (device2020.zip always means 2020, never anything else), so this
            # is precise and doesn't depend on a per-row date — unlike text,
            # which has no DATE_RECEIVED column at all, or device, where a
            # row's date can fail to parse and never match a year() filter.
            self.conn.execute(
                f"DELETE FROM {table} WHERE source_file = '{source_file}'"
            )
            self._ensure_new_columns(table, filepath)
            self.conn.execute(f"INSERT INTO {table} BY NAME {select_sql}")
        else:
            self.conn.execute(f"CREATE TABLE {table} AS {select_sql}")

        rows = self.conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_file = '{source_file}'"
        ).fetchone()[0]

        if self.verbose:
            print(f'    {rows:,} rows')
        return rows

    def _load_all(self, table, filepath, date_column=None, dedup=False):
        """
        Load a cumulative file's full content into table, creating it if it
        doesn't exist yet. Used for master, patient, problem — the caller
        (_process_cumulative_table) is responsible for wiping the table first
        when a fresh load is needed; this just inserts/creates.

        date_column: if given, that column is parsed from VARCHAR to DATE
        (master has one; patient/problem don't).
        dedup: the current-year file's rows can overlap with what the thru-file
        already loaded — pass True (for every group after the first in a given
        table-processing pass) to only insert rows not already present.
        Compared on the data columns only (EXCLUDE source_file), since a row
        that's identical except for which file it came from should still count
        as a duplicate; source_file is attached only after dedup so it doesn't
        interfere with the comparison.
        """
        if self.verbose:
            print(f'  Loading {table} ({os.path.basename(filepath)})...')

        fp = filepath.replace("'", "''")
        source_file = os.path.basename(filepath).replace("'", "''")

        if table == 'problem':
            # foidevproblem has no header row — name columns explicitly so DuckDB
            # doesn't fall back to column0/column1/column2 naming.
            # The file has shipped with 2 or 3 columns depending on the release year.
            _opts = (f"sep='|', encoding='latin-1', quote='', ignore_errors=true, "
                     f"all_varchar=true, strict_mode=false, header=false")
            with open(filepath, 'r', encoding='latin1') as _f:
                _ncols = len(_f.readline().split('|'))
            if _ncols >= 3:
                _col_select = ("column0 AS MDR_REPORT_KEY, "
                               "column1 AS DEVICE_PROBLEM_CODE, "
                               "column2 AS DATE_ADDED_FLAG")
            else:
                _col_select = ("column0 AS MDR_REPORT_KEY, "
                               "column1 AS DEVICE_PROBLEM_CODE")
            raw_select_sql = f"""
                SELECT {_col_select}
                FROM read_csv('{fp}', {_opts})
            """
            if self._table_exists(table):
                # Migrate column names if db was created before explicit-naming fix.
                existing = {r[0] for r in self.conn.execute("DESCRIBE problem").fetchall()}
                if 'column0' in existing and 'MDR_REPORT_KEY' not in existing:
                    for i, name in enumerate(['MDR_REPORT_KEY', 'DEVICE_PROBLEM_CODE', 'DATE_ADDED_FLAG']):
                        if f'column{i}' in existing:
                            self.conn.execute(f'ALTER TABLE problem RENAME COLUMN "column{i}" TO "{name}"')
        else:
            if date_column:
                date_expr = self._parse_date_expr(f'"{date_column}"')
                raw_select_sql = f"""
                    SELECT * REPLACE ({date_expr} AS "{date_column}")
                    FROM read_csv('{fp}', {self._CSV_OPTS})
                """
            else:
                raw_select_sql = f"""
                    SELECT * FROM read_csv('{fp}', {self._CSV_OPTS})
                """
            if self._table_exists(table):
                self._ensure_new_columns(table, filepath)

        if self._table_exists(table):
            if not dedup:
                self.conn.execute(f"""
                    INSERT INTO {table} BY NAME
                    SELECT *, '{source_file}' AS source_file FROM ({raw_select_sql})
                """)
            else:
                # A true duplicate must match on every column, DATE_RECEIVED
                # included — so a current-year file's row can only collide
                # with rows already tagged as this year. Scoping the EXCEPT's
                # "existing" side this way avoids hashing/scanning the entire
                # (potentially tens-of-millions-of-wide-rows) table just to
                # dedupe a handful of current-year rows, which can otherwise
                # blow past memory_limit and exhaust temp disk space.
                existing_scope = (
                    f' WHERE year("{date_column}") = {datetime.now().year}'
                    if date_column else ''
                )
                self.conn.execute(f"""
                    WITH truly_new AS (
                        SELECT * FROM ({raw_select_sql})
                        EXCEPT
                        SELECT * EXCLUDE (source_file) FROM {table}{existing_scope}
                    )
                    INSERT INTO {table} BY NAME
                    SELECT *, '{source_file}' AS source_file FROM truly_new
                """)
        else:
            self.conn.execute(f"""
                CREATE TABLE {table} AS
                SELECT *, '{source_file}' AS source_file FROM ({raw_select_sql})
            """)

        rows = self.conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_file = '{source_file}'"
        ).fetchone()[0]
        if self.verbose:
            print(f'    {rows:,} rows')
        return rows

    def _ensure_new_columns(self, table, filepath):
        """
        Add any columns present in the CSV that are missing from the DuckDB table.
        Handles MAUDE's schema variations across years (e.g., new fields added in later files).
        """
        with open(filepath, 'r', encoding='latin1') as f:
            csv_cols = set(f.readline().strip().split('|'))

        existing = {row[0] for row in self.conn.execute(f"DESCRIBE {table}").fetchall()}

        for col in csv_cols:
            col = col.strip()
            if col and col not in existing:
                try:
                    self.conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" VARCHAR')
                except Exception:
                    pass

    def _create_indexes(self):
        """Create indexes on join keys. DuckDB ART indexes help point lookups and joins."""
        for table, col in [
            ('master', 'MDR_REPORT_KEY'),
            ('master', 'DATE_RECEIVED'),
            ('device', 'MDR_REPORT_KEY'),
            ('device', 'DEVICE_REPORT_PRODUCT_CODE'),
            ('text', 'MDR_REPORT_KEY'),
            ('patient', 'MDR_REPORT_KEY'),
            ('problem', 'MDR_REPORT_KEY'),
        ]:
            if self._table_exists(table):
                idx = f"idx_{table}_{col.lower()}"
                try:
                    self.conn.execute(
                        f'CREATE INDEX IF NOT EXISTS {idx} ON "{table}"("{col}")'
                    )
                except Exception:
                    pass

    # ── Private: downloads ────────────────────────────────────────────────────

    def _download_file(self, table, year, force_download=False):
        """Download and extract a MAUDE zip from the FDA FTP area."""
        url, filename = self._construct_url(table, year)
        if not url:
            return False

        cache_key = (table, filename)
        if not force_download and cache_key in self._download_cache:
            return True

        zip_path = os.path.join(self.data_dir, filename)

        if not force_download and os.path.exists(zip_path):
            if self.verbose:
                print(f'  Using cached {filename}')
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    z.extractall(self.data_dir)
                self._download_cache.add(cache_key)
                return True
            except Exception:
                os.remove(zip_path)

        try:
            if self.verbose:
                print(f'  Downloading {filename}...')
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = requests.get(url, headers=headers, timeout=60)
            r.raise_for_status()
            with open(zip_path, 'wb') as f:
                f.write(r.content)
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(self.data_dir)
            self._download_cache.add(cache_key)
            return True
        except Exception as e:
            if self.verbose:
                print(f'  Error downloading {filename}: {e}')
            return False

    def _construct_url(self, table, year):
        """
        Return (url, filename) for a given table and year.

        Yearly tables:  device{year}.zip  /  {prefix}{year}.zip
        Cumulative:     {prefix}thru{N}.zip  (N = most recent available year)
        Current year:   {current_year_prefix}.zip
        """
        if table not in TABLE_METADATA:
            return None, None

        meta = TABLE_METADATA[table]
        prefix = meta['file_prefix']
        current_year = datetime.now().year

        if year == current_year:
            filename = f"{meta['current_year_prefix']}.zip"
            return f"{FDA_BASE_URL}/{filename}", filename

        if meta['pattern_type'] == 'yearly':
            # Device table uses 'device{year}.zip', others use '{prefix}{year}.zip'.
            filename = f"device{year}.zip" if table == 'device' else f"{prefix}{year}.zip"
            return f"{FDA_BASE_URL}/{filename}", filename

        # Cumulative: FDA releases thru{prev_year} files; probe for the latest available.
        sep = meta.get('thru_separator', '')
        for offset in [1, 2, 3]:
            thru_year = current_year - offset
            filename = f"{prefix}{sep}thru{thru_year}.zip"
            url = f"{FDA_BASE_URL}/{filename}"
            if self._url_exists(url):
                if offset > 1 and self.verbose:
                    print(f'  Note: using {filename} (expected {prefix}{sep}thru{current_year - 1} not available)')
                return url, filename

        filename = f"{prefix}{sep}thru{current_year - 1}.zip"
        return f"{FDA_BASE_URL}/{filename}", filename

    def _url_exists(self, url):
        try:
            r = requests.head(url, headers={'User-Agent': 'Mozilla/5.0'},
                              timeout=5, allow_redirects=True)
            return 200 <= r.status_code < 300
        except Exception:
            return False

    def _make_file_path(self, table, year):
        """
        Find the extracted .txt file for a table/year in data_dir.
        Returns full path or None if not found.
        """
        if table not in TABLE_METADATA:
            return None

        meta = TABLE_METADATA[table]
        prefix = meta['file_prefix']
        current_year = datetime.now().year

        try:
            files = set(os.listdir(self.data_dir))
        except FileNotFoundError:
            return None

        candidates = []

        if year == current_year:
            cp = meta['current_year_prefix']
            candidates += [f"{cp}.txt", f"{cp.upper()}.txt"]

        if meta['pattern_type'] == 'yearly':
            if table == 'device':
                candidates += [f"device{year}.txt", f"DEVICE{year}.txt"]
            else:
                candidates += [f"{prefix}{year}.txt", f"{prefix.upper()}{year}.txt"]
        elif meta['pattern_type'] == 'cumulative':
            # Cumulative: check for thru files from most recent backwards.
            sep = meta.get('thru_separator', '')
            for offset in [1, 2, 3]:
                thru_year = current_year - offset
                candidates += [
                    f"{prefix}{sep}thru{thru_year}.txt",
                    f"{prefix.upper()}{sep}thru{thru_year}.txt",
                ]
            # Fallback: any file matching the cumulative pattern.
            for fn in sorted(files):
                if (fn.lower().startswith(prefix.lower())
                        and 'thru' in fn.lower()
                        and fn.endswith('.txt')):
                    candidates.append(fn)

        for c in candidates:
            if c in files:
                return os.path.join(self.data_dir, c)
        return None

    # ── Private: checksum / metadata ─────────────────────────────────────────

    def _init_metadata_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS _load_metadata (
                table_name VARCHAR,
                year       INTEGER,
                source_file VARCHAR,
                checksum   VARCHAR,
                row_count  INTEGER,
                loaded_at  TIMESTAMP
            )
        """)

    def _get_stored_checksum(self, table, year):
        row = self.conn.execute(
            "SELECT checksum FROM _load_metadata WHERE table_name = ? AND year = ?",
            [table, year]
        ).fetchone()
        return row[0] if row else None

    def _record_load(self, table, year, source_file, checksum, rows):
        self.conn.execute(
            "DELETE FROM _load_metadata WHERE table_name = ? AND year = ?",
            [table, year]
        )
        self.conn.execute(
            "INSERT INTO _load_metadata VALUES (?, ?, ?, ?, ?, current_timestamp)",
            [table, year, source_file, checksum, rows]
        )

    def _checksum(self, filepath):
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()

    def _table_exists(self, table):
        return self.conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = ? AND table_schema = 'main'",
            [table]
        ).fetchone()[0] > 0

    def _get_years_in_db(self):
        try:
            rows = self.conn.execute(
                "SELECT DISTINCT year FROM _load_metadata"
            ).fetchall()
            return sorted(r[0] for r in rows)
        except Exception:
            return []

    def _get_loaded_tables(self):
        try:
            rows = self.conn.execute(
                "SELECT DISTINCT table_name FROM _load_metadata"
            ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []

    # ── Private: year parsing / validation ───────────────────────────────────

    def _parse_year_range(self, years):
        if isinstance(years, int):
            return [years]
        if isinstance(years, list):
            return years
        s = str(years)
        if s == 'all':
            return list(range(1991, datetime.now().year + 1))
        if s == 'latest':
            return [datetime.now().year - 1]
        if s == 'current':
            return [datetime.now().year]
        if '-' in s:
            a, b = s.split('-', 1)
            return list(range(int(a), int(b) + 1))
        return [int(s)]

    def _validate(self, years, tables):
        """Return list of (year, table) pairs that are valid to load."""
        valid = []
        current_year = datetime.now().year
        for table in tables:
            if table not in TABLE_METADATA:
                if self.verbose:
                    print(f"  Unknown table '{table}', skipping")
                continue
            start_year = TABLE_METADATA[table]['start_year']
            for year in years:
                if year < start_year:
                    if self.verbose:
                        print(f"  Skipping {table} {year}: available from {start_year} onwards")
                    continue
                if year > current_year:
                    if self.verbose:
                        print(f"  Skipping {table} {year}: future year")
                    continue
                valid.append((year, table))
        return valid

    def _covered_years(self, table):
        """Years currently recorded as loaded for `table`, from _load_metadata."""
        rows = self.conn.execute(
            "SELECT DISTINCT year FROM _load_metadata WHERE table_name = ?", [table]
        ).fetchall()
        return {r[0] for r in rows}

    def _implied_years(self, table, years_for_table, meta):
        """
        Years `table` would end up covering after loading `years_for_table`.

        Yearly tables (device, text): each year is an independent file, so this
        is just the requested years themselves.

        Cumulative tables (master, patient, problem): the "thru{N}" file fetch
        (_construct_url/_make_file_path) always resolves to whichever historical
        dump is actually latest-available, essentially ignoring the specific
        prior year requested — so requesting any prior year is treated as
        implying coverage through last year, not just up to the requested year.
        The current year, if requested, comes from a separate, current-year-only
        file and only implies itself.
        """
        if meta['pattern_type'] == 'yearly':
            return set(years_for_table)

        current_year = datetime.now().year
        prior = [y for y in years_for_table if y < current_year]
        curr = [y for y in years_for_table if y == current_year]
        implied = set()
        if prior:
            implied |= set(range(meta['start_year'], current_year))
        if curr:
            implied.add(current_year)
        return implied

    # ── Private: search helpers ───────────────────────────────────────────────

    def _normalize_criteria(self, criteria):
        """
        Normalize criteria to list-of-lists (each inner list = AND group, outer = OR).

        'term'             → [['term']]
        ['a', 'b']         → [['a'], ['b']]
        [['a', 'b'], 'c']  → [['a', 'b'], ['c']]
        """
        if isinstance(criteria, str):
            return [[criteria]]
        if not isinstance(criteria, list):
            raise ValueError("criteria must be a string or list")
        result = []
        for item in criteria:
            if isinstance(item, str):
                result.append([item])
            elif isinstance(item, list):
                if not item:
                    raise ValueError("Empty AND group in criteria")
                for t in item:
                    if not isinstance(t, str):
                        raise ValueError(f"All search terms must be strings, got {type(t).__name__}")
                result.append(item)
            else:
                raise ValueError(f"Criteria items must be str or list, got {type(item).__name__}")
        if not result:
            raise ValueError("criteria cannot be empty")
        return result
