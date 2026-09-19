# benchmark_archive.py - time and peak memory for MaudeDatabase.archive()
# (Parquet tables + raw.tar + manifest), for the manuscript.
#
#   python benchmark_archive.py | tee results_benchmark_archive.txt
#   python benchmark_archive.py --keep-archive     # keep the final archive instead of deleting it

import json
import os
import resource
import shutil
import statistics
import subprocess
import sys
import time

from pymaude import MaudeDatabase, verify_archive

DB_PATH           = '../maude.duckdb'
DATA_DIR          = '../maude_data'
# Written and deleted on every replicate. Ideally outside Dropbox: a ~13 GB
# write that Dropbox is syncing at the same time will distort the timing.
OUTPUT_DIR        = '../maude_archive'
COMPRESSION_LEVEL = 3
N_REPLICATES      = 5
# The last replicate's archive is verified, then deleted unless this is True
# (or --keep-archive is passed). Deleting frees ~13 GB.
KEEP_ARCHIVE      = False


def fmt_min_sec(seconds):
    m, s = divmod(round(seconds), 60)
    return f"{m} min {s} sec"


def dir_size(path):
    return sum(os.path.getsize(os.path.join(path, f)) for f in os.listdir(path))


def run_replicate_subprocess():
    """Runs a single archive() in a fresh process so peak RSS reflects just
    that run, then prints the result as JSON for the parent to collect."""
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    db = MaudeDatabase(DB_PATH, data_dir=DATA_DIR, verbose=True, memory_limit='4GB')
    t0 = time.perf_counter()
    db.archive(OUTPUT_DIR, include_raw=True, compression_level=COMPRESSION_LEVEL)
    elapsed = time.perf_counter() - t0
    db.close()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak / 1e6 if sys.platform == 'darwin' else peak / 1e3  # macOS: bytes, Linux: KB
    print(json.dumps({'elapsed': elapsed, 'peak_mb': peak_mb, 'archive_bytes': dir_size(OUTPUT_DIR)}))


if __name__ == '__main__':
    if '--replicate' in sys.argv:
        run_replicate_subprocess()
        sys.exit(0)

    if not os.path.exists(DB_PATH):
        raise Exception(f'{DB_PATH} not found — build the database first (see benchmark_init_db.py)')
    if os.path.exists(OUTPUT_DIR):
        raise Exception(f'{OUTPUT_DIR} already exists — aborting (each replicate deletes and rewrites it)')

    print(f"\nBeginning {N_REPLICATES} replicates of archive() (zstd level {COMPRESSION_LEVEL})...")
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

    # The archive from the last replicate is still on disk: confirm it's intact
    # (before it's removed below). A failure here leaves it in place to inspect.
    problems = verify_archive(OUTPUT_DIR)
    if problems:
        raise Exception('Archive failed verification:\n  ' + '\n  '.join(problems))

    times = [r['elapsed'] for r in replicates]
    peak_gb = max(r['peak_mb'] for r in replicates) / 1e3
    archive_gb = replicates[-1]['archive_bytes'] / 1e9
    db_gb = os.path.getsize(DB_PATH) / 1e9

    print("\n==========================")
    print(f"Median archive time (n={N_REPLICATES}):   {fmt_min_sec(statistics.median(times))}")
    print(f"Range:                           {fmt_min_sec(min(times))} to {fmt_min_sec(max(times))}")
    print(f"Peak memory across replicates:   {peak_gb:.2f} GB RSS (DuckDB memory_limit=4GB)")
    print(f"Archive size on disk:            {archive_gb:.1f} GB (database file: {db_gb:.1f} GB)")
    print("Archive verified against its manifest.")

    if KEEP_ARCHIVE or '--keep-archive' in sys.argv:
        print(f"Archive kept at:                 {os.path.abspath(OUTPUT_DIR)}")
    else:
        shutil.rmtree(OUTPUT_DIR)
        print(f"Archive removed:                 {os.path.abspath(OUTPUT_DIR)} (use --keep-archive to keep it)")
