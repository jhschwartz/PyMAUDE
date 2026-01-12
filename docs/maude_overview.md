# MAUDE Database Overview

This document provides background on the FDA MAUDE database for researchers using the `PyMAUDE` library.

## What is MAUDE?

MAUDE (Manufacturer and User Facility Device Experience) is the FDA's database for medical device adverse event reports. It contains reports of device malfunctions, injuries, and deaths associated with medical devices.

The database is maintained by the FDA's Center for Devices and Radiological Health (CDRH) and is publicly accessible under the Freedom of Information Act (FOI).

For detailed regulatory information, see the [official FDA MAUDE documentation](https://www.fda.gov/medical-devices/mandatory-reporting-requirements-manufacturers-importers-and-device-user-facilities/manufacturer-and-user-facility-device-experience-database-maude).

## Data Sources

MAUDE contains adverse event reports from three primary sources:

1. **Mandatory Manufacturer Reports**: Device manufacturers must report deaths, serious injuries, and malfunctions
2. **Voluntary Reports**: Healthcare facilities, patients, and caregivers may submit reports
3. **User Facility Reports**: Hospitals and nursing homes must report deaths and serious injuries

The FDA updates MAUDE monthly with new reports.

## MAUDE Table Structure

The MAUDE database is organized into several related tables. The `PyMAUDE` library supports the most commonly used tables:

### Master Table (MDRFOI)

**Purpose**: Core event-level information

**Key columns**:
- `MDR_REPORT_KEY` - Unique identifier for each adverse event report
- `EVENT_KEY` - Groups multiple reports of the same event (see critical note below)
- `DATE_RECEIVED` - When FDA received the report
- `EVENT_TYPE` - Type of event (Death, Injury, Malfunction, or combinations)
- `MANUFACTURER_NAME` - Name of device manufacturer
- `REPORT_SOURCE_CODE` - Source of report (manufacturer, user facility, etc.)

**CRITICAL: Understanding EVENT_KEY vs MDR_REPORT_KEY**

Not all MDR_REPORT_KEYs represent unique events! The same adverse event can be reported by multiple sources (manufacturer, hospital, patient), creating multiple reports with different MDR_REPORT_KEYs but the same EVENT_KEY.

- **EVENT_KEY**: Groups reports of the same adverse event (~8% of reports share EVENT_KEY)
- **MDR_REPORT_KEY**: Unique identifier for each report submission

**Impact on Analysis**:
- Counting by MDR_REPORT_KEY overcounts events by approximately 8%
- Use EVENT_KEY for: Event counts, incidence rates, epidemiological analysis
- Use MDR_REPORT_KEY for: Report source analysis, reporting compliance studies

**Example**:
```python
# Count reports (may include duplicates)
report_count = len(results['MDR_REPORT_KEY'].unique())

# Count unique events (deduplicated)
event_count = len(results['EVENT_KEY'].unique())

# Compare and get details
duplication = db.count_unique_events(results)
print(f"Reports: {duplication['total_reports']}")
print(f"Events: {duplication['unique_events']}")
print(f"Duplication rate: {duplication['duplication_rate']:.1f}%")

# Deduplicate to one report per event
deduplicated = db.select_primary_report(results, strategy='first_received')
```

**Availability**: Only available as cumulative files:
- Historical data: `mdrfoithru2025.zip` (all data through previous year; filename updates annually)
- Current year: `mdrfoi.zip` (current year data only; e.g., 2026 as of January 2026)

**Note**: The library automatically uses batch processing to efficiently extract requested years from the cumulative file in a single pass, providing ~29x speedup compared to naive year-by-year processing.

### Device Table (FOIDEV)

**Purpose**: Device-specific information for each report

**Key columns**:
- `MDR_REPORT_KEY` - Links to master table (note: **uppercase** in actual data)
- `DEVICE_REPORT_PRODUCT_CODE` - FDA product code identifying device type
- `GENERIC_NAME` - Generic device name
- `BRAND_NAME` - Brand/trade name of device
- `MANUFACTURER_D_NAME` - Device manufacturer
- `DEVICE_SEQUENCE_NUMBER` - Multiple devices can be involved in one event

**Availability**: Individual year files from 2000-present (`device[year].zip`)

**Note**: Pre-2000 data uses an incompatible schema (contains BASELINE_* columns instead of COMBINATION_PRODUCT_FLAG, UDI fields) and is not supported.

### Text Table (FOITEXT)

**Purpose**: Narrative descriptions of adverse events

**Key columns**:
- `MDR_REPORT_KEY` - Links to master table (**uppercase**)
- `MDR_TEXT_KEY` - Identifier for this text record
- `TEXT_TYPE_CODE` - Type of narrative (D=description, E=evaluation, etc.)
- `FOI_TEXT` - Actual narrative text describing the event

**Availability**: Individual year files from 2000-present (`foitext[year].zip`)

### Patient Table (PATIENT)

**Purpose**: Patient demographic information

**Key columns**:
- `MDR_REPORT_KEY` - Links to master table
- `PATIENT_SEQUENCE_NUMBER` - Multiple patients can be involved in one event
- `DATE_OF_EVENT` - When adverse event occurred
- `SEQUENCE_NUMBER_TREATMENT` - Treatment information
- `SEQUENCE_NUMBER_OUTCOME` - Patient outcome codes

**CRITICAL DATA QUALITY ISSUE: OUTCOME Field Concatenation**

When multiple patients are involved in a single report (same MDR_REPORT_KEY), the OUTCOME and TREATMENT fields concatenate sequentially across patients, causing serious overcounting.

**The Problem**:
```
MDR_REPORT_KEY | PATIENT_SEQ | SEQUENCE_NUMBER_OUTCOME
1234567        | 1           | D
1234567        | 2           | D;H         ← Contains patient 1's + patient 2's outcomes
1234567        | 3           | D;H;L       ← Contains ALL patients' outcomes
```

Patient 3's field contains outcomes for ALL THREE patients, not just patient 3. Naive counting produces greatly inflated totals.

**Impact**: Approximately X% of reports have multiple patients (varies by year and device type). Without proper handling, outcome counts can be inflated by 2-3x.

**Solution - Use Provided Utilities**:
```python
# Safe aggregation - counts each outcome once per report
patient_data = db.enrich_with_patient_data(results)
outcome_summary = db.count_unique_outcomes_per_report(patient_data)

# Count total deaths (avoiding concatenation inflation)
deaths = (outcome_summary['unique_outcomes'].apply(lambda x: 'D' in x)).sum()
print(f"Reports with at least one death: {deaths}")

# Detect affected reports
validation = db.detect_multi_patient_reports(patient_data)
if validation['multi_patient_reports'] > 0:
    print(f"Warning: {validation['affected_percentage']:.1f}% have multiple patients")
```

**Reference**: This issue is documented in Ensign & Cohen (2017) "A Primer to the Structure, Content and Linkage of the FDA's MAUDE Files", Tables 4a and 4b, pages 14-16.

**Availability**: Only available as cumulative files:
- Historical data: `patientthru2025.zip` (all data through previous year; filename updates annually)
- Current year: `patient.zip` (current year data only; e.g., 2026 as of January 2026)

Patient data is distributed as a single large cumulative file (117MB compressed, 841MB uncompressed) containing all historical records. The library uses batch processing to efficiently filter this file and extract only the requested years in a single pass.

### Device Problem Table (FOIDEVPROBLEM)

**Purpose**: Coded device problem classifications

**Key columns**:
- `MDR_REPORT_KEY` - Links to master table
- `DEVICE_SEQUENCE_NUMBER` - Which device (if multiple)
- `DEVICE_PROBLEM_CODE` - Standardized problem code

**Availability**: Individual year files from 2019-present (recent years only)

## Entity Relationships

```
MASTER (MDR_REPORT_KEY)
  |
  +-- DEVICE (MDR_REPORT_KEY) [1:many]
  |     |
  |     +-- DEVICE_PROBLEM (MDR_REPORT_KEY, DEVICE_SEQUENCE_NUMBER) [1:many]
  |
  +-- TEXT (MDR_REPORT_KEY) [1:many]
  |
  +-- PATIENT (MDR_REPORT_KEY) [1:many]
```

One adverse event report (master) can involve:
- Multiple devices
- Multiple narrative text records
- Multiple patients
- Multiple device problems

## Important: Column Name Case

**Critical for queries**: The actual FDA data files use **UPPERCASE** column names for all tables:

- All tables use uppercase: `MDR_REPORT_KEY`, `DEVICE_REPORT_PRODUCT_CODE`, `GENERIC_NAME`, `BRAND_NAME`, `DATE_RECEIVED`, `EVENT_TYPE`, `FOI_TEXT`, etc.

When writing SQL queries directly, always use uppercase column names:

```python
# Correct - uppercase column names
db.query("SELECT GENERIC_NAME, BRAND_NAME FROM device")
db.query("SELECT EVENT_TYPE, DATE_RECEIVED FROM master")

# Incorrect - will fail
db.query("SELECT generic_name FROM device")  # Error: no such column
db.query("SELECT event_type FROM master")    # Error: no such column
```

The `PyMAUDE` query methods handle joins automatically using the correct case.

## Data Availability by Year

| Table | Supported Years | File Pattern | Notes |
|-------|----------------|--------------|-------|
| Master (MDRFOI) | **2000-present** | `mdrfoithru[year].zip` | Cumulative file only (~150MB), filtered by year automatically; filename updates annually |
| Device (FOIDEV) | **2000-present** | `device[year].zip` (2000-2025)<br>`device.zip` (current year) | Schema changed in 2000 |
| Text (FOITEXT) | **2000-present** | `foitext[year].zip` | ~45MB per year |
| Patient | **2000-present** | `patientthru[year].zip` | Cumulative file only (117MB compressed, 841MB uncompressed), filtered by year automatically; filename updates annually |
| Device Problem | **2019-present** | `foidevproblem[year].zip` | Recent years only |

**Note**: All tables start at 2000 for consistency (device table had a schema change in 2000).

### Current Year Support (2026)

For the current year, files use yearless names:
- `device.zip` instead of `device2026.zip`
- `foitext.zip` instead of `foitext2026.zip`
- `mdrfoi.zip` instead of `mdrfoithru2026.zip`
- `patient.zip` instead of `patientthru2026.zip`

**Note**: This section updates yearly. Check the FDA website for the most recent file naming conventions.

### Legacy Data NOT Supported

The library does **not** support legacy "thru" files that were used before individual year files existed:
- `foidevthru1997.zip` - NOT supported
- `foitextthru1995.zip` - NOT supported

If you need data before the supported year ranges, you would need to manually download and process these legacy files.

### Incremental Updates

The library currently does **not** support monthly incremental update files (`*add.zip`, `*change.zip`). Only full year files are supported. For the most current data, use the current year yearless files (e.g., `device.zip` for 2026).

The `PyMAUDE` library automatically handles the different naming conventions and filters cumulative files to extract only the requested years.

## Understanding FDA Product Codes

Each medical device has a three-letter FDA product code that classifies its type. Examples:

- `NIQ` - Catheter, Intravascular, Therapeutic, Short-term Less Than 30 Days
- `DQY` - Pacemaker, Implantable
- `DSM` - Stent, Coronary, Drug-Eluting

**Looking up product codes**:
- [FDA Product Classification Database](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpcd/classification.cfm)
- Use `DEVICE_REPORT_PRODUCT_CODE` column in device table

Product codes are useful for precise device queries:

```python
# More precise than searching by name
devices = db.query_device(product_code='NIQ')
```

## Data Quality Considerations

### Reporting Biases

- **Voluntary reporting**: Not all adverse events are reported
- **Publicity effect**: High-profile device problems may increase reporting
- **Regulatory changes**: Reporting requirements have changed over time
- **Multiple reports**: Same event may generate multiple reports

### Missing Data

- Not all fields are populated in every report
- Narratives may be redacted to protect patient privacy
- Some manufacturers provide more complete data than others

### Using MAUDE Data Responsibly

- MAUDE data **cannot** establish causation between device and adverse event
- Reports are **unverified** - they represent allegations, not confirmed facts
- Use for **signal detection** and **hypothesis generation**, not definitive conclusions
- Always consider denominator (devices in use) when interpreting event counts

## FDA Resources

- **MAUDE Web Interface**: [https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/search.cfm](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/search.cfm)
- **Data Files**: [https://www.fda.gov/medical-devices/mandatory-reporting-requirements-manufacturers-importers-and-device-user-facilities/manufacturer-and-user-facility-device-experience-database-maude](https://www.fda.gov/medical-devices/mandatory-reporting-requirements-manufacturers-importers-and-device-user-facilities/manufacturer-and-user-facility-device-experience-database-maude)
- **Product Code Database**: [https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpcd/classification.cfm](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpcd/classification.cfm)
- **File Format Documentation**: Included in ZIP downloads from FDA

---

**Next**: See [getting_started.md](getting_started.md) for hands-on tutorial using `PyMAUDE`.