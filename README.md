# maude_db

A Python library for downloading, querying, and analyzing FDA MAUDE (Manufacturer and User Facility Device Experience) adverse event data. Designed for medical device safety research and regulatory surveillance.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## What is maude_db?

`maude_db` provides a simple interface to work with the FDA's MAUDE database locally. It handles downloading data files from FDA servers, importing them into a SQLite database, and provides convenient query methods for analysis. The library is designed specifically for researchers who need reproducible, offline access to medical device adverse event data.

For background on the MAUDE database, see [docs/maude_overview.md](docs/maude_overview.md).

## Key Features

- **Automated Downloads**: Fetch MAUDE data files directly from FDA servers with built-in caching
- **Flexible Querying**: Simple methods for common queries plus full SQL access for complex analysis
- **Trend Analysis**: Built-in functions for analyzing adverse events over time
- **Narrative Access**: Retrieve event narrative descriptions for qualitative analysis
- **Export Support**: Export query results to CSV for further analysis
- **Research-Focused**: Designed for reproducibility and offline analysis


## Installation

## Quick Start

### Option 1: For Non-Programmers (SQLite Tools Only)

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
- Try [examples/example_queries.sql](examples/example_queries.sql) for ready-to-use queries

### Option 2: Python API

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

# Install dependencies
pip install -r requirements.txt
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

### For SQLite Tool Users
- **[SQLite Usage Guide](docs/sqlite_guide.md)** - Complete guide for using MAUDE databases with DB Browser, DBeaver, etc.
- **[Example SQL Queries](examples/example_queries.sql)** - Ready-to-use SQL queries for common research tasks

### For Python Users
- **[Getting Started Guide](docs/getting_started.md)** - Step-by-step tutorial for first-time users
- **[API Reference](docs/api_reference.md)** - Complete documentation of all methods

### General Resources
- **[MAUDE Overview](docs/maude_overview.md)** - Understanding the FDA MAUDE database structure
- **[Research Guide](docs/research_guide.md)** - Best practices for medical device research
- **[Troubleshooting](docs/troubleshooting.md)** - Solutions to common problems

## Examples

The [`examples/`](examples/) directory contains working examples:

- **[basic_usage.py](examples/basic_usage.py)** - Minimal example showing core functionality (1998 data, ~3MB download)
- **[analyze_device_trends.py](examples/analyze_device_trends.py)** - Comprehensive example with trend analysis and visualization (2018-2020 data)

Run an example:

```bash
cd examples
python basic_usage.py
```

See [examples/README.md](examples/README.md) for more details and customization options.

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

## Use Cases

This library is designed for:

- **Device Safety Surveillance**: Monitor adverse events for specific device types over time
- **Trend Analysis**: Identify patterns in device malfunctions, injuries, or deaths
- **Regulatory Research**: Analyze FDA reporting data for academic or policy studies
- **Comparative Studies**: Compare safety profiles across different devices or manufacturers
- **Signal Detection**: Screen for potential safety signals in medical devices

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

---

For questions about using this library, see the [documentation](docs/) or open an issue.