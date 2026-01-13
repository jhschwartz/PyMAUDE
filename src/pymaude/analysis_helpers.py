"""
Analysis helper functions for MAUDE data.

These functions operate on pandas DataFrames returned by MaudeDatabase query methods.
They provide common analysis patterns to reduce boilerplate in notebooks.
"""

import pandas as pd
import matplotlib.pyplot as plt
from typing import Dict, List, Optional, Union
import os


# ==================== Existing Helper Methods (Moved from database.py) ====================

def get_narratives_for(db, results_df):
    """
    Get narratives for a query result DataFrame.

    Convenience method that extracts MDR_REPORT_KEYs from a DataFrame
    and retrieves their narratives. Useful for chaining after query_device().

    Args:
        db: MaudeDatabase instance
        results_df: DataFrame containing MDR_REPORT_KEY column
                   (typically from query_device() or similar)

    Returns:
        DataFrame with mdr_report_key and narrative text

    Example:
        results = db.query_device(device_name='thrombectomy')
        narratives = get_narratives_for(db, results)
    """
    if 'MDR_REPORT_KEY' not in results_df.columns:
        raise ValueError("DataFrame must contain 'MDR_REPORT_KEY' column")

    keys = results_df['MDR_REPORT_KEY'].tolist()
    return db.get_narratives(keys)


