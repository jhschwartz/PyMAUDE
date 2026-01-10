# Getting Started with maude_db

This tutorial walks you through your first analysis using the `maude_db` library.

## Prerequisites

Before you begin, make sure you have:

- **Python 3.7 or later** - Check with `python3 --version`
- **Internet connection** - Required for downloading FDA data
- **Disk space** - At least 500MB free (varies by years downloaded)
- **Basic Python knowledge** - Helpful but not required

SQL knowledge is helpful for custom queries but not required for basic usage.

## Installation

### Option 1: Quick Setup with Makefile (Recommended)

The easiest way to set up your environment:

```bash
# Navigate to the maude_db directory
cd maude_db

# Create virtual environment and install dependencies
make setup

# Activate the virtual environment
source venv/bin/activate  # On macOS/Linux
# OR
venv\Scripts\activate     # On Windows

# Your prompt should now show (venv)

# Verify installation
python -c "from maude_db import MaudeDatabase; print('Success!')"
```

If you see "Success!", you're ready to go!

**Note**: For development work (including running tests), use `make dev` instead of `make setup` to install additional testing dependencies.

### Option 2: Manual Setup

If you prefer to set up manually:

```bash
# Navigate to the maude_db directory
cd maude_db

# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On macOS/Linux
# OR
venv\Scripts\activate     # On Windows

# Your prompt should now show (venv)

# Install package with dependencies from pyproject.toml
pip install -e .

# Verify installation
python -c "from maude_db import MaudeDatabase; print('Success!')"
```

## Your First Database

Let's create your first MAUDE database and run a simple query.

### 1. Create a Python Script

Create a file called `my_first_query.py`:

```python
from maude_db import MaudeDatabase

# Create or connect to database
# This creates a file called 'my_maude.db' in the current directory
db = MaudeDatabase('my_maude.db', verbose=True)

# Show database info (currently empty)
db.info()

# Close connection
db.close()
```

Run it:

```bash
python my_first_query.py
```

You should see output showing an empty database. A file `my_maude.db` has been created.

### 2. Understanding the Database Path

The database path (`'my_maude.db'`) determines where your data is stored:

```python
# Current directory
db = MaudeDatabase('my_maude.db')

# Specific directory
db = MaudeDatabase('/path/to/data/maude.db')

# Relative path
db = MaudeDatabase('../data/maude.db')
```

**Tip**: Use absolute paths for scripts you'll run from different locations.

### 3. Directory Structure

After downloading data, you'll have:

```
your_project/
├── my_first_query.py       # Your script
├── my_maude.db             # SQLite database (grows with data)
└── maude_data/             # Downloaded ZIP files (cached)
    ├── foidev1998.zip
    ├── foitext1998.zip
    └── ...
```

## Downloading Your First Data

Let's download one year of device data. We'll use 2000 because it's relatively small (~10MB).

```python
from maude_db import MaudeDatabase

db = MaudeDatabase('my_maude.db', verbose=True)

# Download 2000 device data (device data available from 2000 onwards due to FDA schema change)
db.add_years(
    years=2000,               # Single year
    tables=['device'],        # Just device table
    download=True,            # Download from FDA
    data_dir='./maude_data'   # Where to cache files
)

# Show what we downloaded
db.info()

db.close()
```

**What happens**:
1. Checks if `foidev1998.zip` exists in `maude_data/`
2. If not, downloads it from FDA server (~3MB, ~30 seconds)
3. Extracts and imports to SQLite
4. Creates indexes for fast queries

**Subsequent runs**: The ZIP file is cached, so re-running is instant.

**Note**: For cumulative files (master and patient tables), the library automatically handles FDA's delayed update schedule. If you request data in early January and FDA hasn't yet uploaded the new year's cumulative file (e.g., `mdrfoithru2025.zip`), the library will automatically fall back to the most recent available file (e.g., `mdrfoithru2024.zip`) and show a warning. This is normal behavior and ensures you always get the latest available data.

### Download Parameters Explained

```python
db.add_years(
    years=1998,              # Which years to download
    tables=['device'],       # Which tables (device, text, patient)
    download=True,           # If False, only imports existing files
    data_dir='./maude_data', # Where to store/find ZIP files
    strict=True,             # If True, errors on missing files
    chunk_size=10000         # Rows per batch (advanced)
)
```

### Year Format Examples

```python
# Single year (int)
db.add_years(2020, ...)

# Multiple years (list)
db.add_years([2018, 2019, 2020], ...)

# Year range (string)
db.add_years('2018-2020', ...)  # Includes 2018, 2019, 2020

# Latest complete year
db.add_years('latest', ...)     # Currently 2024

# All available years (use with caution!)
db.add_years('all', ...)        # 1991-present
```

### Expected Download Times

| Years | Tables | Size | Time (typical) |
|-------|--------|------|---------------|
| 1998 | device | ~3MB | ~30 seconds |
| 2020 | device | ~45MB | ~2 minutes |
| 2020 | device, text | ~90MB | ~4 minutes |
| 2015-2020 | device, text | ~500MB | ~15 minutes |

Times vary by internet speed. Files are cached, so re-runs are instant.

## Basic Queries

Now that you have data, let's query it!

### Simple Count

```python
from maude_db import MaudeDatabase

db = MaudeDatabase('my_maude.db')

# Count all device records
result = db.query("SELECT COUNT(*) as count FROM device")
print(f"Total devices: {result['count'][0]:,}")

db.close()
```

Output: `Total devices: ~52,800` (for 2000 data)

### Search by Device Name

