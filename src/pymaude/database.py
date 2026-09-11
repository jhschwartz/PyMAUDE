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
import re
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
        self._repair_stats = defaultdict(lambda: {
            'fixed': 0, 'dropped_too_many': 0, 'dropped_unexplained': 0
        })

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
            force_partial: Cumulative tables (master, patient, device_problem,
                patient_problem) are fully replaced on every reload, so a
                request that doesn't cover years already loaded for one of
                them would silently drop those years.
                That's rejected by default — pass True to proceed anyway. Doesn't
                apply to yearly tables (device, text), which can't lose data this
                way since each year is an independent file.
        """
        years_list = self._parse_year_range(years)
        if tables is None:
            tables = ['master', 'device', 'text', 'patient']

        self._repair_stats = defaultdict(lambda: {
            'fixed': 0, 'dropped_too_many': 0, 'dropped_unexplained': 0
        })

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
                # Years below start_year (including the _ALL_YEARS sentinel used
                # for patient/device_problem/patient_problem) are always bundled into whatever thru-file
                # a prior-year request pulls in — they're never separately
                # droppable, so they'd otherwise trip this guard permanently.
                covered = {y for y in self._covered_years(table) if y >= meta['start_year']}
                missing = covered - implied
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
        if self.verbose:
            self._print_repair_report()

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

    def _enrich(self, results_df, table, suffix):
        """
        Left-join `table` onto results_df by MDR_REPORT_KEY.

        Shared implementation behind enrich_with_patient_data,
        enrich_with_device_problems, and enrich_with_patient_problems — they
        differ only in which table they join and which suffix resolves a
        column-name collision.
        """
        keys = results_df['MDR_REPORT_KEY'].tolist()
        if not keys:
            return results_df
        placeholders = ', '.join(['?'] * len(keys))
        other = self.conn.execute(
            f"SELECT * FROM {table} WHERE MDR_REPORT_KEY IN ({placeholders})", keys
        ).df()
        return results_df.merge(other, on='MDR_REPORT_KEY', how='left',
                                suffixes=('', suffix))

    def enrich_with_patient_data(self, results_df):
        """
        Left-join patient outcome data onto a results DataFrame.

        Args:
            results_df: DataFrame with MDR_REPORT_KEY column.

        Returns:
            results_df with patient columns appended (suffixed '_patient' on collision).
        """
        return self._enrich(results_df, 'patient', '_patient')

    def enrich_with_device_problems(self, results_df):
        """
        Left-join device problem codes onto a results DataFrame.

        Args:
            results_df: DataFrame with MDR_REPORT_KEY column.

        Returns:
            results_df with device_problem columns appended (suffixed
            '_device_problem' on collision).
        """
        return self._enrich(results_df, 'device_problem', '_device_problem')

    def enrich_with_patient_problems(self, results_df):
        """
        Left-join patient problem codes onto a results DataFrame.

        Args:
            results_df: DataFrame with MDR_REPORT_KEY column.

        Returns:
            results_df with patient_problem columns appended (suffixed
            '_patient_problem' on collision).
        """
        return self._enrich(results_df, 'patient_problem', '_patient_problem')

    def filter_by_outcome(self, results_df, outcome):
        """
        Keep only rows whose SEQUENCE_NUMBER_OUTCOME includes at least one of
        the given codes.

        Requires enrich_with_patient_data() to have been called first — that's
        what adds the SEQUENCE_NUMBER_OUTCOME column. A single patient record
        can carry multiple codes at once (e.g. "H; O"), so this matches on
        membership in that list rather than exact equality.

        Outcome codes: D=Death, L=Life Threatening, H=Hospitalization,
        S=Disability, C=Congenital Anomaly, R=Required Intervention, O=Other,
        U=Unknown, I=No Information, A=Not Applicable, *=Invalid Data.

        Args:
            results_df: DataFrame with a SEQUENCE_NUMBER_OUTCOME column.
            outcome: A code (e.g. 'D') or list of codes (e.g. ['D', 'L']),
                combined with OR logic.

        Returns:
            Filtered DataFrame.
        """
        if 'SEQUENCE_NUMBER_OUTCOME' not in results_df.columns:
            raise ValueError(
                "results_df has no SEQUENCE_NUMBER_OUTCOME column. Call "
                "enrich_with_patient_data() first."
            )
        codes = {outcome} if isinstance(outcome, str) else set(outcome)
        matches = results_df['SEQUENCE_NUMBER_OUTCOME'].apply(
            lambda v: isinstance(v, str) and bool(codes & {c.strip() for c in v.split(';')})
        )
        return results_df[matches]

    def filter_by_patient(self, results_df, age_min=None, age_max=None, sex=None):
        """
        Filter to rows matching patient demographic criteria.

        Requires enrich_with_patient_data() to have been called first — that's
        what adds the PATIENT_AGE and PATIENT_SEX columns.

        PATIENT_AGE in the raw MAUDE data is free text like "56 YR", with
        inconsistent units (MO, DA, WK, HR) and placeholder values (NA,
        UNKNOWN, *) where age wasn't reported. age_min/age_max only match the
        "<n> YR" pattern; rows in any other format are excluded when an age
        filter is given, since e.g. months or days aren't comparable to a
        year range.

        Args:
            results_df: DataFrame with PATIENT_AGE/PATIENT_SEX columns.
            age_min: Minimum age in years, inclusive.
            age_max: Maximum age in years, inclusive.
            sex: PATIENT_SEX value to match, e.g. 'Male', 'Female', 'Unknown'
                (case-insensitive).

        Returns:
            Filtered DataFrame.
        """
        missing = {'PATIENT_AGE', 'PATIENT_SEX'} - set(results_df.columns)
        if missing:
            raise ValueError(
                f"results_df is missing {sorted(missing)}. Call "
                "enrich_with_patient_data() first."
            )
        mask = pd.Series(True, index=results_df.index)
        if age_min is not None or age_max is not None:
            years = pd.to_numeric(
                results_df['PATIENT_AGE'].str.extract(
                    r'^\s*(\d+)\s*YR\s*$', flags=re.IGNORECASE
                )[0],
                errors='coerce'
            )
            if age_min is not None:
                mask &= years >= age_min
            if age_max is not None:
                mask &= years <= age_max
        if sex is not None:
            mask &= results_df['PATIENT_SEX'].str.lower() == sex.lower()
        return results_df[mask]

    def _filter_by_code_column(self, results_df, column, code, enrich_hint):
        """
        Keep only rows whose `column` matches one of `code`.

        Shared implementation behind filter_by_device_problem and
        filter_by_patient_problem — they differ only in which enriched code
        column they match on and which enrich_with_* method the error
        message points readers to.
        """
        if column not in results_df.columns:
            raise ValueError(
                f"results_df has no {column} column. Call {enrich_hint}() first."
            )
        codes = {code} if isinstance(code, str) else set(code)
        return results_df[results_df[column].isin(codes)]

    def filter_by_device_problem(self, results_df, problem_code):
        """
        Keep only rows matching the given device problem code(s).

        Requires enrich_with_device_problems() to have been called first —
        that's what adds the DEVICE_PROBLEM_CODE column.
        enrich_with_device_problems produces one row per (report, problem
        code) pair, so this just selects the matching rows; a report's
        other, non-matching problem codes simply aren't included.

        Args:
            results_df: DataFrame with a DEVICE_PROBLEM_CODE column.
            problem_code: A code (e.g. '3189') or list of codes, combined
                with OR logic.

        Returns:
            Filtered DataFrame.
        """
        return self._filter_by_code_column(
            results_df, 'DEVICE_PROBLEM_CODE', problem_code, 'enrich_with_device_problems'
        )

    def filter_by_patient_problem(self, results_df, problem_code):
        """
        Keep only rows matching the given patient problem code(s).

        Requires enrich_with_patient_problems() to have been called first —
        that's what adds the PATIENT_PROBLEM_CODE column.
        enrich_with_patient_problems produces one row per (report, problem
        code) pair, so this just selects the matching rows; a report's
        other, non-matching problem codes simply aren't included.

        Args:
            results_df: DataFrame with a PATIENT_PROBLEM_CODE column.
            problem_code: A code (e.g. '3189') or list of codes, combined
                with OR logic.

        Returns:
            Filtered DataFrame.
        """
        return self._filter_by_code_column(
            results_df, 'PATIENT_PROBLEM_CODE', problem_code, 'enrich_with_patient_problems'
        )

    def filter_by_narrative(self, results_df, term):
        """
        Keep only rows whose FOI_TEXT narrative contains the given substring.

        Unlike the other filter_by_* methods, this doesn't require a prior
        enrich step — it queries the text table directly for the
        MDR_REPORT_KEYs already present in results_df. A report matches if
        any of its (possibly several) narrative entries contain the term.

        Args:
            results_df: DataFrame with an MDR_REPORT_KEY column.
            term: Substring to search for in FOI_TEXT (case-insensitive).

        Returns:
            Filtered DataFrame.
        """
        keys = results_df['MDR_REPORT_KEY'].unique().tolist()
        if not keys:
            return results_df
        placeholders = ', '.join(['?'] * len(keys))
        matching_keys = self.conn.execute(
            f"SELECT DISTINCT MDR_REPORT_KEY FROM text "
            f"WHERE MDR_REPORT_KEY IN ({placeholders}) AND FOI_TEXT ILIKE ?",
            keys + [f'%{term}%']
        ).df()['MDR_REPORT_KEY']
        return results_df[results_df['MDR_REPORT_KEY'].isin(matching_keys)]

    def query(self, sql, params=None):
        """Execute a raw DuckDB SQL query and return a DataFrame."""
        return self.conn.execute(sql, params or []).df()

    def info(self):
        """Print a summary of loaded tables."""
        print(f"Database : {self.db_path}")
        print(f"Data dir : {self.data_dir}")
        tables = ['master', 'device', 'text', 'patient', 'device_problem', 'patient_problem']
        width = max(len(t) for t in tables)
        for t in tables:
            if not self._table_exists(t):
                print(f"  {t:{width}s}: not loaded")
                continue
            count = self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            # Years the table *should* cover, per _load_metadata, rather than
            # deriving from the raw data — real MAUDE files have malformed
            # dates (e.g. a placeholder year like 1900) that would otherwise
            # make this range misleading.
            years = self._covered_years(t)
            real_years = years - {self._ALL_YEARS}
            if not TABLE_METADATA[t].get('date_column'):
                # patient/device_problem/patient_problem load one whole-history file recorded under
                # the _ALL_YEARS sentinel, plus the current year's increment —
                # real_years alone would misleadingly look like a one-year span.
                # There's no date column to verify actual row-level coverage
                # from, so the label states TABLE_METADATA's documented
                # start_year rather than implying a computed/confirmed span —
                # what's really loaded is "every row FDA's cumulative file
                # contains", whatever years that happens to include.
                if self._ALL_YEARS in years:
                    start_year = TABLE_METADATA[t]['start_year']
                    label = (
                        f"FDA docs: {start_year}+, current thru {max(real_years)} (coverage unverified)"
                        if real_years else
                        f"FDA docs: {start_year}+ (coverage unverified)"
                    )
                elif real_years:
                    label = f"{min(real_years)}–{max(real_years)}"
                else:
                    label = None
                print(f"  {t:{width}s}: {count:>10,} rows  ({label})" if label
                      else f"  {t:{width}s}: {count:>10,} rows")
            elif real_years:
                # Drop pre-1991 years (before MAUDE existed) from the displayed
                # range — they're implausible-date rows, not real coverage.
                plausible = {y for y in real_years if y >= self._MAUDE_INCEPTION_YEAR}
                display_years = plausible or real_years
                print(f"  {t:{width}s}: {count:>10,} rows  ({min(display_years)}–{max(display_years)})")
            else:
                print(f"  {t:{width}s}: {count:>10,} rows")

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
        legacy_thru = TABLE_METADATA[table].get('legacy_cumulative_thru')
        legacy_years = [y for y in years if legacy_thru and y <= legacy_thru]
        years = [y for y in years if not (legacy_thru and y <= legacy_thru)]

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

        if legacy_years:
            self._load_legacy_cumulative(table, legacy_thru, download, force_download, force_reload)

    def _load_legacy_cumulative(self, table, legacy_thru, download, force_download, force_reload):
        """
        Some yearly tables (device) shipped their earliest years bundled into
        one cumulative file instead of one file per year (e.g. device data
        through 1997 is a single foidevthru1997.zip, not device1991.zip..
        device1997.zip). Unlike the normal per-year loop, every legacy year
        resolves to this same file, so it's loaded once here and per-year row
        counts are recorded via GROUP BY — same approach _process_cumulative_table
        uses for master/patient/device_problem/patient_problem.
        """
        if download:
            self._download_file(table, legacy_thru, force_download)
        fp = self._make_file_path(table, legacy_thru)
        if not fp:
            if self.verbose:
                print(f'  Skipping {table} (thru {legacy_thru}): file not found in {self.data_dir}')
            return

        cksum = self._checksum(fp)
        source_file = os.path.basename(fp)
        if not force_reload and self._get_stored_checksum(table, legacy_thru) == cksum:
            if self.verbose:
                print(f'  {table} (thru {legacy_thru}): up to date, skipping')
            return

        self._load_yearly(table, legacy_thru, fp)

        date_column = TABLE_METADATA[table].get('date_column', 'DATE_RECEIVED')
        covered_rows = self.conn.execute(
            f'SELECT year("{date_column}") AS y, COUNT(*) FROM {table} '
            f"WHERE source_file = ? GROUP BY y", [source_file]
        ).fetchall()
        for y, c in covered_rows:
            if y is not None:
                self._record_load(table, y, source_file, cksum, c)

    def _process_cumulative_table(self, table, years, meta, download, force_download, force_reload):
        """
        Load a cumulative table (master, patient, device_problem,
        patient_problem) from its two source files: a historical "thru{N}"
        file and the small current-year file.

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
            self._get_stored_checksum(
                table,
                current_year if is_current else (anchor if date_column else self._ALL_YEARS)
            ) != cksum
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
                    # Record every year this file *actually* contains — thru-file
                    # selection chases whatever's latest-available regardless of
                    # the specific year requested, so the real content can cover
                    # more than the requested anchor (see _implied_years), and
                    # real MAUDE data also carries a few implausible dates (e.g.
                    # 1900) that still land somewhere via _parse_date_expr. Rows
                    # are never filtered out of the table itself, so every year
                    # found here must be recorded — clipping to start_year..
                    # current_year previously left those rows in the table but
                    # invisible to _load_metadata, making recorded and actual
                    # row counts silently diverge. The add_years() guard above
                    # already ignores years below start_year when checking for
                    # silently-dropped data, so recording them here is safe.
                    covered_rows = self.conn.execute(
                        f'SELECT year("{date_column}") AS y, COUNT(*) FROM {table} '
                        f"WHERE source_file = '{source_file}' GROUP BY y"
                    ).fetchall()
                    implausible = []
                    for y, c in covered_rows:
                        if y is None:
                            continue
                        self._record_load(table, y, source_file, cksum, c)
                        if y < meta['start_year'] or y > current_year:
                            implausible.append((y, c))
                    if implausible and self.verbose:
                        detail = ', '.join(f'{c:,} row(s) in {y}' for y, c in sorted(implausible))
                        print(f'  Warning: {table} contains data outside '
                              f'{meta["start_year"]}-{current_year}: {detail}')
                else:
                    # No date column to attribute rows to a year (patient,
                    # device_problem, patient_problem) — the whole file is
                    # one unit, so record it once
                    # under the _ALL_YEARS sentinel rather than once per
                    # calendar year (which previously multiplied the recorded
                    # row count by ~25x with no way to tell real from duplicate
                    # entries).
                    self._record_load(table, self._ALL_YEARS, source_file, cksum, rows)

        if self.verbose:
            total = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f'  {table}: {total:,} total rows')

    # ── Private: DuckDB loading ───────────────────────────────────────────────

    # Sentinel _load_metadata year for cumulative tables with no date_column
    # (patient, device_problem, patient_problem): their thru-file is loaded in full, with no way to
    # attribute rows to individual years, so it's recorded once under this
    # value rather than once per calendar year.
    _ALL_YEARS = 0

    # MAUDE's reporting program began in 1991; a handful of cumulative-file
    # rows carry earlier placeholder/garbage dates (e.g. 1900). Those rows are
    # kept and recorded accurately in _load_metadata, but excluded from the
    # displayed year range in info() so one stray date doesn't make the whole
    # table's coverage look wrong.
    _MAUDE_INCEPTION_YEAR = 1991

    # DuckDB CSV read options shared across all load methods.
    # all_varchar=true prevents DuckDB from auto-inferring types, which would
    # cause TRY_STRPTIME to fail (it expects VARCHAR, not auto-detected DATE).
    # Types for key columns are handled explicitly in each SELECT.
    _CSV_OPTS = "sep='|', encoding='latin-1', quote='', ignore_errors=true, all_varchar=true, strict_mode=false"

    def _repair_malformed_lines(self, filepath):
        """
        Reconstruct MAUDE source records broken across multiple physical lines
        by a raw newline embedded in an unquoted text field (e.g. an address
        field with a line break). Detected as a run of consecutive lines whose
        delimiter counts don't individually match the header's column count,
        but do once their raw text is concatenated — that concatenation (not
        a re-split-and-rejoin of each fragment's own fields) exactly
        reconstructs the original record, since it just undoes the line break
        that broke it in the first place.

        A line with MORE delimiters than expected (a stray literal delimiter
        typed into a text field) can't be disambiguated this way, and neither
        can a run that never resolves to the expected column count (e.g. a
        truncated file) — both are left for read_csv's ignore_errors to drop,
        same as today.

        Returns (repaired_rows, columns, n_dropped_too_many, n_dropped_unexplained).
        repaired_rows is a list of tuples of field values (str), in the same
        column order as the file's header, ready to union into the normal
        read_csv(...) result (which already silently drops all of these lines
        itself, via ignore_errors=true).
        """
        repaired_rows = []
        n_too_many = 0
        n_unexplained = 0

        with open(filepath, 'rb') as f:
            header = f.readline().rstrip(b'\r\n')
            columns = [c.decode('latin-1') for c in header.split(b'|')]
            expected = len(columns)

            pending_raw = None
            pending_fields = 0

            for raw in f:
                nf = raw.count(b'|') + 1
                if pending_raw is None:
                    if nf == expected:
                        continue
                    elif nf > expected:
                        n_too_many += 1
                    else:
                        pending_raw = raw
                        pending_fields = nf
                else:
                    pending_raw += raw
                    pending_fields += nf - 1
                    if pending_fields == expected:
                        values = pending_raw.rstrip(b'\r\n').split(b'|')
                        repaired_rows.append(tuple(v.decode('latin-1') for v in values))
                        pending_raw = None
                    elif pending_fields > expected:
                        n_unexplained += 1
                        pending_raw = None
                        if nf == expected:
                            pass
                        elif nf > expected:
                            n_too_many += 1
                        else:
                            pending_raw = raw
                            pending_fields = nf

            if pending_raw is not None:
                n_unexplained += 1

        return repaired_rows, columns, n_too_many, n_unexplained

    def _repaired_csv_source(self, table, filepath, csv_opts):
        """
        SQL source for one file's data: the normal read_csv(...) plus any
        rows recovered by _repair_malformed_lines, unioned in. Updates
        self._repair_stats[table] for add_years()'s end-of-run report.
        """
        fp = filepath.replace("'", "''")
        base_sql = f"SELECT * FROM read_csv('{fp}', {csv_opts})"

        repaired_rows, columns, n_too_many, n_unexplained = self._repair_malformed_lines(filepath)

        stats = self._repair_stats[table]
        stats['fixed'] += len(repaired_rows)
        stats['dropped_too_many'] += n_too_many
        stats['dropped_unexplained'] += n_unexplained

        if not repaired_rows:
            return base_sql

        view_name = f'_repaired_rows_{table}'
        self.conn.register(view_name, pd.DataFrame(repaired_rows, columns=columns))
        return f"{base_sql} UNION ALL SELECT * FROM {view_name}"

    def _print_repair_report(self):
        """Summarize source-line repairs from this add_years() call, by table."""
        if not self._repair_stats:
            return
        active = {t: s for t, s in self._repair_stats.items() if any(s.values())}
        if not active:
            return
        print('\nSource-line repair summary (records split or corrupted by a raw '
              'delimiter/newline in the source file):')
        for table in sorted(active):
            s = active[table]
            print(f'  {table}: {s["fixed"]:,} recovered, '
                  f'{s["dropped_too_many"]:,} dropped (stray delimiter, unrecoverable), '
                  f'{s["dropped_unexplained"]:,} dropped (unresolved)')

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

        source_file = os.path.basename(filepath).replace("'", "''")
        csv_source_sql = self._repaired_csv_source(table, filepath, self._CSV_OPTS)

        if table == 'device':
            # Parse DATE_RECEIVED and add DEVICE_NAME_CONCAT in one CTE pass.
            date_expr = self._parse_date_expr('DATE_RECEIVED')
            select_sql = f"""
                WITH raw AS (
                    {csv_source_sql}
                )
                SELECT * REPLACE ({date_expr} AS DATE_RECEIVED),
                    upper(coalesce(BRAND_NAME, '') || '|' ||
                          coalesce(GENERIC_NAME, '') || '|' ||
                          coalesce(MANUFACTURER_D_NAME, '')) AS DEVICE_NAME_CONCAT,
                    '{source_file}' AS source_file
                FROM raw
            """
        else:
            # text: no date column that needs parsing.
            select_sql = f"""
                SELECT *, '{source_file}' AS source_file
                FROM ({csv_source_sql})
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
        doesn't exist yet. Used for master, patient, device_problem,
        patient_problem — the caller (_process_cumulative_table) is
        responsible for wiping the table first when a fresh load is needed;
        this just inserts/creates.

        date_column: if given, that column is parsed from VARCHAR to DATE
        (master has one; patient/device_problem/patient_problem don't).
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

        headerless_columns = TABLE_METADATA[table].get('headerless_columns')

        if headerless_columns:
            # device_problem ships with no header row (patient_problem uses
            # the column_renames/else branch below instead — its real file
            # has a genuine header) — name columns explicitly so DuckDB
            # doesn't fall back to column0/column1/... naming. device_problem's
            # file has shipped with 2 or 3 columns depending on release year;
            # slicing the configured column list to the file's actual sniffed
            # width handles both vintages with one code path.
            _opts = (f"sep='|', encoding='latin-1', quote='', ignore_errors=true, "
                     f"all_varchar=true, strict_mode=false, header=false")
            with open(filepath, 'r', encoding='latin1') as _f:
                _ncols = len(_f.readline().split('|'))
            _names = headerless_columns[:_ncols]
            _col_select = ", ".join(f"column{i} AS {name}" for i, name in enumerate(_names))
            raw_select_sql = f"""
                SELECT {_col_select}
                FROM read_csv('{fp}', {_opts})
            """
            if self._table_exists(table):
                # Without this, a thru-file/current-year-file pair that
                # differ in sniffed width (e.g. one is the legacy 2-column
                # format, the other 3-column) would either crash the dedup
                # EXCEPT below (mismatched column counts) or fail the
                # INSERT ... BY NAME if the existing table's schema is
                # narrower than the newly-loaded file's columns.
                self._ensure_new_columns(table, filepath, columns=_names)
        else:
            csv_source_sql = self._repaired_csv_source(table, filepath, self._CSV_OPTS)
            if date_column:
                date_expr = self._parse_date_expr(f'"{date_column}"')
                raw_select_sql = f"""
                    SELECT * REPLACE ({date_expr} AS "{date_column}")
                    FROM ({csv_source_sql})
                """
            else:
                raw_select_sql = f"""
                    SELECT * FROM ({csv_source_sql})
                """
            column_renames = TABLE_METADATA[table].get('column_renames')
            if column_renames:
                # patient_problem's real header names its code column
                # PROBLEM_CODE — renamed here to PATIENT_PROBLEM_CODE to
                # match the DEVICE_PROBLEM_CODE naming convention.
                rename_clause = ", ".join(
                    f'"{old}" AS "{new}"' for old, new in column_renames.items()
                )
                raw_select_sql = f"""
                    SELECT * RENAME ({rename_clause})
                    FROM ({raw_select_sql})
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

    def _ensure_new_columns(self, table, filepath, columns=None):
        """
        Add any columns present in the source file that are missing from the
        DuckDB table. Handles MAUDE's schema variations across years (e.g.,
        new fields added in later files).

        columns: explicit column names to check, for headerless files where
        there's no header line to read (the caller already knows the names
        it sliced from headerless_columns). When omitted, the file's own
        header line is read and split.
        """
        if columns is None:
            with open(filepath, 'r', encoding='latin1') as f:
                columns = f.readline().strip().split('|')
        csv_cols = set(columns)

        renames = TABLE_METADATA[table].get('column_renames', {})
        existing = {row[0] for row in self.conn.execute(f"DESCRIBE {table}").fetchall()}

        for col in csv_cols:
            col = col.strip()
            col = renames.get(col, col)
            if col and col not in existing:
                try:
                    self.conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" VARCHAR')
                except Exception as e:
                    if self.verbose:
                        print(f'  Warning: could not add column "{col}" to {table}: {e}')

    def _create_indexes(self):
        """Create indexes on join keys. DuckDB ART indexes help point lookups and joins."""
        for table, col in [
            ('master', 'MDR_REPORT_KEY'),
            ('master', 'DATE_RECEIVED'),
            ('device', 'MDR_REPORT_KEY'),
            ('device', 'DEVICE_REPORT_PRODUCT_CODE'),
            ('text', 'MDR_REPORT_KEY'),
            ('patient', 'MDR_REPORT_KEY'),
            ('device_problem', 'MDR_REPORT_KEY'),
            ('patient_problem', 'MDR_REPORT_KEY'),
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

        Device is a yearly table with two exceptions from its FDA-published
        history: years up to legacy_cumulative_thru ship as one cumulative
        {prefix}thru{N}.zip (like foidevthru1997.zip) rather than per-year
        files, and 1998-1999 use '{prefix}{year}.zip' (foidev1998.zip) instead
        of the 'device{year}.zip' naming every later year uses.
        """
        if table not in TABLE_METADATA:
            return None, None

        meta = TABLE_METADATA[table]
        prefix = meta['file_prefix']
        current_year = datetime.now().year

        if year == current_year:
            filename = f"{meta['current_year_prefix']}.zip"
            return f"{FDA_BASE_URL}/{filename}", filename

        legacy_thru = meta.get('legacy_cumulative_thru')
        if legacy_thru and year <= legacy_thru:
            filename = f"{prefix}thru{legacy_thru}.zip"
            return f"{FDA_BASE_URL}/{filename}", filename

        if meta['pattern_type'] == 'yearly':
            # Device table uses 'device{year}.zip' from 2000 on, but 'foidev{year}.zip'
            # (its normal file_prefix) for 1998-1999; others use '{prefix}{year}.zip'.
            if table == 'device':
                filename = f"{prefix}{year}.zip" if legacy_thru and year <= legacy_thru + 2 else f"device{year}.zip"
            else:
                filename = f"{prefix}{year}.zip"
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

        legacy_thru = meta.get('legacy_cumulative_thru')
        if legacy_thru and year <= legacy_thru:
            candidates += [f"{prefix}thru{legacy_thru}.txt", f"{prefix.upper()}THRU{legacy_thru}.txt"]
        elif meta['pattern_type'] == 'yearly':
            if table == 'device':
                if legacy_thru and year <= legacy_thru + 2:
                    candidates += [f"{prefix}{year}.txt", f"{prefix.upper()}{year}.txt"]
                else:
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
            # Fallback: any file matching the cumulative pattern. Must match
            # right after prefix+sep (not just "starts with prefix and
            # contains 'thru' somewhere") — otherwise e.g. patient's prefix
            # 'patient' would also match patient_problem's
            # 'patientproblemcode_thru{year}.txt' files.
            thru_marker = f"{prefix.lower()}{sep}thru"
            for fn in sorted(files):
                if fn.lower().startswith(thru_marker) and fn.endswith('.txt'):
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
                "SELECT DISTINCT year FROM _load_metadata WHERE year != ?", [self._ALL_YEARS]
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
        is just the requested years themselves — except device's legacy years
        (see legacy_cumulative_thru), which all resolve to one shared file, so
        requesting any one of them implies the whole legacy range.

        Cumulative tables (master, patient, device_problem, patient_problem):
        the "thru{N}" file fetch
        (_construct_url/_make_file_path) always resolves to whichever historical
        dump is actually latest-available, essentially ignoring the specific
        prior year requested — so requesting any prior year is treated as
        implying coverage through last year, not just up to the requested year.
        The current year, if requested, comes from a separate, current-year-only
        file and only implies itself.
        """
        if meta['pattern_type'] == 'yearly':
            implied = set(years_for_table)
            legacy_thru = meta.get('legacy_cumulative_thru')
            if legacy_thru and any(y <= legacy_thru for y in years_for_table):
                implied |= set(range(meta['start_year'], legacy_thru + 1))
            return implied

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