def trends_for(results_df):
    """
    Get yearly trends for a query result DataFrame.

    Analyzes the provided DataFrame to compute yearly event counts
    and breakdowns by event type (deaths, injuries, malfunctions).

    Args:
        results_df: DataFrame with DATE_RECEIVED and EVENT_TYPE columns
                   (typically from query_device())

    Returns:
        DataFrame with columns: year, event_count, deaths, injuries, malfunctions

    Example:
        results = db.query_device(device_name='pacemaker')
        trends = trends_for(results)
    """
    required_cols = ['DATE_RECEIVED', 'EVENT_TYPE']
    missing = [col for col in required_cols if col not in results_df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    # Create a temporary copy with year extracted
    # Handle duplicate columns (e.g., when joining master and device tables)
    df = results_df.copy()
    # Get the first DATE_RECEIVED column if there are duplicates
    date_received = df['DATE_RECEIVED']
    if isinstance(date_received, pd.DataFrame):
        # Multiple DATE_RECEIVED columns - use the first one (from master table)
        date_received = date_received.iloc[:, 0]
    df['year'] = pd.to_datetime(date_received).dt.year

    # Get EVENT_TYPE column, handling duplicates if they exist
    event_type_col = df['EVENT_TYPE']
    if isinstance(event_type_col, pd.DataFrame):
        # Multiple EVENT_TYPE columns - use the first one (from master table)
        event_type_col = event_type_col.iloc[:, 0]
    df['event_type_clean'] = event_type_col

    # Aggregate by year
    # FDA uses abbreviations: D=Death, IN=Injury, M=Malfunction
    trends = df.groupby('year').agg(
        event_count=('year', 'size'),
        deaths=('event_type_clean', lambda x: x.str.contains(r'\bD\b|Death', case=False, na=False, regex=True).sum()),
        injuries=('event_type_clean', lambda x: x.str.contains(r'\bIN\b|Injury', case=False, na=False, regex=True).sum()),
        malfunctions=('event_type_clean', lambda x: x.str.contains(r'\bM\b|Malfunction', case=False, na=False, regex=True).sum())
    ).reset_index()

    return trends


def event_type_breakdown_for(results_df):
    """
    Get event type breakdown for a query result DataFrame.

    Provides summary statistics of event types (deaths, injuries, malfunctions)
    in the provided DataFrame. Counts unique events (MDR_REPORT_KEY) to handle
    cases where multiple devices may be associated with a single event.

    Args:
        results_df: DataFrame with EVENT_TYPE and MDR_REPORT_KEY columns
                   (typically from query_device())

    Returns:
        dict with counts: {
            'total': int,
            'deaths': int,
            'injuries': int,
            'malfunctions': int,
            'other': int
        }

    Example:
        results = db.query_device(device_name='thrombectomy')
        breakdown = event_type_breakdown_for(results)
        print(f"Deaths: {breakdown['deaths']}")
    """
    if 'EVENT_TYPE' not in results_df.columns:
        raise ValueError("DataFrame must contain 'EVENT_TYPE' column")

    # Count unique events (MDR_REPORT_KEY) to avoid double-counting multi-device events
    if 'MDR_REPORT_KEY' in results_df.columns:
        # Get unique MDR_REPORT_KEYs with their EVENT_TYPE
        mdr_key = results_df['MDR_REPORT_KEY']
        if isinstance(mdr_key, pd.DataFrame):
            mdr_key = mdr_key.iloc[:, 0]

        event_type = results_df['EVENT_TYPE']
        if isinstance(event_type, pd.DataFrame):
            event_type = event_type.iloc[:, 0]

        # Create a deduplicated DataFrame
        unique_df = pd.DataFrame({
            'MDR_REPORT_KEY': mdr_key,
            'EVENT_TYPE': event_type
        }).drop_duplicates(subset=['MDR_REPORT_KEY'])

        total = len(unique_df)
        event_type = unique_df['EVENT_TYPE'].fillna('')
    else:
        # Fallback: count all rows if MDR_REPORT_KEY not available
        total = len(results_df)
        event_type = results_df['EVENT_TYPE']
        if isinstance(event_type, pd.DataFrame):
            event_type = event_type.iloc[:, 0]
        event_type = event_type.fillna('')

    # FDA uses abbreviations: D=Death, IN=Injury, M=Malfunction
    # Also check for full words for backwards compatibility
    deaths = event_type.str.contains(r'\bD\b|Death', case=False, regex=True).sum()
    injuries = event_type.str.contains(r'\bIN\b|Injury', case=False, regex=True).sum()
    malfunctions = event_type.str.contains(r'\bM\b|Malfunction', case=False, regex=True).sum()

    # Events can have multiple types, so other is approximate
    other = total - max(deaths, injuries, malfunctions)

    return {
        'total': total,
        'deaths': int(deaths),
        'injuries': int(injuries),
        'malfunctions': int(malfunctions),
        'other': max(0, int(other))
    }


def top_manufacturers_for(results_df, n=10):
    """
    Get top manufacturers from a query result DataFrame.

    Args:
        results_df: DataFrame with MANUFACTURER_D_NAME column
                   (typically from query_device())
        n: Number of top manufacturers to return (default: 10)

    Returns:
        DataFrame with columns: manufacturer, event_count
        Sorted by event_count descending

    Example:
        results = db.query_device(device_name='pacemaker')
        top_mfg = top_manufacturers_for(results, n=5)
    """
    if 'MANUFACTURER_D_NAME' not in results_df.columns:
        raise ValueError("DataFrame must contain 'MANUFACTURER_D_NAME' column")

    counts = results_df['MANUFACTURER_D_NAME'].value_counts().head(n)
    return pd.DataFrame({
        'manufacturer': counts.index,
        'event_count': counts.values
    })


def date_range_summary_for(results_df):
    """
    Get date range summary for a query result DataFrame.

    Args:
        results_df: DataFrame with DATE_RECEIVED column
                   (typically from query_device())

    Returns:
        dict with: {
            'first_date': str,
            'last_date': str,
            'total_days': int,
            'total_records': int
        }

    Example:
        results = db.query_device(device_name='thrombectomy')
        summary = date_range_summary_for(results)
        print(f"Data spans {summary['total_days']} days")
    """
    if 'DATE_RECEIVED' not in results_df.columns:
        raise ValueError("DataFrame must contain 'DATE_RECEIVED' column")

    # Handle duplicate DATE_RECEIVED columns (e.g., from joining master and device tables)
    date_received = results_df['DATE_RECEIVED']
    if isinstance(date_received, pd.DataFrame):
        # Multiple DATE_RECEIVED columns - use the first one
        date_received = date_received.iloc[:, 0]

    dates = pd.to_datetime(date_received)
    first = dates.min()
    last = dates.max()

    return {
        'first_date': str(first.date()) if pd.notna(first) else None,
        'last_date': str(last.date()) if pd.notna(last) else None,
        'total_days': (last - first).days if pd.notna(first) and pd.notna(last) else 0,
        'total_records': len(results_df)
    }


# ==================== New Multi-Device Methods ====================

def query_multiple_devices(db, device_names, start_date=None, end_date=None,
                          deduplicate=True, brand_column='query_brand'):
    """
    Query multiple device brands and combine results.

    Args:
        db: MaudeDatabase instance
        device_names: List of device names to query
        start_date: Optional start date (YYYY-MM-DD)
        end_date: Optional end date (YYYY-MM-DD)
        deduplicate: Remove duplicate MDR_REPORT_KEYs (default: True)
        brand_column: Column name for tracking which brand matched (default: 'query_brand')

    Returns:
        Combined DataFrame with additional columns:
        - {brand_column}: Which search term found this report
        - all_matching_brands: List of all brands that matched (if deduplicated)

    Example:
        brands = ['Venovo', 'Vici', 'Zilver Vena']
        results = query_multiple_devices(db, brands, start_date='2019-01-01')
    """
    all_results = []

    for device_name in device_names:
        if db.verbose:
            print(f"Querying {device_name}...")

        results = db.query_device(
            device_name=device_name,
            start_date=start_date,
            end_date=end_date
        )

        if len(results) > 0:
            results[brand_column] = device_name
            all_results.append(results)
            if db.verbose:
                print(f"  Found {len(results)} reports")

    if not all_results:
        if db.verbose:
            print("\nNo reports found for any brand")
        return pd.DataFrame()

    combined = pd.concat(all_results, ignore_index=True)

    # Remove duplicate column names (e.g., when query_device returns both m.* and d.*)
    # Keep only the first occurrence of each column name
    combined = combined.loc[:, ~combined.columns.duplicated()]

    if deduplicate:
        # Track which brands each MDR appears in
        multi_brand_mdrs = combined.groupby('MDR_REPORT_KEY')[brand_column].apply(list)
        combined['all_matching_brands'] = combined['MDR_REPORT_KEY'].map(multi_brand_mdrs)

        # Keep first occurrence
        initial_count = len(combined)
        combined = combined.drop_duplicates(subset=['MDR_REPORT_KEY'], keep='first')

        if db.verbose and initial_count > len(combined):
            n_duplicates = initial_count - len(combined)
            print(f"\nRemoved {n_duplicates} duplicate MDRs appearing in multiple brand searches")

    return combined


def query_device_catalog(db, device_catalog, start_date=None, end_date=None):
    """
    Query multiple devices from a catalog with multiple search terms per device.

    This helper allows you to efficiently search for a list of devices where each
    device may have multiple brand names, generic names, and/or PMN/PMA numbers.
    Each device's search terms are combined with OR logic (matching ANY term counts),
    and results are deduplicated within each device to avoid counting the same report
    multiple times.

    Args:
        db: MaudeDatabase instance
        device_catalog: List of dicts with device search criteria:
            [
                {
                    'device_id': 'CLEANER_XT',  # Your identifier for this device
                    'search_terms': ['CLEANER XT', 'Cleaner 9mm'],  # Brand/generic names
                    'pma_pmn_numbers': ['P180037'],  # Optional PMN/PMA numbers
                },
                {
                    'device_id': 'ANGIOJET_ZELANTE',
                    'search_terms': ['AngioJet Zelante', 'Zelante DVT'],
                    'pma_pmn_numbers': [],  # Can be empty if none available
                },
                ...
            ]
        start_date: Optional start date (YYYY-MM-DD format)
        end_date: Optional end date (YYYY-MM-DD format)

    Returns:
        DataFrame with all matching reports plus additional columns:
        - device_id: Your identifier from the catalog
        - matched_via: Which search term or PMN found this report
        - All columns from master and device tables

    Notes:
        - Search terms use partial, case-insensitive matching (SQL LIKE)
        - Reports matching multiple search terms for the same device are deduplicated
        - Reports matching multiple different devices appear once per device
        - PMN/PMA searches are exact matches

    Example:
        # Define device catalog (e.g., from a comparison table)
        devices = [
            {
                'device_id': 'CLEANER_XT',
                'search_terms': ['CLEANER XT'],
                'pma_pmn_numbers': ['P180037']
            },
            {
                'device_id': 'ANGIOJET_ZELANTE',
                'search_terms': ['AngioJet Zelante', 'Zelante DVT'],
                'pma_pmn_numbers': []
            },
        ]

        # Query all devices
        results = query_device_catalog(db, devices,
                                      start_date='2019-01-01',
                                      end_date='2024-12-31')

        # Analyze by device
        print(results.groupby('device_id').size())

        # See which search terms found each report
        print(results[['device_id', 'matched_via', 'BRAND_NAME']].head(10))
    """
    all_results = []

    for device in device_catalog:
        device_id = device.get('device_id')
        if not device_id:
            raise ValueError("Each device in catalog must have a 'device_id' field")

        device_results = []

        # Search by brand/generic names using existing partial matching
        for term in device.get('search_terms', []):
            if db.verbose:
                print(f"Querying {device_id} via term: {term}...")

            results = db.query_device(
                device_name=term,
                start_date=start_date,
                end_date=end_date
            )
            if len(results) > 0:
                results['device_id'] = device_id
                results['matched_via'] = term
                device_results.append(results)
                if db.verbose:
                    print(f"  Found {len(results)} reports")

        # Search by PMN/PMA if provided
        for pmn in device.get('pma_pmn_numbers', []):
            if db.verbose:
                print(f"Querying {device_id} via PMN: {pmn}...")

            # Build query with optional date filters
            date_filter = ""
            if start_date:
                date_filter += f" AND DATE(m.DATE_RECEIVED) >= '{start_date}'"
            if end_date:
                date_filter += f" AND DATE(m.DATE_RECEIVED) < DATE('{end_date}', '+1 day')"

            results = db.query(f"""
                SELECT m.*, d.*
                FROM master m
                JOIN device d ON m.MDR_REPORT_KEY = d.MDR_REPORT_KEY
                WHERE m.PMA_PMN_NUM = '{pmn}'{date_filter}
            """)
            if len(results) > 0:
                results['device_id'] = device_id
                results['matched_via'] = f'PMN:{pmn}'
                device_results.append(results)
                if db.verbose:
                    print(f"  Found {len(results)} reports")

        # Combine and deduplicate within this device
        if device_results:
            device_df = pd.concat(device_results, ignore_index=True)
            # Remove duplicate columns from m.* and d.* joins
            device_df = device_df.loc[:, ~device_df.columns.duplicated()]

            # Deduplicate by MDR_REPORT_KEY, keeping first match
            initial_count = len(device_df)
            device_df = device_df.drop_duplicates(subset=['MDR_REPORT_KEY'], keep='first')

            if db.verbose and initial_count > len(device_df):
                n_duplicates = initial_count - len(device_df)
                print(f"  Removed {n_duplicates} duplicate reports for {device_id}")

            all_results.append(device_df)

    if not all_results:
        if db.verbose:
            print("\nNo reports found for any device in catalog")
        return pd.DataFrame()

    # Combine all devices
    final_results = pd.concat(all_results, ignore_index=True)

    if db.verbose:
        print(f"\nTotal reports found: {len(final_results)}")
        print("Breakdown by device:")
        print(final_results.groupby('device_id').size())

    return final_results


def enrich_with_problems(db, results_df):
    """
    Join device problem codes to query results.

    Args:
        db: MaudeDatabase instance
        results_df: DataFrame from query_device() or similar

    Returns:
        DataFrame with problems table columns joined

    Raises:
        ValueError: If problems table not loaded

    Example:
        results = db.query_device(device_name='thrombectomy')
        enriched = enrich_with_problems(db, results)
        print(enriched[['MDR_REPORT_KEY', 'DEVICE_PROBLEM_CODE']])
    """
    # Check MDR_REPORT_KEY column
    if 'MDR_REPORT_KEY' not in results_df.columns:
        raise ValueError("DataFrame must contain 'MDR_REPORT_KEY' column")

    # Check problems table exists (STRICT)
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='problems'",
        db.conn
    )['name'].tolist()

    if 'problems' not in tables:
        raise ValueError(
            "Problems table not loaded. Load with:\n"
            "  db.add_years(years, tables=['problems'], download=True)\n"
            "Note: problems table only available from 2019 onwards"
        )

    mdr_keys = results_df['MDR_REPORT_KEY'].unique().tolist()

    if not mdr_keys:
        return results_df

    placeholders = ','.join(['?'] * len(mdr_keys))
    problems = pd.read_sql_query(f"""
        SELECT MDR_REPORT_KEY, DEVICE_SEQUENCE_NUMBER, DEVICE_PROBLEM_CODE
        FROM problems
        WHERE MDR_REPORT_KEY IN ({placeholders})
    """, db.conn, params=mdr_keys)

    if db.verbose:
        print(f"Joined {len(problems)} device problem entries")

    # Left join to preserve all original rows
    enriched = results_df.merge(
        problems,
        on='MDR_REPORT_KEY',
        how='left'
    )

    return enriched


