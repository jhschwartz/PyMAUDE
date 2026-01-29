# Systematic Review Guide

Complete guide to conducting systematic device reviews with PyMAUDE following PRISMA 2020 and RECORD guidelines.

## Overview

PyMAUDE provides tools for reproducible, transparent systematic reviews of FDA MAUDE adverse event data. This guide covers:

- PRISMA/RECORD methodology for MAUDE data
- DeviceSearchStrategy workflow
- Adjudication best practices
- Complete workflow example
- PRISMA flow diagram generation

## PRISMA 2020 & RECORD

### PRISMA 2020

[PRISMA 2020](https://www.prisma-statement.org/) (Preferred Reporting Items for Systematic Reviews and Meta-Analyses) provides reporting guidelines for systematic reviews. Key items relevant to MAUDE:

- **Item 7**: Document search strategy with full boolean criteria
- **Item 8**: Describe selection process and screening methods
- **Item 16**: PRISMA flow diagram showing study selection
- **Item 27**: Make data, code, and materials available

### RECORD

[RECORD](https://www.record-statement.org/) extends PRISMA for routinely collected health data. Key additions:

- **RECORD 1.2-1.3**: Provide access to code lists (device search criteria)
- **RECORD 1.4**: Describe data cleaning and linkage methods
- **RECORD 1.5**: Document database linkage procedures

### Applying to MAUDE

MAUDE data requires special consideration:
- **Voluntary reporting**: Not all adverse events are reported
- **Data quality**: ~90% have device info, ~25% have patient outcomes
- **EVENT_KEY duplication**: ~8% of reports share EVENT_KEY (same event, multiple sources)
- **Linkage**: MDR_REPORT_KEY joins master/device/patient/text tables

---

## Workflow Overview

### Step 1: Define Search Strategy

Create a `DeviceSearchStrategy` documenting your inclusion criteria.

```python
from pymaude import DeviceSearchStrategy

strategy = DeviceSearchStrategy(
    name="venous_stent",
    description="Venous stents for iliofemoral thrombosis",
    version="1.0.0",
    author="Your Name",

    # Broad search: Cast wide net
    broad_criteria=[
        ['venous', 'stent'],
        ['venovo'],
        ['zilver', 'vena']
    ],

    # Narrow search: Refined criteria
    narrow_criteria=[
        ['venous', 'stent'],
        ['iliofemoral', 'stent']
    ],

    # Known false positives
    exclusion_patterns=[
        'arterial',
        'coronary',
        'biliary'
    ],

    search_rationale="""
    Venous stents are identified by generic name ('venous stent') or
    brand names (Venovo, Zilver Vena). Broad search captures variants,
    narrow search focuses on clinical indication. Exclusion patterns
    remove arterial/coronary stents (different indication).
    """
)

# Save for version control
strategy.to_yaml('search_strategies/venous_stent_v1.yaml')
```

**Best Practices:**
- Document rationale for each search term
- Test broad criteria on sample data first
- Iterate narrow criteria to balance precision/recall
- Version control YAML files in git

---

### Step 2: Apply Search Strategy

Execute the search following PRISMA workflow.

```python
from pymaude import MaudeDatabase

# Load database
db = MaudeDatabase('maude.db')
db.add_years('2019-2024', tables=['master', 'device'], download=True)

# Apply strategy
included, excluded, needs_review = strategy.apply(
    db,
    start_date='2019-01-01',
    end_date='2023-12-31'
)

print(f"Broad search: {len(included) + len(excluded) + len(needs_review)} reports")
print(f"Narrow search: {len(included)} reports")
print(f"Excluded by patterns: {len(excluded)} reports")
print(f"Needs manual review: {len(needs_review)} reports")
```

**Three DataFrames returned:**
- `included`: Reports matching narrow criteria (automatically included)
- `excluded`: Reports matching exclusion patterns (automatically excluded)
- `needs_review`: Reports in broad but not narrow, requiring adjudication

---

### Step 3: Manual Adjudication

Review `needs_review` DataFrame and make inclusion/exclusion decisions.

```python
from pymaude.adjudication import AdjudicationLog

# Create adjudication log
log = AdjudicationLog('adjudication/venous_stent_decisions.csv')

# Review reports (example: manual review)
for idx, row in needs_review.iterrows():
    mdr_key = str(row['MDR_REPORT_KEY'])
    brand = row.get('BRAND_NAME', '')
    generic = row.get('GENERIC_NAME', '')

    print(f"\nReport {mdr_key}:")
    print(f"  Brand: {brand}")
    print(f"  Generic: {generic}")

    # Manual decision (in practice, review full report)
    decision = input("Include? (y/n): ")
    reason = input("Reason: ")

    if decision.lower() == 'y':
        log.add(mdr_key, 'include', reason, 'Reviewer Name', strategy.version)
    else:
        log.add(mdr_key, 'exclude', reason, 'Reviewer Name', strategy.version)

# Save decisions
log.to_csv()
```

**Adjudication Best Practices:**
- **Dual review**: Have two reviewers independently assess
- **Reconciliation**: Resolve disagreements through discussion
- **Document reasons**: Clear, specific rationale for each decision
- **Track version**: Link decisions to strategy version
- **Inter-rater reliability**: Calculate Cohen's kappa for agreement

---

### Step 4: Apply Manual Decisions

Incorporate adjudication decisions into final dataset.

```python
# Load adjudication log
log = AdjudicationLog.from_csv('adjudication/venous_stent_decisions.csv')
manual_includes = log.get_inclusion_keys()
manual_excludes = log.get_exclusion_keys()

# Apply to needs_review DataFrame
import pandas as pd

# Add manually included reports
manually_included = needs_review[
    needs_review['MDR_REPORT_KEY'].astype(str).isin(manual_includes)
]
final_included = pd.concat([included, manually_included], ignore_index=True)

# Add manually excluded reports
manually_excluded = needs_review[
    needs_review['MDR_REPORT_KEY'].astype(str).isin(manual_excludes)
]
final_excluded = pd.concat([excluded, manually_excluded], ignore_index=True)

# Remaining reports (not yet adjudicated)
remaining = needs_review[
    ~needs_review['MDR_REPORT_KEY'].astype(str).isin(manual_includes | manual_excludes)
]

print(f"Final included: {len(final_included)} reports")
print(f"Final excluded: {len(final_excluded)} reports")
print(f"Remaining to review: {len(remaining)} reports")
```

---

### Step 5: Generate PRISMA Counts

Create counts for PRISMA flow diagram.

```python
# Get PRISMA counts
counts = strategy.get_prisma_counts(final_included, final_excluded, remaining)

print("\n=== PRISMA 2020 Flow Diagram Counts ===")
print(f"Records identified through broad search: {counts['broad_matches']}")
print(f"Records after narrow search: {counts['narrow_matches']}")
print(f"Records excluded by patterns: {counts['excluded_by_patterns']}")
print(f"Records requiring manual review: {counts['needs_manual_review']}")
print(f"Records manually included: {counts['manual_inclusions']}")
print(f"Records manually excluded: {counts['manual_exclusions']}")
print(f"Final included in analysis: {counts['final_included']}")
```

**PRISMA Flow Diagram Structure:**
```
Records identified through database searching
    ↓
Records after duplicates removed (EVENT_KEY deduplication)
    ↓
Records screened (broad → narrow)
    ├─→ Records excluded (patterns)
    └─→ Records assessed for eligibility
            ├─→ Records excluded (manual)
            └─→ Records included in analysis
```

---

## Complete Example

End-to-end workflow for venous stent analysis:

```python
from pymaude import MaudeDatabase, DeviceSearchStrategy
from pymaude.adjudication import AdjudicationLog
import pandas as pd

# 1. Load/create search strategy
strategy = DeviceSearchStrategy.from_yaml('search_strategies/venous_stent_v1.yaml')

# 2. Apply to database
db = MaudeDatabase('maude.db')
included, excluded, needs_review = strategy.apply(db, start_date='2019-01-01')

# 3. Load adjudication decisions (assume completed)
log = AdjudicationLog.from_csv('adjudication/venous_stent_decisions.csv')

# 4. Apply manual decisions
manual_includes = log.get_inclusion_keys()
manual_excludes = log.get_exclusion_keys()

manually_included = needs_review[
    needs_review['MDR_REPORT_KEY'].astype(str).isin(manual_includes)
]
manually_excluded = needs_review[
    needs_review['MDR_REPORT_KEY'].astype(str).isin(manual_excludes)
]

final_included = pd.concat([included, manually_included], ignore_index=True)
final_excluded = pd.concat([excluded, manually_excluded], ignore_index=True)

# 5. Enrich with additional data
final_included = db.enrich_with_patient_data(final_included)
final_included = db.enrich_with_narratives(final_included)

# 6. Generate PRISMA counts
remaining = needs_review[
    ~needs_review['MDR_REPORT_KEY'].astype(str).isin(manual_includes | manual_excludes)
]
counts = strategy.get_prisma_counts(final_included, final_excluded, remaining)

# 7. Print summary
print(f"Analysis dataset: {len(final_included)} reports")
print(f"Date range: {final_included['DATE_RECEIVED'].min()} to {final_included['DATE_RECEIVED'].max()}")
print(f"Unique events: {final_included['EVENT_KEY'].nunique()}")

# 8. Save for analysis
final_included.to_csv('outputs/venous_stent_included_reports.csv', index=False)
```

---

## Project Structure

Use the project generator for standardized organization:

```bash
python scripts/create_project.py venous_stent "Your Name"
cd studies/pymaude_venous_stent
```

**Generated structure:**
```
pymaude_venous_stent/
├── search_strategies/
│   └── venous_stent_v1.yaml       # Version-controlled strategy
├── adjudication/
│   └── venous_stent_decisions.csv # Tracked in git
├── notebooks/
│   ├── 01_exploration/            # Messy work (gitignored)
│   ├── 02_search_development/     # Refine criteria
│   └── 03_analysis/               # Clean analysis
├── src/
│   └── generate_manuscript_outputs.py  # Reproducible pipeline
├── outputs/
│   ├── figures/                   # Generated plots
│   └── tables/                    # Generated tables
├── PRISMA_checklist.md            # Reporting checklist
└── README.md                      # Project documentation
```

---

## Tips & Best Practices

### Search Strategy Development

1. **Start broad**: Cast wide net initially, narrow iteratively
2. **Test on samples**: Use `start_date`/`end_date` for testing
3. **Document decisions**: Record why each term was included/excluded
4. **Version control**: Track strategy evolution in git

### Adjudication

1. **Standardize process**: Create decision rules before starting
2. **Dual review**: Independent review by 2+ reviewers
3. **Track disagreements**: Calculate inter-rater reliability
4. **Document rationale**: Brief but specific reasons

### Reproducibility

1. **YAML strategies**: Version-controlled, human-readable
2. **CSV adjudication**: Git-friendly, Excel-compatible
3. **Scripts over notebooks**: `generate_manuscript_outputs.py` for final pipeline
4. **PRISMA checklist**: Complete before manuscript submission

### MAUDE-Specific

1. **EVENT_KEY**: Always deduplicate (8% duplication rate)
2. **Date filtering**: Use DATE_RECEIVED for temporal queries
3. **Data quality**: Note completeness rates in limitations
4. **Product codes**: Cross-reference with FDA database, but use at your own risk (frequently absent or incorrect in MAUDE)

---

## Reporting

### PRISMA Checklist

Complete `PRISMA_checklist.md` in your project root. Key sections:

- **Methods → Eligibility**: Link to `search_strategies/*.yaml`
- **Methods → Search**: Document boolean criteria
- **Methods → Selection**: Link to `adjudication/*.csv`
- **Results → Study selection**: Use PRISMA flow diagram with counts
- **Discussion → Limitations**: Address MAUDE data quality

### RECORD Extensions

- **RECORD 1.2**: Provide `search_strategies/*.yaml` as supplementary material
- **RECORD 1.4**: Describe exclusion pattern logic in methods
- **RECORD 1.5**: Document MDR_REPORT_KEY linkage across tables

---

## Example Studies

See `examples/search_strategies/` for:
- `rotational_thrombectomy_v1.yaml` - Complex search with false positives
- `examples/notebooks/systematic_review_example.ipynb` - Complete workflow

---

## Troubleshooting

### No reports in needs_review

**Problem**: narrow_criteria too broad, nothing to adjudicate

**Solution**: Make narrow_criteria more specific

### Too many false positives

**Problem**: Broad criteria capturing unrelated devices

**Solution**: Add exclusion patterns or refine narrow criteria

### Adjudication CSV corrupted

**Problem**: Manual edits broke CSV format

**Solution**: Use `AdjudicationLog.from_csv()` to validate, or edit in Excel

---

## References

- PRISMA 2020: https://www.prisma-statement.org/
- RECORD: https://www.record-statement.org/
- FDA MAUDE: https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/search.cfm

---

**Next**: See `examples/notebooks/systematic_review_example.ipynb` for hands-on tutorial.

<!-- TODO: that notebook doesn't exist yet -->