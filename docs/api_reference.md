# API Reference

Complete technical reference for the `maude_db` library.

## Table of Contents

- [MaudeDatabase Class](#maudedatabase-class)
  - [Initialization](#initialization)
  - [Data Management](#data-management)
  - [Querying](#querying)
  - [Helper Query Methods](#helper-query-methods)
  - [Export & Utilities](#export--utilities)
  - [Internal Methods](#internal-methods-advanced)

---

## MaudeDatabase Class

Main class for interfacing with the FDA MAUDE database.

### Initialization

#### `__init__(db_path, verbose=True)`

Initialize connection to MAUDE database.

**Parameters**:
- `db_path` (str): Path to SQLite database file. Will be created if it doesn't exist.
- `verbose` (bool, default=True): Print progress messages during operations

**Returns**: MaudeDatabase instance

**Example**:
```python
from pymaude import MaudeDatabase

# Create/connect to database
db = MaudeDatabase('maude.db')

# Silent mode
db = MaudeDatabase('maude.db', verbose=False)
```

**Notes**:
- Creates new database if file doesn't exist
- Connects to existing database if file exists
- Database is SQLite format

---

#### Context Manager Usage

The `MaudeDatabase` class supports Python's `with` statement for automatic cleanup.

**Example**:
```python
with MaudeDatabase('maude.db') as db:
    db.add_years(2020, tables=['device'], download=True)
    results = db.query_device(device_name='pacemaker')
# Connection automatically closed
```

**Methods**: `__enter__()`, `__exit__()`

---

#### `close()`

Close database connection.

**Parameters**: None

**Returns**: None

**Example**:
```python
db = MaudeDatabase('maude.db')
# ... use database ...
db.close()
```

**Notes**:
- Always close connections when done
- Or use context manager (`with` statement)
- Closed connections cannot be reused

---

### Data Management

#### `add_years(years, tables=None, download=False, strict=False, chunk_size=100000, data_dir='./maude_data', interactive=True, force_refresh=False)`

Add MAUDE data for specified years to the database.

**Intelligent Checksum Tracking**: This method automatically tracks file checksums to prevent duplicate data and detect FDA updates. When you add a year that's already been loaded, it checks if the source file has changed. If unchanged, processing is skipped. If changed (FDA updated the file), old data is automatically replaced with the new version.

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `years` | int, list, or str | Required | Year(s) to add (see formats below) |
| `tables` | list | `['master', 'device', 'patient', 'text']` | Tables to include |
| `download` | bool | `False` | Download files from FDA if missing |
| `strict` | bool | `False` | Raise error on missing files (vs. skip) |
| `chunk_size` | int | `100000` | Rows per batch (memory management) |
| `data_dir` | str | `'./maude_data'` | Directory for data files |
| `interactive` | bool | `True` | Prompt for validation issues |
| `force_refresh` | bool | `False` | Reload data even if unchanged |

**Year Format Options**:

```python
# Single year (int)
db.add_years(2020, ...)

# Multiple years (list)
db.add_years([2018, 2019, 2020], ...)

# Year range (string)
db.add_years('2018-2020', ...)  # Includes 2018, 2019, 2020

# Latest complete year (string)
db.add_years('latest', ...)     # Previous calendar year

# All available years (string)
db.add_years('all', ...)        # 1991 to present (use with caution!)
```

**Available Tables** (all start at 2000 for consistency):
- `'master'` - Core event data (MDRFOI) - 2000+
- `'device'` - Device details (FOIDEV) - 2000+ (schema changed in 2000)
- `'text'` - Event narratives (FOITEXT) - 2000+
- `'patient'` - Patient demographics (PATIENT) - 2000+
- `'problems'` - Device problem codes (FOIDEVPROBLEM) - 2019+

**Returns**: None

**Examples**:

```python
# Download single year of device data
db.add_years(1998, tables=['device'], download=True)

# Multiple years, device + text data
db.add_years('2018-2020', tables=['device', 'text'], download=True)

# Use existing files (no download)
db.add_years(2020, tables=['device'], download=False, data_dir='./my_data')

# Strict mode - fail if any file missing
db.add_years([2018, 2019], strict=True, download=True)
```

**Notes**:
- **Checksum Tracking**: Automatically prevents duplicate data when adding the same year multiple times
  - First run: Processes file and stores SHA256 checksum
  - Subsequent runs: Skips processing if file unchanged (instant!)
  - FDA updates: Detects changed files and automatically refreshes data
  - Use `force_refresh=True` to reload data even if unchanged
- **Cumulative File Fallback**: For master and patient tables (cumulative files), the library automatically handles FDA's delayed update schedule
  - If the expected cumulative file isn't available (e.g., `mdrfoithru2025.zip` in early January 2026), the library will automatically try older files
  - Falls back through up to 3 years (e.g., tries 2025 → 2024 → 2023)
  - Displays a warning when using an older file than expected
  - This ensures you always get the latest available data, even during FDA's transition periods
- Files are cached in `data_dir` - subsequent runs are fast
- Strict mode useful for critical data requirements
- Master table only available as comprehensive file (too large)
- Default chunk_size (100000) works for most systems
- Lower chunk_size if you encounter memory issues

**Examples with Checksum Tracking**:

```python
# First load - processes file
db.add_years(2020, tables=['device'], download=True)

# Second load - skips processing (file unchanged)
db.add_years(2020, tables=['device'])  # Instant! Prints: "device for year 2020 already loaded and unchanged, skipping"

# Force refresh (ignore checksums)
db.add_years(2020, tables=['device'], force_refresh=True)  # Reprocesses even if unchanged

# FDA updates historical data
db.add_years(2020, tables=['device'], download=True)
# If FDA changed the file: Automatically detects change, deletes old 2020 data, loads new version
# If unchanged: Skips processing
```

**Related**: `update()`, `_download_file()`, `_make_file_path()`

---

#### `update(add_new_years, download=True)`

Update existing years in database with latest FDA data.

**Parameters**:
- `add_new_years` (bool, required keyword-only): If True, also adds any missing years since the most recent year in database. If False, only refreshes existing years.
- `download` (bool, optional): If True, download files from FDA. If False, use local files (default: True)

**Returns**: None

**Example**:
```python
db = MaudeDatabase('maude.db')

# Refresh existing years only (check for FDA updates)
db.update(add_new_years=False)

# Refresh existing years AND add new years
db.update(add_new_years=True)

# Update from local files without downloading
db.update(add_new_years=False, download=False)
```

**Notes**:
- Uses checksum tracking to skip files that haven't changed
- Only reprocesses data if FDA has updated source files
- When `add_new_years=True`, fills all gaps from max existing year to current year
- Returns early with message if database is empty
- Requires internet connection

**Related**: `add_years()`, `_get_latest_available_year()`, `_get_years_in_db()`

---

### Querying

#### `query(sql, params=None)`

Execute raw SQL query and return results.

**Parameters**:
- `sql` (str): SQL query string
- `params` (dict or tuple, optional): Parameters for safe queries

**Returns**: pandas.DataFrame with query results

**Examples**:

```python
# Simple query
df = db.query("SELECT COUNT(*) as count FROM device")
print(df['count'][0])

# Parameterized query (safe from SQL injection)
df = db.query(
    "SELECT * FROM device WHERE GENERIC_NAME LIKE :name",
    params={'name': '%catheter%'}
)

# Join multiple tables
df = db.query("""
    SELECT m.event_type, COUNT(*) as count
    FROM master m
    JOIN device d ON m.mdr_report_key = d.MDR_REPORT_KEY
    WHERE d.GENERIC_NAME LIKE '%pacemaker%'
    GROUP BY m.event_type
""")
```

**Column Name Case**:
- All MAUDE tables use **UPPERCASE** column names (`MDR_REPORT_KEY`, `GENERIC_NAME`, `BRAND_NAME`, `DATE_RECEIVED`, `EVENT_TYPE`)
- This reflects the actual FDA data format

**Notes**:
- Always use parameterized queries for user input
- Results are pandas DataFrames
- Full SQL syntax supported (SQLite dialect)

**Related**: `query_device()`, `get_trends_by_year()`, `get_narratives()`

---

#### `query_device(device_name=None, product_code=None, start_date=None, end_date=None)`

Query device events with optional filters.

**Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `device_name` | str | Filter by generic/brand name (partial match, case-insensitive) |
| `product_code` | str | Filter by exact FDA product code |
| `start_date` | str | Only events on/after this date (format: 'YYYY-MM-DD') |
| `end_date` | str | Only events on/before this date (format: 'YYYY-MM-DD') |

**Returns**: pandas.DataFrame with columns from master + device tables joined

**Examples**:

```python
# Search by device name (partial match)
catheters = db.query_device(device_name='catheter')

# Exact product code
devices = db.query_device(product_code='NIQ')

# Date range
recent = db.query_device(
    device_name='pacemaker',
    start_date='2020-01-01',
    end_date='2020-12-31'
)

# Multiple filters
results = db.query_device(
    device_name='stent',
    start_date='2019-01-01'
)
```

**Notes**:
- All parameters are optional (omit for no filtering)
- `device_name` matches both GENERIC_NAME and BRAND_NAME
- Returns joined data from master and device tables
- Empty DataFrame if no matches

**Common Patterns**:

```python
# Get all events for specific device
all_pacers = db.query_device(device_name='pacemaker')

# Count results
count = len(db.query_device(device_name='stent'))

# Get specific columns
results = db.query_device(device_name='catheter')
print(results[['GENERIC_NAME', 'BRAND_NAME', 'EVENT_TYPE']])
```

**Related**: `query()`, `get_trends_by_year()`, `export_subset()`

---

#### `get_trends_by_year(product_code=None, device_name=None)`

Get yearly event counts and breakdown by event type.

**Parameters**:
- `product_code` (str, optional): Filter by FDA product code
- `device_name` (str, optional): Filter by device name (partial match)

**Returns**: pandas.DataFrame with columns:
- `year` (str): Year as string
- `event_count` (int): Total events
- `deaths` (int): Events involving death
- `injuries` (int): Events involving injury
- `malfunctions` (int): Events involving malfunction

**Examples**:

```python
# Trends for all devices
all_trends = db.get_trends_by_year()

# Specific device by name
pacer_trends = db.get_trends_by_year(device_name='pacemaker')

# Specific device by product code
trends = db.get_trends_by_year(product_code='NIQ')

# Display results
print(trends)
#    year  event_count  deaths  injuries  no_patient_impact
# 0  2018         1245      12       345                 888
# 1  2019         1356      15       389                 952
# 2  2020         1423      18       412                1003
```

**Notes**:
- Event types are not mutually exclusive (one event can have multiple types)
- Use either `product_code` OR `device_name`, not both
- Returns empty DataFrame if no matching events
- Years with zero events are excluded

**Visualization Example**:

```python
import matplotlib.pyplot as plt

trends = db.get_trends_by_year(device_name='catheter')

plt.plot(trends['year'], trends['event_count'])
plt.xlabel('Year')
plt.ylabel('Number of Events')
plt.title('Catheter Adverse Events Over Time')
plt.show()
```

**Related**: `query_device()`, `query()`, `trends_for()`

---

#### `get_narratives(mdr_report_keys)`

Get event narrative text for specific report keys.

**Parameters**:
- `mdr_report_keys` (list): List of MDR report keys (integers or strings)

**Returns**: pandas.DataFrame with columns:
- `MDR_REPORT_KEY`: Report identifier
- `FOI_TEXT`: Narrative description text

**Example**:

```python
# First, get some device events
devices = db.query_device(device_name='defibrillator')

# Get report keys for first 5 events
keys = devices['MDR_REPORT_KEY'].head(5).tolist()

# Retrieve narratives
narratives = db.get_narratives(keys)

# Display narratives
for idx, row in narratives.iterrows():
    print(f"\nReport {row['MDR_REPORT_KEY']}:")
    print(row['FOI_TEXT'])
```

**Notes**:
- Requires text table to be loaded (`add_years(..., tables=['text'], ...)`)
- Not all events have narratives
- Multiple text records can exist per report key
- Narratives may be redacted for privacy

**Common Workflow**:

```python
# 1. Query devices
results = db.query_device(device_name='pacemaker', start_date='2020-01-01')

# 2. Filter to serious events using FDA abbreviations (D=Death, IN=Injury)
serious = results[results['EVENT_TYPE'].str.contains(r'\bD\b|\bIN\b', case=False, na=False, regex=True)]

# 3. Get narratives
keys = serious['MDR_REPORT_KEY'].tolist()
narratives = db.get_narratives(keys)
```

**Related**: `query_device()`, `add_years()`, `get_narratives_for()`

---

### Helper Query Methods

These methods operate on query result DataFrames to reduce boilerplate code and make common analysis tasks easier. They accept DataFrames returned by `query_device()` or similar methods.

---

#### `get_narratives_for(results_df)`

Get narratives for a query result DataFrame.

Convenience wrapper that extracts MDR_REPORT_KEYs from a DataFrame and retrieves their narratives.

**Parameters**:
- `results_df` (DataFrame): DataFrame containing `MDR_REPORT_KEY` column (typically from `query_device()`)

**Returns**: pandas.DataFrame with `MDR_REPORT_KEY` and `FOI_TEXT` columns

**Example**:

```python
# Old way (more verbose)
results = db.query_device(device_name='thrombectomy')
keys = results['MDR_REPORT_KEY'].tolist()
narratives = db.get_narratives(keys)

# New way (cleaner)
results = db.query_device(device_name='thrombectomy')
narratives = db.get_narratives_for(results)
```

**Implementation Note**: This method is implemented in `analysis_helpers` module. For direct access: `from pymaude import analysis_helpers`

**Related**: `get_narratives()`, `query_device()`

---

#### `trends_for(results_df)`

Get yearly trends for a query result DataFrame.

Analyzes the provided DataFrame to compute yearly event counts and breakdowns by event type.

**Parameters**:
- `results_df` (DataFrame): DataFrame with `DATE_RECEIVED` and `EVENT_TYPE` columns

**Returns**: pandas.DataFrame with columns: `year`, `event_count`, `deaths`, `injuries`, `malfunctions`

**Example**:

```python
# Query for specific device
results = db.query_device(device_name='pacemaker')

# Get trends just for these results
trends = db.trends_for(results)
print(trends)
#    year  event_count  deaths  injuries  malfunctions
# 0  2020          150       5        45           100
# 1  2021          165       7        52           106
```

**Implementation Note**: This method is implemented in `analysis_helpers` module.

**Related**: `get_trends_by_year()`, `query_device()`

---

#### `event_type_breakdown_for(results_df)`

Get event type breakdown for a query result DataFrame.

Provides summary statistics of event types in the provided DataFrame.

**Parameters**:
- `results_df` (DataFrame): DataFrame with `EVENT_TYPE` column

**Returns**: dict with counts:
```python
{
    'total': int,           # Total events
    'deaths': int,          # Events with Death
    'injuries': int,        # Events with Injury
    'malfunctions': int,    # Events with Malfunction
    'other': int           # Events not in above categories
}
```

**Example**:

```python
results = db.query_device(device_name='thrombectomy')
breakdown = db.event_type_breakdown_for(results)

print(f"Total: {breakdown['total']}")
print(f"Deaths: {breakdown['deaths']} ({breakdown['deaths']/breakdown['total']*100:.1f}%)")
print(f"Injuries: {breakdown['injuries']}")
print(f"Malfunctions: {breakdown['malfunctions']}")
```

**Notes**:
- Event types are not mutually exclusive (one event can have multiple types)
- `other` is approximate since events can have multiple types

**Implementation Note**: This method is implemented in `analysis_helpers` module.

**Related**: `query_device()`

---

#### `top_manufacturers_for(results_df, n=10)`

Get top manufacturers from a query result DataFrame.

**Parameters**:
- `results_df` (DataFrame): DataFrame with `MANUFACTURER_D_NAME` column
- `n` (int, default=10): Number of top manufacturers to return

**Returns**: pandas.DataFrame with columns: `manufacturer`, `event_count`

**Example**:

```python
results = db.query_device(device_name='pacemaker')
top_5 = db.top_manufacturers_for(results, n=5)

print("Top 5 Manufacturers:")
for idx, row in top_5.iterrows():
    print(f"{idx+1}. {row['manufacturer']}: {row['event_count']} events")
```

**Implementation Note**: This method is implemented in `analysis_helpers` module.

**Related**: `query_device()`

---

#### `date_range_summary_for(results_df)`

Get date range summary for a query result DataFrame.

**Parameters**:
- `results_df` (DataFrame): DataFrame with `DATE_RECEIVED` column

**Returns**: dict with:
```python
{
    'first_date': str,      # First event date (YYYY-MM-DD)
    'last_date': str,       # Last event date (YYYY-MM-DD)
    'total_days': int,      # Days between first and last
    'total_records': int    # Total records
}
```

**Example**:

```python
results = db.query_device(device_name='catheter')
summary = db.date_range_summary_for(results)

print(f"Data spans {summary['total_days']} days")
print(f"From {summary['first_date']} to {summary['last_date']}")
print(f"Total records: {summary['total_records']:,}")
```

**Implementation Note**: This method is implemented in `analysis_helpers` module.

**Related**: `query_device()`

---

### Analysis Helper Methods

These convenience methods are available via `db.method_name()` and are implemented in the `analysis_helpers` module. They operate on DataFrames returned by query methods to reduce boilerplate code in analysis notebooks. For direct access to the module: `from pymaude import analysis_helpers`

---

#### Multi-Device Analysis

##### `query_multiple_devices(device_names, start_date=None, end_date=None, deduplicate=True, brand_column='query_brand')`

Query multiple device brands and combine results.

**Parameters**:
- `device_names` (list): List of device names to query
- `start_date` (str, optional): Start date filter (YYYY-MM-DD)
- `end_date` (str, optional): End date filter (YYYY-MM-DD)
- `deduplicate` (bool, default=True): Remove duplicate MDR_REPORT_KEYs
- `brand_column` (str, default='query_brand'): Column name to track which brand matched

**Returns**: DataFrame with additional columns:
- `{brand_column}`: Which search term found this report
- `all_matching_brands`: List of all brands that matched (if deduplicated)

**Examples**:

```python
# Query multiple venous stent brands
brands = ['Venovo', 'Vici', 'Zilver Vena', 'Wallstent', 'Abre', 'Duo']
results = db.query_multiple_devices(
    brands,
    start_date='2019-01-01',
    end_date='2024-12-31'
)

print(f"Total reports: {len(results)}")
print(results['query_brand'].value_counts())

# Check for reports matching multiple brands
multi_brand = results[results['all_matching_brands'].apply(len) > 1]
print(f"Reports matching multiple brands: {len(multi_brand)}")
```

**Notes**:
- Automatically deduplicates by MDR_REPORT_KEY (keeps first occurrence)
- Tracks which brands matched each report before deduplication
- More efficient than manual looping and concatenation
- Prints progress if `verbose=True`

**Related**: `query_device()`, `standardize_brand_names()`

---

##### `query_device_catalog(device_catalog, start_date=None, end_date=None)`

Query multiple devices from a catalog with multiple search terms per device.

This helper allows you to efficiently search for a list of devices where each device may have multiple brand names, generic names, and/or PMN/PMA numbers. Ideal for comparative studies where you have a structured list of devices to analyze (e.g., from a product comparison table).

**Parameters**:
- `device_catalog` (list): List of dicts with device search criteria:
  ```python
  [
      {
          'device_id': 'CLEANER_XT',  # Your identifier
          'search_terms': ['CLEANER XT', 'Cleaner 9mm'],  # Brand/generic names
          'pma_pmn_numbers': ['P180037'],  # Optional PMN/PMA numbers
      },
      ...
  ]
  ```
- `start_date` (str, optional): Start date filter (YYYY-MM-DD)
- `end_date` (str, optional): End date filter (YYYY-MM-DD)

**Returns**: DataFrame with all matching reports plus additional columns:
- `device_id`: Your identifier from the catalog
- `matched_via`: Which search term or PMN found this report
- All columns from master and device tables

**Examples**:

```python
# Define device catalog (e.g., from a thrombectomy device comparison table)
devices = [
    {
        'device_id': 'CLEANER_XT',
        'search_terms': ['CLEANER XT'],
        'pma_pmn_numbers': ['P180037']
    },
    {
        'device_id': 'ANGIOJET_ZELANTE',
        'search_terms': ['AngioJet Zelante', 'Zelante DVT'],
        'pma_pmn_numbers': []  # None available
    },
    {
        'device_id': 'INARI_FLOWTRIEVER',
        'search_terms': ['FlowTriever', 'Inari FlowTriever'],
        'pma_pmn_numbers': ['P180013']
    },
]

# Query all devices at once
results = db.query_device_catalog(
    devices,
    start_date='2019-01-01',
    end_date='2024-12-31'
)

# Analyze by device
print(f"Total reports: {len(results)}")
print("\nBreakdown by device:")
print(results.groupby('device_id').size())

# See which search terms found each report
print("\nSample of matched results:")
print(results[['device_id', 'matched_via', 'BRAND_NAME', 'DATE_RECEIVED']].head(10))

# Get event type breakdown per device
for device_id in results['device_id'].unique():
    device_data = results[results['device_id'] == device_id]
    breakdown = db.event_type_breakdown_for(device_data)
    print(f"\n{device_id}: {breakdown}")
```

**Notes**:
- Search terms use partial, case-insensitive matching (SQL LIKE `%term%`)
- Reports matching multiple search terms for the same device are deduplicated
- Reports matching different devices appear once per device
- PMN/PMA searches are exact matches
- More efficient than manual looping through devices
- Prints progress if `verbose=True`

**Use Cases**:
- Comparative device studies with structured device lists
- Analyzing devices from product specification tables
- Research where PMN/PMA numbers are available but sparse
- Systematic review of multiple related devices

**Related**: `query_multiple_devices()`, `query_device()`

---

#### Data Enrichment Methods

These methods join additional MAUDE tables to query results.

##### `enrich_with_problems(results_df)`

Join device problem codes to query results.

**Parameters**:
- `results_df` (DataFrame): Results from `query_device()` or similar

**Returns**: DataFrame with problem columns joined:
- `DEVICE_SEQUENCE_NUMBER`: Device sequence in report
- `DEVICE_PROBLEM_CODE`: FDA problem code

**Raises**:
- `ValueError`: If `problems` table not loaded in database

**Examples**:

```python
# Query devices and get problem codes
results = db.query_device(device_name='thrombectomy', start_date='2020-01-01')
enriched = db.enrich_with_problems(results)

# Analyze problem codes
print(f"Unique problem codes: {enriched['DEVICE_PROBLEM_CODE'].nunique()}")
print(enriched['DEVICE_PROBLEM_CODE'].value_counts().head(10))

# Export for manual categorization
enriched[['MDR_REPORT_KEY', 'DEVICE_PROBLEM_CODE']].to_csv('problem_codes.csv')
```

**Notes**:
- Requires `problems` table: `db.add_years(years, tables=['problems'], download=True)`
- Problems table only available from 2019 onwards
- Left join preserves all original rows (adds NaN for reports without problem codes)
- One MDR may have multiple problem codes (result has more rows than input)

**Related**: `enrich_with_patient_data()`, `enrich_with_narratives()`

---

##### `enrich_with_patient_data(results_df)`

Join patient outcome data to query results.

**Parameters**:
- `results_df` (DataFrame): Results from `query_device()` or similar

**Returns**: DataFrame with patient table columns joined, including:
- `PATIENT_SEQUENCE_NUMBER`: Patient sequence in report
- `SEQUENCE_NUMBER_OUTCOME`: Raw outcome codes (semicolon-separated)
- `outcome_codes`: Parsed list of outcome codes
- `PATIENT_AGE`, `PATIENT_SEX`, etc.

**Raises**:
- `ValueError`: If `patient` table not loaded in database

**Examples**:

```python
# Query and enrich with patient data
results = db.query_device(device_name='stent')
enriched = db.enrich_with_patient_data(results)

# Check outcome codes
print("Outcome code frequency:")
all_codes = [code for codes in enriched['outcome_codes'] for code in codes]
print(pd.Series(all_codes).value_counts())

# Filter to deaths
deaths = enriched[enriched['outcome_codes'].apply(lambda x: 'D' in x if x else False)]
print(f"Reports involving death: {len(deaths.drop_duplicates('MDR_REPORT_KEY'))}")
```

**Outcome Codes**:
- `D` = Death
- `L` = Life threatening
- `H` = Hospitalization
- `S` = Disability
- `C` = Congenital Anomaly
- `R` = Required Intervention
- `O` = Other

**Notes**:
- Requires `patient` table: `db.add_years(years, tables=['patient'], download=True)`
- Reports without patient records have NaN values
- One report may have multiple patient records
- Outcome codes are parsed from semicolon-separated strings into lists

**Related**: `enrich_with_problems()`, `event_type_breakdown_for()`

---

##### `enrich_with_narratives(results_df)`

Join event narrative text to query results.

**Parameters**:
- `results_df` (DataFrame): Results from `query_device()` or similar

**Returns**: DataFrame with narrative column joined:
- `FOI_TEXT`: Event narrative description

**Raises**:
- `ValueError`: If `text` table not loaded in database

**Examples**:

```python
# Get narratives for analysis
results = db.query_device(device_name='catheter', start_date='2023-01-01')
with_text = db.enrich_with_narratives(results)

# Review serious events
serious = with_text[with_text['EVENT_TYPE'].str.contains('Death|Injury', na=False)]
for idx, row in serious.head(5).iterrows():
    print(f"\\nReport {row['MDR_REPORT_KEY']}:")
    print(row['FOI_TEXT'][:500])

# Export for categorization
with_text[['MDR_REPORT_KEY', 'FOI_TEXT']].to_csv('narratives_for_coding.csv')
```

**Notes**:
- Requires `text` table: `db.add_years(years, tables=['text'], download=True)`
- Not all reports have narratives
- Some narratives may be redacted for privacy
- Left join preserves all original rows

**Related**: `get_narratives()`, `get_narratives_for()`

---

#### Event Deduplication Methods

##### `count_unique_events(results_df, event_key_col='EVENT_KEY')`

Count unique events vs total reports to detect duplication.

**Critical Context**: Multiple sources can report the same adverse event, creating multiple MDR_REPORT_KEYs with the same EVENT_KEY. Counting by MDR_REPORT_KEY overcounts events by ~8%.

**Parameters**:
- `results_df` (DataFrame): Query results containing EVENT_KEY column
- `event_key_col` (str, default='EVENT_KEY'): Column name for EVENT_KEY

**Returns**: dict with keys:
- `total_reports` (int): Total number of reports (MDR_REPORT_KEYs)
- `unique_events` (int): Number of unique EVENT_KEYs
- `duplication_rate` (float): Percentage of reports that are duplicates
- `multi_report_events` (list): EVENT_KEYs with multiple reports

**Examples**:

```python
# Check duplication rate in your results
results = db.query_device(device_name='pacemaker', start_date='2020-01-01')
duplication = db.count_unique_events(results)

print(f"Total reports: {duplication['total_reports']}")
print(f"Unique events: {duplication['unique_events']}")
print(f"Duplication: {duplication['duplication_rate']:.1f}%")

# Decide whether to deduplicate
if duplication['duplication_rate'] > 5:
    print(f"⚠️ {duplication['duplication_rate']:.1f}% duplication detected")
    results = db.select_primary_report(results)
```

**Notes**:
- Essential for epidemiological analysis and event counting
- ~8% duplication rate is typical across MAUDE
- Use before calculating incidence rates or event counts

**Related**: `detect_multi_report_events()`, `select_primary_report()`

---

##### `detect_multi_report_events(results_df, event_key_col='EVENT_KEY')`

Identify which events have multiple reports (different sources reporting same event).

**Parameters**:
- `results_df` (DataFrame): Query results containing EVENT_KEY column
- `event_key_col` (str, default='EVENT_KEY'): Column name for EVENT_KEY

**Returns**: DataFrame with columns:
- `EVENT_KEY` (str): Event identifier
- `report_count` (int): Number of reports for this event
- `mdr_report_keys` (list): List of MDR_REPORT_KEYs for this event

**Examples**:

```python
# Identify duplicated events
results = db.query_device(device_name='stent', start_date='2023-01-01')
multi_reports = db.detect_multi_report_events(results)

print(f"Found {len(multi_reports)} events with multiple reports")

# Examine most-reported events
top_duplicates = multi_reports.sort_values('report_count', ascending=False).head(10)
print(top_duplicates)

# Investigate specific event
event_of_interest = multi_reports[multi_reports['report_count'] >= 5]
for idx, row in event_of_interest.iterrows():
    print(f"EVENT_KEY {row['EVENT_KEY']} has {row['report_count']} reports:")
    print(f"  MDR_REPORT_KEYs: {', '.join(row['mdr_report_keys'][:5])}")
```

**Notes**:
- Useful for understanding reporting patterns
- High report counts may indicate serious events
- Can identify manufacturer vs user facility reporting differences

**Related**: `count_unique_events()`, `select_primary_report()`

---

##### `select_primary_report(results_df, event_key_col='EVENT_KEY', strategy='first_received')`

When multiple reports exist for same event, select one primary report per event.

**Parameters**:
- `results_df` (DataFrame): Query results containing EVENT_KEY column
- `event_key_col` (str, default='EVENT_KEY'): Column name for EVENT_KEY
- `strategy` (str, default='first_received'): Selection strategy
  - `'first_received'`: Select earliest DATE_RECEIVED (chronologically first report)
  - `'manufacturer'`: Prefer manufacturer reports (REPORT_SOURCE_CODE='Manufacturer')
  - `'most_complete'`: Select report with most non-null fields (most detailed)

**Returns**: DataFrame with one row per unique EVENT_KEY (deduplicated)

**Examples**:

```python
# Deduplicate to earliest report per event
results = db.query_device(device_name='catheter', start_date='2022-01-01')
deduplicated = db.select_primary_report(results, strategy='first_received')
print(f"Reduced from {len(results)} reports to {len(deduplicated)} unique events")

# Prefer manufacturer reports (usually more detailed)
mfr_primary = db.select_primary_report(results, strategy='manufacturer')

# Select most complete reports (for narrative analysis)
complete_primary = db.select_primary_report(results, strategy='most_complete')

# Compare before/after deduplication
print(f"Original: {len(results)} reports")
print(f"Deduplicated: {len(deduplicated)} events")
print(f"Reduction: {(1 - len(deduplicated)/len(results))*100:.1f}%")
```

**Notes**:
- Essential for accurate event counting in epidemiological studies
- Choice of strategy depends on analysis goal:
  - `first_received`: Temporal studies, signal detection
  - `manufacturer`: Detailed device information needed
  - `most_complete`: Qualitative analysis, narrative review
- Preserves all columns from selected report

**Related**: `count_unique_events()`, `detect_multi_report_events()`, `compare_report_vs_event_counts()`

---

##### `compare_report_vs_event_counts(results_df, event_key_col='EVENT_KEY', group_by=None)`

Compare counting by reports vs events to quantify overcounting.

**Parameters**:
- `results_df` (DataFrame): Query results containing EVENT_KEY column
- `event_key_col` (str, default='EVENT_KEY'): Column name for EVENT_KEY
- `group_by` (str, optional): Column to group by (e.g., 'year', 'EVENT_TYPE')

**Returns**: DataFrame with columns:
- `[group_by]`: Grouping column (if specified)
- `report_count` (int): Count of MDR_REPORT_KEYs
- `event_count` (int): Count of unique EVENT_KEYs
- `inflation_pct` (float): Percentage overcounting from using report_count

**Examples**:

```python
# Overall comparison
results = db.query_device(device_name='venous stent')
comparison = db.compare_report_vs_event_counts(results)
print(comparison)
#    report_count  event_count  inflation_pct
# 0          2156         1998           7.9%

# Compare by year
results['year'] = pd.to_datetime(results['DATE_RECEIVED']).dt.year
yearly = db.compare_report_vs_event_counts(results, group_by='year')
print(yearly)
#    year  report_count  event_count  inflation_pct
# 0  2019           245          228           7.5
# 1  2020           389          361           7.8
# 2  2021           512          471           8.7

# Compare by event type
comparison_by_type = db.compare_report_vs_event_counts(results, group_by='EVENT_TYPE')
print(comparison_by_type)
```

**Notes**:
- Demonstrates importance of EVENT_KEY deduplication
- Inflation typically 5-10% but varies by device type
- Use to justify deduplication in methods section of papers
- Can reveal temporal trends in reporting duplication

**Related**: `count_unique_events()`, `select_primary_report()`

---

#### Patient Data Quality Methods

##### `detect_multi_patient_reports(patient_df)`

Detect reports with multiple patients (potential outcome concatenation issue).

**Critical Context**: When multiple patients are in a report, OUTCOME and TREATMENT fields concatenate sequentially across patients, causing serious overcounting if not handled properly.

**Parameters**:
- `patient_df` (DataFrame): Patient data from `enrich_with_patient_data()`

**Returns**: dict with keys:
- `total_reports` (int): Total unique MDR_REPORT_KEYs
- `multi_patient_reports` (int): Count of reports with >1 patient
- `affected_percentage` (float): % of reports affected
- `affected_mdr_keys` (list): MDR_REPORT_KEYs with multiple patients

**Examples**:

```python
# Check for concatenation issues
results = db.query_device(device_name='catheter', start_date='2023-01-01')
enriched = db.enrich_with_patient_data(results)
validation = db.detect_multi_patient_reports(enriched)

print(f"Total reports: {validation['total_reports']}")
print(f"Multi-patient reports: {validation['multi_patient_reports']}")
print(f"Affected: {validation['affected_percentage']:.1f}%")

if validation['affected_percentage'] > 10:
    print("⚠️ High multi-patient rate - use count_unique_outcomes_per_report()")
    print("   for accurate outcome counting")

# Examine specific multi-patient reports
multi_patient_keys = validation['affected_mdr_keys'][:5]
examples = enriched[enriched['MDR_REPORT_KEY'].isin(multi_patient_keys)]
print(examples[['MDR_REPORT_KEY', 'PATIENT_SEQUENCE_NUMBER', 'SEQUENCE_NUMBER_OUTCOME']])
```

**Notes**:
- Essential before analyzing patient outcomes
- Percentage varies by device type (typically 5-20%)
- Multi-patient reports often involve multi-patient procedures or devices
- See docs/maude_overview.md for detailed explanation of concatenation issue

**Related**: `count_unique_outcomes_per_report()`, `enrich_with_patient_data()`

---

##### `count_unique_outcomes_per_report(patient_df, outcome_col='SEQUENCE_NUMBER_OUTCOME')`

Count unique outcome codes per report, preventing inflation from concatenation.

**Critical Context**: Patient OUTCOME fields concatenate across patients in multi-patient reports. This function counts each outcome code ONCE per report, regardless of concatenation.

**Parameters**:
- `patient_df` (DataFrame): Patient data with SEQUENCE_NUMBER_OUTCOME column
- `outcome_col` (str, default='SEQUENCE_NUMBER_OUTCOME'): Column name for outcomes

**Returns**: DataFrame with columns:
- `MDR_REPORT_KEY` (str): Report identifier
- `patient_count` (int): Number of patients in this report
- `unique_outcomes` (list): Unique outcome codes for this report
- `outcome_counts` (dict): Count of each outcome code (all 1 for unique per report)

**Examples**:

```python
# Safe outcome counting
results = db.query_device(device_name='stent', start_date='2022-01-01')
patient_data = db.enrich_with_patient_data(results)
outcome_summary = db.count_unique_outcomes_per_report(patient_data)

# Count reports with deaths (avoiding concatenation inflation)
deaths = (outcome_summary['unique_outcomes'].apply(lambda x: 'D' in x)).sum()
print(f"Reports with at least one death: {deaths}")

# Count reports with hospitalizations
hosp = (outcome_summary['unique_outcomes'].apply(lambda x: 'H' in x)).sum()
print(f"Reports with hospitalization: {hosp}")

# Analyze outcome patterns
outcome_summary['outcome_str'] = outcome_summary['unique_outcomes'].apply(
    lambda x: ';'.join(sorted(x)) if x else 'None'
)
print("\\nMost common outcome patterns:")
print(outcome_summary['outcome_str'].value_counts().head(10))

# Compare with naive counting (demonstrates inflation)
naive_count = patient_data['SEQUENCE_NUMBER_OUTCOME'].str.contains('D', na=False).sum()
correct_count = deaths
print(f"\\nNaive death count: {naive_count}")
print(f"Correct death count: {correct_count}")
print(f"Inflation: {(naive_count/correct_count - 1)*100:.1f}%")
```

**Notes**:
- **Essential for accurate outcome analysis** - naive counting inflates by 2-3x
- Outcome codes: D=Death, S=Serious Injury, I=Injury, M=Malfunction, etc.
- Handles semicolon-separated lists and strips whitespace
- Preserves report-level granularity (one row per MDR_REPORT_KEY)
- See Ensign & Cohen (2017) for detailed explanation of this data quality issue

**Related**: `detect_multi_patient_reports()`, `enrich_with_patient_data()`

---

#### Summary and Aggregation

##### `summarize_by_brand(results_df, group_column='standard_brand', include_temporal=True)`

Generate comprehensive summary statistics by device brand.

**Parameters**:
- `results_df` (DataFrame): Results from query
- `group_column` (str, default='standard_brand'): Column to group by
- `include_temporal` (bool, default=True): Include yearly breakdowns

**Returns**: dict with:
```python
{
    'counts': dict,            # Total reports per brand
    'event_types': DataFrame,  # Event type breakdown per brand
    'date_range': DataFrame,   # First/last dates per brand
    'temporal': DataFrame      # Yearly counts (if include_temporal=True)
}
```

**Examples**:

```python
# Multi-device study summary
brands = ['Venovo', 'Vici', 'Zilver Vena']
results = db.query_multiple_devices(brands, start_date='2019-01-01')
results = db.standardize_brand_names(results, {'venovo': 'Venovo', 'vici': 'Vici', 'zilver': 'Zilver Vena'})

summary = db.summarize_by_brand(results)

# View counts
print("Reports by brand:")
for brand, count in summary['counts'].items():
    print(f"  {brand}: {count}")

# Export summary tables
summary['temporal'].to_csv('table_temporal_trends.csv')
summary['event_types'].to_csv('table_event_types.csv')
```

**Notes**:
- Requires `group_column` to exist (use `standardize_brand_names()` first)
- Handles missing columns gracefully (skips event_types if EVENT_TYPE missing)
- Useful for generating manuscript tables

**Related**: `query_multiple_devices()`, `standardize_brand_names()`

---

#### Brand Name Standardization

##### `find_brand_variations(search_terms, max_results=50)`

Find all brand name variations in database.

**Parameters**:
- `search_terms` (str or list): Search term(s) to find variations for
- `max_results` (int, default=50): Maximum variations to return

**Returns**: DataFrame with columns:
- `BRAND_NAME`: Actual brand name in database
- `count`: Number of reports with this brand name
- `sample_mdr_keys`: Sample report keys (comma-separated)

**Examples**:

```python
# Discover all "Venovo" variations
variations = db.find_brand_variations('venovo')
print(variations)
#            BRAND_NAME  count  sample_mdr_keys
# 0              VENOVO    234  1234567, 1234568, ...
# 1              Venovo    123  9876543, 9876544, ...
# 2  Venovo Venous Stent   45  5555555, 5555556, ...
```

**Notes**:
- Case-insensitive search
- Uses SQL LIKE with wildcards (partial matching)
- Ordered by frequency (most common first)
- Useful before standardization to understand naming inconsistencies

**Related**: `standardize_brand_names()`, `query_multiple_devices()`

---

##### `standardize_brand_names(results_df, mapping_dict, source_col='BRAND_NAME', target_col='standard_brand')`

Standardize brand names using a mapping dictionary.

**Parameters**:
- `results_df` (DataFrame): DataFrame with brand names
- `mapping_dict` (dict): Mapping from patterns to standard names
- `source_col` (str, default='BRAND_NAME'): Column with original names
- `target_col` (str, default='standard_brand'): New column for standardized names

**Returns**: DataFrame with new `{target_col}` column

**Examples**:

```python
# Create standardization mapping
mapping = {
    'venovo': 'Venovo',
    'vici': 'Vici',
    'zilver': 'Zilver Vena'
}

# Apply standardization
results = db.query_multiple_devices(['Venovo', 'VICI', 'Zilver Vena'])
results = db.standardize_brand_names(results, mapping)

# Use standardized names for analysis
summary = db.summarize_by_brand(results, group_column='standard_brand')
```

**Notes**:
- Case-insensitive pattern matching
- First matching pattern wins (order mapping dict carefully)
- Preserves original brand name if no pattern matches
- NaN values remain NaN

**Related**: `find_brand_variations()`, `query_multiple_devices()`

---

#### Statistical Analysis

##### `create_contingency_table(results_df, row_var, col_var, normalize=False)`

Create contingency table for chi-square analysis.

**Parameters**:
- `results_df` (DataFrame): Results with categorical variables
- `row_var` (str): Row variable (e.g., 'standard_brand')
- `col_var` (str): Column variable (e.g., 'problem_category')
- `normalize` (bool, default=False): If True, also return percentages

**Returns**: DataFrame if `normalize=False`, or dict with 'counts' and 'percentages' DataFrames

**Examples**:

```python
# Create table with percentages
table = db.create_contingency_table(
    enriched,
    row_var='standard_brand',
    col_var='problem_category',
    normalize=True
)

print("Counts:")
print(table['counts'])
print("\\nPercentages:")
print(table['percentages'])

# Export for manuscript
table['counts'].to_csv('table_device_problems_counts.csv')
table['percentages'].to_csv('table_device_problems_percentages.csv')
```

**Notes**:
- Uses `pd.crosstab()` internally
- Percentages are row-wise (sum to 100% per row)
- Missing combinations appear as 0

**Related**: `chi_square_test()`, `summarize_by_brand()`

---

##### `chi_square_test(results_df, row_var, col_var, exclude_cols=None)`

Perform chi-square test of independence on categorical variables.

**Parameters**:
- `results_df` (DataFrame): Results with categorical variables
- `row_var` (str): Row variable for contingency table
- `col_var` (str): Column variable for contingency table
- `exclude_cols` (list, optional): Column values to exclude

**Returns**: dict with:
```python
{
    'chi2_statistic': float,
    'p_value': float,
    'dof': int,
    'expected_frequencies': DataFrame,
    'significant': bool  # True if p < 0.05
}
```

**Examples**:

```python
# Test if problem distributions differ by brand
chi2_result = db.chi_square_test(
    enriched,
    row_var='standard_brand',
    col_var='problem_category',
    exclude_cols=['Uncategorized']
)

print(f"Chi-square: {chi2_result['chi2_statistic']:.2f}")
print(f"p-value: {chi2_result['p_value']:.6f}")
print(f"Significant: {chi2_result['significant']}")
```

**Notes**:
- Uses `scipy.stats.chi2_contingency()`
- Assumes independent observations
- Check expected frequencies (should be ≥5 for validity)

**Related**: `create_contingency_table()`, `event_type_comparison()`

---

##### `event_type_comparison(results_df, group_var='standard_brand')`

Compare event type distributions across groups with statistical tests.

**Parameters**:
- `results_df` (DataFrame): Results with EVENT_TYPE column
- `group_var` (str, default='standard_brand'): Variable to compare across

**Returns**: dict with:
```python
{
    'counts': DataFrame,       # Event counts by group
    'percentages': DataFrame,  # Percentage of each event type
    'chi2_test': dict,         # Chi-square test results
    'summary': str            # Formatted summary text
}
```

**Examples**:

```python
# Compare event severity across devices
comparison = db.event_type_comparison(results, group_var='standard_brand')

print(comparison['summary'])
# Output:
# Event Type Comparison by standard_brand
# ======================================
# Chi-square: 45.23 (p=0.0001)
# Device A: 4.5% deaths, 30.2% injuries, 65.3% malfunctions
# Device B: 2.0% deaths, 50.1% injuries, 47.9% malfunctions
```

**Notes**:
- Automatically handles FDA event type abbreviations (D, IN, M)
- Events can have multiple types
- Compares serious events (Death/Injury) vs. Malfunction patterns

**Related**: `chi_square_test()`, `event_type_breakdown_for()`

---

#### Visualization Methods

These methods generate publication-ready figures using matplotlib.

##### `plot_temporal_trends(summary_dict, output_file=None, figsize=(12, 6), **kwargs)`

Generate temporal trend figure from summarize_by_brand() output.

**Parameters**:
- `summary_dict` (dict): Output from `summarize_by_brand()`
- `output_file` (str, optional): Path to save figure
- `figsize` (tuple, default=(12, 6)): Figure size in inches
- `**kwargs`: Additional matplotlib customization

**Returns**: matplotlib Figure and Axes objects

**Examples**:

```python
# Generate temporal trend figure
summary = db.summarize_by_brand(results, include_temporal=True)
fig, ax = db.plot_temporal_trends(
    summary,
    output_file='figure1_temporal_trends.png',
    title='Annual MAUDE Reports for Venous Stents (2019-2024)'
)
```

**Notes**:
- Requires `temporal` key in summary_dict
- DPI=300 recommended for publication quality
- Grid enabled by default

**Related**: `summarize_by_brand()`, `plot_problem_distribution()`

---

##### `plot_problem_distribution(contingency_table, output_file=None, stacked=True, **kwargs)`

Generate stacked bar chart for problem distribution analysis.

**Parameters**:
- `contingency_table` (DataFrame): From `create_contingency_table()` with normalize=True
- `output_file` (str, optional): Path to save figure
- `stacked` (bool, default=True): Create stacked vs. grouped bars
- `**kwargs`: Additional matplotlib customization

**Returns**: matplotlib Figure and Axes objects

**Examples**:

```python
# Create device problem distribution figure
table = db.create_contingency_table(
    enriched,
    row_var='standard_brand',
    col_var='problem_category',
    normalize=True
)

fig, ax = db.plot_problem_distribution(
    table['percentages'],
    output_file='figure2_device_problems.png',
    title='Device Problem Distribution'
)
```

**Notes**:
- Input should be percentages for better comparison
- Stacked bars show relative distribution (sum to 100%)

**Related**: `create_contingency_table()`, `export_publication_figures()`

---

##### `export_publication_figures(results_df, output_dir, prefix='figure', formats=['png', 'pdf'], **kwargs)`

Batch export all standard manuscript figures.

**Parameters**:
- `results_df` (DataFrame): Results from multi-device query
- `output_dir` (str): Directory for figure outputs
- `prefix` (str, default='figure'): Filename prefix
- `formats` (list, default=['png', 'pdf']): Output formats
- `**kwargs`: Passed to individual plot functions

**Returns**: dict mapping figure names to file paths

**Examples**:

```python
# Generate all manuscript figures at once
figures = db.export_publication_figures(
    results,
    output_dir='./figures',
    prefix='venous_stents',
    formats=['png', 'pdf']
)

print("Generated figures:")
for name, paths in figures.items():
    print(f"  {name}: {paths}")
```

**Figures Generated**:
1. Temporal trends (line chart)
2. Device problem distribution (stacked bar)
3. Patient outcome distribution (stacked bar, if patient data available)
4. Event type comparison (grouped bar)

**Notes**:
- Creates output directory if doesn't exist
- High-resolution (DPI=300) for publication
- Both PNG and PDF formats recommended

**Related**: `plot_temporal_trends()`, `plot_problem_distribution()`

---

### Export & Utilities

#### `export_subset(output_file, **filters)`

Export filtered device data to CSV file.

**Parameters**:
- `output_file` (str): Path for output CSV file
- `**filters`: Keyword arguments passed to `query_device()`

**Returns**: None (writes file)

**Examples**:

```python
# Export all pacemaker events
db.export_subset('pacemakers.csv', device_name='pacemaker')

# Export with date filter
db.export_subset(
    'recent_stents.csv',
    device_name='stent',
    start_date='2020-01-01'
)

# Export by product code
db.export_subset('catheters.csv', product_code='NIQ')
```

**Notes**:
- Accepts same filters as `query_device()`
- Creates CSV with all columns from master + device tables
- Prints record count if `verbose=True`
- Overwrites existing files

**Related**: `query_device()`

---

#### `info()`

Print summary statistics about the database.

**Parameters**: None

**Returns**: None (prints to console)

**Example**:

```python
db = MaudeDatabase('maude.db')
db.info()
```

**Output**:
```
Database: maude.db
============================================================
device          423,891 records
text            156,234 records

Date range: 2018-01-05 to 2020-12-31
Database size: 0.15 GB
```

**Notes**:
- Shows all tables present
- Record counts for each table
- Date range (if master table exists)
- Database file size
- Use to verify downloads completed

**Related**: `add_years()`

---

### Internal Methods (Advanced)

These methods are typically used internally but can be called directly for advanced use cases.

#### `_parse_year_range(year_str)`

Convert year specification to list of integers.

**Parameters**:
- `year_str` (int, list, or str): Year specification

**Returns**: List of year integers

**Examples**:
```python
db._parse_year_range(2020)          # [2020]
db._parse_year_range([2018, 2020])  # [2018, 2020]
db._parse_year_range('2018-2020')   # [2018, 2019, 2020]
db._parse_year_range('latest')      # [2024] (or current - 1)
```

---

#### `_make_file_path(table, year, data_dir='./maude_data')`

Find path to MAUDE data file.

**Parameters**:
- `table` (str): Table name ('master', 'device', 'text', 'patient')
- `year` (int): Year
- `data_dir` (str): Directory containing data files

**Returns**:
- File path (str) if exists
- `False` if not found

**Example**:
```python
path = db._make_file_path('device', 2020, './maude_data')
if path:
    print(f"Found: {path}")
```

---

#### `_download_file(year, file_prefix, data_dir='./maude_data')`

Download and extract MAUDE file from FDA.

**Parameters**:
- `year` (int): Year to download
- `file_prefix` (str): File type ('mdrfoi', 'foidev', 'foitext', 'patient')
- `data_dir` (str): Directory to save files

**Returns**:
- `True` if successful
- `False` if download failed

**Example**:
```python
success = db._download_file(2020, 'foidev', './maude_data')
if success:
    print("Download complete")
```

---

#### `_check_file_exists(year, file_prefix)`

Check if file exists on FDA server without downloading.

**Parameters**:
- `year` (int): Year to check
- `file_prefix` (str): File type to check

**Returns**:
- `True` if file exists (HTTP 200)
- `False` otherwise

**Example**:
```python
if db._check_file_exists(2025, 'foidev'):
    print("2025 data is available")
```

---

#### `_get_years_in_db()`

Get list of years currently in database.

**Returns**: List of year integers

**Example**:
```python
years = db._get_years_in_db()
print(f"Database contains: {years}")  # [2018, 2019, 2020]
```

---

#### `_get_latest_available_year()`

Find most recent year available on FDA server.

**Returns**: Year integer

**Example**:
```python
latest = db._get_latest_available_year()
print(f"Latest available: {latest}")
```

---

## Data Types

### pandas.DataFrame

All query methods return pandas DataFrames. Common operations:

```python
# Get first rows
df.head(10)

# Get specific columns
df[['GENERIC_NAME', 'event_type']]

# Filter rows
df[df['event_type'] == 'Death']

# Save to CSV
df.to_csv('output.csv', index=False)

# Count rows
len(df)

# Get column names
df.columns.tolist()
```

---

## Constants

### Table File Mappings

```python
MaudeDatabase.table_files = {
    'master': 'mdrfoi',
    'device': 'foidev',
    'patient': 'patient',
    'text': 'foitext',
    'problems': 'foidevproblem'
}
```

### Base URL

```python
MaudeDatabase.base_url = "https://www.accessdata.fda.gov/MAUDE/ftparea"
```

---

## Common Pitfalls

### Column Name Case

**Problem**: `sqlite3.OperationalError: no such column: generic_name`

**Solution**: Use uppercase for device/text tables:
```python
# Correct
db.query("SELECT GENERIC_NAME FROM device")

# Incorrect
db.query("SELECT generic_name FROM device")
```

### Missing Tables

**Problem**: Querying tables that weren't downloaded

**Solution**: Ensure tables are loaded:
```python
db.add_years(2020, tables=['device', 'text'], download=True)
# Now both device and text tables available
```

### Memory Issues

**Problem**: Out of memory when processing large files

**Solution**: Reduce chunk size:
```python
db.add_years(2020, chunk_size=10000)  # Default is 100000
```

---

**See Also**:
- [Getting Started Guide](getting_started.md) - Tutorial and basic usage
- [Research Guide](research_guide.md) - Research workflows and best practices
- [Troubleshooting](troubleshooting.md) - Solutions to common problems