def enrich_with_patient_data(db, results_df):
    """
    Join patient outcome data to query results.

    Args:
        db: MaudeDatabase instance
        results_df: DataFrame from query_device() or similar

    Returns:
        DataFrame with patient table columns joined, including parsed outcome_codes

    Raises:
        ValueError: If patient table not loaded

    Example:
        results = db.query_device(device_name='stent')
        enriched = enrich_with_patient_data(db, results)
        # Check outcome codes
        deaths = enriched[enriched['outcome_codes'].apply(lambda x: 'D' in x if x else False)]
    """
    # Check MDR_REPORT_KEY column
    if 'MDR_REPORT_KEY' not in results_df.columns:
        raise ValueError("DataFrame must contain 'MDR_REPORT_KEY' column")

    # Check patient table exists (STRICT)
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='patient'",
        db.conn
    )['name'].tolist()

    if 'patient' not in tables:
        raise ValueError(
            "Patient table not loaded. Load with:\n"
            "  db.add_years(years, tables=['patient'], download=True)"
        )

    mdr_keys = results_df['MDR_REPORT_KEY'].unique().tolist()

    if not mdr_keys:
        return results_df

    placeholders = ','.join(['?'] * len(mdr_keys))
    patient = pd.read_sql_query(f"""
        SELECT *
        FROM patient
        WHERE MDR_REPORT_KEY IN ({placeholders})
    """, db.conn, params=mdr_keys)

    if db.verbose:
        print(f"Joined {len(patient)} patient records")

    # Parse outcome codes from semicolon-separated strings
    def parse_outcomes(outcome_str):
        if pd.isna(outcome_str):
            return []
        return [code.strip() for code in str(outcome_str).split(';') if code.strip()]

    patient['outcome_codes'] = patient['SEQUENCE_NUMBER_OUTCOME'].apply(parse_outcomes)

    # Left join to preserve all original rows
    enriched = results_df.merge(
        patient,
        on='MDR_REPORT_KEY',
        how='left'
    )

    return enriched


def enrich_with_narratives(db, results_df):
    """
    Join event narrative text to query results.

    Args:
        db: MaudeDatabase instance
        results_df: DataFrame from query_device() or similar

    Returns:
        DataFrame with narrative column (FOI_TEXT) joined

    Raises:
        ValueError: If text table not loaded

    Example:
        results = db.query_device(device_name='catheter', start_date='2023-01-01')
        with_text = enrich_with_narratives(db, results)
        # Review serious events
        serious = with_text[with_text['EVENT_TYPE'].str.contains('Death|Injury', na=False)]
        for idx, row in serious.head(5).iterrows():
            print(f"\\nReport {row['MDR_REPORT_KEY']}:")
            print(row['FOI_TEXT'][:500])
    """
    # Check MDR_REPORT_KEY column
    if 'MDR_REPORT_KEY' not in results_df.columns:
        raise ValueError("DataFrame must contain 'MDR_REPORT_KEY' column")

    # Check text table exists (STRICT)
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='text'",
        db.conn
    )['name'].tolist()

    if 'text' not in tables:
        raise ValueError(
            "Text table not loaded. Load with:\n"
            "  db.add_years(years, tables=['text'], download=True)"
        )

    mdr_keys = results_df['MDR_REPORT_KEY'].unique().tolist()

    if not mdr_keys:
        return results_df

    placeholders = ','.join(['?'] * len(mdr_keys))
    text = pd.read_sql_query(f"""
        SELECT MDR_REPORT_KEY, FOI_TEXT
        FROM text
        WHERE MDR_REPORT_KEY IN ({placeholders})
    """, db.conn, params=mdr_keys)

    if db.verbose:
        print(f"Joined {len(text)} narrative texts")

    # Left join to preserve all original rows
    enriched = results_df.merge(
        text,
        on='MDR_REPORT_KEY',
        how='left'
    )

    return enriched


