# validation.py - retrieval validation for the manuscript
#
# Three checks, matching the manuscript's validation section:
#   1. Full-database agreement: PyMAUDE master table vs. the complete openFDA
#      device-event bulk export (MDR report keys, 1991+ — matching how far
#      back the master table itself is loaded).
#   2. Query-level agreement: query_device() vs. the openFDA search API, for
#      the shared cases in query_cases.py.
#   3. Internal validation of search_by_device_names() against independently
#      written SQL, plus union/intersection identities for compound criteria.
#
# The bulk export (part 1) is never persisted in full: each partition file is
# downloaded, its MDR report keys/years are pulled into memory, and the file
# is discarded before the next one is fetched. Only one partition's worth of
# disk space is used at a time.

import io
import json
import zipfile
from datetime import datetime

import pandas as pd
import requests

from pymaude import MaudeDatabase
from query_cases import QUERY_DEVICE_CASES, DEVICE_NAME_SEARCH_CASES, SEARCH_TERMS

DB_PATH   = '../maude.duckdb'
DATA_DIR  = '../maude_data'
MIN_YEAR  = 1991

OPENFDA_DOWNLOAD_URL = 'https://api.fda.gov/download.json'
OPENFDA_SEARCH_URL   = 'https://api.fda.gov/device/event.json'
OPENFDA_PAGE_LIMIT   = 999  # 1000 requires a (free) api_key; 999 works unauthenticated
OPENFDA_MAX_PAGES    = 5000  # safety net against a runaway pagination loop


# ── Part 1: full-database agreement ─────────────────────────────────────────

def get_bulk_partitions():
    r = requests.get(OPENFDA_DOWNLOAD_URL, timeout=60)
    r.raise_for_status()
    event = r.json()['results']['device']['event']
    return event['export_date'], event['partitions']


def extract_keys_from_partition(url):
    """Download one partition, pull (mdr_report_key, year), discard the file."""
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        data = json.loads(zf.read(zf.namelist()[0]))
    out = []
    for rec in data['results']:
        key, date = rec.get('mdr_report_key'), rec.get('date_received')
        if key and date:
            out.append((key, int(date[:4])))
    return out


def fetch_openfda_keys():
    export_date, partitions = get_bulk_partitions()
    key_year = {}
    for i, part in enumerate(partitions, 1):
        print(f'  partition {i}/{len(partitions)}: {part["file"]}')
        for key, year in extract_keys_from_partition(part['file']):
            if year >= MIN_YEAR:
                key_year[key] = year
    return export_date, key_year


def fetch_pymaude_keys(db):
    rows = db.conn.execute(
        "SELECT MDR_REPORT_KEY, YEAR(DATE_RECEIVED) FROM master "
        "WHERE DATE_RECEIVED >= ?::DATE",
        [f'{MIN_YEAR}-01-01'],
    ).fetchall()
    return {str(key): year for key, year in rows}


def fetch_pymaude_retrieved_date(db):
    """Most recent load timestamp for the master table — a proxy for when its
    source file was downloaded, since add_years() downloads immediately
    before loading."""
    result = db.conn.execute(
        "SELECT MAX(loaded_at) FROM _load_metadata WHERE table_name = 'master'"
    ).fetchone()[0]
    return result.date() if result is not None else None


