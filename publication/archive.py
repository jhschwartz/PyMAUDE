from pymaude import MaudeDatabase
import os


DB_PATH     = '../maude.duckdb'
DATA_DIR    = '../maude_data'
OUTPUT_DIR  = '../maude_archive'
INCLUDE_RAW = True   # bundle raw MAUDE source files alongside the .duckdb file


if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        raise Exception(f'{DB_PATH} not found — build the database first (see benchmark_init_db.py)')

    if os.path.exists(OUTPUT_DIR):
        raise Exception(f'{OUTPUT_DIR} already exists — aborting to avoid overwriting a prior archive')

    db = MaudeDatabase(DB_PATH, data_dir=DATA_DIR, verbose=True)
    manifest_path = db.archive(OUTPUT_DIR, include_raw=INCLUDE_RAW)
    db.close()

    print(f'\nArchive ready for upload at: {os.path.abspath(OUTPUT_DIR)}')
    print(f'Manifest: {manifest_path}')