def summarize_by_brand(results_df, group_column='standard_brand', include_temporal=True):
    """
    Generate summary statistics by device brand.

    Args:
        results_df: DataFrame from query
        group_column: Column to group by (default: 'standard_brand')
        include_temporal: Include yearly breakdowns (default: True)

    Returns:
        Dict with:
            'counts': Total reports per brand (dict)
            'event_types': Event type breakdown per brand (DataFrame)
            'date_range': First/last report dates per brand (DataFrame)
            'temporal': Yearly counts per brand (DataFrame, if include_temporal=True)

    Example:
        summary = summarize_by_brand(results)
        print(summary['counts'])
        print(summary['temporal'])
    """
    if group_column not in results_df.columns:
        raise ValueError(f"DataFrame must contain '{group_column}' column")

    summary = {}

    # Basic counts
    summary['counts'] = results_df[group_column].value_counts().to_dict()

    # Event type breakdown
    if 'EVENT_TYPE' in results_df.columns:
        summary['event_types'] = results_df.groupby(
            [group_column, 'EVENT_TYPE']
        ).size().unstack(fill_value=0)

    # Date range
    if 'DATE_RECEIVED' in results_df.columns:
        summary['date_range'] = results_df.groupby(group_column)['DATE_RECEIVED'].agg([
            ('first_report', 'min'),
            ('last_report', 'max'),
            ('total_reports', 'count')
        ])

    # Temporal trends
    if include_temporal and 'DATE_RECEIVED' in results_df.columns:
        df_copy = results_df.copy()
        df_copy['year'] = pd.to_datetime(df_copy['DATE_RECEIVED']).dt.year
        summary['temporal'] = df_copy.groupby(
            [group_column, 'year']
        ).size().unstack(fill_value=0)

    return summary


# ==================== Brand Standardization Helpers ====================

def find_brand_variations(db, search_terms, max_results=50):
    """
    Find all brand name variations in database.

    Args:
        db: MaudeDatabase instance
        search_terms: String or list of strings to search for
        max_results: Maximum variations to return (default: 50)

    Returns:
        DataFrame with columns: BRAND_NAME, count, sample_mdr_keys

    Example:
        variations = find_brand_variations(db, 'venovo')
        # Shows: VENOVO (234), Venovo (123), Venovo Venous Stent (45)
    """
    if isinstance(search_terms, str):
        search_terms = [search_terms]

    # Build LIKE conditions for case-insensitive search
    conditions = " OR ".join([
        f"UPPER(BRAND_NAME) LIKE UPPER('%{term}%')"
        for term in search_terms
    ])

    query = f"""
        SELECT
            BRAND_NAME,
            COUNT(*) as count,
            GROUP_CONCAT(MDR_REPORT_KEY, ', ') as sample_mdr_keys
        FROM device
        WHERE {conditions}
        GROUP BY BRAND_NAME
        ORDER BY count DESC
        LIMIT {max_results}
    """

    return pd.read_sql_query(query, db.conn)


def standardize_brand_names(results_df, mapping_dict,
                            source_col='BRAND_NAME',
                            target_col='standard_brand'):
    """
    Standardize brand names using a mapping dictionary.

    Args:
        results_df: DataFrame with brand names
        mapping_dict: Dict mapping patterns to standard names
        source_col: Column with original brand names (default: 'BRAND_NAME')
        target_col: New column for standardized names (default: 'standard_brand')

    Returns:
        DataFrame with new standardized column

    Example:
        mapping = {
            'venovo': 'Venovo',
            'vici': 'Vici',
            'zilver': 'Zilver Vena'
        }
        df = standardize_brand_names(results, mapping)
    """
    if source_col not in results_df.columns:
        raise ValueError(f"DataFrame must contain '{source_col}' column")

    def standardize(brand_name):
        if pd.isna(brand_name):
            return None
        brand_lower = str(brand_name).lower()
        for pattern, standard_name in mapping_dict.items():
            if pattern.lower() in brand_lower:
                return standard_name
        return brand_name  # Keep original if no match

    results_df[target_col] = results_df[source_col].apply(standardize)
    return results_df


def hierarchical_brand_standardization(results_df,
                                       specific_mapping=None,
                                       family_mapping=None,
                                       manufacturer_mapping=None,
                                       source_col='BRAND_NAME',
                                       manufacturer_col='MANUFACTURER_D_NAME'):
    """
    Apply hierarchical brand name standardization with multiple levels.

    This function performs multi-level brand standardization in a single pass:
    1. First tries to match specific device models (e.g., "ClotTriever XL")
    2. Then tries to match device families for unmatched items (e.g., "ClotTriever (unspecified)")
    3. Finally tries to match manufacturers for still-unmatched items (e.g., "Inari Medical")

    Each level only processes items that weren't matched by the previous level,
    preventing "ClotTriever XL" from being incorrectly matched to just "ClotTriever".

    Args:
        results_df: DataFrame with brand names to standardize
        specific_mapping: Dict mapping patterns to specific model names
            Example: {'clottriever xl': 'Inari Medical ClotTriever XL',
                     'clottriever bold': 'Inari Medical ClotTriever BOLD'}
        family_mapping: Dict mapping patterns to device family names
            Example: {'clottriever': 'Inari Medical ClotTriever (unspecified)',
                     'flowtriever': 'Inari Medical FlowTriever (unspecified)'}
        manufacturer_mapping: Dict mapping patterns to manufacturer names
            Example: {'boston': 'Boston Scientific',
                     'inari': 'Inari Medical'}
        source_col: Column with original brand names for model/family matching (default: 'BRAND_NAME')
        manufacturer_col: Column to use for manufacturer matching (default: 'MANUFACTURER_D_NAME')

    Returns:
        DataFrame with three new columns added:
        - device_model: Most specific match (from specific_mapping or family_mapping)
        - device_family: Family-level grouping (from family_mapping if available)
        - manufacturer: Manufacturer name (from manufacturer_mapping if available)

        Original rows are preserved; new columns are None for unmatched items.

    Example:
        >>> specific = {
        ...     'clottriever xl': 'Inari Medical ClotTriever XL',
        ...     'clottriever bold': 'Inari Medical ClotTriever BOLD'
        ... }
        >>> family = {
        ...     'clottriever': 'Inari Medical ClotTriever (unspecified)',
        ...     'flowtriever': 'Inari Medical FlowTriever (unspecified)'
        ... }
        >>> manufacturer = {
        ...     'boston': 'Boston Scientific',
        ...     'inari': 'Inari Medical'
        ... }
        >>> df = hierarchical_brand_standardization(
        ...     results,
        ...     specific_mapping=specific,
        ...     family_mapping=family,
        ...     manufacturer_mapping=manufacturer
        ... )
        >>> # Now df has device_model, device_family, and manufacturer columns
        >>> # "ClotTriever XL" -> device_model="Inari Medical ClotTriever XL"
        >>> # "ClotTriever" -> device_model="Inari Medical ClotTriever (unspecified)"
        >>> # Both -> manufacturer="Inari Medical"

    Notes:
        - Pattern matching is case-insensitive substring matching
        - More specific patterns in each mapping should be listed first (dict order matters)
        - Pass None for any level you don't need
        - Original BRAND_NAME column is preserved unchanged
        - Manufacturer matching uses MANUFACTURER_D_NAME by default (can be overridden)
    """
    if source_col not in results_df.columns:
        raise ValueError(f"DataFrame must contain '{source_col}' column")

    if manufacturer_mapping is not None and manufacturer_col not in results_df.columns:
        raise ValueError(f"DataFrame must contain '{manufacturer_col}' column for manufacturer matching")

    # Create a copy to avoid modifying the original
    df = results_df.copy()

    # Initialize result columns
    df['device_model'] = None
    df['device_family'] = None
    df['manufacturer'] = None

    # Helper function to match a single brand name against a mapping
    def find_match(brand_name, mapping):
        if pd.isna(brand_name) or mapping is None:
            return None
        brand_lower = str(brand_name).lower()
        for pattern, standard_name in mapping.items():
            if pattern.lower() in brand_lower:
                return standard_name
        return None

    # Process each row
    for idx, row in df.iterrows():
        brand_name = row[source_col]

        # Level 1: Try specific mapping
        if specific_mapping:
            specific_match = find_match(brand_name, specific_mapping)
            if specific_match:
                df.at[idx, 'device_model'] = specific_match
                # Also set family if we can derive it from family_mapping
                # Try matching against the brand_name first
                if family_mapping:
                    family_match = find_match(brand_name, family_mapping)
                    if family_match:
                        df.at[idx, 'device_family'] = family_match
                    else:
                        # If brand_name doesn't match family pattern, try matching
                        # against all family patterns to see if the specific model
                        # belongs to any family (e.g., "FlowTriever T16" belongs to "FlowTriever family")
                        for pattern, family_name in family_mapping.items():
                            if pattern.lower() in specific_match.lower():
                                df.at[idx, 'device_family'] = family_name
                                break

        # Level 2: Try family mapping (only if no specific match found)
        if family_mapping and df.at[idx, 'device_model'] is None:
            family_match = find_match(brand_name, family_mapping)
            if family_match:
                # For device_model, append (unspecified) to clarify this is a family-level match
                # Remove existing (family) suffix if present and add (family - unspecified)
                if '(family)' in family_match.lower():
                    model_name = family_match.replace('(family)', '(family - unspecified)').replace('(Family)', '(family - unspecified)')
                else:
                    model_name = f"{family_match} (unspecified)"
                df.at[idx, 'device_model'] = model_name
                df.at[idx, 'device_family'] = family_match

        # Level 3: Try manufacturer mapping (uses manufacturer_col, not brand_name)
        if manufacturer_mapping:
            manufacturer_name = row[manufacturer_col]
            mfr_match = find_match(manufacturer_name, manufacturer_mapping)
            if mfr_match:
                df.at[idx, 'manufacturer'] = mfr_match

    return df


