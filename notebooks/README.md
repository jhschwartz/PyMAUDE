# PyMAUDE Jupyter Notebooks

Interactive examples for the PyMAUDE library. These notebooks demonstrate real research workflows for analyzing FDA MAUDE adverse event data.

**Author**: Jacob Schwartz <jaschwa@umich.edu>
**GitHub**: jhschwartz
**Copyright**: 2026, GNU GPL v3

## Quick Start

```bash
# From PyMAUDE directory
cd notebooks/
jupyter notebook
```

Start with [01_getting_started.ipynb](01_getting_started.ipynb) if you're new to PyMAUDE.

## Notebooks

### Tutorial Series (Start Here)

These notebooks provide a comprehensive introduction to PyMAUDE's redesigned API:

#### **[01_getting_started.ipynb](01_getting_started.ipynb)** 🟢
**What you'll learn:**
- Database setup and data downloading
- Boolean name search with `search_by_device_names()`
- Exact-match queries with `query_device()`
- Date filtering and result manipulation
- Getting event narratives
- Exporting results

**Best for**: New users, understanding the basics
**Data**: 2023, device + text (~200MB)
**Runtime**: ~5 minutes

---

#### **[02_grouped_search.ipynb](02_grouped_search.ipynb)** 🟡
**What you'll learn:**
- Dict-based grouped search for device comparisons
- Working with the `search_group` column
- Using helper functions with grouped results
- Handling overlapping search criteria
- Real-world VTE device comparison example

**Best for**: Comparative device studies
**Data**: 2020-2023, device (~600MB)
**Runtime**: ~8 minutes

---

#### **[03_exact_queries.ipynb](03_exact_queries.ipynb)** 🟡
**What you'll learn:**
- Exact vs partial matching strategies
- Querying by brand, generic name, manufacturer
- Product code and PMA/PMN queries
- Combining multiple search parameters
- When to use exact queries vs boolean search

**Best for**: Targeting specific devices
**Data**: 2020-2023, device (~600MB)
**Runtime**: ~6 minutes

---

#### **[04_analysis_helpers.ipynb](04_analysis_helpers.ipynb)** 🟡
**What you'll learn:**
- Trend analysis with `get_trends_by_year()`
- Summary statistics with `summarize_by_brand()`
- Event type comparisons and chi-square tests
- Brand name standardization (simple and hierarchical)
- Patient data enrichment
- Deduplication strategies
- Visualization helpers

**Best for**: Statistical analysis and visualization
**Data**: 2020-2023, device + patient + text (~800MB)
**Runtime**: ~10 minutes

---

#### **[05_advanced_workflows.ipynb](05_advanced_workflows.ipynb)** 🔴
**What you'll learn:**
- Post-market surveillance study design
- Comparative device safety analysis
- Failure mode identification from narratives
- Manufacturer comparison
- Regulatory signal detection (statistical process control)
- Publication-ready exports

**Best for**: Complete research workflows
**Data**: 2018-2023, device + patient + text (~1.2GB)
**Runtime**: ~12 minutes

---

### Reference & Examples

#### **[boolean_search_examples.ipynb](boolean_search_examples.ipynb)**
Comprehensive reference for boolean search functionality with 10 sections covering all search patterns, AND/OR logic, and grouped search examples.

**Best for**: Quick reference while coding

---

#### **[widget_search.ipynb](widget_search.ipynb)**
Legacy interactive widget for device selection (deprecated - use dict-based grouped search instead).

## Learning Paths

### I want to...

**...get started with PyMAUDE (30 min):**
- Path: **01 → 02**

**...analyze a specific device (1 hour):**
- Path: **01 → 03 → 04**

**...compare multiple devices (1.5 hours):**
- Path: **01 → 02 → 04**

**...prepare a publication (2-3 hours):**
- Path: **01 → 02 → 04 → 05**

**...learn the complete API:**
- Path: **01 → 02 → 03 → 04 → boolean_search_examples**

**...do safety surveillance (advanced):**
- Path: **01 → 02 → 04 → 05**

## Setup

### Installation

```bash
# Install PyMAUDE
pip install -e ..

# Install visualization dependencies
pip install matplotlib seaborn

# Launch Jupyter
jupyter notebook
```

### Python Path (If Needed)

If you see `ModuleNotFoundError: No module named 'pymaude'`:

```python
# Add this to the first cell of any notebook:
import sys
from pathlib import Path
sys.path.insert(0, str(Path().resolve().parent / 'src'))
```

This is already included in all tutorial notebooks.

## Data Download Notes

### First Run

Notebooks download data from FDA on first run. Downloaded files are cached in the database, so subsequent runs are instant:

- **First run**: Downloads and processes files (~5-10 minutes depending on years)
- **Subsequent runs**: Skips processing if file unchanged (instant!)

### Disk Space Requirements

- **Notebook 01**: ~500MB
- **Notebooks 01-04**: ~1.5GB
- **All notebooks**: ~2GB

### Data is Cached

Downloaded data is stored in your database file and reused across notebooks. After your first multi-year download, other notebooks run much faster.

## Key API Features

### Two Search Paradigms

1. **Boolean name search** - `search_by_device_names()`
   - Flexible AND/OR logic with partial matching
   - Perfect for exploration and grouped comparisons
   - Searches across brand, generic, manufacturer, and concatenated names

2. **Exact-match query** - `query_device()`
   - Precise field matching (case-insensitive)
   - Perfect when you know exact device identifiers
   - Query by brand, generic name, product code, PMA/PMN

### Grouped Search (New!)

Compare multiple device categories in a single query:

```python
results = db.search_by_device_names({
    'mechanical': [['argon', 'cleaner'], 'angiojet'],
    'aspiration': 'penumbra'
})

# Results include 'search_group' column
# Helper functions automatically use search_group for grouping
trends = db.get_trends_by_year(results)  # Includes group breakdown
```

### Helper Functions Use search_group by Default

All analysis helpers now default to using the `search_group` column for automatic grouping:

- `get_trends_by_year(results)` - Temporal trends with group breakdown
- `summarize_by_brand(results)` - Statistics by group
- `event_type_comparison(results)` - Compare distributions across groups

## Troubleshooting

### Import Errors

If `from pymaude import MaudeDatabase` fails:
1. Make sure you're in a virtual environment with PyMAUDE installed
2. Or add the Python path fix shown above

### Matplotlib Not Found

For notebooks with visualizations:

```bash
pip install matplotlib seaborn
```

### Slow Downloads

If FDA servers are slow:
- Try a different time of day
- Data is cached after first download
- Consider starting with notebook 01 (smaller dataset)

### Database Locked

If you see "database is locked":
- Close any open database connections: `db.close()`
- Only run one notebook at a time
- Restart Jupyter kernel

## Additional Resources

- **[../docs/getting_started.md](../docs/getting_started.md)** - Installation and setup guide
- **[../docs/api_reference.md](../docs/api_reference.md)** - Complete API documentation
- **[../docs/research_guide.md](../docs/research_guide.md)** - Research best practices and workflows
- **[../README.md](../README.md)** - Main project documentation

## Contributing

Found a bug or have suggestions? Please open an issue or PR at [github.com/jhschwartz/PyMAUDE](https://github.com/jhschwartz/PyMAUDE).

## Questions?

- Check the [API Reference](../docs/api_reference.md) for detailed function documentation
- Review the [Research Guide](../docs/research_guide.md) for workflow patterns
- Open an issue on GitHub for bugs or feature requests