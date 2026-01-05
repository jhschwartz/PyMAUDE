PYTHON := python3.11

.PHONY: setup install dev test init-db check-fda check-fda-quick archive archive-recent clean-notebooks clean

setup:
	$(PYTHON) -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -e .

install: setup
	venv/bin/pip install -r requirements.txt

dev: setup
	venv/bin/pip install -r requirements.txt
	venv/bin/pip install -r requirements-dev.txt

test:
	venv/bin/python -m pytest

init-db: setup
	@echo "Initializing MAUDE database..."
	./init_full_db.sh

check-fda:
	@echo "Checking FDA MAUDE website compatibility..."
	venv/bin/python archive_tools/check_fda_compatibility.py

check-fda-quick:
	@echo "Quick FDA compatibility check..."
	venv/bin/python archive_tools/check_fda_compatibility.py --quick

archive:
	@echo "Preparing Zenodo archive (all years)..."
	venv/bin/python archive_tools/prepare_zenodo_archive.py --years all --output maude_archive

archive-recent:
	@echo "Preparing Zenodo archive (last 5 years)..."
	@CURRENT_YEAR=$$(date +%Y); \
	START_YEAR=$$((CURRENT_YEAR - 4)); \
	venv/bin/python archive_tools/prepare_zenodo_archive.py --years $$START_YEAR-$$CURRENT_YEAR --output maude_recent

clean-notebooks:
	@echo "Cleaning notebook-generated files..."
	rm -rf notebooks/maude_data
	rm -f notebooks/*.db
	rm -f notebooks/*.png
	rm -f notebooks/*.pdf
	rm -f notebooks/*.txt
	rm -f notebooks/*.csv

clean: clean-notebooks
	@echo "Cleaning all generated files..."
	rm -rf venv
	rm -rf maude_data/*.zip
	rm -rf __pycache__ tests/__pycache__ src/maude_db/__pycache__
	rm -f *.db
	rm -rf .pytest_cache
	rm -rf *.egg-info build dist .eggs
	rm -rf examples/maude_data
	rm -f examples/*.db
	rm -f examples/*.csv
	rm -f examples/*.png
	rm -f examples/*.pdf

.DEFAULT_GOAL := setup