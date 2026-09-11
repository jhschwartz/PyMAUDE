# PyMAUDE

PyMAUDE is a Python library for local, reproducible analysis of the FDA **MAUDE** (Manufacturer and User Facility Device Experience) adverse event database. It bulk-loads FDA's raw flat files into a local [DuckDB](https://duckdb.org/) database and gives you a fast, scriptable API for searching, enriching, and filtering medical device adverse event reports — without depending on the MAUDE web UI or a rate-limited API for every query.

MAUDE is updated continuously and isn't versioned, so PyMAUDE also supports checksummed, citable snapshots (`db.archive()`) for analyses that need to be reproducible for peer review or publication.

## Why

- **Local and fast.** FDA's own search UI and the openFDA API are fine for one-off lookups, but slow and rate-limited for the kind of bulk, iterative querying research requires. PyMAUDE downloads the raw data once and queries it locally via DuckDB.
- **Reproducible.** `db.archive()` freezes the exact database backing an analysis — with a manifest recording every source file's SHA-256 checksum, row count, and load timestamp — so results can be cited or re-derived later.
- **Covers the full MDR family.** Master records, device info, event narratives, patient demographics/outcomes, and both device- and patient-side problem codes — joined on `MDR_REPORT_KEY` throughout.

## Installation

> **Use a virtual environment.** Installing PyMAUDE (or any Python package) directly into your system or base conda Python can silently break other tools you depend on. Create and activate a virtual environment first:
> ```bash
> python -m venv .venv
> source .venv/bin/activate   # on Windows: .venv\Scripts\activate
> ```
> Do this before running any `pip install` command below.

### From PyPI

```bash
pip install pymaude
```

> Note: this package is under active development ahead of its associated manuscript (see [Publication](#publication) below) — if `pymaude` isn't yet available on PyPI, install from source instead.

### From source

```bash
git clone https://github.com/jhschwartz/PyMAUDE.git
cd PyMAUDE
pip install .
```

For development (editable install + test dependencies):

```bash
pip install -e ".[dev]"
pytest tests/
```

Requires Python ≥3.9.

## Quickstart

```python
from pymaude import MaudeDatabase

db = MaudeDatabase('./maude.duckdb', data_dir='./maude_data')
db.add_years('2024-2026', tables=['master', 'device', 'text', 'patient'], download=True)

results = db.query_device(product_code='NIQ')  # e.g. venous stents
print(f'{len(results):,} events')
```

For a guided walkthrough, open [`quickstart.ipynb`](./quickstart.ipynb) — it downloads real FDA data and runs your first few queries. For deeper dives into specific capabilities, see [`examples/`](./examples).

## Project structure

```
pymaude-new/
├── src/pymaude/                       # library source
│   ├── database.py                    # MaudeDatabase — the main API
│   └── metadata.py                    # TABLE_METADATA — FDA file layout config
├── tests/                             # pytest test suite (synthetic data, no FDA download needed)
├── quickstart.ipynb                   # short intro notebook — start here
├── examples/                          # deeper-dive notebooks
│   ├── searching.ipynb                # substring/OR/AND/grouped search, narratives
│   ├── enrichment_and_filtering.ipynb # patient outcomes, problem codes, chained filters
│   ├── trends_and_sql.ipynb           # year-over-year trends, raw SQL
│   └── archiving.ipynb                # reproducible snapshots for publication
├── publication/                       # validation & benchmark scripts supporting the manuscript
├── dev_local/                         # personal dev scripts (gitignored, not part of the package)
├── pyproject.toml
└── LICENSE
```

## Data tables

`add_years()` loads any subset of these into your local DuckDB file, all joinable on `MDR_REPORT_KEY`:

| Table | FDA source | Description |
|---|---|---|
| `master` | `mdrfoi` | Master adverse event records |
| `device` | `foidev` | Device information |
| `text` | `foitext` | Event narrative text (`FOI_TEXT`) |
| `patient` | `patient` | Patient demographics and outcomes |
| `device_problem` | `foidevproblem` | Device problem codes |
| `patient_problem` | `patientproblemcode` | Patient problem codes |

## Core API

- **Loading:** `add_years()`, `update()`
- **Querying:** `query_device()` (exact-field), `search_by_device_names()` (substring, with OR/AND/grouped logic), `get_narratives()`, `query()` (raw SQL)
- **Enrichment:** `enrich_with_patient_data()`, `enrich_with_device_problems()`, `enrich_with_patient_problems()`
- **Filtering:** `filter_by_outcome()`, `filter_by_patient()`, `filter_by_device_problem()`, `filter_by_patient_problem()`, `filter_by_narrative()`
- **Analysis & reproducibility:** `get_trends_by_year()`, `info()`, `archive()`

See the docstrings in [`src/pymaude/database.py`](./src/pymaude/database.py) or [`examples/`](./examples) for details on each.

## Publication

A manuscript describing PyMAUDE is in preparation. Citation details will be added here once it's published.

```bibtex
@article{pymaude,
  title   = {},
  author  = {Schwartz, Jacob and others},
  journal = {},
  year    = {},
  doi     = {}
}
```

## License

MIT — see [LICENSE](./LICENSE).

## Contact

Jacob Schwartz — jaschwa@umich.edu