# ==================== Statistical Analysis Methods ====================

def create_contingency_table(results_df, row_var, col_var, normalize=False):
    """
    Create contingency table for chi-square analysis.

    Args:
        results_df: DataFrame with categorical variables
        row_var: Row variable name
        col_var: Column variable name
        normalize: If True, include percentages

    Returns:
        DataFrame (if normalize=False) or dict with 'counts' and 'percentages'

    Example:
        table = create_contingency_table(df, 'standard_brand', 'problem_category', normalize=True)
        print(table['counts'])
        print(table['percentages'])
    """
    if row_var not in results_df.columns:
        raise ValueError(f"DataFrame must contain '{row_var}' column")
    if col_var not in results_df.columns:
        raise ValueError(f"DataFrame must contain '{col_var}' column")

    # Create contingency table
    counts = pd.crosstab(results_df[row_var], results_df[col_var])

    if normalize:
        # Row-wise percentages (sum to 100% per row)
        percentages = counts.div(counts.sum(axis=1), axis=0) * 100
        return {
            'counts': counts,
            'percentages': percentages
        }

    return counts


def chi_square_test(results_df, row_var, col_var, exclude_cols=None):
    """
    Perform chi-square test of independence.

    Args:
        results_df: DataFrame with categorical variables
        row_var: Row variable name
        col_var: Column variable name
        exclude_cols: List of column values to exclude (optional)

    Returns:
        dict with chi2_statistic, p_value, dof, expected_frequencies, significant

    Example:
        result = chi_square_test(df, 'brand', 'problem_category', exclude_cols=['Uncategorized'])
        print(f"Chi-square: {result['chi2_statistic']:.2f}, p={result['p_value']:.4f}")
    """
    from scipy.stats import chi2_contingency

    # Create contingency table
    contingency = create_contingency_table(results_df, row_var, col_var)

    # Exclude specified columns
    if exclude_cols:
        contingency = contingency.drop(columns=exclude_cols, errors='ignore')

    # Perform chi-square test
    chi2, p_value, dof, expected = chi2_contingency(contingency)

    return {
        'chi2_statistic': float(chi2),
        'p_value': float(p_value),
        'dof': int(dof),
        'expected_frequencies': pd.DataFrame(expected,
                                             index=contingency.index,
                                             columns=contingency.columns),
        'significant': p_value < 0.05
    }


def event_type_comparison(results_df, group_var='standard_brand'):
    """
    Compare event type distributions across groups.

    Args:
        results_df: DataFrame with EVENT_TYPE column
        group_var: Variable to compare across

    Returns:
        dict with counts, percentages, chi2_test, summary

    Example:
        comparison = event_type_comparison(results, group_var='standard_brand')
        print(comparison['summary'])
    """
    if 'EVENT_TYPE' not in results_df.columns:
        raise ValueError("DataFrame must contain 'EVENT_TYPE' column")
    if group_var not in results_df.columns:
        raise ValueError(f"DataFrame must contain '{group_var}' column")

    # Deduplicate by MDR_REPORT_KEY
    unique_df = results_df.drop_duplicates(subset=['MDR_REPORT_KEY'], keep='first')

    # Extract event type flags
    unique_df = unique_df.copy()
    event_type_str = unique_df['EVENT_TYPE'].fillna('')
    unique_df['has_death'] = event_type_str.str.contains(r'\bD\b|Death', case=False, regex=True)
    unique_df['has_injury'] = event_type_str.str.contains(r'\bIN\b|Injury', case=False, regex=True)
    unique_df['has_malfunction'] = event_type_str.str.contains(r'\bM\b|Malfunction', case=False, regex=True)

    # Count by group
    counts = unique_df.groupby(group_var).agg({
        'MDR_REPORT_KEY': 'count',
        'has_death': 'sum',
        'has_injury': 'sum',
        'has_malfunction': 'sum'
    }).rename(columns={
        'MDR_REPORT_KEY': 'total',
        'has_death': 'deaths',
        'has_injury': 'injuries',
        'has_malfunction': 'malfunctions'
    })

    # Calculate percentages
    percentages = counts[['deaths', 'injuries', 'malfunctions']].div(counts['total'], axis=0) * 100

    # Chi-square test on event types
    # Create binary columns for each event type
    chi2_df = unique_df[[group_var, 'has_death', 'has_injury', 'has_malfunction']].copy()
    chi2_df_long = pd.melt(chi2_df, id_vars=[group_var],
                           value_vars=['has_death', 'has_injury', 'has_malfunction'],
                           var_name='event_type', value_name='has_event')
    chi2_df_long = chi2_df_long[chi2_df_long['has_event']]  # Only True values
    chi2_result = chi_square_test(chi2_df_long, group_var, 'event_type')

    # Generate summary text
    summary_lines = [
        f"Event Type Comparison by {group_var}",
        "=" * 50,
        f"Chi-square: {chi2_result['chi2_statistic']:.2f} (p={chi2_result['p_value']:.4f})",
        ""
    ]
    for group in percentages.index:
        pcts = percentages.loc[group]
        summary_lines.append(
            f"{group}: {pcts['deaths']:.1f}% deaths, {pcts['injuries']:.1f}% injuries, "
            f"{pcts['malfunctions']:.1f}% malfunctions"
        )

    return {
        'counts': counts,
        'percentages': percentages,
        'chi2_test': chi2_result,
        'summary': '\n'.join(summary_lines)
    }


