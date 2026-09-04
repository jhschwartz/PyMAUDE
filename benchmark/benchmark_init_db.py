from pymaude import MaudeDatabase
import time, os
import resource


DB_PATH  = '../maude.duckdb'
DATA_DIR = '../maude_data'
YEARS    = 'all'
TABLES   = ['master', 'device', 'text', 'patient', 'problems']


def run(download):
    db = MaudeDatabase(DB_PATH, data_dir=DATA_DIR, verbose=True, memory_limit='2GB')
    t0 = time.perf_counter()
    db.add_years(YEARS, tables=TABLES, download=download)
    elapsed = time.perf_counter() - t0
    db.close()
    return elapsed


if __name__ == '__main__':
    if os.path.exists(DB_PATH) or os.path.exists(DATA_DIR):
        raise Exception('db files already exist — aborting to avoid tainting benchmark')

    print("\nBeginning Run 1 (download + load)...")
    t_full = run(download=True)
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # macOS: bytes

    print(f"\nRun 1 (download + load): {t_full:.1f} seconds, {peak_mb} mb")
    
    print("--------------------------")

    os.remove(DB_PATH)

    print("\nBeginning Run 2 (load only)...")
    t_load = run(download=False)
    print(f"Run 2 (load only):       {t_load:.1f} seconds, {peak_mb} mb")
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # macOS: bytes
    print(f"Estimated download time: {t_full - t_load:.1f}s")
