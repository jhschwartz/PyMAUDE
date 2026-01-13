# Research Guide

Practical guide for using MAUDE data in medical device research.

## Table of Contents

1. [Planning Your Analysis](#planning-your-analysis)
2. [Which Data to Download](#which-data-to-download)
3. [Common Analysis Patterns](#common-analysis-patterns)
4. [Data Quality Tips](#data-quality-tips)
5. [Working with Large Datasets](#working-with-large-datasets)
6. [Reproducibility](#reproducibility)
7. [Common Research Workflows](#common-research-workflows)
8. [Understanding Limitations](#understanding-limitations)
9. [Citing Your Work](#citing-your-work)

---

## Planning Your Analysis

### Define Your Research Question

Start with a clear, specific question:

**Good examples**:
- "How have thrombectomy device adverse events changed from 2015-2020?"
- "What are the most common failure modes for drug-eluting stents?"
- "How does event reporting differ between manufacturer vs. user facility reports?"

**Too vague**:
- "Are pacemakers safe?" (needs denominator data, causation)
- "What devices have problems?" (too broad)

### Determine Your Time Range

Consider:
- **Reporting changes**: FDA requirements have evolved
- **Device evolution**: Newer models may have different profiles
- **Sample size**: More years = more events but slower downloads
- **Recent data**: Latest year may be incomplete

**Quick start**: 3-5 recent years gives good trends without overwhelming data.

```python
# Good starting point for trend analysis
db.add_years('2018-2022', tables=['device'], download=True)
```

### Choose Your Device Scope

Options for identifying devices:

1. **Generic name**: Broad category (`'catheter'`, `'pacemaker'`)
2. **Product code**: Specific device type (`'NIQ'`)
3. **Brand name**: Specific manufacturer product (`'Trevo'`)

**Tip**: Start broad, then narrow:

```python
# Step 1: See what's available
all_catheters = db.query_device(device_name='catheter')
print(all_catheters['GENERIC_NAME'].value_counts())

# Step 2: Pick specific type
specific = db.query_device(device_name='intravascular catheter')
```

---

## Which Data to Download

### Essential Tables

**For most research**:
```python
db.add_years('2018-2020', tables=['device'], download=True)
```

- **device**: Device information (brand, generic name, manufacturer)
- Good for: Counting events, trends, device comparisons

**Add for richer analysis**:
```python
db.add_years('2018-2020', tables=['device', 'text'], download=True)
```

- **text**: Narrative descriptions of events
- Good for: Qualitative analysis, understanding failure modes

**Add for patient demographics**:
```python
db.add_years('2018-2020', tables=['device', 'patient'], download=True)
```

- **patient**: Age, outcomes, event dates
- Good for: Patient outcome analysis

### Disk Space Considerations

Approximate sizes per year:

| Tables | Size/Year | 5 Years Total |
|--------|-----------|---------------|
| device only | ~45 MB | ~225 MB |
| device + text | ~90 MB | ~450 MB |
| device + text + patient | ~100 MB | ~500 MB |

**Tip**: Start with device table, add others if needed.

### Master Table Note

The master table (MDRFOI) is only available as a comprehensive file covering all years:
- Very large (~1+ GB)
- Not downloaded automatically by `maude_db`
- Device table contains most key fields via joins

For most research, device + text tables are sufficient.

---

## Common Analysis Patterns

### Pattern 1: Count Events Over Time

```python
# Simple trend
trends = db.get_trends_by_year(device_name='pacemaker')
print(trends)

# Visualize
import matplotlib.pyplot as plt
plt.plot(trends['year'], trends['event_count'])
plt.xlabel('Year')
plt.ylabel('Events Reported')
plt.title('Pacemaker Adverse Events')
plt.show()
```

### Pattern 2: Compare Device Types

```python
# Get events for multiple device types
catheters = db.query_device(device_name='catheter')
stents = db.query_device(device_name='stent')

print(f"Catheter events: {len(catheters)}")
print(f"Stent events: {len(stents)}")
```

### Pattern 3: Identify Top Generic Names

```python
devices = db.query_device(start_date='2020-01-01', end_date='2020-12-31')

# Count by generic name
top_devices = devices['GENERIC_NAME'].value_counts().head(10)
print(top_devices)
```

### Pattern 4: Analyze Event Types

```python
results = db.query_device(device_name='defibrillator')

# Count event types
print(results['EVENT_TYPE'].value_counts())

# Filter to serious events using FDA abbreviations (D=Death, IN=Injury)
serious = results[results['EVENT_TYPE'].str.contains(r'\bD\b|\bIN\b', case=False, na=False, regex=True)]
print(f"Serious events: {len(serious)}/{len(results)}")
```

### Pattern 5: Examine Narratives

```python
# Get events
events = db.query_device(device_name='thrombectomy', start_date='2020-01-01')

# Sample some events
sample_keys = events['MDR_REPORT_KEY'].sample(10).tolist()

# Get narratives
narratives = db.get_narratives(sample_keys)

# Look for patterns
for idx, row in narratives.iterrows():
    text = row['FOI_TEXT'].lower()
    if 'fracture' in text or 'break' in text:
        print(f"Report {row['MDR_REPORT_KEY']}: {row['FOI_TEXT'][:150]}")
```

### Pattern 6: Filter by Manufacturer

```python
results = db.query_device(device_name='stent')

# Count by manufacturer
mfr_counts = results['manufacturer_d_name'].value_counts()
print(mfr_counts.head())

# Filter to specific manufacturer
medtronic = results[results['manufacturer_d_name'].str.contains('Medtronic', na=False, case=False)]
```

---

## Data Quality Tips

### Check for Completeness

```python
# How many events have narratives?
devices = db.query_device(device_name='catheter')
keys = devices['MDR_REPORT_KEY'].tolist()
narratives = db.get_narratives(keys)

print(f"Events: {len(devices)}")
print(f"With narratives: {len(narratives)}")
print(f"Coverage: {len(narratives)/len(devices)*100:.1f}%")
```

### Handle Missing Data

```python
results = db.query_device(device_name='pacemaker')

# Check for missing brand names
missing_brand = results['BRAND_NAME'].isna().sum()
print(f"Missing brand names: {missing_brand}/{len(results)}")

# Filter to complete records
complete = results.dropna(subset=['BRAND_NAME', 'GENERIC_NAME'])
```

### Understand Reporting Bias

Be aware that:
- **Voluntary reporting** is inconsistent
- **High-profile events** increase reporting temporarily
- **New devices** may have higher reporting (heightened awareness)
- **Old devices** may be underreported (less attention)

**Tip**: Use year-over-year trends to identify real patterns vs. reporting artifacts.

### Verify Unexpected Results

If you see surprising patterns:

```python
# Sudden spike in events?
trends = db.get_trends_by_year(device_name='insulin pump')
# Look at year-to-year changes

# Unusual event count?
devices = db.query_device(device_name='unusual_device')
# Check sample narratives to verify it's actually your target device
```

---

## Common Pitfalls and How to Avoid Them

### Pitfall 1: Counting Reports Instead of Events

**Problem**: Using MDR_REPORT_KEY for event counts inflates totals by ~8% because multiple sources can report the same event.

**Why it happens**: The same adverse event can be reported by the manufacturer, hospital, and patient, creating 2-3 reports with different MDR_REPORT_KEYs but the same EVENT_KEY.

**Solution**: Always check for EVENT_KEY duplication before calculating event counts.

```python
# INCORRECT - counts reports (includes duplicates)
results = db.query_device(device_name='catheter', start_date='2022-01-01')
report_count = len(results['MDR_REPORT_KEY'].unique())  # WRONG!
print(f"Events: {report_count}")  # Overcounts by ~8%

# CORRECT - check duplication and use events
duplication = db.count_unique_events(results)
print(f"Reports: {duplication['total_reports']}")
print(f"Events: {duplication['unique_events']}")
print(f"Duplication: {duplication['duplication_rate']:.1f}%")

if duplication['duplication_rate'] > 5:
    print("⚠️ Significant duplication detected - deduplicating")
    results = db.select_primary_report(results, strategy='first_received')

event_count = len(results)  # Now accurate
```

**When it matters**:
- ✅ Epidemiological analysis
- ✅ Incidence calculations
- ✅ Signal detection
- ✅ Event rate comparisons

**When it doesn't matter**:
- ❌ Reporting compliance analysis
- ❌ Comparing report sources (manufacturer vs facility)

**Example impact**:
```python
# Real example with venous stents
results = db.query_device(device_name='venous stent')
comparison = db.compare_report_vs_event_counts(results)
print(comparison)
#    report_count  event_count  inflation_pct
# 0          2156         1998           7.9
```

---

### Pitfall 2: Patient Outcome Inflation from Concatenation

**Problem**: When multiple patients share a report, OUTCOME fields concatenate sequentially, leading to massive overcounting (2-3x inflation).

**Why it happens**: MAUDE stores multi-patient reports with cumulative concatenation:
```
Report 1234567:
  Patient 1: OUTCOME = "D"          (death)
  Patient 2: OUTCOME = "D;H"        (death + hospitalization)
  Patient 3: OUTCOME = "D;H;L"      (death + hospitalization + life-threatening)
```

Patient 3's field contains ALL THREE patients' outcomes, not just patient 3's outcome!

**Solution**: Use smart aggregation to count each outcome once per report.

```python
# INCORRECT - naive counting inflates totals
results = db.query_device(device_name='stent', start_date='2022-01-01')
enriched = db.enrich_with_patient_data(results)

# This counts "D" three times in example above!
death_count = enriched['SEQUENCE_NUMBER_OUTCOME'].str.contains('D', na=False).sum()  # WRONG!

# CORRECT - count unique outcomes per report
outcome_summary = db.count_unique_outcomes_per_report(enriched)
death_count = (outcome_summary['unique_outcomes'].apply(lambda x: 'D' in x)).sum()
print(f"Reports with deaths: {death_count}")  # Accurate!

# Always check for affected reports
validation = db.detect_multi_patient_reports(enriched)
if validation['affected_percentage'] > 10:
    print(f"⚠️ {validation['affected_percentage']:.1f}% have multiple patients")
    print("   Using safe aggregation method")
```

**Example impact**:
```python
# Demonstrate inflation
patient_data = db.enrich_with_patient_data(results)

# Naive method
naive_df = patient_data.copy()
naive_df['outcome_list'] = naive_df['SEQUENCE_NUMBER_OUTCOME'].apply(
    lambda x: [c.strip() for c in str(x).split(';') if c.strip()]
)
naive_deaths = sum('D' in outcomes for outcomes in naive_df['outcome_list'])

# Correct method
outcome_summary = db.count_unique_outcomes_per_report(patient_data)
correct_deaths = sum('D' in outcomes for outcomes in outcome_summary['unique_outcomes'])

print(f"Naive count: {naive_deaths}")
print(f"Correct count: {correct_deaths}")
print(f"Inflation: {(naive_deaths/correct_deaths - 1)*100:.1f}%")
# Output: Inflation: 187.3%  (nearly 3x overcounting!)
```

**When it matters**:
- ✅ **Any outcome analysis** (deaths, hospitalizations, injuries)
- ✅ Safety comparisons between devices
- ✅ Adverse event rate calculations

**Reference**: Ensign & Cohen (2017) "A Primer to the Structure, Content and Linkage of the FDA's MAUDE Files", Tables 4a-4b, pp. 14-16.

---

### Pitfall 3: Device Sequence Assumptions

**Problem**: Assuming one device per report. A single adverse event can involve multiple devices.

**Example**: Patient has pacemaker and defibrillator malfunction in same event → 2 device records, 1 master record.

**Solution**: Always account for DEVICE_SEQUENCE_NUMBER.

```python
results = db.query_device(device_name='pacemaker')

# Count unique reports (events)
report_count = results['MDR_REPORT_KEY'].nunique()

# Count total devices involved (may be higher)
device_count = len(results)

print(f"Reports: {report_count}")
print(f"Devices involved: {device_count}")
print(f"Avg devices per report: {device_count/report_count:.2f}")

if device_count > report_count:
    print(f"⚠️ {device_count - report_count} reports involve multiple devices")
```

---

### Pitfall 4: Case-Sensitive Searches

**Problem**: Missing results due to inconsistent capitalization in MAUDE data.

**Example**:
```python
# May miss "VENOUS STENT", "Venous Stent", "venous stent"
results = db.query_device(device_name='venous stent')  # ✓ Handled automatically

# But raw SQL requires UPPER()
results = db.query(
    "SELECT * FROM device WHERE UPPER(GENERIC_NAME) LIKE UPPER('%venous stent%')"
)
```

**Solution**: PyMAUDE's `query_device()` automatically handles case-insensitive matching. If writing raw SQL, always use `UPPER()` on both sides.

---

### Best Practices Checklist

Before publishing results:

- [ ] **Check EVENT_KEY duplication**: Run `count_unique_events()` and deduplicate if >5%
- [ ] **Verify patient outcomes**: Run `detect_multi_patient_reports()` and use `count_unique_outcomes_per_report()`
- [ ] **Document deduplication method**: Report which EVENT_KEY strategy used (first_received, manufacturer, most_complete)
- [ ] **Check device sequences**: Report if multiple devices per event affect analysis
- [ ] **Validate date ranges**: Confirm start/end dates match intended study period
- [ ] **Review sample narratives**: Spot-check that device name matches intended device
- [ ] **Report data quality**: Include duplication rates, missing data percentages

**Example methods section text**:
> "We queried the FDA MAUDE database for [device name] from [start] to [end].
> Multiple reports of the same event (EVENT_KEY duplication) occurred in X.X% of
> reports; we deduplicated to the first received report per event. Patient outcome
> data was aggregated to prevent inflation from multi-patient concatenation
> (Ensign & Cohen, 2017). [N] reports involved multiple devices; we analyzed at
> the device level where appropriate."

---

## Working with Large Datasets

### Efficient Querying

**Do**: Filter early
```python
# Good - filter in query
recent_pacers = db.query_device(
    device_name='pacemaker',
    start_date='2020-01-01'
)
```

**Don't**: Load everything then filter
```python
# Inefficient
all_devices = db.query("SELECT * FROM device")  # Loads millions of rows
pacers = all_devices[all_devices['GENERIC_NAME'].str.contains('pacemaker')]
```

### Chunked Processing

For very large result sets:

```python
# Process in chunks
query = """
    SELECT MDR_REPORT_KEY, GENERIC_NAME
    FROM device
    WHERE GENERIC_NAME LIKE '%catheter%'
"""

for chunk in pd.read_sql_query(query, db.conn, chunksize=10000):
    # Process each chunk
    print(f"Processing {len(chunk)} records...")
    # Your analysis here
```

### Memory Management

```python
# Free memory after large operations
import gc

large_result = db.query_device(device_name='catheter')
# ... use large_result ...
del large_result
gc.collect()
```

---

## Reproducibility

### Document Your Setup

Create a README for your project:

```markdown
# My Analysis

## Environment
- Python 3.9.7
- maude_db version: [commit hash or release]
- Analysis date: 2025-12-29

## Data
- Years: 2018-2020
- Tables: device, text
- Downloaded: 2025-12-29
- FDA MAUDE access: https://www.fda.gov/...
```

### Save Your Queries

Keep analysis scripts:

```python
# analysis.py
from pymaude import MaudeDatabase

# Setup
db = MaudeDatabase('maude_2018_2020.db')

# Analysis 1: Trend analysis
trends = db.get_trends_by_year(device_name='thrombectomy')
trends.to_csv('results/thrombectomy_trends.csv', index=False)

# Analysis 2: Event type breakdown
events = db.query_device(device_name='thrombectomy')
breakdown = events['event_type'].value_counts()
breakdown.to_csv('results/event_type_breakdown.csv')
```

### Version Your Database

```bash
# Create dated database snapshots
cp maude.db backups/maude_2025-12-29.db
```

### Track Data Versions

```python
# Save metadata with results
import datetime

metadata = {
    'analysis_date': datetime.date.today().isoformat(),
    'database': 'maude.db',
    'years': '2018-2020',
    'device': 'thrombectomy',
    'event_count': len(results)
}

import json
with open('results/metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)
```

---

## Common Research Workflows

### Workflow 1: Device Safety Surveillance

**Goal**: Monitor adverse events for a specific device type

```python
db = MaudeDatabase('surveillance.db')

# Download recent years
db.add_years('2020-2023', tables=['device', 'text'], download=True)

# Query device
events = db.query_device(device_name='insulin pump')

# Analyze trends
trends = db.get_trends_by_year(device_name='insulin pump')

# Identify serious events using FDA abbreviations (D=Death, IN=Injury)
serious = events[events['EVENT_TYPE'].str.contains(r'\bD\b|\bIN\b', case=False, na=False, regex=True)]

# Examine narratives of serious events
serious_keys = serious['MDR_REPORT_KEY'].head(20).tolist()
narratives = db.get_narratives(serious_keys)

# Export for detailed review
serious.to_csv('serious_events.csv', index=False)
```

### Workflow 2: Comparative Device Study Using Device Catalog

**Goal**: Compare safety profiles across multiple specific devices from a structured list

This workflow is ideal when you have a table or list of devices to compare (e.g., from a product specification sheet, literature review, or clinical comparison table).

```python
db = MaudeDatabase('comparison.db')
db.add_years('2019-2024', tables=['device'], download=True)

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
        'pma_pmn_numbers': []
    },
    {
        'device_id': 'PENUMBRA_INDIGO',
        'search_terms': ['Penumbra Indigo', 'Indigo System'],
        'pma_pmn_numbers': ['P180013']
    },
    {
        'device_id': 'INARI_FLOWTRIEVER',
        'search_terms': ['FlowTriever', 'Inari FlowTriever'],
        'pma_pmn_numbers': ['P200026']
    },
]

# Query all devices at once
results = db.query_device_catalog(devices, start_date='2019-01-01', end_date='2024-12-31')

print(f"Total reports across all devices: {len(results)}")

# Compare event counts by device
print("\nEvent counts by device:")
device_counts = results.groupby('device_id').size().sort_values(ascending=False)
print(device_counts)

# Compare event types across devices
print("\nEvent type breakdown by device:")
for device_id in results['device_id'].unique():
    device_data = results[results['device_id'] == device_id]
    breakdown = db.event_type_breakdown_for(device_data)
    print(f"\n{device_id}:")
    print(f"  Total: {breakdown['total']}")
    print(f"  Deaths: {breakdown['deaths']}")
    print(f"  Injuries: {breakdown['injuries']}")
    print(f"  Malfunctions: {breakdown['malfunctions']}")

# Visualize trends over time by device
import matplotlib.pyplot as plt

for device_id in results['device_id'].unique():
    device_data = results[results['device_id'] == device_id]
    trends = db.trends_for(device_data)
    plt.plot(trends['year'], trends['event_count'], label=device_id, marker='o')

plt.xlabel('Year')
plt.ylabel('Event Count')
plt.title('Adverse Events by Device Over Time')
plt.legend()
plt.grid(True, alpha=0.3)
plt.show()

# Export for further analysis
results.to_csv('device_comparison_results.csv', index=False)
```

**Alternative: Simple Two-Device Comparison**

For comparing just two devices without a structured catalog:

```python
db = MaudeDatabase('comparison.db')
db.add_years('2018-2022', tables=['device'], download=True)

# Get events for each device
device_a = db.query_device(device_name='Brand A Device')
device_b = db.query_device(device_name='Brand B Device')

# Compare event types
print("Device A event types:")
print(device_a['EVENT_TYPE'].value_counts())

print("\nDevice B event types:")
print(device_b['EVENT_TYPE'].value_counts())
```

### Workflow 3: Failure Mode Analysis

**Goal**: Identify common device failure patterns

```python
db = MaudeDatabase('failure_modes.db')
db.add_years('2020-2022', tables=['device', 'text'], download=True)

# Get device events
events = db.query_device(device_name='cardiac catheter')

# Get all narratives
keys = events['MDR_REPORT_KEY'].tolist()
narratives = db.get_narratives(keys)

# Search narratives for failure keywords
keywords = ['fracture', 'break', 'disconnect', 'leak', 'malfunction']

for keyword in keywords:
    count = narratives['FOI_TEXT'].str.contains(keyword, case=False, na=False).sum()
    print(f"{keyword}: {count} mentions")

# Extract examples
fractures = narratives[narratives['FOI_TEXT'].str.contains('fracture', case=False, na=False)]
print(f"\n{len(fractures)} fracture-related events")
```

### Workflow 4: Temporal Analysis

**Goal**: Identify when event reporting changed

```python
db = MaudeDatabase('temporal.db')
db.add_years('2015-2023', tables=['device'], download=True)

# Get long-term trends
trends = db.get_trends_by_year(device_name='pacemaker')

# Calculate year-over-year changes
trends['yoy_change'] = trends['event_count'].pct_change() * 100

print("Year-over-year change in reporting:")
print(trends[['year', 'event_count', 'yoy_change']])

# Identify notable changes
notable = trends[abs(trends['yoy_change']) > 20]
print(f"\nYears with >20% change: {notable['year'].tolist()}")
```

### Workflow 5: SQLite-Only Research

**Goal**: Conduct research using only SQLite tools (no Python coding)

This workflow is ideal for researchers comfortable with SQL but not Python, or those who want to export data for analysis in Excel, R, or other tools.

#### Step 1: Initialize Database

```bash
cd /path/to/maude_db
./init_full_db.sh
```

Follow prompts:
- Year range: `2018-2024`
- Tables: `1,2` (device and text)
- Filename: `my_research.db`

#### Step 2: Open in SQLite Tool

- Download [DB Browser for SQLite](https://sqlitebrowser.org/) (free, cross-platform)
- Open `my_research.db`

#### Step 3: Explore Data

```sql
-- Check what's in the database
SELECT COUNT(*) FROM device;

-- Find your device type
SELECT DISTINCT GENERIC_NAME
FROM device
WHERE GENERIC_NAME LIKE '%your_device%'
ORDER BY GENERIC_NAME;
```

#### Step 4: Run Analysis Queries

See [04_advanced_querying.ipynb](../notebooks/04_advanced_querying.ipynb) for ready-to-use queries:

```sql
-- Count events by year
SELECT
    strftime('%Y', DATE_RECEIVED) as year,
    COUNT(*) as report_count
FROM device
WHERE GENERIC_NAME LIKE '%pacemaker%'
GROUP BY year
ORDER BY year;

-- Get reports with narratives
SELECT
    d.GENERIC_NAME,
    d.BRAND_NAME,
    d.MANUFACTURER_D_NAME,
    t.FOI_TEXT
FROM device d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY
WHERE d.GENERIC_NAME LIKE '%your_device%'
LIMIT 100;
```

#### Step 5: Export Results

**In DB Browser for SQLite:**
1. Run your query
2. Click "Export to CSV" button
3. Save the results

**In DBeaver:**
1. Run your query
2. Right-click results → "Export Data"
3. Choose CSV, Excel, or other format

#### Step 6: Analyze Exported Data

- Open CSV in Excel for charts and pivot tables
- Import into R or Python for statistical analysis
- Use Tableau, PowerBI for visualization
- Share with collaborators

#### Example Research Workflow

**Research Question**: "How have pacemaker adverse events changed over time?"

1. **Initialize database** with years 2015-2024, device and text tables
2. **Query device counts** by year (SQL query)
3. **Export to CSV**
4. **Create chart in Excel** showing trends
5. **Sample narratives** for qualitative analysis (SQL query with RANDOM())
6. **Export narratives to CSV** for thematic coding
7. **Combine quantitative and qualitative findings**

#### Benefits of SQLite-Only Workflow

- **No coding required**: Just SQL queries
- **Visual interface**: Browse data in tables
- **Easy export**: CSV works everywhere
- **Shareable**: Send database file to collaborators
- **Flexible**: Can always add Python later if needed

#### Tips for SQLite Workflows

1. **Start broad, then narrow**: First count total, then filter
2. **Use LIMIT**: Preview before exporting large results
3. **Save queries**: Keep a text file of useful queries
4. **Check the guide**: See [sqlite_guide.md](sqlite_guide.md) for detailed instructions
5. **Export early**: Get data into your preferred analysis tool

#### When to Consider Python

Switch to Python API when you need:
- Complex data transformations
- Automated workflows
- Statistical analysis in Python
- Integration with pandas, scikit-learn, etc.

The database works with both approaches - use what fits your skills and needs!

---

## Understanding Limitations

### What MAUDE Can Tell You

- **Adverse events occurred**: Reports document what happened
- **Patterns exist**: Trends and common issues
- **Signals for investigation**: Potential safety concerns

### What MAUDE Cannot Tell You

- **Causation**: Reports don't prove device caused event
- **Incidence rates**: No denominator (devices in use)
- **Comparison across devices**: Different usage rates, reporting patterns
- **Complete picture**: Voluntary reporting means many events unreported

### Using MAUDE Responsibly

**Do**:
- Use for signal detection and hypothesis generation
- Combine with other data sources (literature, registries)
- Consider reporting biases in interpretation
- Note limitations in publications

**Don't**:
- Claim causation from MAUDE data alone
- Compare raw counts across dissimilar devices
- Assume absence of reports means device is safe
- Use single reports as definitive evidence

### Example Methods Section

For publications using MAUDE data:

> We analyzed FDA MAUDE adverse event reports for [device type] from [years].
> MAUDE contains voluntary and mandatory reports of device-related deaths,
> injuries, and malfunctions. Reports are unverified allegations and do not
> establish causation. We used MAUDE data for signal detection and hypothesis
> generation, recognizing inherent reporting biases and the lack of denominator
> data on total devices in use. Analysis was performed using the maude_db
> Python library (version X.X, Schwartz 2025).

---

## Citing Your Work

### Citing MAUDE Data

Always cite the FDA database:

```
U.S. Food and Drug Administration. (2024). MAUDE - Manufacturer and User
Facility Device Experience Database. Retrieved [date] from
https://www.fda.gov/medical-devices/mandatory-reporting-requirements-manufacturers-importers-and-device-user-facilities/manufacturer-and-user-facility-device-experience-database-maude
```

### Citing This Library

```
Schwartz, J. (2025). maude_db: A Python library for FDA MAUDE database analysis.
https://github.com/jhschwartz/maude_db
```

### In-Text Example

> We queried the FDA MAUDE database (FDA 2024) using the maude_db Python
> library (Schwartz 2025) for all adverse event reports involving thrombectomy
> devices from 2018-2022.

### Data Availability Statement

> FDA MAUDE data is publicly available at https://www.fda.gov/medical-devices/
> [...]. Our analysis code and processed datasets are available at [your repo].

---

## Next Steps

- **API Reference**: See [api_reference.md](api_reference.md) for complete method documentation
- **Interactive Tutorials**: Check [`notebooks/`](../notebooks/) for Jupyter notebooks with working examples
- **Troubleshooting**: See [troubleshooting.md](troubleshooting.md) for common issues

**Questions?** Open an issue on GitHub or consult the FDA MAUDE documentation.