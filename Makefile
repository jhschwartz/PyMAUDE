PYTHON := python3.11

setup:
	$(PYTHON) -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt

install:
	venv/bin/pip install -r requirements.txt

dev:
	venv/bin/pip install -r requirements.txt 
	venv/bin/pip install -r requirements-dev.txt

test:
	venv/bin/python -m unittest discover tests -v

init-db: setup
	@echo "Initializing MAUDE database..."
	./init_full_db.sh

clean:
	rm -rf venv
	rm -rf maude_data/*.zip
	rm -rf __pycache__ tests/__pycache__
	rm -f *.db
	rm -rf .pytest_cache
	rm -rf examples/maude_data
	rm -f examples/*.db
	rm -f examples/*.csv
	rm -f examples/*.png
	rm -f examples/*.pdf

.DEFAULT_GOAL := setup