# ==================== Visualization Methods ====================

def plot_temporal_trends(summary_dict, output_file=None, figsize=(12, 6), **kwargs):
    """
    Generate temporal trend figure.

    Args:
        summary_dict: Output from summarize_by_brand()
        output_file: Path to save figure (optional)
        figsize: Figure size tuple
        **kwargs: Additional matplotlib parameters (title, xlabel, ylabel, etc.)

    Returns:
        Figure and Axes objects

    Example:
        summary = summarize_by_brand(results, include_temporal=True)
        fig, ax = plot_temporal_trends(summary, output_file='figure1.png')
    """
    if 'temporal' not in summary_dict:
        raise ValueError("summary_dict must contain 'temporal' key. "
                        "Set include_temporal=True in summarize_by_brand()")

    temporal_df = summary_dict['temporal']

    fig, ax = plt.subplots(figsize=figsize)

    # Plot each brand as a line
    for brand in temporal_df.index:
        ax.plot(temporal_df.columns, temporal_df.loc[brand],
               marker='o', linewidth=2, markersize=8, label=brand)

    # Styling
    ax.set_xlabel(kwargs.get('xlabel', 'Year'), fontsize=12, fontweight='bold')
    ax.set_ylabel(kwargs.get('ylabel', 'Number of MDRs'), fontsize=12, fontweight='bold')
    ax.set_title(kwargs.get('title', 'Temporal Trends in MAUDE Reports'),
                fontsize=14, fontweight='bold')
    ax.legend(loc=kwargs.get('legend_loc', 'best'), fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(temporal_df.columns)

    plt.tight_layout()

    if output_file:
        fig.savefig(output_file, dpi=kwargs.get('dpi', 300), bbox_inches='tight')

    return fig, ax


def plot_problem_distribution(contingency_table, output_file=None, stacked=True, **kwargs):
    """
    Generate stacked bar chart for problem distributions.

    Args:
        contingency_table: DataFrame with percentages (from create_contingency_table)
        output_file: Path to save figure (optional)
        stacked: Create stacked (True) or grouped (False) bars
        **kwargs: Additional matplotlib parameters

    Returns:
        Figure and Axes objects

    Example:
        table = create_contingency_table(df, 'brand', 'category', normalize=True)
        fig, ax = plot_problem_distribution(table['percentages'])
    """
    fig, ax = plt.subplots(figsize=kwargs.get('figsize', (12, 6)))

    contingency_table.plot(kind='bar', stacked=stacked, ax=ax,
                          colormap=kwargs.get('colormap', 'Set3'),
                          edgecolor='black', linewidth=0.5)

    ax.set_xlabel(kwargs.get('xlabel', 'Device Brand'), fontsize=12, fontweight='bold')
    ylabel = 'Percentage (%)' if stacked else 'Count'
    ax.set_ylabel(kwargs.get('ylabel', ylabel), fontsize=12, fontweight='bold')
    ax.set_title(kwargs.get('title', 'Problem Distribution by Device'),
                fontsize=14, fontweight='bold')
    ax.legend(title=kwargs.get('legend_title', 'Category'),
             bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=9)
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha='right')

    if stacked:
        ax.set_ylim(0, 100)

    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()

    if output_file:
        fig.savefig(output_file, dpi=kwargs.get('dpi', 300), bbox_inches='tight')

    return fig, ax


def export_publication_figures(db, results_df, output_dir, prefix='figure',
                               formats=['png', 'pdf'], **kwargs):
    """
    Batch export all standard manuscript figures.

    Args:
        db: MaudeDatabase instance (for checking available data)
        results_df: Results DataFrame
        output_dir: Output directory path
        prefix: Filename prefix
        formats: List of output formats
        **kwargs: Passed to individual plot functions

    Returns:
        dict mapping figure names to file paths

    Example:
        figures = export_publication_figures(db, results, './figures', prefix='study1')
    """
    os.makedirs(output_dir, exist_ok=True)
    generated = {}

    # Check required columns
    has_brand = 'standard_brand' in results_df.columns
    has_problem_category = 'problem_category' in results_df.columns
    has_patient_category = 'patient_problem_category' in results_df.columns

    if not has_brand:
        raise ValueError("results_df must have 'standard_brand' column. "
                        "Use standardize_brand_names() first.")

    # Figure 1: Temporal Trends
    summary = summarize_by_brand(results_df, include_temporal=True)
    for fmt in formats:
        fname = f"{output_dir}/{prefix}_temporal_trends.{fmt}"
        plot_temporal_trends(summary, output_file=fname, **kwargs)
        if 'temporal_trends' not in generated:
            generated['temporal_trends'] = []
        generated['temporal_trends'].append(fname)

    # Figure 2: Device Problem Distribution (if available)
    if has_problem_category:
        table = create_contingency_table(results_df, 'standard_brand',
                                        'problem_category', normalize=True)
        for fmt in formats:
            fname = f"{output_dir}/{prefix}_device_problems.{fmt}"
            plot_problem_distribution(table['percentages'], output_file=fname,
                                     title='Device Problem Distribution', **kwargs)
            if 'device_problems' not in generated:
                generated['device_problems'] = []
            generated['device_problems'].append(fname)

    # Figure 3: Patient Outcome Distribution (if available)
    if has_patient_category:
        table = create_contingency_table(results_df, 'standard_brand',
                                        'patient_problem_category', normalize=True)
        for fmt in formats:
            fname = f"{output_dir}/{prefix}_patient_outcomes.{fmt}"
            plot_problem_distribution(table['percentages'], output_file=fname,
                                     title='Patient Outcome Distribution', **kwargs)
            if 'patient_outcomes' not in generated:
                generated['patient_outcomes'] = []
            generated['patient_outcomes'].append(fname)

    # Figure 4: Event Type Comparison
    comparison = event_type_comparison(results_df, group_var='standard_brand')
    for fmt in formats:
        fname = f"{output_dir}/{prefix}_event_type_comparison.{fmt}"
        comparison['counts'][['deaths', 'injuries', 'malfunctions']].plot(
            kind='bar', figsize=(10, 6), colormap='viridis'
        )
        plt.xlabel('Device Brand', fontweight='bold')
        plt.ylabel('Number of Events', fontweight='bold')
        plt.title('Event Type Comparison by Device', fontweight='bold')
        plt.legend(['Deaths', 'Injuries', 'Malfunctions'])
        plt.xticks(rotation=45, ha='right')
        plt.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig(fname, dpi=300, bbox_inches='tight')
        plt.close()
        if 'event_type_comparison' not in generated:
            generated['event_type_comparison'] = []
        generated['event_type_comparison'].append(fname)

    return generated


# ==============================================================================
# EVENT_KEY Deduplication and Validation Functions
# ==============================================================================