```python
db = MaudeDatabase('my_maude.db')

# Find catheter devices
result = db.query("""
    SELECT GENERIC_NAME, COUNT(*) as count
    FROM device
    WHERE GENERIC_NAME LIKE '%catheter%'
    GROUP BY GENERIC_NAME
    ORDER BY count DESC
    LIMIT 5
""")

print(result)
db.close()
```

**Note**: Use `GENERIC_NAME` (uppercase) for device table columns.

### Using Query Methods

Instead of raw SQL, use the convenience methods:

```python
db = MaudeDatabase('my_maude.db')

# Query by device name (partial match)
catheters = db.query_device(device_name='catheter')
print(f"Found {len(catheters)} catheter reports")

# First few rows
print(catheters.head())

db.close()
```

### Filter by Date Range

```python
# Download multiple years first
db.add_years('2018-2020', tables=['device'], download=True)

# Query with date filter
recent = db.query_device(
    device_name='pacemaker',
    start_date='2019-01-01',
    end_date='2019-12-31'
)

print(f"Pacemaker reports in 2019: {len(recent)}")
```

### Exploring with db.info()

The `info()` method shows your database contents:

```python
db = MaudeDatabase('my_maude.db')
db.info()
```

Output:
```
Database: my_maude.db
Tables: device
Years in database: 1998, 2019, 2020
Total records:
  device: 423,891
```

## Working with Results

Query results are returned as pandas DataFrames:

```python
results = db.query_device(device_name='stent')

# Show first 5 rows
print(results.head())

# Get specific columns
print(results[['GENERIC_NAME', 'BRAND_NAME']])

# Filter results further
drug_stents = results[results['GENERIC_NAME'].str.contains('drug', case=False)]

# Save to CSV
results.to_csv('stent_reports.csv', index=False)
```

### Working with Narratives

Download text data to get event descriptions:

```python
# Download text data
db.add_years(2020, tables=['device', 'text'], download=True)

# Get device events
devices = db.query_device(device_name='defibrillator')

# Get narratives for first 5 events
report_keys = devices['MDR_REPORT_KEY'].head(5).tolist()
narratives = db.get_narratives(report_keys)

# Show narratives
for idx, row in narratives.iterrows():
    print(f"\nReport {row['MDR_REPORT_KEY']}:")
    print(row['FOI_TEXT'][:200])  # First 200 characters
```

## Alternative: Using SQLite Tools Directly

If you prefer to work with SQLite tools (DB Browser, DBeaver, etc.) instead of Python, you can initialize a database and use it entirely through SQL queries.

### Why Use SQLite Tools?

**Benefits:**
- No Python programming required
- Visual data browsing
- Easy CSV export
- Familiar SQL interface
- Works with Excel, R, or other analysis tools

**When to use:**
- You're comfortable with SQL but not Python
- You want to export data to Excel or other tools
- You prefer visual database browsers
- You need to share data with non-programmers

### Quick Start with SQLite Tools

1. **Initialize the database:**
   ```bash
   cd /path/to/maude_db
   ./init_full_db.sh
   ```

2. **Follow the prompts:**
   - Enter year range (e.g., `2020-2024`)
   - Select tables (e.g., `1,2` for device and text)
   - Specify filename (e.g., `maude.db`)

3. **Open in SQLite tool:**
   - Download [DB Browser for SQLite](https://sqlitebrowser.org/) (free)
   - Open your `.db` file
   - Start querying!

4. **Try example queries:**
   - See [04_advanced_querying.ipynb](../notebooks/04_advanced_querying.ipynb)
   - Copy SQL queries from the notebook into your SQLite tool's SQL editor
   - Modify search terms for your research

### Complete SQLite Guide

For detailed instructions, see the **[SQLite Usage Guide](sqlite_guide.md)**, which covers:
- Installing and using SQLite tools
- Table structure and column names
- Example queries for common research tasks
- Exporting results to CSV
- Performance tips

### Using Both Approaches

You can use both Python and SQLite tools on the same database:
- Use Python for complex analysis and automation
- Use SQLite tools for quick queries and data exploration
- Export from either tool for use in R, Excel, etc.

The database file (`.db`) works with both approaches interchangeably.

## Next Steps

Now that you can download data and run basic queries, you're ready for:

### Interactive Tutorials

Check out the [`notebooks/`](../notebooks/) directory for interactive Jupyter notebooks:
- [`02_getting_started.ipynb`](../notebooks/02_getting_started.ipynb) - Similar to this tutorial
- [`03_trend_analysis_visualization.ipynb`](../notebooks/03_trend_analysis_visualization.ipynb) - Trend analysis with visualization
- [`04_advanced_querying.ipynb`](../notebooks/04_advanced_querying.ipynb) - Ready-to-use SQL queries

### Advanced Features

See the [API Reference](api_reference.md) for:
- `get_trends_by_year()` - Analyze trends over time
- `export_subset()` - Export filtered data
- Custom SQL queries with parameters
- Product code filtering

### Research Best Practices

See the [Research Guide](research_guide.md) for:
- Planning your analysis
- Data quality considerations
- Common research workflows (including SQL-only workflows)
- Reproducibility tips

### SQLite Tools

See the [SQLite Usage Guide](sqlite_guide.md) for:
- Detailed SQLite tool instructions
- SQL query examples
- Export and analysis workflows

### Troubleshooting

If you encounter issues, check [Troubleshooting](troubleshooting.md) for:
- Download problems
- Database errors
- Query issues
- Platform-specific problems

---

**Congratulations!** You've completed the getting started tutorial. You now know how to create a database, download MAUDE data, and run queries using Python or SQLite tools.