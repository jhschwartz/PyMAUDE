# API Reference

Complete technical reference for the `PyMAUDE` library.

## Table of Contents

- [MaudeDatabase Class](#maudedatabase-class)
  - [Initialization](#initialization)
  - [Data Management](#data-management)
  - [Querying](#querying)
  - [Device Search (Boolean)](#device-search-boolean)
  - [Helper Query Methods](#helper-query-methods)
  - [Analysis Helper Methods](#analysis-helper-methods)
  - [Export & Utilities](#export--utilities)
  - [Internal Methods](#internal-methods-advanced)
- [Search Refinement Helper Functions](#search-refinement-helper-functions)
- [DeviceSearchStrategy Class](#devicesearchstrategy-class)
- [AdjudicationLog Class](#adjudicationlog-class)
- [Project Generator](#project-generator)
- [Data Types](#data-types)
- [Constants](#constants)
- [Common Pitfalls](#common-pitfalls)

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
# Download single year of device data (RECOMMENDED - use download=True)
db.add_years(1998, tables=['device'], download=True)

# Multiple years, device + text data
db.add_years('2018-2020', tables=['device', 'text'], download=True)

# Strict offline mode - fails if files missing (rarely needed)
db.add_years(2020, tables=['device'], download=False, data_dir='./my_data')

# Strict mode - fail if any file missing
db.add_years([2018, 2019], strict=True, download=True)
```

> **💡 Quick Tip:** Almost always use `download=True`. This enables smart caching: uses local files if available, downloads only what's missing. The `download=False` option is only for strict offline mode (never attempt network activity).

**Notes**:
- **Download and Processing Control**: PyMAUDE provides independent flags for controlling data updates:

  **`download` flag** (default: `False`)
  - Controls whether to allow network downloads from FDA
  - `True`: **Smart behavior** - use cached files if available, download if missing (recommended)
  - `False`: **Strict local-only mode** - never attempt network download, fail if files missing
  - **Most users should always use `download=True`** for normal operation
  - **Only use `download=False` for:** Offline work, testing with pre-downloaded files, or CI/CD pipelines that want explicit failures on missing files rather than automatic downloads

  **`force_download` flag** (default: `False`)
  - Controls download caching behavior when `download=True`
  - `True`: Always download fresh files from FDA, bypassing local zip cache
  - `False`: Use cached local zip files if they exist, download only if missing
  - **Use when:** You suspect FDA has updated their files and want to ensure you get fresh copies
  - Only meaningful when `download=True`
  - **Note:** The common pattern `download=True, force_download=False` already gives you smart behavior: uses cache when available, downloads when missing

  **`force_refresh` flag** (default: `False`)
  - Controls database processing behavior
  - `True`: Re-process files into database, even if checksums match
  - `False`: Skip processing if file checksums haven't changed (smart default)
  - **Use when:** Rebuilding database from existing files (e.g., after corruption)
  - Works with both downloaded and local files

- **Checksum Tracking**: Automatically prevents duplicate data when adding the same year multiple times
  - First run: Processes file and stores SHA256 checksum
  - Subsequent runs:
    - With `force_download=False`: Uses cached zip files
    - Computes checksum of local files
    - Skips processing if checksum unchanged (instant!)
    - Re-processes if FDA updated the file (checksum changed)
  - **Forcing updates:**
    - `force_download=True`: Get fresh files from FDA
    - `force_refresh=True`: Re-process even if unchanged

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

**Common Scenarios**:

```python
# Scenario 1: First download
db.add_years('2020-2024', download=True)
# Downloads new files, processes them

# Scenario 2: Re-run without changes (uses caches efficiently)
db.add_years('2020-2024', download=True)
# Uses cached zip files
# Skips processing (checksums match)
# Instant!

# Scenario 3: Get FDA updates (RECOMMENDED for updates)
db.add_years('2020-2024', download=True, force_download=True)
# Re-downloads files even if cached locally
# Only processes if checksums changed (efficient!)
# Use this when FDA has updated their files

# Scenario 4: Rebuild database from existing files
db.add_years('2020-2024', download=False, force_refresh=True)
# Uses existing local files
# Re-processes everything into database
# Use when database is corrupted or you want to rebuild

# Scenario 5: Fresh start (re-download and rebuild everything)
db.add_years('2020-2024', download=True, force_download=True, force_refresh=True)
# Re-downloads everything from FDA
# Re-processes everything into database
# Nuclear option - rarely needed
```

**Understanding the Flags**:

| Scenario | `download` | `force_download` | `force_refresh` | Result |
|----------|-----------|-----------------|----------------|---------|
| **Normal operation (recommended)** | `True` | `False` | `False` | Uses cached zips, downloads if missing, skips processing if checksums match |
| **Get FDA updates** | `True` | `True` | `False` | Fresh download bypassing cache, processes only if changed |
| **Rebuild database** | `False` | `False` | `True` | Uses existing local files only, re-processes everything |
| **Nuclear option** | `True` | `True` | `True` | Re-downloads and re-processes everything |
| **Offline mode** | `False` | `False` | `False` | Uses existing local files only, skips if checksums match |

**Note:** The rows with `download=False` are for special cases only (offline work, testing, CI/CD). For normal use, always use `download=True`.

**Related**: `update()`, `_download_file()`, `_make_file_path()`

---

#### `update(add_new_years, download=True, force_download=False)`

Update existing years in database with latest FDA data.

**Parameters**:
- `add_new_years` (bool, required keyword-only): If True, also adds any missing years since the most recent year in database. If False, only refreshes existing years.
- `download` (bool, optional): If True, download files from FDA. If False, use local files (default: True)
- `force_download` (bool, optional): If True, re-download from FDA even if files exist locally (default: False). Use when FDA has updated their files. Only has effect when `download=True`.

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

# Force fresh download from FDA (RECOMMENDED for getting FDA updates)
db.update(add_new_years=False, force_download=True)
```

**Notes**:
- Uses checksum tracking to skip files that haven't changed
- Only reprocesses data if FDA has updated source files
- **Getting FDA Updates**: Use `force_download=True` to bypass local zip cache and get fresh files from FDA. Without this flag, cached zip files are used and FDA updates won't be detected.
- When `add_new_years=True`, fills all gaps from max existing year to current year
- Returns early with message if database is empty
- Requires internet connection (unless `download=False`)

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

#### `query_device(brand_name=None, generic_name=None, manufacturer_name=None, device_name_concat=None, product_code=None, pma_pmn=None, start_date=None, end_date=None, deduplicate_events=True)`

Query device events by exact field matching (case-insensitive).

**Purpose**: Precise queries for known device names, manufacturers, or regulatory numbers. For flexible boolean searching, use `search_by_device_names()`.

**Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `brand_name` | str | Exact brand name match (case-insensitive) |
| `generic_name` | str | Exact generic name match (case-insensitive) |
| `manufacturer_name` | str | Exact manufacturer match (case-insensitive) |
| `device_name_concat` | str | Exact match on concatenated name column |
| `product_code` | str | Exact FDA product code |
| `pma_pmn` | str | Exact PMA or PMN number (searches both fields) |
| `start_date` | str | Only events on/after this date ('YYYY-MM-DD') |
| `end_date` | str | Only events on/before this date ('YYYY-MM-DD') |
| `deduplicate_events` | bool | If True, deduplicate by EVENT_KEY (default: True) |

**Returns**: pandas.DataFrame with columns from master + device tables joined

**Examples**:

```python
# Exact brand match
venovo = db.query_device(brand_name='Venovo')

# Exact generic name
stents = db.query_device(generic_name='Venous Stent')

# Exact manufacturer
medtronic = db.query_device(manufacturer_name='Medtronic')

# Product code (as before)
devices = db.query_device(product_code='NIQ')

# PMA/PMN number
pma_devices = db.query_device(pma_pmn='P180037')

# Multiple parameters (AND logic)
specific = db.query_device(
    brand_name='Venovo',
    manufacturer_name='Medtronic'
)

# With date filtering
recent = db.query_device(
    brand_name='Venovo',
    start_date='2020-01-01',
    end_date='2020-12-31'
)
```

**Notes**:
- **Exact matching**: All name parameters use exact case-insensitive matching (not partial/substring)
- **Multiple parameters**: Combine with AND logic
- **At least one required**: Must specify at least one search parameter
- **pma_pmn**: Searches PMA_PMN_NUM field in master table (exact match)
- For partial matching or boolean logic, use `search_by_device_names()`

**Common Patterns**:

```python
# Known brand query
results = db.query_device(brand_name='AngioJet Zelante')

# Manufacturer analysis
all_medtronic = db.query_device(manufacturer_name='Medtronic')

# Regulatory lookup
pma_devices = db.query_device(pma_pmn='K123456')

# Combine exact matches
results = db.query_device(
    generic_name='Thrombectomy Catheter',
    manufacturer_name='Argon Medical'
)
```

**Related**: `query()`, `search_by_device_names()`, `get_trends_by_year()`, `export_subset()`

---

### Device Search (Boolean)

Advanced device search with AND/OR boolean logic. These methods provide more flexible searching than `query_device()`.

#### `create_search_index()`

Create concatenated search column and index for fast boolean device searches.

This is a **one-time operation** that optimizes the database for fast boolean searches. It adds a `DEVICE_NAME_CONCAT` column to the device table (containing BRAND_NAME, GENERIC_NAME, and MANUFACTURER_D_NAME concatenated together) and creates an index on it.

**Parameters**: None

**Returns**: dict with:
- `created` (bool): True if column was created, False if already existed
- `rows_updated` (int): Number of rows updated (if created)
- `time_seconds` (float): Time taken

**Examples**:

```python
# One-time setup
db = MaudeDatabase('maude.db')
db.add_years('2020-2024', tables=['device'], download=True)

# Create search index (do this once)
result = db.create_search_index()
print(f"Indexed {result['rows_updated']:,} devices in {result['time_seconds']:.1f}s")

# Now searches will be much faster
results = db.search_devices(['argon', 'penumbra'])
```

**Notes**:
- This method is **idempotent** - safe to call multiple times
- If column already exists, returns immediately with `created=False`
- Recommended to run after `add_years()` for optimal performance
- Index creation takes ~5-30 seconds for typical database sizes
- Can be skipped - `search_devices()` works without it (but slower)

**Related**: `search_devices()`, `add_years()`

---

#### `search_by_device_names(criteria, start_date=None, end_date=None, deduplicate_events=True, use_concat_column=True, group_column='search_group')`

Search for device events using boolean name matching with optional grouping.

**Purpose**: Flexible partial-match search with AND/OR boolean logic. Ideal for exploratory analysis and comparing device categories. For exact matching on known names, use `query_device()`.

This method provides powerful device searching:
- **Single string**: Simple search for one term
- **List of strings**: OR search (matches ANY term)
- **List of lists**: OR of AND groups (complex boolean logic)
- **Dict**: Grouped search returning results with `search_group` column for comparative analysis

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `criteria` | str, list, list of lists, or dict | Required | Search criteria (see examples below) |
| `start_date` | str | None | Only events on/after this date ('YYYY-MM-DD') |
| `end_date` | str | None | Only events on/before this date ('YYYY-MM-DD') |
| `deduplicate_events` | bool | True | If True, return one row per EVENT_KEY |
| `use_concat_column` | bool | True | Use concatenated search column (faster if `create_search_index()` was called) |
| `group_column` | str | 'search_group' | Column name for group membership (dict input only) |

**Returns**: pandas.DataFrame with matching records
- Dict input: includes `search_group` column tracking group membership
- Non-dict input: no group column

**Examples - Basic Search**:

```python
# Simple single-term search
results = db.search_by_device_names('argon')

# OR search - matches ANY of these terms
results = db.search_by_device_names(['argon', 'penumbra', 'angiojet'])
# Returns devices containing "argon" OR "penumbra" OR "angiojet"

# AND search - both terms must match
results = db.search_by_device_names([['argon', 'cleaner']])
# Returns devices containing BOTH "argon" AND "cleaner"

# Complex boolean: (A AND B) OR C
results = db.search_by_device_names([
    ['argon', 'cleaner'],  # Argon Cleaner devices
    'angiojet'              # OR AngioJet devices
])
# Returns: (argon AND cleaner) OR (angiojet)

# Three-way OR with AND groups
results = db.search_by_device_names([
    ['argon', 'cleaner'],      # Argon Cleaner
    ['boston', 'angiojet'],    # OR Boston AngioJet
    ['penumbra', 'indigo']     # OR Penumbra Indigo
])

# With date filtering
results = db.search_by_device_names(
    [['argon', 'cleaner'], 'angiojet'],
    start_date='2020-01-01',
    end_date='2023-12-31'
)
```

**Examples - Grouped Search (Dict Input)**:

```python
# Grouped search for device comparison
results = db.search_by_device_names({
    'mechanical': [['argon', 'cleaner'], 'angiojet'],
    'aspiration': [['penumbra', 'indigo'], ['penumbra', 'lightning']],
    'other': 'cleaner xt'
})

# Results include search_group column
print(results['search_group'].unique())
# Output: ['mechanical', 'aspiration', 'other']

# Use with helper functions for comparative analysis
summary = db.summarize_by_brand(results)  # Automatically groups by search_group
trends = db.get_trends_by_year(results)    # Includes search_group breakdown
comparison = db.event_type_comparison(results)  # Compares groups

# Custom group column name
results = db.search_by_device_names(
    {'venous': 'venous stent', 'arterial': 'arterial stent'},
    group_column='vessel_type'
)

# With date filtering (applies to all groups)
results = db.search_by_device_names(
    {'g1': 'argon', 'g2': 'penumbra'},
    start_date='2020-01-01'
)
```

**Grouped Search - Overlap Handling**:

When using dict input, events can match multiple groups. PyMAUDE handles this with "first-match-wins" logic:
- Events only appear in the **first matching group** (based on Python dict order)
- Warnings issued per source group: "N events previously matched to 'group_X' were skipped from 'group_Y'"
- Empty groups (0 matches) are absent from returned DataFrame

```python
# Overlapping groups
results = db.search_by_device_names({
    'all_argon': 'argon',
    'cleaner_xt': [['argon', 'cleaner', 'xt']]  # Subset of all_argon
})
# ⚠️ Warning: "X events previously matched to 'all_argon' were skipped from 'cleaner_xt'"
# Cleaner XT devices only appear in 'all_argon' group, not 'cleaner_xt'
```

**Search Logic**:

```python
# Single list = OR all terms
['A', 'B', 'C']  →  A OR B OR C

# List of lists = OR groups, AND within each group
[['A', 'B'], ['C']]  →  (A AND B) OR C

# Complex nested logic
[['A', 'B'], ['C', 'D'], ['E']]  →  (A AND B) OR (C AND D) OR E

# Dict = grouped searches with search_group column
{'group1': ['A', 'B'], 'group2': 'C'}  →  Two separate searches, results tagged with group name
```

**Notes**:
- All searches are **case-insensitive**
- Terms are matched as **substrings** (LIKE %term%)
- Searches across BRAND_NAME, GENERIC_NAME, and MANUFACTURER_D_NAME
- Run `create_search_index()` first for 10-30x better performance
- Empty results return empty DataFrame (not None)
- Special characters (%, _, ', etc.) are automatically escaped

**Performance Tips**:
- Create search index first: `db.create_search_index()`
- Use date filters to reduce result set
- More specific terms = faster searches
- Consider using `deduplicate_events=False` if you need report-level data

**Common Patterns**:

```python
# Device family search (manufacturer + device type)
results = db.search_devices([
    ['argon', 'thrombectomy'],
    ['penumbra', 'thrombectomy']
])

# Exclude pattern (search for A but not B)
# Note: NOT operator not yet supported - filter results afterward
results = db.search_devices('argon')
results = results[~results['BRAND_NAME'].str.contains('BALLOON', case=False, na=False)]

# Count matches without loading all data
results = db.search_devices(['argon', 'penumbra'])
print(f"Found {len(results)} devices")

# Get unique device names
results = db.search_devices(['thrombectomy'])
unique_brands = results['BRAND_NAME'].unique()
```

**Related**: `query_device()`, `create_search_index()`, `get_trends_by_year()`

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

#### `get_trends_by_year(results_df)`

Get year-by-year trends for device events from a results DataFrame.

**Purpose**: DataFrame-only helper for analyzing temporal trends. Accepts results from `search_by_device_names()` or `query_device()` and computes yearly event counts.

**Parameters**:
- `results_df` (DataFrame): DataFrame from search/query with `DATE_RECEIVED` column

**Returns**: pandas.DataFrame with columns:
- `year` (int): Year
- `event_count` (int): Number of events
- `search_group` (str, optional): Group name if present in input DataFrame

**Examples**:

```python
# From boolean search
results = db.search_by_device_names('catheter')
trends = db.get_trends_by_year(results)
print(trends)
#    year  event_count
# 0  2020          150
# 1  2021          165
# 2  2022          180

# From exact query
results = db.query_device(product_code='NIQ')
trends = db.get_trends_by_year(results)

# Grouped search - includes search_group breakdown
results = db.search_by_device_names({
    'mechanical': [['argon', 'cleaner'], 'angiojet'],
    'aspiration': 'penumbra'
})
trends = db.get_trends_by_year(results)
print(trends)
#   search_group  year  event_count
# 0   mechanical  2020           45
# 1   mechanical  2021           52
# 2   aspiration  2020           30
# 3   aspiration  2021           35

# Trends for single group from grouped search
g1_only = results[results['search_group'] == 'mechanical']
trends_g1 = db.get_trends_by_year(g1_only)
```

**Notes**:
- **DataFrame-only**: Accepts only DataFrames, not search parameters
- **Automatic grouping**: If `search_group` column present, includes it in output
- **Empty handling**: Returns empty DataFrame with correct structure for empty input
- **Sorting**: Results sorted by year (and search_group if present)

**Visualization**:

```python
import matplotlib.pyplot as plt

results = db.search_by_device_names('pacemaker')
trends = db.get_trends_by_year(results)

plt.plot(trends['year'], trends['event_count'], marker='o')
plt.xlabel('Year')
plt.ylabel('Events Reported')
plt.title('Pacemaker Adverse Events Over Time')
plt.grid(True, alpha=0.3)
plt.show()
```

**Related**: `search_by_device_names()`, `query_device()`, `summarize_by_brand()`

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

##### `summarize_by_brand(results_df, group_column='search_group', include_temporal=True)`

Generate comprehensive summary statistics by device group or brand.

**Parameters**:
- `results_df` (DataFrame): Results from `search_by_device_names()` or `query_device()`
- `group_column` (str, default='search_group'): Column to group by
- `include_temporal` (bool, default=True): Include yearly breakdowns

**Returns**: dict with:
```python
{
    'counts': dict,            # Total reports per group
    'event_types': DataFrame,  # Event type breakdown per group
    'date_range': DataFrame,   # First/last dates per group
    'temporal': DataFrame      # Yearly counts (if include_temporal=True)
}
```

**Examples**:

```python
# Grouped search analysis
results = db.search_by_device_names({
    'mechanical': [['argon', 'cleaner'], 'angiojet'],
    'aspiration': 'penumbra'
})

summary = db.summarize_by_brand(results)  # Uses search_group automatically

# View counts
print("Reports by device group:")
for group, count in summary['counts'].items():
    print(f"  {group}: {count}")

# Export summary tables
summary['temporal'].to_csv('table_temporal_trends.csv')
summary['event_types'].to_csv('table_event_types.csv')

# Use with brand standardization
results = db.search_by_device_names('stent')
results = db.standardize_brand_names(results, {'venovo': 'Venovo', 'zilver': 'Zilver Vena'})
summary = db.summarize_by_brand(results, group_column='standard_brand')
```

**Notes**:
- **Default**: Works with `search_group` column from grouped search
- Requires `group_column` to exist in DataFrame
- Handles missing columns gracefully (skips event_types if EVENT_TYPE missing)
- Useful for generating manuscript tables

**Related**: `search_by_device_names()`, `standardize_brand_names()`, `event_type_comparison()`

---

#### Brand Name Standardization


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

**Related**: `find_brand_variations()`, `query_multiple_devices()`, `hierarchical_brand_standardization()`

---

##### `hierarchical_brand_standardization(results_df, specific_mapping=None, family_mapping=None, manufacturer_mapping=None, source_col='BRAND_NAME')`

Apply hierarchical brand name standardization with multiple levels.

**Parameters**:
- `results_df` (DataFrame): DataFrame with brand names to standardize
- `specific_mapping` (dict, optional): Mapping for specific device models (e.g., 'ClotTriever XL')
- `family_mapping` (dict, optional): Mapping for device families (e.g., 'ClotTriever (unspecified)')
- `manufacturer_mapping` (dict, optional): Mapping for manufacturers (e.g., 'Inari Medical')
- `source_col` (str, default='BRAND_NAME'): Column with original brand names

**Returns**: DataFrame with three new columns:
- `device_model`: Most specific match (from specific_mapping or family_mapping)
- `device_family`: Family-level grouping (from family_mapping)
- `manufacturer`: Manufacturer name (from manufacturer_mapping)

**Examples**:

```python
# Define hierarchical mappings
# IMPORTANT: List more specific patterns FIRST (first-match-wins)
specific_models = {
    # More specific patterns first
    'prodigy 8f-s': 'ImperativeCare Prodigy 8F-S',  # Must come before 'prodigy 8f'
    'prodigy 8f': 'ImperativeCare Prodigy 8F',
    'prodigy 6f': 'ImperativeCare Prodigy 6F',
    'prodigy 5f': 'ImperativeCare Prodigy 5F',
    'clottriever xl': 'Inari Medical ClotTriever XL',
    'clottriever bold': 'Inari Medical ClotTriever BOLD',
    'flowtriever xl': 'Inari Medical FlowTriever XL',
}

device_families = {
    'prodigy': 'ImperativeCare Prodigy (unspecified)',
    'clottriever': 'Inari Medical ClotTriever (unspecified)',
    'flowtriever': 'Inari Medical FlowTriever (unspecified)',
    'lightning': 'Penumbra Lightning (unspecified)',
}

manufacturers = {
    'prodigy': 'ImperativeCare',
    'clottriever': 'Inari Medical',
    'flowtriever': 'Inari Medical',
    'lightning': 'Penumbra',
}

# Query and standardize
results = db.query_device_catalog(devices_catalog)
results_std = db.hierarchical_brand_standardization(
    results,
    specific_mapping=specific_models,
    family_mapping=device_families,
    manufacturer_mapping=manufacturers
)

# Analyze at different levels
# 1. Specific models
print(results_std['device_model'].value_counts())

# 2. By manufacturer
summary = db.summarize_by_brand(results_std, group_column='manufacturer')

# 3. All ClotTriever variants together
clottriever_all = results_std[
    results_std['device_family'].str.contains('ClotTriever', case=False, na=False)
]
```

**Notes**:
- Hierarchical matching prevents double-counting: "ClotTriever XL" won't also match "ClotTriever"
- Each level only processes items not matched by previous levels
- Case-insensitive substring matching
- **IMPORTANT**: More specific patterns must be listed first in each mapping (uses first-match-wins)
  - Example: Put `'prodigy 8f-s'` before `'prodigy 8f'` to avoid "Prodigy 8F-S" matching "8F"
  - Python 3.7+ preserves dictionary insertion order
- Pass `None` to skip any level you don't need
- Original `BRAND_NAME` column is preserved

**Use Cases**:
1. **Specific + Family**: Separate specific models (XL, BOLD) from generic reports
2. **Family + Manufacturer**: Group device families, then aggregate by manufacturer
3. **Manufacturer Only**: Simple manufacturer-level aggregation

**Related**: `standardize_brand_names()`, `query_device_catalog()`, `summarize_by_brand()`

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

##### `event_type_comparison(results_df, group_var='search_group')`

Compare event type distributions across groups with statistical tests.

**Parameters**:
- `results_df` (DataFrame): Results with EVENT_TYPE column
- `group_var` (str, default='search_group'): Variable to compare across

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
# Grouped search comparison
results = db.search_by_device_names({
    'mechanical': [['argon', 'cleaner'], 'angiojet'],
    'aspiration': 'penumbra'
})
comparison = db.event_type_comparison(results)  # Uses search_group automatically

print(comparison['summary'])
# Output:
# Event Type Comparison by search_group
# ======================================
# Chi-square: 45.23 (p=0.0001)
# mechanical: 4.5% deaths, 30.2% injuries, 65.3% malfunctions
# aspiration: 2.0% deaths, 50.1% injuries, 47.9% malfunctions

# With brand standardization
results = db.search_by_device_names('stent')
results = db.standardize_brand_names(results, {'venovo': 'Venovo', 'zilver': 'Zilver Vena'})
comparison = db.event_type_comparison(results, group_var='standard_brand')
```

**Notes**:
- **Default**: Works with `search_group` column from grouped search
- Automatically handles FDA event type abbreviations (D, IN, M)
- Events can have multiple types
- Compares serious events (Death/Injury) vs. Malfunction patterns

**Related**: `chi_square_test()`, `event_type_breakdown_for()`, `search_by_device_names()`

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

## Search Refinement Helper Functions

Standalone utility functions for refining device search criteria during exploratory analysis. These functions help you iterate on search terms before formalizing them into a DeviceSearchStrategy.

**Module**: `pymaude.analysis_helpers`

**Import**: `from pymaude import analysis_helpers`

**Typical Workflow**:
1. Run broad search with `db.search_by_device_names()`
2. Run refined search with more specific criteria
3. Use `exclude_results()` to find what broad search captured that narrow search missed
4. Use `filter_by_text()` to remove known false positives
5. Use `summarize_devices()` to review what remains
6. Iterate on search criteria until satisfied
7. Formalize into `DeviceSearchStrategy` for reproducibility

---

### `exclude_results(main_df, exclude_df, key='MDR_REPORT_KEY')`

Return rows from main_df whose key values don't appear in exclude_df.

Useful for search term refinement: find what matches a broad search but not a narrow search, to identify potentially missed results.

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `main_df` | DataFrame | required | DataFrame to filter |
| `exclude_df` | DataFrame | required | DataFrame containing rows to exclude |
| `key` | str | `'MDR_REPORT_KEY'` | Column to match on |

**Returns**: DataFrame with excluded rows removed

**Raises**:
- `ValueError`: If key column is missing from either DataFrame

**Examples**:

```python
from pymaude import analysis_helpers

# Find what's in broad search but not narrow search
broad = db.search_by_device_names('omni')
narrow = db.search_by_device_names([['angiojet', 'omni'], ['boston sci', 'omni']])
missed = analysis_helpers.exclude_results(broad, narrow)

# Review what's being missed
print(f"Missed {len(missed)} reports")

# Use EVENT_KEY instead of MDR_REPORT_KEY
missed_events = analysis_helpers.exclude_results(broad, narrow, key='EVENT_KEY')
```

**Notes**:
- Use `MDR_REPORT_KEY` to check individual report overlap
- Use `EVENT_KEY` to check event-level overlap (accounts for duplicate reports)

**Related**: `filter_by_text()`, `summarize_devices()`

---

### `filter_by_text(df, exclude_terms=None, include_terms=None, column='DEVICE_NAME_CONCAT')`

Filter results by text matching on a specified column.

Useful for removing obvious noise (e.g., insulin pumps) from search results or keeping only rows matching certain terms.

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `df` | DataFrame | required | DataFrame to filter |
| `exclude_terms` | list | `None` | Terms to exclude - removes rows matching ANY |
| `include_terms` | list | `None` | Terms to include - keeps only rows matching ANY |
| `column` | str | `'DEVICE_NAME_CONCAT'` | Column to search |

**Returns**: DataFrame with filtered rows

**Raises**:
- `ValueError`: If column is missing from DataFrame

**Examples**:

```python
from pymaude import analysis_helpers

# Remove insulin-related results from search
missed = analysis_helpers.exclude_results(broad_search, narrow_search)
cleaned = analysis_helpers.filter_by_text(missed, exclude_terms=['insulin', 'pump'])

# Keep only catheter-related results
catheters = analysis_helpers.filter_by_text(results, include_terms=['catheter', 'cath'])

# Combine both: keep catheters, exclude insulin
filtered = analysis_helpers.filter_by_text(
    results,
    exclude_terms=['insulin'],
    include_terms=['catheter']
)

# Filter on a different column
filtered = analysis_helpers.filter_by_text(
    results,
    exclude_terms=['medtronic'],
    column='MANUFACTURER_D_NAME'
)
```

**Notes**:
- Case-insensitive matching
- Terms are matched as substrings (partial matches work)
- When both exclude and include are provided, exclude is applied first

**Related**: `exclude_results()`, `summarize_devices()`

---

### `summarize_devices(df, columns=None)`

Quick view of unique devices in results for search refinement.

Shows distinct combinations of device identifiers to help review what devices are captured by a search.

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `df` | DataFrame | required | DataFrame with device information |
| `columns` | list | `['BRAND_NAME', 'GENERIC_NAME', 'MANUFACTURER_D_NAME']` | Columns to include |

**Returns**: DataFrame with unique device combinations, sorted by first column

**Raises**:
- `ValueError`: If none of the specified columns exist in DataFrame

**Examples**:

```python
from pymaude import analysis_helpers

# See what devices are being missed by narrow search
missed = analysis_helpers.exclude_results(broad_search, narrow_search)
analysis_helpers.summarize_devices(missed)

# Summarize with only brand names
analysis_helpers.summarize_devices(results, columns=['BRAND_NAME'])

# Full workflow: refine search terms
broad = db.search_by_device_names('omni')
narrow = db.search_by_device_names([['angiojet', 'omni'], ['boston sci', 'omni']])

missed = analysis_helpers.exclude_results(broad, narrow)
missed = analysis_helpers.filter_by_text(missed, exclude_terms=['insulin', 'pump'])
analysis_helpers.summarize_devices(missed)  # Review what's left
```

**Notes**:
- Only includes columns that exist in the DataFrame
- Results are sorted alphabetically by first column
- Useful for iterating on search criteria

**Related**: `exclude_results()`, `filter_by_text()`

---

### `remap_device_groups(results_df, new_group_mapping, group_var='search_group', new_group_column=None, allow_unspecified=False)`

Remap group assignments within a DataFrame of device events.

Useful for combining fine-grained search groups into broader categories or renaming groups for analysis.

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `results_df` | DataFrame | required | DataFrame with group column |
| `new_group_mapping` | dict | required | Mapping of new group names to old group names |
| `group_var` | str | `'search_group'` | Column containing current group assignments |
| `new_group_column` | str | `None` | New column for remapped groups (overwrites if None) |
| `allow_unspecified` | bool | `False` | If True, unmapped groups pass through unchanged |

**Returns**: DataFrame with remapped group assignments

**Raises**:
- `ValueError`: If `group_var` column is missing
- `ValueError`: If an old group is assigned to multiple new groups
- `ValueError`: If `allow_unspecified=False` and groups are unmapped

**Examples**:

```python
from pymaude import analysis_helpers

# Combine device models into broader categories
results = db.search_by_device_names({
    'cleaner_15': [['argon', 'cleaner', '15']],
    'cleaner_xt': [['argon', 'cleaner', 'xt']],
    'cleaner_other': [['argon', 'cleaner']],
    'angiojet': ['angiojet']
})

# Remap: combine all cleaner models, keep angiojet separate
remapped = analysis_helpers.remap_device_groups(results, {
    'Argon Cleaner': ['cleaner_15', 'cleaner_xt', 'cleaner_other'],
    'AngioJet': 'angiojet'
})

# Remap to new column (preserve original groups)
remapped = analysis_helpers.remap_device_groups(
    results,
    {'Mechanical': ['cleaner_15', 'angiojet']},
    new_group_column='device_category',
    allow_unspecified=True
)
```

**Notes**:
- Dict values can be a single string or list of strings
- Order of `new_group_mapping` determines final group order
- Use `allow_unspecified=True` when only remapping some groups

**Related**: `search_by_device_names()`, `summarize_by_group()`

---

## DeviceSearchStrategy Class

Reproducible search strategy class for systematic device review following PRISMA 2020 and RECORD guidelines.

### Overview

The `DeviceSearchStrategy` class encapsulates device search criteria, enabling:
- Version-controlled search strategies (YAML format)
- Systematic broad → narrow → adjudication workflow
- Manual inclusion/exclusion tracking
- PRISMA flow diagram count generation

### Initialization

```python
from pymaude import DeviceSearchStrategy

strategy = DeviceSearchStrategy(
    name="my_device",
    description="Search strategy for my device category",
    version="1.0.0",
    author="Your Name",
    broad_criteria=[['term1', 'term2'], 'term3'],
    narrow_criteria=[['term1', 'term2', 'specific']],
    exclusion_patterns=['false_positive_pattern'],
    search_rationale="Why these terms were chosen..."
)
```

**Parameters:**
- `name` (str): Strategy identifier (e.g., "rotational_thrombectomy")
- `description` (str): Human-readable description
- `version` (str, default="1.0.0"): Semantic version
- `author` (str, optional): Strategy author name
- `created_at` (datetime, auto): Creation timestamp
- `updated_at` (datetime, auto): Last modification timestamp
- `broad_criteria` (list): Broad search criteria (PyMAUDE list format)
- `narrow_criteria` (list): Refined search criteria
- `known_variants` (list, optional): Device name variants for documentation
- `exclusion_patterns` (list, optional): Known false positive patterns
- `inclusion_overrides` (list, optional): MDR_REPORT_KEYs to force-include
- `exclusion_overrides` (list, optional): MDR_REPORT_KEYs to force-exclude
- `search_rationale` (str, optional): Documentation of search approach

**Boolean Search Format:**
- OR: `['term1', 'term2']`
- AND: `[['term1', 'term2']]`
- Complex: `[['argon', 'cleaner'], 'angiojet']` = `(argon AND cleaner) OR angiojet`

---

### `apply(db, name_column="DEVICE_NAME_CONCAT", start_date=None, end_date=None)`

Apply search strategy to a MaudeDatabase following PRISMA workflow.

**Parameters:**
- `db` (MaudeDatabase): Database instance to search
- `name_column` (str, default="DEVICE_NAME_CONCAT"): Column for substring matching
- `start_date` (str, optional): Start date (YYYY-MM-DD)
- `end_date` (str, optional): End date (YYYY-MM-DD)

**Returns:** Tuple of (included, excluded, needs_review) DataFrames

**Example:**
```python
from pymaude import MaudeDatabase, DeviceSearchStrategy

# Load strategy
strategy = DeviceSearchStrategy.from_yaml('strategies/my_device.yaml')

# Apply to database
db = MaudeDatabase('maude.db')
included, excluded, needs_review = strategy.apply(db, start_date='2020-01-01')

print(f"Included: {len(included)} reports")
print(f"Needs review: {len(needs_review)} reports")
```

---

### `to_yaml(path=None)` / `from_yaml(path)`

Export/import strategy to/from YAML format.

**Example:**
```python
# Save
strategy.to_yaml('strategies/my_device_v1.yaml')

# Load
strategy = DeviceSearchStrategy.from_yaml('strategies/my_device_v1.yaml')
```

---

### `add_manual_decision(mdr_key, decision, reason="")` 

Record manual inclusion/exclusion decision.

### `get_prisma_counts(included_df, excluded_df, needs_review_df)`

Generate counts for PRISMA flow diagram.

---

## AdjudicationLog Class

CSV-based tracking of manual decisions for device search adjudication workflow.

### Overview

The `AdjudicationLog` class provides structured tracking of manual inclusion/exclusion decisions during device search review. Decisions are stored in CSV format for transparency and version control.

### Initialization

#### `__init__(path)`

Initialize a new adjudication log.

**Parameters**:
- `path` (str): Path to CSV file for storing adjudication records

**Returns**: AdjudicationLog instance

**Example**:
```python
from pymaude.adjudication import AdjudicationLog

# Create new log
log = AdjudicationLog('adjudication/my_decisions.csv')
```

**Notes**:
- Automatically loads existing decisions if file exists
- Creates empty log if file doesn't exist
- Parent directories created automatically on save

---

### Methods

#### `add(mdr_key, decision, reason, reviewer, strategy_version="", device_info="")`

Add an adjudication decision to the log.

**Parameters**:
- `mdr_key` (str): MDR_REPORT_KEY for the report being adjudicated
- `decision` (str): Either "include" or "exclude"
- `reason` (str): Explanation for the decision
- `reviewer` (str): Name or ID of reviewer making decision
- `strategy_version` (str, optional): Version of search strategy being used
- `device_info` (str, optional): Device name/info for context

**Returns**: None

**Raises**:
- `ValueError`: If decision is not "include" or "exclude"

**Example**:
```python
log = AdjudicationLog('adjudication/devices.csv')

# Add inclusion decision
log.add('1234567', 'include', 'Matches device criteria', 'Jake',
        strategy_version='v1.0', device_info='Argon Cleaner 15')

# Add exclusion decision
log.add('7654321', 'exclude', 'Ultrasonic cleaner (false positive)', 'Jake')

# Save decisions
log.to_csv()
```

**Notes**:
- Decisions are added to memory; call `to_csv()` to persist
- Timestamp is automatically recorded
- All parameters are stored for PRISMA reporting

---

#### `to_csv()`

Save all adjudication decisions to CSV file.

**Parameters**: None

**Returns**: None

**Example**:
```python
log = AdjudicationLog('adjudication/devices.csv')
log.add('1234567', 'include', 'Matches criteria', 'Reviewer A')
log.add('7654321', 'exclude', 'False positive', 'Reviewer A')

# Save to CSV
log.to_csv()
```

**Notes**:
- Creates parent directories if they don't exist
- Overwrites existing file with all current decisions
- CSV format is git-friendly and Excel-compatible
- CSV columns: mdr_report_key, decision, reason, reviewer, date, strategy_version, device_info

---

#### `from_csv(path)` (classmethod)

Load existing adjudication log from CSV file.

**Parameters**:
- `path` (str): Path to CSV file

**Returns**: AdjudicationLog instance with loaded decisions

**Raises**:
- `FileNotFoundError`: If CSV file doesn't exist

**Example**:
```python
from pymaude.adjudication import AdjudicationLog

# Load existing log
log = AdjudicationLog.from_csv('adjudication/devices.csv')

print(f"Loaded {len(log.records)} decisions")

# Add more decisions
log.add('9999999', 'include', 'New decision', 'Reviewer B')
log.to_csv()
```

**Notes**:
- Automatically called by `__init__()` if file exists
- Useful for explicitly loading logs
- Parses ISO-format dates from CSV

---

#### `get_inclusion_keys()`

Get set of MDR_REPORT_KEYs marked for inclusion.

**Parameters**: None

**Returns**: Set of report keys (as strings)

**Example**:
```python
log = AdjudicationLog.from_csv('adjudication/devices.csv')

# Get reports to include
include_keys = log.get_inclusion_keys()
print(f"Including {len(include_keys)} reports")

# Filter query results
results = db.query_device(device_name='catheter')
included = results[results['MDR_REPORT_KEY'].astype(str).isin(include_keys)]
```

**Notes**:
- Returns strings (MDR_REPORT_KEYs are stored as strings in log)
- Use with DeviceSearchStrategy.apply() for manual overrides
- Empty set if no inclusions

**Related**: `get_exclusion_keys()`

---

#### `get_exclusion_keys()`

Get set of MDR_REPORT_KEYs marked for exclusion.

**Parameters**: None

**Returns**: Set of report keys (as strings)

**Example**:
```python
log = AdjudicationLog.from_csv('adjudication/devices.csv')

# Get reports to exclude
exclude_keys = log.get_exclusion_keys()
print(f"Excluding {len(exclude_keys)} reports")

# Filter query results
results = db.query_device(device_name='catheter')
final = results[~results['MDR_REPORT_KEY'].astype(str).isin(exclude_keys)]
```

**Notes**:
- Returns strings (MDR_REPORT_KEYs are stored as strings in log)
- Use with DeviceSearchStrategy.apply() for manual overrides
- Empty set if no exclusions

**Related**: `get_inclusion_keys()`

---

#### `to_dataframe()`

Convert adjudication log to pandas DataFrame for analysis.

**Parameters**: None

**Returns**: pandas.DataFrame with columns:
- `mdr_report_key` (str): Report identifier
- `decision` (str): "include" or "exclude"
- `reason` (str): Decision rationale
- `reviewer` (str): Reviewer name/ID
- `date` (datetime): Decision timestamp
- `strategy_version` (str): Search strategy version
- `device_info` (str): Device context

**Example**:
```python
log = AdjudicationLog.from_csv('adjudication/devices.csv')

# Convert to DataFrame for analysis
df = log.to_dataframe()

# Analyze decision patterns
print(df['decision'].value_counts())
print(df.groupby('reviewer')['decision'].value_counts())

# Most common exclusion reasons
exclusions = df[df['decision'] == 'exclude']
print(exclusions['reason'].value_counts().head(10))

# Export for reporting
df.to_csv('adjudication_summary.csv', index=False)
```

**Notes**:
- Returns empty DataFrame with correct columns if no decisions
- Useful for inter-rater reliability analysis
- Date column is datetime type (not string)

**Related**: `get_statistics()`

---

#### `get_statistics()`

Get summary statistics for PRISMA reporting.

**Parameters**: None

**Returns**: dict with keys:
- `total_decisions` (int): Total number of decisions
- `inclusions` (int): Count of inclusion decisions
- `exclusions` (int): Count of exclusion decisions
- `reviewers` (list): Sorted list of unique reviewer names
- `date_range` (tuple): (earliest_date, latest_date) as datetime objects

**Example**:
```python
log = AdjudicationLog.from_csv('adjudication/devices.csv')

# Get summary statistics
stats = log.get_statistics()

print(f"Total decisions: {stats['total_decisions']}")
print(f"Inclusions: {stats['inclusions']}")
print(f"Exclusions: {stats['exclusions']}")
print(f"Reviewers: {', '.join(stats['reviewers'])}")

first_date, last_date = stats['date_range']
print(f"Review period: {first_date.date()} to {last_date.date()}")

# Use in PRISMA flow diagram
print(f"Records screened manually: {stats['total_decisions']}")
print(f"Records excluded after review: {stats['exclusions']}")
```

**Notes**:
- Returns all fields as None/empty if log has no decisions
- Useful for Methods section and PRISMA diagrams
- Date range helps document review timeline

**Related**: `to_dataframe()`, `DeviceSearchStrategy.get_prisma_counts()`

---

## Project Generator

```bash
python scripts/create_project.py <project_name> [author] [description]
```

Creates standardized analysis project with PRISMA compliance.

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

