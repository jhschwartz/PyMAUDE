#!/usr/bin/env bash
# Run from anywhere, with the venv that has pymaude installed already active.
# The scripts use ../maude.duckdb and write their CSVs to the cwd, so they must
# run from publication/.
set -e
cd "$(dirname "$0")"

python benchmark_init_db.py
python benchmark_query.py
python benchmark_archive.py
python validation.py