def count_unique_events(results_df, event_key_col='EVENT_KEY'):
    """
    Count unique events vs total reports to detect duplication.

    Approximately 8% of MAUDE reports share EVENT_KEY with other reports
    (same event reported by manufacturer, hospital, patient, etc.). This
    function helps identify the duplication rate in your dataset.

    IMPORTANT: Reports with null/missing EVENT_KEY are each considered unique
    events. A missing EVENT_KEY indicates the FDA did not assign a shared event
    identifier, so each report represents a distinct event.

    Args:
        results_df: DataFrame with query results
        event_key_col: Column name for EVENT_KEY (default: 'EVENT_KEY')

    Returns:
        dict with keys:
        - total_reports (int): Total number of reports (rows)
        - unique_events (int): Number of unique events (null EVENT_KEYs each count as 1)
        - duplication_rate (float): Percentage of reports that are duplicates (0-100)
        - multi_report_events (list): EVENT_KEYs that have multiple reports (excludes nulls)

    Example:
        >>> results = db.query_device(device_name='pacemaker')
        >>> stats = count_unique_events(results)
        >>> print(f"Duplication: {stats['duplication_rate']:.1f}%")
        Duplication: 7.8%
    """
    if results_df.empty:
        return {
            'total_reports': 0,
            'unique_events': 0,
            'duplication_rate': 0.0,
            'multi_report_events': []
        }

    if event_key_col not in results_df.columns:
        raise ValueError(f"Column '{event_key_col}' not found in DataFrame. "
                        "EVENT_KEY column is required for event deduplication.")

    total_reports = len(results_df)

    # Count unique non-null EVENT_KEYs
    unique_non_null_events = results_df[event_key_col].nunique()

    # Count null EVENT_KEYs (each null represents a unique event)
    null_count = results_df[event_key_col].isna().sum()

    # Total unique events = non-null unique EVENT_KEYs + each null EVENT_KEY
    unique_events = unique_non_null_events + null_count

    # Find EVENT_KEYs with multiple reports (exclude nulls)
    event_counts = results_df[results_df[event_key_col].notna()].groupby(event_key_col).size()
    multi_report_events = event_counts[event_counts > 1].index.tolist()

    # Calculate duplication rate
    duplicates = total_reports - unique_events
    duplication_rate = (duplicates / total_reports * 100) if total_reports > 0 else 0.0

    return {
        'total_reports': total_reports,
        'unique_events': unique_events,
        'duplication_rate': duplication_rate,
        'multi_report_events': multi_report_events
    }


def detect_multi_report_events(results_df, event_key_col='EVENT_KEY'):
    """
    Identify which events have multiple reports.

    Useful for understanding which specific events have duplicate reporting
    from multiple sources (manufacturer, hospital, patient, etc.).

    Args:
        results_df: DataFrame with query results
        event_key_col: Column name for EVENT_KEY (default: 'EVENT_KEY')

    Returns:
        DataFrame with columns:
        - EVENT_KEY: Event identifier
        - report_count: Number of reports for this event
        - mdr_report_keys: List of MDR_REPORT_KEYs for this event

    Example:
        >>> multi_reports = detect_multi_report_events(results)
        >>> print(f"Found {len(multi_reports)} events with multiple reports")
        >>> print(multi_reports.head())
    """
    if results_df.empty:
        return pd.DataFrame(columns=[event_key_col, 'report_count', 'mdr_report_keys'])

    if event_key_col not in results_df.columns:
        raise ValueError(f"Column '{event_key_col}' not found in DataFrame")

    if 'MDR_REPORT_KEY' not in results_df.columns:
        raise ValueError("Column 'MDR_REPORT_KEY' not found in DataFrame")

    # Group by EVENT_KEY and count reports
    grouped = results_df.groupby(event_key_col).agg(
        report_count=('MDR_REPORT_KEY', 'size'),
        mdr_report_keys=('MDR_REPORT_KEY', lambda x: list(x))
    ).reset_index()

    # Filter to only multi-report events
    multi_reports = grouped[grouped['report_count'] > 1].copy()

    return multi_reports.sort_values('report_count', ascending=False).reset_index(drop=True)


def select_primary_report(results_df, event_key_col='EVENT_KEY',
                          strategy='first_received'):
    """
    When multiple reports exist for same event, select primary report.

    This function manually deduplicates a DataFrame that may contain multiple
    reports for the same event. Note: query_device() now deduplicates by default,
    so this function is mainly useful for analyzing already-retrieved data or
    when working with results from deduplicate_events=False queries.

    Args:
        results_df: DataFrame with query results
        event_key_col: Column name for EVENT_KEY (default: 'EVENT_KEY')
        strategy: Selection strategy (default: 'first_received')
            - 'first_received': Select earliest DATE_RECEIVED
            - 'manufacturer': Prefer manufacturer reports (REPORT_SOURCE_CODE)
            - 'most_complete': Select report with most non-null fields

    Returns:
        DataFrame with one row per unique EVENT_KEY

    Example:
        >>> # Get all reports including duplicates
        >>> all_reports = db.query_device(device_name='stent', deduplicate_events=False)
        >>> # Manually deduplicate by selecting first received
        >>> deduplicated = select_primary_report(all_reports, strategy='first_received')
        >>> print(f"Reduced from {len(all_reports)} to {len(deduplicated)} events")
    """
    if results_df.empty:
        return results_df.copy()

    if event_key_col not in results_df.columns:
        raise ValueError(f"Column '{event_key_col}' not found in DataFrame")

    if strategy == 'first_received':
        if 'DATE_RECEIVED' not in results_df.columns:
            raise ValueError("Strategy 'first_received' requires DATE_RECEIVED column")

        # Convert to datetime if needed
        df = results_df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df['DATE_RECEIVED']):
            df['DATE_RECEIVED'] = pd.to_datetime(df['DATE_RECEIVED'], errors='coerce')

        # Sort by EVENT_KEY and DATE_RECEIVED, then take first
        df_sorted = df.sort_values([event_key_col, 'DATE_RECEIVED'])
        deduplicated = df_sorted.groupby(event_key_col, as_index=False).first()

    elif strategy == 'manufacturer':
        if 'REPORT_SOURCE_CODE' not in results_df.columns:
            # Fallback to first_received if column missing
            return select_primary_report(results_df, event_key_col, 'first_received')

        df = results_df.copy()
        # Prefer manufacturer reports, then take first by any tie-breaker
        df['is_manufacturer'] = df['REPORT_SOURCE_CODE'].str.lower().str.contains('manufacturer', na=False)
        df_sorted = df.sort_values([event_key_col, 'is_manufacturer'], ascending=[True, False])
        deduplicated = df_sorted.groupby(event_key_col, as_index=False).first()
        deduplicated = deduplicated.drop(columns=['is_manufacturer'])

    elif strategy == 'most_complete':
        df = results_df.copy()
        # Count non-null fields per row
        df['_completeness'] = df.notna().sum(axis=1)
        df_sorted = df.sort_values([event_key_col, '_completeness'], ascending=[True, False])
        deduplicated = df_sorted.groupby(event_key_col, as_index=False).first()
        deduplicated = deduplicated.drop(columns=['_completeness'])

    else:
        raise ValueError(f"Unknown strategy: {strategy}. "
                        "Must be 'first_received', 'manufacturer', or 'most_complete'")

    return deduplicated.reset_index(drop=True)