def compare_full_export(db):
    print('\n=== Part 1: full-database agreement ===')
    export_date, openfda = fetch_openfda_keys()
    pymaude = fetch_pymaude_keys(db)

    retrieved_date = fetch_pymaude_retrieved_date(db)
    print(f'PyMAUDE source files retrieved: {retrieved_date}')
    print(f'openFDA export date:            {export_date}')
    if retrieved_date is not None:
        gap_days = (datetime.strptime(export_date, '%Y-%m-%d').date() - retrieved_date).days
        print(f'Interval between snapshots:     {gap_days} days')

    both = openfda.keys() & pymaude.keys()
    only_pymaude = pymaude.keys() - openfda.keys()
    only_openfda = openfda.keys() - pymaude.keys()
    total = len(openfda.keys() | pymaude.keys())

    print(f'Total reports in either source: {total}')
    print(f'  In both:          {len(both)} ({100 * len(both) / total:.1f}%)')
    print(f'  Only in PyMAUDE:  {len(only_pymaude)}')
    print(f'  Only in openFDA:  {len(only_openfda)}')

    mismatches = (
        [{'mdr_report_key': k, 'year': pymaude[k], 'only_in': 'pymaude'} for k in only_pymaude] +
        [{'mdr_report_key': k, 'year': openfda[k], 'only_in': 'openfda'} for k in only_openfda]
    )
    pd.DataFrame(mismatches).to_csv('validation_full_export_mismatches.csv', index=False)
    print(f'Wrote validation_full_export_mismatches.csv ({len(mismatches)} rows)')

    years = sorted({*openfda.values(), *pymaude.values()})
    rows = []
    for year in years:
        year_openfda = {k for k, y in openfda.items() if y == year}
        year_pymaude = {k for k, y in pymaude.items() if y == year}
        rows.append({
            'year': year,
            'n_pymaude': len(year_pymaude),
            'n_openfda': len(year_openfda),
            'n_both': len(year_pymaude & year_openfda),
            'n_only_pymaude': len(year_pymaude - year_openfda),
            'n_only_openfda': len(year_openfda - year_pymaude),
        })
    table = pd.DataFrame(rows)
    table.to_csv('validation_full_export_by_year.csv', index=False)
    print('Wrote validation_full_export_by_year.csv')
    return table


# ── Part 2: query-level agreement ───────────────────────────────────────────

OPENFDA_FIELD_MAP = {
    'brand_name': 'device.brand_name.exact',
    'generic_name': 'device.generic_name.exact',
    'manufacturer_name': 'device.manufacturer_d_name.exact',
    'product_code': 'device.device_report_product_code',
}


def build_openfda_query(kwargs):
    clauses = []
    for field, openfda_field in OPENFDA_FIELD_MAP.items():
        value = kwargs.get(field)
        if value:
            clauses.append(f'{openfda_field}:"{value.upper()}"')
    start, end = kwargs.get('start_date'), kwargs.get('end_date')
    if start or end:
        start = (start or '1900-01-01').replace('-', '')
        end = (end or '2100-01-01').replace('-', '')
        clauses.append(f'date_received:[{start} TO {end}]')
    return ' AND '.join(clauses)


def openfda_query_keys(query):
    """Follow the response's Link: rel="next" cursor rather than skip+limit —
    openFDA caps skip at 25000, but the Link header switches to a search_after
    cursor that keeps working past that for large cohorts."""
    keys = set()
    url = OPENFDA_SEARCH_URL
    params = {'search': query, 'limit': OPENFDA_PAGE_LIMIT, 'skip': 0}
    for _ in range(OPENFDA_MAX_PAGES):
        r = requests.get(url, params=params, timeout=60)
        if r.status_code == 404:
            break
        r.raise_for_status()
        keys.update(item['mdr_report_key'] for item in r.json().get('results', []))
        next_url = r.links.get('next', {}).get('url')
        if not next_url:
            break
        url, params = next_url, None
    else:
        print(f'  WARNING: hit {OPENFDA_MAX_PAGES}-page pagination safety cap for query: {query!r}')
    return keys


