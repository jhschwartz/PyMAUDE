# Troubleshooting Guide

Solutions to common problems when using `maude_db`.

## Table of Contents

1. [Installation Issues](#installation-issues)
2. [Download Problems](#download-problems)
3. [Database Errors](#database-errors)
4. [Query Issues](#query-issues)
5. [Memory & Performance](#memory--performance)
6. [Data Quality Issues](#data-quality-issues)
7. [Platform-Specific Issues](#platform-specific-issues)
8. [Getting Help](#getting-help)

---

## Installation Issues

### Problem: ImportError: No module named 'maude_db'

**Cause**: Library not in Python path or virtual environment not activated

**Solution**:
```bash
# Ensure you're in the correct directory
cd /path/to/maude_db

# Activate virtual environment
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows

# Verify Python can find module
python -c "from maude_db import MaudeDatabase; print('OK')"
```

---

### Problem: ModuleNotFoundError: No module named 'pandas'

**Cause**: Dependencies not installed

**Solution**:
```bash
# Install requirements
pip install -r requirements.txt

# Verify installation
pip list | grep pandas
pip list | grep requests
```

---

### Problem: Permission denied when creating database

**Cause**: No write permission in target directory

**Solution**:
```python
# Option 1: Use directory where you have permissions
db = MaudeDatabase('~/Documents/maude.db')

# Option 2: Fix permissions
# chmod 755 /path/to/directory  # Unix/macOS

# Option 3: Run as administrator (Windows)
```

---

## Download Problems

### Problem: HTTP 404 Error during download

**Cause**: Requested year/table combination not available on FDA server

**Solution**:

Check data availability:
- Device (FOIDEV): 1998-present
- Text (FOITEXT): 1996-present
- Master (MDRFOI): Comprehensive file only
- Patient: 1996-present

```python
# Use available years
db.add_years('1998-2020', tables=['device'], download=True)  # Works
db.add_years('1990-1995', tables=['device'], download=True)  # Fails - too early

# Check if file exists before downloading
if db._check_file_exists(2025, 'foidev'):
    db.add_years(2025, tables=['device'], download=True)
```

**Note**: For cumulative files (master, patient), the library automatically falls back to older years if the expected file isn't available yet. This is common in early January when FDA hasn't updated to the new year yet. If you see a warning like:

```
WARNING: Expected file mdrfoithru2025.zip not available.
Using mdrfoithru2024.zip instead (latest available cumulative file).
```

This is normal and the library will automatically use the most recent available file.

---

### Problem: Network timeout during download

**Cause**: Slow connection, FDA server issues, or firewall

**Solution**:

```python
# Downloads are cached - rerun to resume
db.add_years(2020, tables=['device'], download=True)
# If interrupted, running again will use cached ZIP

# For flaky connections, download one year at a time
for year in range(2018, 2021):
    try:
        db.add_years(year, tables=['device'], download=True)
    except Exception as e:
        print(f"Failed {year}: {e}")
```

**Alternative**: Manually download files
```bash
# Download manually from https://www.fda.gov/...
# Place in maude_data/ directory
# Run with download=False
db.add_years(2020, tables=['device'], download=False, data_dir='./maude_data')
```

---

### Problem: ZIP file corrupted

**Cause**: Interrupted download or transmission error

**Solution**:

```bash
# Delete corrupted file
rm maude_data/foidev2020.zip

# Re-download
python -c "
from maude_db import MaudeDatabase
db = MaudeDatabase('maude.db')
db.add_years(2020, tables=['device'], download=True)
"
```

---

### Problem: Disk space full during download

**Cause**: Insufficient disk space for ZIP files + extracted data

**Solution**:

```python
# Check space requirements
# Device table: ~45MB compressed, ~100MB extracted per year
# Text table: ~45MB compressed, ~150MB extracted per year

# Download fewer years
db.add_years(2020, tables=['device'], download=True)  # ~150MB total

# Clean up old data
import shutil
shutil.rmtree('./maude_data')  # Remove cached ZIPs
```

---

### Problem: FDA server unavailable

**Cause**: FDA website maintenance or outage

**Solution**:

```python
# Check FDA server status
import requests
try:
    r = requests.head('https://www.accessdata.fda.gov/MAUDE/ftparea/')
    print(f"Server status: {r.status_code}")
except:
    print("Server unreachable - try later")

# Use cached files if available
db.add_years(2020, tables=['device'], download=False)
```

---

## Database Errors

### Problem: "No such column" error

**Cause**: Column name case mismatch

**Solution**:

```python
# Device/text tables use UPPERCASE
# Correct
db.query("SELECT MDR_REPORT_KEY, GENERIC_NAME FROM device")

# Incorrect
db.query("SELECT mdr_report_key, generic_name FROM device")  # Error!

# All tables use uppercase
db.query("SELECT MDR_REPORT_KEY, EVENT_TYPE FROM master")  # Correct

# Use query methods to avoid case issues
results = db.query_device(device_name='pacemaker')  # Handles case automatically
```

---

### Problem: database is locked

**Cause**: Multiple connections to same database or unclosed connection

**Solution**:

```python
# Always close connections
db = MaudeDatabase('maude.db')
# ... use db ...
db.close()  # Important!

# Or use context manager
with MaudeDatabase('maude.db') as db:
    results = db.query_device(device_name='catheter')
# Automatically closed

# Kill other connections
# Check for other Python processes accessing database
# Close other database tools (DB Browser for SQLite, etc.)
```

---

### Problem: Database corrupted

**Cause**: Interrupted write, system crash, or disk error

**Solution**:

```python
# Try SQLite recovery
import sqlite3
conn = sqlite3.connect('maude.db')
conn.execute('PRAGMA integrity_check')  # Check integrity
conn.close()

# If corrupted, rebuild from scratch
import os
os.remove('maude.db')  # Delete corrupted database

db = MaudeDatabase('maude.db')
db.add_years('2018-2020', tables=['device'], download=False)  # Use cached files
```

---

### Problem: Database file very large

**Cause**: Duplicate imports or many years of data

**Solution**:

```python
# Check what's in database
db.info()  # Shows record counts

# Remove duplicates (if accidentally imported twice)
db.conn.execute("""
    DELETE FROM device
    WHERE rowid NOT IN (
        SELECT MIN(rowid)
        FROM device
        GROUP BY MDR_REPORT_KEY, DEVICE_SEQUENCE_NUMBER
    )
""")
db.conn.commit()

# Start fresh if needed
os.remove('maude.db')
db = MaudeDatabase('maude.db')
db.add_years('2020-2022', tables=['device'], download=False, strict=False)
```

---

## Query Issues

### Problem: Empty results when expecting data

**Cause**: Wrong table loaded, case-sensitive search, or date format

**Solution**:

```python
# Check what tables exist
db.info()  # Shows loaded tables

# Check column names
df = db.query("SELECT * FROM device LIMIT 1")
print(df.columns.tolist())  # See actual column names

# Check device names available
all_devices = db.query("SELECT DISTINCT GENERIC_NAME FROM device LIMIT 20")
print(all_devices)

# Use LIKE for partial matches
results = db.query_device(device_name='pacem')  # Partial match works
```

---

### Problem: Column name mismatch in joins

**Cause**: Column name typos or missing tables

**Solution**:

```python
# All columns use uppercase
query = """
    SELECT m.EVENT_TYPE, d.GENERIC_NAME
    FROM master m
    JOIN device d ON m.MDR_REPORT_KEY = d.MDR_REPORT_KEY
"""
# Note: All columns use uppercase

# Or use query methods which handle this
results = db.query_device(device_name='catheter')  # Handles join correctly
```

---

### Problem: Query very slow

**Cause**: Missing indexes or full table scan

**Solution**:

```python
# Ensure indexes were created
db._create_indexes(['device', 'master', 'text'])

# Use indexed columns in WHERE clause
# Fast - uses index
db.query("SELECT * FROM device WHERE MDR_REPORT_KEY = '1234567'")

# Slow - no index on BRAND_NAME
db.query("SELECT * FROM device WHERE BRAND_NAME = 'DeviceX'")

# Filter early
db.query_device(device_name='pacemaker', start_date='2020-01-01')  # Good
# vs.
all_data = db.query("SELECT * FROM device")  # Loads everything - slow
filtered = all_data[...]  # Then filters in Python
```

---

### Problem: pandas SettingWithCopyWarning

**Cause**: Modifying DataFrame slice

**Solution**:

```python
# Make explicit copy
results = db.query_device(device_name='catheter')
subset = results[results['EVENT_TYPE'] == 'D'].copy()  # .copy() here (D = Death)
subset['new_column'] = 'value'  # No warning

# Or modify original
results.loc[results['EVENT_TYPE'] == 'D', 'new_column'] = 'value'
```

---

## Memory & Performance

### Problem: Out of memory error

**Cause**: Loading too much data at once

**Solution**:

```python
# Load fewer years
db.add_years(2020, tables=['device'], download=True)  # Not 'all'

# Query subsets
recent = db.query_device(device_name='catheter', start_date='2020-01-01')
# vs.
all_catheters = db.query_device(device_name='catheter')  # All years

# Use chunked processing
query = "SELECT * FROM device WHERE GENERIC_NAME LIKE '%catheter%'"
for chunk in pd.read_sql_query(query, db.conn, chunksize=10000):
    process(chunk)  # Process in pieces

# Reduce chunk_size during import
db.add_years(2020, chunk_size=10000, download=True)  # Default is 100000
```

---

### Problem: Import very slow

**Cause**: Large files, slow disk, or too-small chunks

**Solution**:

```python
# Increase chunk size (if you have RAM)
db.add_years(2020, chunk_size=500000, download=True)  # Faster but uses more RAM

# Close other programs
# Free up memory before import

# Use SSD instead of HDD if possible

# Import fewer tables
db.add_years(2020, tables=['device'], download=True)  # Just what you need
```

---

### Problem: DataFrame operations slow

**Cause**: Inefficient pandas operations

**Solution**:

```python
# Use vectorized operations
# Slow
results['new_col'] = results.apply(lambda row: row['col1'] + row['col2'], axis=1)

# Fast
results['new_col'] = results['col1'] + results['col2']

# Filter in SQL, not pandas
# Slow
all_data = db.query("SELECT * FROM device")
filtered = all_data[all_data['GENERIC_NAME'].str.contains('catheter')]

# Fast
filtered = db.query("SELECT * FROM device WHERE GENERIC_NAME LIKE '%catheter%'")
```

---

## Data Quality Issues

### Problem: Missing narratives

**Cause**: Not all events have text records

**Solution**:

```python
# Check coverage
devices = db.query_device(device_name='catheter')
keys = devices['MDR_REPORT_KEY'].tolist()
narratives = db.get_narratives(keys)

print(f"Events: {len(devices)}")
print(f"With narratives: {len(narratives)}")
print(f"Coverage: {len(narratives)/len(devices)*100:.1f}%")

# Only analyze events with narratives
has_narrative = devices[devices['MDR_REPORT_KEY'].isin(narratives['MDR_REPORT_KEY'])]
```

---

### Problem: Unexpected data values

**Cause**: Real-world data messiness

**Solution**:

```python
# Check unique values
results = db.query_device(device_name='pacemaker')
print(results['EVENT_TYPE'].value_counts())
print(results['GENERIC_NAME'].value_counts())

# Clean data
results['EVENT_TYPE'] = results['EVENT_TYPE'].fillna('Unknown')
results = results[results['GENERIC_NAME'].notna()]

# Standardize text
results['GENERIC_NAME'] = results['GENERIC_NAME'].str.lower().str.strip()
```

---

### Problem: Date format inconsistencies

**Cause**: FDA data uses different date formats

**Solution**:

```python
# Convert to datetime
results['DATE_RECEIVED'] = pd.to_datetime(results['DATE_RECEIVED'], errors='coerce')

# Filter by date
recent = results[results['DATE_RECEIVED'] > '2020-01-01']

# Handle invalid dates
invalid_dates = results[results['DATE_RECEIVED'].isna()]
print(f"Invalid dates: {len(invalid_dates)}")
```

---

## Platform-Specific Issues

### macOS: Case-insensitive filesystem

**Problem**: File paths may not match exactly

**Solution**: The library handles this automatically via `_make_file_path()`, but if issues occur:

```bash
# Check actual filenames
ls maude_data/

# Library tries both:
# foidev2020.txt (lowercase)
# FOIDEV2020.txt (uppercase)
```

---

### Windows: Path issues

**Problem**: Backslashes in paths

**Solution**:

```python
# Use forward slashes or raw strings
db = MaudeDatabase('C:/Users/name/maude.db')  # Works
db = MaudeDatabase(r'C:\Users\name\maude.db')  # Works
db = MaudeDatabase('C:\\Users\\name\\maude.db')  # Works

# Avoid
db = MaudeDatabase('C:\Users\name\maude.db')  # May fail
```

---

### Linux: Permission errors

**Problem**: No permission to create files

**Solution**:

```bash
# Check permissions
ls -la /path/to/directory

# Fix permissions
chmod 755 /path/to/directory

# Or use home directory
db = MaudeDatabase('~/maude.db')
```

---

## Getting Help

### Before Asking for Help

1. **Check this guide** - Is your issue listed above?
2. **Check the docs** - See [getting_started.md](getting_started.md) and [api_reference.md](api_reference.md)
3. **Search GitHub issues** - Has someone else had this problem?

### Creating a Bug Report

Include:

1. **Python version**: `python --version`
2. **Operating system**: macOS 13.5, Windows 11, Ubuntu 22.04, etc.
3. **Library version**: Commit hash or release number
4. **Minimal reproducible example**:

```python
from maude_db import MaudeDatabase

db = MaudeDatabase('test.db')
# ... minimal code that shows the problem ...
```

5. **Full error message**: Copy entire stack trace

### Good Bug Report Example

```
Title: "No such column error when querying device table"

Environment:
- Python 3.9.7
- macOS 13.5
- maude_db commit abc123

Problem:
Getting "sqlite3.OperationalError: no such column: generic_name"

Code:
from maude_db import MaudeDatabase
db = MaudeDatabase('maude.db')
db.add_years(2020, tables=['device'], download=True)
results = db.query("SELECT generic_name FROM device")  # Fails here

Error:
sqlite3.OperationalError: no such column: generic_name
```

### Getting Version Info

```python
import sys
import pandas as pd
import sqlite3

print(f"Python: {sys.version}")
print(f"pandas: {pd.__version__}")
print(f"SQLite: {sqlite3.sqlite_version}")
```

---

## Common Error Messages

### `FileNotFoundError: No file found for table=device, year=1995`

→ See [Problem: HTTP 404 Error](#problem-http-404-error-during-download)

### `sqlite3.OperationalError: no such column`

→ See [Problem: "No such column" error](#problem-no-such-column-error)

### `MemoryError` or `Killed`

→ See [Problem: Out of memory error](#problem-out-of-memory-error)

### `sqlite3.OperationalError: database is locked`

→ See [Problem: database is locked](#problem-database-is-locked)

### `requests.exceptions.ConnectionError`

→ See [Problem: Network timeout](#problem-network-timeout-during-download)

### `zipfile.BadZipFile`

→ See [Problem: ZIP file corrupted](#problem-zip-file-corrupted)

---

## Still Stuck?

If this guide didn't solve your problem:

1. Open an issue on GitHub with details (see [Creating a Bug Report](#creating-a-bug-report))
2. Check the FDA MAUDE documentation for data-specific questions
3. Post on relevant forums (Stack Overflow, Reddit /r/bioinformatics, etc.)

**Remember**: Be specific, include code examples, and share error messages!