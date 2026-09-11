# query_cases.py - shared test queries for validation.py and benchmark_query.py
#
# Edit these to reflect device terms/cohorts relevant to the manuscript
# (e.g. product codes and cohort sizes matching the paper's device of interest).
# Kept in one place so the validation and benchmark scripts exercise the same
# queries, as described in the manuscript's query-level validation paragraph.

# query_device() cases: varying field combinations, with/without date restriction.
QUERY_DEVICE_CASES = [
    {
        'label': 'product code only',
        'kwargs': {'product_code': 'NIQ'},
    },
    {
        'label': 'product code + date range',
        'kwargs': {'product_code': 'NIQ', 'start_date': '2015-01-01', 'end_date': '2023-12-31'},
    },
    {
        'label': 'brand name exact',
        'kwargs': {'brand_name': 'RESOLUTE ONYX RX'},
    },
    {
        'label': 'generic name exact',
        'kwargs': {'generic_name': 'VENOUS STENT'},
    },
    {
        'label': 'manufacturer + product code',
        'kwargs': {'manufacturer_name': 'BOSTON SCIENTIFIC CORPORATION', 'product_code': 'NIQ'},
    },
]

# search_by_device_names() cases: single term, OR of terms, and a compound
# AND-within-OR group, spanning the complexity levels the manuscript describes.
SEARCH_TERMS = ['argon', 'cleaner', 'angiojet']

DEVICE_NAME_SEARCH_CASES = [
    {'label': 'single term', 'criteria': 'argon'},
    {'label': 'OR of two terms', 'criteria': ['argon', 'cleaner']},
    {'label': 'AND-within-OR (compound)', 'criteria': [['argon', 'cleaner'], 'angiojet']},
]
