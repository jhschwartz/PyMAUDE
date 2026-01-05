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
from maude_db import MaudeDatabase

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

**Available Tables**:
- `'master'` - Core event data (MDRFOI) - **Note**: Only comprehensive file available
- `'device'` - Device details (FOIDEV) - Available 1998+
- `'text'` - Event narratives (FOITEXT) - Available 1996+
- `'patient'` - Patient demographics (PATIENT) - Available 1996+
- `'problems'` - Device problem codes (FOIDEVPROBLEM) - Recent years only

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

**Related**: `query_device()`

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
path = db._make_file_path('device', 1998, './maude_data')
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