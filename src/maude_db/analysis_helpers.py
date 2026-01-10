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
        f"BRAND_NAME LIKE '%{term}%'"
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
