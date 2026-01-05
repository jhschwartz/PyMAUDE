# SQLite Tools Usage Guide

This guide shows how to use MAUDE databases with external SQLite tools, without writing any Python code.

## Table of Contents

1. [Getting Started with SQLite Tools](#getting-started-with-sqlite-tools)
2. [Opening Your Database](#opening-your-database)
3. [Understanding the Table Structure](#understanding-the-table-structure)
4. [Example SQL Queries](#example-sql-queries)
5. [Exporting Results](#exporting-results)
6. [Performance Tips](#performance-tips)

---

## Getting Started with SQLite Tools

### Recommended Tool: DB Browser for SQLite (Free)

**DB Browser for SQLite** is a free, open-source tool that works on Windows, macOS, and Linux.

**Download**: [https://sqlitebrowser.org/](https://sqlitebrowser.org/)

**Features**:
- Visual table browser
- SQL query editor with syntax highlighting
- Export to CSV, JSON, SQL
- Create, design, and edit database files
- Search and filter data
- No installation required (portable version available)

### Alternative Tools

| Tool | Platform | Cost | Best For |
|------|----------|------|----------|
| **DBeaver** | Windows, macOS, Linux | Free (Community Edition) | Power users, multi-database |
| **DataGrip** | Windows, macOS, Linux | Paid | Professional development |
| **SQLiteStudio** | Windows, macOS, Linux | Free | Lightweight, portable |
| **TablePlus** | macOS, Windows, Linux | Freemium | Modern UI |

All tools listed work with SQLite databases created by `maude_db`.

---

## Opening Your Database

### In DB Browser for SQLite

1. Launch DB Browser for SQLite
2. Click **"Open Database"** button (or File → Open Database)
3. Navigate to your database file (e.g., `maude.db`)
4. Click **"Open"**

The database will open and you'll see the table list in the left sidebar.

### In DBeaver

1. Launch DBeaver
2. Click **"Database"** → **"New Database Connection"**
3. Select **"SQLite"**
4. Click **"Next"**
5. Click **"Open"** next to "Path" and select your database file
6. Click **"Finish"**

### In Other Tools

Most SQLite tools have a similar workflow:
1. File → Open/Connect
2. Select SQLite as database type
3. Browse to your `.db` file
4. Connect/Open

---

## Understanding the Table Structure

Your MAUDE database contains these main tables:

### `device` Table

Contains device information for each adverse event report.

**Key Columns**:
- `MDR_REPORT_KEY` - Unique report identifier (links to other tables)
- `GENERIC_NAME` - Device type (e.g., "CATHETER, INTRAVASCULAR, THERAPEUTIC")
- `BRAND_NAME` - Brand name of the device
- `MANUFACTURER_D_NAME` - Manufacturer name
- `DEVICE_REPORT_PRODUCT_CODE` - FDA product code (e.g., "NIQ")
- `DATE_RECEIVED` - Date the report was received by FDA
- `MODEL_NUMBER` - Device model number
- `CATALOG_NUMBER` - Device catalog number
- `LOT_NUMBER` - Device lot number

**Important**: Column names in the `device` table are **UPPERCASE** (e.g., `GENERIC_NAME`, not `generic_name`).

**Example row**:
```
MDR_REPORT_KEY: 1234567
GENERIC_NAME: CATHETER, INTRAVASCULAR, THERAPEUTIC, LONG-TERM GREATER THAN 30 DAYS
BRAND_NAME: Trevo
MANUFACTURER_D_NAME: STRYKER NEUROVASCULAR
DEVICE_REPORT_PRODUCT_CODE: NIQ
```

### `text` Table

Contains narrative descriptions of adverse events.

**Key Columns**:
- `MDR_REPORT_KEY` - Report identifier (links to device table)
- `MDR_TEXT_KEY` - Unique text record identifier
- `TEXT_TYPE_CODE` - Type of text (e.g., "D" for device narrative)
- `FOI_TEXT` - The actual narrative text describing the event

**Important**: Column names in the `text` table are **UPPERCASE**.

**Example row**:
```
MDR_REPORT_KEY: 1234567
FOI_TEXT: "DEVICE FAILED TO RETRIEVE CLOT. PHYSICIAN SWITCHED TO ALTERNATIVE DEVICE."
```

### `patient` Table

Contains patient demographic and outcome information.

**Key Columns**:
- `mdr_report_key` - Report identifier (links to other tables)
- `patient_sequence_number` - Patient number (if multiple patients)
- `date_received` - Date report was received
- `sequence_number_outcome` - Outcome codes
- `sequence_number_treatment` - Treatment codes

**Important**: Column names in the `patient` table are **lowercase** (different from device/text).

### Joining Tables

Tables are linked using `MDR_REPORT_KEY`:

```sql
-- Example: Join device and text tables
SELECT d.GENERIC_NAME, d.BRAND_NAME, t.FOI_TEXT
FROM device d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY
WHERE d.GENERIC_NAME LIKE '%thrombectomy%'
LIMIT 10;
```

---

## Example SQL Queries

### Basic Queries

#### Count Total Device Reports

```sql
SELECT COUNT(*) as total_reports
FROM device;
```

#### Find Unique Device Types

```sql
SELECT DISTINCT GENERIC_NAME
FROM device
ORDER BY GENERIC_NAME;
```

#### Search for Specific Device

```sql
SELECT *
FROM device
WHERE GENERIC_NAME LIKE '%pacemaker%'
LIMIT 100;
```

**Tip**: Use `LIMIT` to preview results without loading the entire table.

#### Count Reports by Device Type

```sql
SELECT
    GENERIC_NAME,
    COUNT(*) as report_count
FROM device
GROUP BY GENERIC_NAME
ORDER BY report_count DESC
LIMIT 20;
```

### Intermediate Queries

#### Find Reports by Manufacturer

```sql
SELECT
    MANUFACTURER_D_NAME,
    COUNT(*) as report_count
FROM device
WHERE GENERIC_NAME LIKE '%stent%'
GROUP BY MANUFACTURER_D_NAME
ORDER BY report_count DESC;
```

#### Get Device Reports with Narratives

```sql
SELECT
    d.MDR_REPORT_KEY,
    d.GENERIC_NAME,
    d.BRAND_NAME,
    d.MANUFACTURER_D_NAME,
    t.FOI_TEXT
FROM device d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY
WHERE d.GENERIC_NAME LIKE '%catheter%'
LIMIT 50;
```

#### Search Narratives for Keywords

```sql
SELECT
    d.GENERIC_NAME,
    d.BRAND_NAME,
    t.FOI_TEXT
FROM device d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY
WHERE
    d.GENERIC_NAME LIKE '%thrombectomy%'
    AND t.FOI_TEXT LIKE '%fracture%'
LIMIT 25;
```

### Advanced Queries

#### Reports by Year

```sql
SELECT
    strftime('%Y', DATE_RECEIVED) as year,
    COUNT(*) as report_count
FROM device
WHERE GENERIC_NAME LIKE '%pacemaker%'
GROUP BY year
ORDER BY year;
```

#### Top Brands by Report Count

```sql
SELECT
    BRAND_NAME,
    MANUFACTURER_D_NAME,
    COUNT(*) as report_count
FROM device
WHERE GENERIC_NAME LIKE '%defibrillator%'
GROUP BY BRAND_NAME, MANUFACTURER_D_NAME
ORDER BY report_count DESC
LIMIT 10;
```

#### Sample Random Reports

```sql
SELECT *
FROM device
WHERE GENERIC_NAME LIKE '%insulin pump%'
ORDER BY RANDOM()
LIMIT 20;
```

#### Filter by Multiple Criteria

```sql
SELECT
    MDR_REPORT_KEY,
    GENERIC_NAME,
    BRAND_NAME,
    MANUFACTURER_D_NAME,
    DATE_RECEIVED
FROM device
WHERE
    GENERIC_NAME LIKE '%stent%'
    AND MANUFACTURER_D_NAME LIKE '%Medtronic%'
    AND DATE_RECEIVED >= '2020-01-01'
ORDER BY DATE_RECEIVED DESC;
```

---

## Exporting Results

### In DB Browser for SQLite

1. Run your query in the "Execute SQL" tab
2. Click **"Export to CSV"** button above the results
3. Choose location and filename
4. Click **"Save"**

**Or export entire table**:
1. Go to "Browse Data" tab
2. Select the table
3. Click **"File"** → **"Export"** → **"Table to CSV"**

### In DBeaver

1. Run your query
2. Right-click on the results grid
3. Select **"Export Data"**
4. Choose format (CSV, Excel, JSON, etc.)
5. Configure export options
6. Click **"Proceed"**

### In SQLiteStudio

1. Run your query
2. Click **"Tools"** → **"Export"**
3. Select **"Query results"**
4. Choose CSV format
5. Click **"Export"**

### Using SQL COPY Command (Advanced)

Some tools support exporting directly from SQL:

```sql
-- Note: Syntax varies by tool
.mode csv
.output my_results.csv
SELECT * FROM device WHERE GENERIC_NAME LIKE '%catheter%';
.output stdout
```

---

## Performance Tips

### Use LIMIT for Exploration

When exploring data, always use `LIMIT` to avoid loading millions of rows:

```sql
-- Good: Quick preview
SELECT * FROM device LIMIT 100;

-- Bad: Loads all rows (may be very slow)
SELECT * FROM device;
```

### Leverage Indexes

The database has indexes on key columns:
- `device.MDR_REPORT_KEY`
- `device.DEVICE_REPORT_PRODUCT_CODE`
- `text.MDR_REPORT_KEY`

Queries using these columns will be faster:

```sql
-- Fast (uses index)
SELECT * FROM device WHERE MDR_REPORT_KEY = 1234567;

-- Fast (uses index)
SELECT * FROM device WHERE DEVICE_REPORT_PRODUCT_CODE = 'NIQ';

-- Slower (no index, must scan all rows)
SELECT * FROM device WHERE MODEL_NUMBER = 'XYZ123';
```

### Use LIKE Efficiently

```sql
-- Faster: Pattern at end
WHERE GENERIC_NAME LIKE 'CATHETER%'

-- Slower: Pattern at start (can't use index)
WHERE GENERIC_NAME LIKE '%CATHETER'

-- Slowest: Pattern in middle
WHERE GENERIC_NAME LIKE '%CATHETER%'
```

### Filter Before Joining

```sql
-- Better: Filter first, then join
SELECT d.*, t.FOI_TEXT
FROM (SELECT * FROM device WHERE GENERIC_NAME LIKE '%stent%') d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY
LIMIT 100;

-- Okay but potentially slower
SELECT d.*, t.FOI_TEXT
FROM device d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY
WHERE d.GENERIC_NAME LIKE '%stent%'
LIMIT 100;
```

### Use COUNT for Quick Stats

Instead of loading all rows to count, use `COUNT(*)`:

```sql
-- Fast
SELECT COUNT(*) FROM device WHERE GENERIC_NAME LIKE '%pacemaker%';

-- Slow (loads all rows)
-- SELECT * FROM device WHERE GENERIC_NAME LIKE '%pacemaker%';
-- Then count rows in the tool
```

### Check Query Execution Plans

In most SQL tools, you can see how a query will execute:

```sql
EXPLAIN QUERY PLAN
SELECT * FROM device WHERE MDR_REPORT_KEY = 1234567;
```

Look for:
- **SEARCH** (good - using index)
- **SCAN** (slower - checking every row)

---

## Common Tasks

### Find All Reports for a Specific Device

```sql
SELECT
    MDR_REPORT_KEY,
    BRAND_NAME,
    DATE_RECEIVED,
    MANUFACTURER_D_NAME
FROM device
WHERE
    GENERIC_NAME LIKE '%your device name%'
ORDER BY DATE_RECEIVED DESC;
```

### Get Narratives for Those Reports

After finding report keys, get narratives:

```sql
SELECT
    MDR_REPORT_KEY,
    FOI_TEXT
FROM text
WHERE MDR_REPORT_KEY IN (1234567, 1234568, 1234569);
-- Replace with your actual report keys
```

### Export Filtered Data for Analysis

1. Create and test your query
2. Export results to CSV
3. Open CSV in Excel, R, Python, or your analysis tool

---

## Troubleshooting

### "Database is locked" error

- Close other programs accessing the database
- Only one program can write to SQLite at a time
- Multiple readers are fine

### Query is very slow

- Add `LIMIT` to test queries first
- Check if you're filtering on indexed columns
- Consider filtering before joining tables

### Results look incomplete

- Check if `LIMIT` is restricting results
- Verify your `WHERE` clause conditions
- Check for NULL values in key columns

### Column names don't match

- `device` and `text` tables use **UPPERCASE** column names
- `patient` table uses **lowercase** column names
- SQL is case-sensitive for column names in SQLite

---

## Next Steps

- Try the [example queries in notebook 04](../notebooks/04_advanced_querying.ipynb)
- Read the [Research Guide](research_guide.md) for analysis patterns
- See the [API Reference](api_reference.md) if you want to use Python
- Check [Troubleshooting](troubleshooting.md) for common issues

---

**Questions?** See the [MAUDE Overview](maude_overview.md) for background on the database structure and FDA reporting requirements.
