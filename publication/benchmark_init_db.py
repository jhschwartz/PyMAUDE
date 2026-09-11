from pymaude import MaudeDatabase
import json
import os
import resource
import statistics
import subprocess
import sys
import time


DB_PATH      = '../maude.duckdb'
DATA_DIR     = '../maude_data'
YEARS        = 'all'
TABLES       = ['master', 'device', 'text', 'patient', 'device_problem', 'patient_problem']
N_REPLICATES = 5


def build(download):
    db = MaudeDatabase(DB_PATH, data_dir=DATA_DIR, verbose=True, memory_limit='2GB')
    t0 = time.perf_counter()
    db.add_years(YEARS, tables=TABLES, download=download)
    elapsed = time.perf_counter() - t0
    db.close()
    return elapsed


def fmt_min_sec(seconds):
    m, s = divmod(round(seconds), 60)
    return f"{m} min {s} sec"


def run_replicate_subprocess():
    """Runs a single load-only build in a fresh process so peak RSS reflects
    just that build, then prints the result as JSON for the parent to collect."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    elapsed = build(download=False)
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # macOS: bytes
    print(json.dumps({'elapsed': elapsed, 'peak_mb': peak_mb}))


if __name__ == '__main__':
    if '--replicate' in sys.argv:
        run_replicate_subprocess()
        sys.exit(0)

    if os.path.exists(DB_PATH) or os.path.exists(DATA_DIR):
        raise Exception('db files already exist — aborting to avoid tainting benchmark')

    print("\nBeginning Run 1 (download + load)...")
    t_full = build(download=True)
    print(f"\nRun 1 (download + load): {t_full:.1f} seconds")

    print("--------------------------")

    os.remove(DB_PATH)

    print(f"\nBeginning {N_REPLICATES} replicates (load only, from cached source files)...")
    replicates = []
    for i in range(N_REPLICATES):
        proc = subprocess.run(
            [sys.executable, __file__, '--replicate'],
            capture_output=True, text=True,
        )
        if proc.stdout:
            print(proc.stdout, end='' if proc.stdout.endswith('\n') else '\n')
        if proc.returncode != 0:
            print(f"\nReplicate {i + 1} failed (exit code {proc.returncode}):")
            print(proc.stderr)
            proc.check_returncode()
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        replicates.append(result)
        print(f"  Replicate {i + 1}: {result['elapsed']:.1f} s, {result['peak_mb']:.0f} MB peak RSS")

    load_times = [r['elapsed'] for r in replicates]
    peak_mbs = [r['peak_mb'] for r in replicates]

    median_load = statistics.median(load_times)
    min_load, max_load = min(load_times), max(load_times)
    peak_gb = max(peak_mbs) / 1e3
    download_estimate = t_full - median_load
    disk_bytes = os.path.getsize(DB_PATH)
    disk_gb = disk_bytes / 1e9

    print("\n==========================")
    print(f"Estimated download time:        {fmt_min_sec(download_estimate)}")
    print(f"Median local build time (n={N_REPLICATES}): {fmt_min_sec(median_load)}")
    print(f"Range:                           {fmt_min_sec(min_load)} to {fmt_min_sec(max_load)}")
    print(f"Peak memory across replicates:   {peak_gb:.2f} GB (DuckDB memory_limit=2GB)")
    print(f"Database size on disk:           {disk_gb:.1f} GB")