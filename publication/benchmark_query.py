# benchmark_query.py - timing for query_device() and search_by_device_names()
# across queries of varying complexity, for the manuscript's Table 4.

import statistics
import time

import pandas as pd

from pymaude import MaudeDatabase
from query_cases import QUERY_DEVICE_CASES, DEVICE_NAME_SEARCH_CASES, GROUPED_CASE

DB_PATH      = '../maude.duckdb'
DATA_DIR     = '../maude_data'
N_REPLICATES = 5


def time_call(fn, *args, **kwargs):
    """Returns (n_rows, n_reports, times). Results are one row per matching
    device record, so n_rows can exceed n_reports (unique MDR_REPORT_KEY) when
    a report lists several matching devices. n_reports is the figure that
    corresponds to validation.py's counts."""
    times = []
    n_rows = n_reports = None
    for _ in range(N_REPLICATES):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        times.append(time.perf_counter() - t0)
        n_rows = len(result)
        n_reports = result['MDR_REPORT_KEY'].nunique()
    return n_rows, n_reports, times


def run(db):
    rows = []

    print('timing simple queries...')
    for case in QUERY_DEVICE_CASES:
        n_rows, n_reports, times = time_call(db.query_device, **case['kwargs'])
        rows.append({
            'function': 'query_device',
            'label': case['label'],
            'n_rows': n_rows,
            'n_reports': n_reports,
            'median_s': statistics.median(times),
            'min_s': min(times),
            'max_s': max(times),
        })
        print(f'query_device — {case["label"]}: reports={n_reports}, rows={n_rows}, median={statistics.median(times):.3f}s, [{min(times):.3f},{max(times):.3f}]')

    print('timing compund queries...')
    for case in DEVICE_NAME_SEARCH_CASES:
        n_rows, n_reports, times = time_call(db.search_by_device_names, case['criteria'])
        rows.append({
            'function': 'search_by_device_names',
            'label': case['label'],
            'n_rows': n_rows,
            'n_reports': n_reports,
            'median_s': statistics.median(times),
            'min_s': min(times),
            'max_s': max(times),
        })
        print(f'search_by_device_names — {case["label"]}: reports={n_reports}, rows={n_rows}, median={statistics.median(times):.3f}s, [{min(times):.3f},{max(times):.3f}]')

    print('timing grouped queries...')
    for case in GROUPED_CASE:
            n_rows, n_reports, times = time_call(db.search_by_device_names, case['criteria'])
            rows.append({
                'function': 'search_by_device_names',
                'label': case['label'],
                'n_rows': n_rows,
                'n_reports': n_reports,
                'median_s': statistics.median(times),
                'min_s': min(times),
                'max_s': max(times),
            })
            print(f'Grouped case of search_by_device_names — {case["label"]}: reports={n_reports}, rows={n_rows}, median={statistics.median(times):.3f}s, [{min(times):.3f},{max(times):.3f}]')

    return pd.DataFrame(rows)


if __name__ == '__main__':
    db = MaudeDatabase(DB_PATH, data_dir=DATA_DIR, verbose=False)
    table = run(db)
    db.close()

    table.to_csv('benchmark_query_results.csv', index=False)
    print('\nWrote benchmark_query_results.csv')
    print(f'\nRange of medians: {table["median_s"].min():.3f}s to {table["median_s"].max():.3f}s')