def compare_queries(db):
    print('\n=== Part 2: query-level agreement ===')
    rows = []
    for case in QUERY_DEVICE_CASES:
        local_df = db.query_device(**case['kwargs'])
        local_keys = set(local_df['MDR_REPORT_KEY'].astype(str))

        query = build_openfda_query(case['kwargs'])
        openfda_keys = openfda_query_keys(query)

        identical = local_keys == openfda_keys
        print(f'  {case["label"]}: local={len(local_keys)} openfda={len(openfda_keys)} '
              f'identical={identical}')
        rows.append({
            'label': case['label'],
            'n_pymaude': len(local_keys),
            'n_openfda': len(openfda_keys),
            'identical': identical,
            'n_only_pymaude': len(local_keys - openfda_keys),
            'n_only_openfda': len(openfda_keys - local_keys),
        })
    table = pd.DataFrame(rows)
    table.to_csv('validation_query_level.csv', index=False)
    print('Wrote validation_query_level.csv')
    return table


# ── Part 3: internal validation of search_by_device_names() ────────────────

def normalize_criteria(criteria):
    """Independent re-implementation of the AND/OR grouping rules, so this
    check doesn't share logic with the code it's validating."""
    if isinstance(criteria, str):
        return [[criteria]]
    return [group if isinstance(group, list) else [group] for group in criteria]


def reference_search(db, criteria):
    """Same criteria, applied as substring matches on the three separate
    name columns (not the concatenated field search_by_device_names uses)."""
    or_groups, params = [], []
    for and_group in normalize_criteria(criteria):
        and_parts = []
        for term in and_group:
            and_parts.append(
                "(d.BRAND_NAME ILIKE ? OR d.GENERIC_NAME ILIKE ? OR d.MANUFACTURER_D_NAME ILIKE ?)"
            )
            params.extend([f'%{term}%'] * 3)
        or_groups.append('(' + ' AND '.join(and_parts) + ')')
    where = '(' + ' OR '.join(or_groups) + ')'
    sql = f"""
        SELECT DISTINCT m.MDR_REPORT_KEY
        FROM device d JOIN master m USING (MDR_REPORT_KEY)
        WHERE {where}
    """
    return set(db.conn.execute(sql, params).df()['MDR_REPORT_KEY'].astype(str))


def compare_search_by_device_names(db):
    print('\n=== Part 3: search_by_device_names() internal validation ===')
    rows = []
    for case in DEVICE_NAME_SEARCH_CASES:
        library_keys = set(db.search_by_device_names(case['criteria'])['MDR_REPORT_KEY'].astype(str))
        reference_keys = reference_search(db, case['criteria'])
        identical = library_keys == reference_keys
        print(f'  {case["label"]}: n={len(library_keys)} identical={identical}')
        rows.append({'label': case['label'], 'n': len(library_keys), 'identical': identical})

    # Compound identity checks: OR of terms == union of single-term results;
    # a single AND-group == intersection of single-term results.
    singles = {
        term: set(db.search_by_device_names(term)['MDR_REPORT_KEY'].astype(str))
        for term in SEARCH_TERMS
    }
    a, b = SEARCH_TERMS[0], SEARCH_TERMS[1]

    union_result = set(db.search_by_device_names([a, b])['MDR_REPORT_KEY'].astype(str))
    union_identical = union_result == (singles[a] | singles[b])
    print(f'  union identity ({a} OR {b}): identical={union_identical}')
    rows.append({'label': f'union identity ({a} OR {b})', 'n': len(union_result), 'identical': union_identical})

    intersection_result = set(db.search_by_device_names([[a, b]])['MDR_REPORT_KEY'].astype(str))
    intersection_identical = intersection_result == (singles[a] & singles[b])
    print(f'  intersection identity ({a} AND {b}): identical={intersection_identical}')
    rows.append({
        'label': f'intersection identity ({a} AND {b})',
        'n': len(intersection_result),
        'identical': intersection_identical,
    })

    table = pd.DataFrame(rows)
    table.to_csv('validation_search_by_device_names.csv', index=False)
    print('Wrote validation_search_by_device_names.csv')
    return table


if __name__ == '__main__':
    db = MaudeDatabase(DB_PATH, data_dir=DATA_DIR, verbose=True)
    compare_full_export(db)
    compare_queries(db)
    compare_search_by_device_names(db)
    db.close()
