# Running Tests

## Setup
```bash
cd scripts/maude_db
source venv/bin/activate
pip install pytest
```

## Run Tests

```bash
# All tests (fast unit tests only)
pytest -m "not integration"

# Include slow integration tests that download real FDA data
pytest -m integration

# Everything
pytest
```

Integration tests download small 1992-1996 data files from FDA servers to verify downloading works.