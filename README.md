# maude_db

A Python library for downloading, querying, and analyzing FDA MAUDE (Manufacturer and User Facility Device Experience) adverse event data. Designed for medical device safety research and regulatory surveillance.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/yourusername/maude_db/main?filepath=notebooks%2F01_quickstart_binder.ipynb)
[![FDA Site Compatibility](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/jhschwartz/2be19fadf256e3b5de290996b99b1f19/raw/maude_db_fda_compatibility.json)](https://github.com/jhschwartz/maude_db/actions/workflows/fda_compatibility_check.yml)
<!-- Replace the badge above with your actual dynamic badge once set up - see docs/github_badge_setup.md -->

## What is maude_db?

`maude_db` provides a simple interface to work with the FDA's MAUDE database locally. It handles downloading data files from FDA servers, importing them into a SQLite database, and provides convenient query methods for analysis. The library is designed specifically for researchers who need reproducible, offline access to medical device adverse event data.

For background on the MAUDE database, see [docs/maude_overview.md](docs/maude_overview.md).

## Key Features

- **Intelligent Checksum Tracking**: Automatically prevents duplicate data and detects FDA file updates
  - Skip reprocessing unchanged files (instant re-runs!)
  - Automatically refresh when FDA updates historical data
  - No manual deduplication needed
- **Automated Downloads**: Fetch MAUDE data files directly from FDA servers with built-in caching
- **Flexible Querying**: Simple methods for common queries plus full SQL access for complex analysis
- **Trend Analysis**: Built-in functions for analyzing adverse events over time
- **Narrative Access**: Retrieve event narrative descriptions for qualitative analysis
- **Export Support**: Export query results to CSV for further analysis
- **Research-Focused**: Designed for reproducibility and offline analysis


## Installation

## Try It Now (No Installation)

**🚀 Interactive Demo**: Click the Binder badge above to try maude_db in your browser! Uses 2005 data for a quick (~1 minute) introduction.

## Quick Start

### Option 1: Interactive Notebooks (Recommended)

**Best way to learn!** Explore the [notebooks/](notebooks/) directory for interactive examples:

- **[01_quickstart_binder.ipynb](notebooks/01_quickstart_binder.ipynb)** - 5-minute intro (works in Binder)
- **[02_getting_started.ipynb](notebooks/02_getting_started.ipynb)** - Complete local setup guide
- **[03_trend_analysis_visualization.ipynb](notebooks/03_trend_analysis_visualization.ipynb)** - Your first real analysis

See [notebooks/README.md](notebooks/README.md) for complete guide with beginner/intermediate/advanced tracks.

### Option 2: For Non-Programmers (SQLite Tools Only)

If you want to use SQLite tools (DB Browser, DBeaver, etc.) without writing Python code:

```bash
# Run the initialization script
./init_full_db.sh

# Follow the prompts to:
# 1. Enter year range (e.g., 2020-2024)
# 2. Select tables (device, text, patient)
# 3. Specify database filename

# Then open the resulting .db file in your SQLite tool
```

**Next steps:**
- Download DB Browser for SQLite: [https://sqlitebrowser.org/](https://sqlitebrowser.org/)
- See [docs/sqlite_guide.md](docs/sqlite_guide.md) for usage guide

### Option 3: Python API

```python
from maude_db import MaudeDatabase

# Create database and download data
db = MaudeDatabase('maude.db')
db.add_years(2020, tables=['device'], download=True)

# Query for specific devices
results = db.query_device(device_name='pacemaker')
print(f"Found {len(results)} pacemaker events in 2020")

# Analyze trends
trends = db.get_trends_by_year(device_name='pacemaker')
print(trends)

db.close()
```

### Requirements

- Python 3.7 or later
- Internet connection (for downloading FDA data)
- Sufficient disk space (varies by years downloaded; ~100MB per year for device data)

### Setup

**Quick setup using Makefile (recommended)**:

```bash
# Clone or download this repository
cd maude_db

# Create virtual environment and install dependencies
make setup

# Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

**Manual setup**:

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install package in editable mode (includes dependencies)
pip install -e .
```

**For development** (includes testing dependencies):

```bash
make dev
source venv/bin/activate
```

For installing from GitHub:

```bash
pip install git+https://github.com/yourusername/maude_db.git
```

## Documentation

### Interactive Tutorials
- **[Jupyter Notebooks](notebooks/)** - Complete learning path from beginner to advanced
- **[Notebooks README](notebooks/README.md)** - Guide to all 8 interactive tutorials

### For SQLite Tool Users
- **[SQLite Usage Guide](docs/sqlite_guide.md)** - Complete guide for using MAUDE databases with DB Browser, DBeaver, etc.
- **[Advanced SQL Examples](notebooks/04_advanced_querying.ipynb)** - Complex SQL queries in notebook format

### For Python Users
- **[Getting Started Guide](docs/getting_started.md)** - Step-by-step tutorial for first-time users
- **[API Reference](docs/api_reference.md)** - Complete documentation of all methods

### General Resources
- **[MAUDE Overview](docs/maude_overview.md)** - Understanding the FDA MAUDE database structure
- **[Research Guide](docs/research_guide.md)** - Best practices for medical device research
- **[Troubleshooting](docs/troubleshooting.md)** - Solutions to common problems

### Archiving & Maintenance
- **[Archiving Guide](archive_tools/ARCHIVING_GUIDE.md)** - Complete guide for creating reproducible archives
- **[GitHub Badge Setup](docs/github_badge_setup.md)** - Set up automatic FDA compatibility monitoring

## Testing

Run the test suite to verify your installation:

```bash
# Run all tests
pytest

# Run only unit tests (fast, no downloads)
pytest -m "not integration"

# Run integration tests (downloads real FDA data)
pytest -m integration
```

All tests should pass. Integration tests require an internet connection and will download small amounts of real FDA data.

## Archiving and Data Preservation

### Create Zenodo Archive

To create a complete archive suitable for upload to Zenodo or other research repositories:

```bash
# Using Makefile (recommended)
make archive              # Full archive (all years)
make archive-recent       # Last 5 years only

# Or run the script directly
python archive_tools/prepare_zenodo_archive.py --years all --output maude_full_archive

# Or for specific years
python archive_tools/prepare_zenodo_archive.py --years 2020-2024 --output maude_2020_2024
```

This creates a comprehensive archive including:
- Complete SQLite database
- Schema documentation
- Metadata and statistics
- SHA-256 checksums
- DOI-ready README

See [archive_tools/ARCHIVING_GUIDE.md](archive_tools/ARCHIVING_GUIDE.md) for detailed instructions.

### Check FDA Site Compatibility

Monitor whether the FDA MAUDE website structure has changed:

```bash
# Using Makefile (recommended)
make check-fda           # Full check with test download
make check-fda-quick     # Quick check (HEAD requests only)

# Or run the script directly
python archive_tools/check_fda_compatibility.py
python archive_tools/check_fda_compatibility.py --quick
python archive_tools/check_fda_compatibility.py --json
```

**Automated Monitoring:** Set up GitHub Actions to automatically check compatibility daily and display a status badge on your README. See [docs/github_badge_setup.md](docs/github_badge_setup.md) for setup instructions.

## Use Cases

This library is designed for:

- **Device Safety Surveillance**: Monitor adverse events for specific device types over time
- **Trend Analysis**: Identify patterns in device malfunctions, injuries, or deaths
- **Regulatory Research**: Analyze FDA reporting data for academic or policy studies
- **Comparative Studies**: Compare safety profiles across different devices or manufacturers
- **Signal Detection**: Screen for potential safety signals in medical devices
- **Data Preservation**: Create reproducible archives for long-term research

## Contributing & Issues

Bug reports and feature requests are welcome! Please open an issue on GitHub:

- Check existing issues first to avoid duplicates
- Provide a minimal reproducible example for bugs
- Describe your use case for feature requests

## Citation

If you use this library in your research, please cite:

```
Schwartz, J. (2025). maude_db: A Python library for FDA MAUDE database analysis.
https://github.com/jhschwartz/maude_db
```

**Note**: This citation format may be updated if/when results using this library are published in peer-reviewed literature.

When using MAUDE data, also cite the FDA database:

```
U.S. Food and Drug Administration. (2024). MAUDE - Manufacturer and User Facility
Device Experience Database. https://www.fda.gov/medical-devices/mandatory-reporting-requirements-manufacturers-importers-and-device-user-facilities/manufacturer-and-user-facility-device-experience-database-maude
```

## License

This project is licensed under the GNU General Public License v3.0 (GPLv3) - see the [LICENSE](LICENSE) file for details.

Copyright (C) 2025 Jacob Schwartz, jaschwa@umich.edu

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

## Author

**Jacob Schwartz**
jaschwa@umich.edu

## Acknowledgments

Documentation and testing development assisted by Claude (Anthropic AI).

---

For questions about using this library, see the [documentation](docs/) or open an issue.