def compare_report_vs_event_counts(results_df, event_key_col='EVENT_KEY',
                                    group_by=None):
    """
    Compare counting by reports vs events to show potential overcounting.

    Demonstrates the impact of EVENT_KEY deduplication on event counts.
    Useful for validating analysis methods and understanding data quality.

    IMPORTANT: Null/missing EVENT_KEYs are each treated as unique events.
    This matches FDA guidance where missing EVENT_KEY indicates each report
    represents a distinct event.

    Args:
        results_df: DataFrame with query results
        event_key_col: Column name for EVENT_KEY (default: 'EVENT_KEY')
        group_by: Optional column to group by (e.g., 'year', 'BRAND_NAME')
                 If None, returns overall counts only

    Returns:
        DataFrame with columns:
        - [group_by column]: If group_by specified
        - report_count: Total number of reports
        - event_count: Number of unique events (null EVENT_KEYs each count as 1)
        - inflation_pct: Percentage inflation from counting reports vs events

    Example:
        >>> # Overall comparison
        >>> comparison = compare_report_vs_event_counts(results)
        >>> print(comparison)

        >>> # By year
        >>> results['year'] = pd.to_datetime(results['DATE_RECEIVED']).dt.year
        >>> yearly = compare_report_vs_event_counts(results, group_by='year')
        >>> print(yearly)
    """
    if results_df.empty:
        cols = ['report_count', 'event_count', 'inflation_pct']
        if group_by:
            cols.insert(0, group_by)
        return pd.DataFrame(columns=cols)

    if event_key_col not in results_df.columns:
        raise ValueError(f"Column '{event_key_col}' not found in DataFrame")

    if group_by:
        if group_by not in results_df.columns:
            raise ValueError(f"Column '{group_by}' not found in DataFrame")

        # Group-wise comparison
        # Need to handle null EVENT_KEYs properly (each null is unique)
        def count_unique_with_nulls(series):
            """Count unique values treating each null as unique."""
            non_null_unique = series.nunique()
            null_count = series.isna().sum()
            return non_null_unique + null_count

        grouped = results_df.groupby(group_by).agg({
            'MDR_REPORT_KEY': 'count',  # Total reports
            event_key_col: count_unique_with_nulls  # Unique events (nulls are unique)
        }).reset_index()

        grouped.columns = [group_by, 'report_count', 'event_count']

    else:
        # Overall comparison
        # Count null EVENT_KEYs as unique events
        non_null_unique = results_df[event_key_col].nunique()
        null_count = results_df[event_key_col].isna().sum()
        unique_events = non_null_unique + null_count

        grouped = pd.DataFrame({
            'report_count': [len(results_df)],
            'event_count': [unique_events]
        })

    # Calculate inflation percentage
    grouped['inflation_pct'] = ((grouped['report_count'] - grouped['event_count']) /
                                grouped['event_count'] * 100).fillna(0.0)

    return grouped


# ==============================================================================
# Patient OUTCOME Concatenation Detection Functions
# ==============================================================================

def detect_multi_patient_reports(patient_df):
    """
    Detect reports with multiple patients (potential outcome concatenation).

    In MAUDE data, when multiple patients are involved in a single report,
    the OUTCOME fields concatenate sequentially across patients, leading to
    inflated outcome counts. This function identifies affected reports.

    Args:
        patient_df: DataFrame with patient data (must have MDR_REPORT_KEY column)

    Returns:
        dict with keys:
        - total_reports (int): Total unique MDR_REPORT_KEYs
        - multi_patient_reports (int): Count of reports with >1 patient
        - affected_percentage (float): % of reports affected (0-100)
        - affected_mdr_keys (list): MDR_REPORT_KEYs with multiple patients

    Example:
        >>> patient_data = db.enrich_with_patient_data(results)
        >>> validation = detect_multi_patient_reports(patient_data)
        >>> if validation['affected_percentage'] > 10:
        ...     print(f"Warning: {validation['affected_percentage']:.1f}% have multiple patients")
    """
    if patient_df.empty:
        return {
            'total_reports': 0,
            'multi_patient_reports': 0,
            'affected_percentage': 0.0,
            'affected_mdr_keys': []
        }

    if 'MDR_REPORT_KEY' not in patient_df.columns:
        raise ValueError("Column 'MDR_REPORT_KEY' not found in DataFrame")

    # Count patients per report
    patients_per_report = patient_df.groupby('MDR_REPORT_KEY').size()

    total_reports = len(patients_per_report)
    multi_patient_reports = (patients_per_report > 1).sum()
    affected_percentage = (multi_patient_reports / total_reports * 100) if total_reports > 0 else 0.0

    # Get list of affected MDR_REPORT_KEYs
    affected_mdr_keys = patients_per_report[patients_per_report > 1].index.tolist()

    return {
        'total_reports': total_reports,
        'multi_patient_reports': multi_patient_reports,
        'affected_percentage': affected_percentage,
        'affected_mdr_keys': affected_mdr_keys
    }


def count_unique_outcomes_per_report(patient_df, outcome_col='SEQUENCE_NUMBER_OUTCOME'):
    """
    Count unique outcome codes per report, preventing inflation from concatenation.

    When multiple patients share a report, outcome fields concatenate sequentially.
    This function counts each outcome code ONCE per report, regardless of how many
    times it appears in concatenated fields.

    Args:
        patient_df: DataFrame with patient data
        outcome_col: Column name for outcomes (default: 'SEQUENCE_NUMBER_OUTCOME')

    Returns:
        DataFrame with columns:
        - MDR_REPORT_KEY: Report identifier
        - patient_count: Number of patients in this report
        - unique_outcomes: List of unique outcome codes for this report
        - outcome_counts: Dict with count of each outcome code

    Example:
        >>> patient_data = db.enrich_with_patient_data(results)
        >>> outcome_summary = count_unique_outcomes_per_report(patient_data)
        >>> # Count reports with at least one death (avoiding concatenation inflation)
        >>> death_count = (outcome_summary['unique_outcomes'].apply(lambda x: 'D' in x)).sum()
        >>> print(f"Reports with deaths: {death_count}")
    """
    if patient_df.empty:
        return pd.DataFrame(columns=['MDR_REPORT_KEY', 'patient_count', 'unique_outcomes', 'outcome_counts'])

    if 'MDR_REPORT_KEY' not in patient_df.columns:
        raise ValueError("Column 'MDR_REPORT_KEY' not found in DataFrame")

    if outcome_col not in patient_df.columns:
        raise ValueError(f"Column '{outcome_col}' not found in DataFrame")

    def extract_outcomes(outcome_str):
        """Extract individual outcome codes from semicolon-separated string."""
        if pd.isna(outcome_str):
            return set()
        return {code.strip() for code in str(outcome_str).split(';') if code.strip()}

    # For each report, collect all outcomes from all patients and deduplicate
    report_outcomes = []

    for mdr_key, group in patient_df.groupby('MDR_REPORT_KEY'):
        all_outcomes = set()
        for outcome_str in group[outcome_col]:
            all_outcomes.update(extract_outcomes(outcome_str))

        outcome_list = sorted(all_outcomes)
        outcome_counts_dict = {code: 1 for code in outcome_list}  # Each outcome counted once per report

        report_outcomes.append({
            'MDR_REPORT_KEY': mdr_key,
            'patient_count': len(group),
            'unique_outcomes': outcome_list,
            'outcome_counts': outcome_counts_dict
        })

    return pd.DataFrame(report_outcomes)
