# archive.py - portable, verifiable snapshots of a MaudeDatabase
# Copyright (C) 2026 Jacob Schwartz <jaschwa@umich.edu>
# MIT License

"""
Write, verify, and restore MaudeDatabase snapshots.

An archive is a plain directory:

    maude_archive/
        master.parquet, device.parquet, text.parquet, ...   one per loaded table
        raw.tar            the FDA source zips, byte-identical (optional)
        manifest.json      checksums, row counts, versions, provenance

Tables are Parquet (zstd) rather than a copy of the .duckdb file: DuckDB
stores the narrative column uncompressed, so the database file is ~10x the
size of the same data as Parquet, and a Parquet file is readable without
DuckDB-version compatibility concerns. raw.tar is an uncompressed tar of the
zips FDA distributes (already compressed), so they stay byte-identical to
the originals and the whole raw set is a single file.

The manifest is written last, so its presence means the archive is complete.
Nothing here talks to any hosting service: the directory is the archive.
"""

import hashlib
import json
import os
import shutil
import tarfile
import zipfile
from datetime import datetime

from .metadata import TABLE_METADATA

MANIFEST_VERSION = 2
MANIFEST_NAME = 'manifest.json'
RAW_TAR_NAME = 'raw.tar'


# ── Public ────────────────────────────────────────────────────────────────────

def write_archive(db, output_dir, include_raw=True, compression_level=3,
                  resume=False, overwrite=False):
    """Implementation of MaudeDatabase.archive(); see that docstring."""
    import pymaude

    if resume and overwrite:
        raise ValueError('resume and overwrite are mutually exclusive')
    if not isinstance(compression_level, int) or not 1 <= compression_level <= 22:
        raise ValueError('compression_level must be an integer from 1 to 22')

    if os.path.isdir(output_dir) and os.listdir(output_dir) and not (resume or overwrite):
        raise FileExistsError(
            f'{output_dir} is not empty. Pass resume=True to continue an interrupted '
            f'archive, or overwrite=True to replace it.'
        )
    os.makedirs(output_dir, exist_ok=True)

    # Drop the manifest first: while it's absent the directory is, by
    # definition, an incomplete archive. Also clear leftovers of an
    # interrupted run.
    _remove(os.path.join(output_dir, MANIFEST_NAME))
    for fn in os.listdir(output_dir):
        if fn.endswith('.tmp'):
            _remove(os.path.join(output_dir, fn))

    def say(msg):
        if db.verbose:
            print(msg)

    tables = {}
    for table in TABLE_METADATA:
        if not db._table_exists(table):
            continue
        filename = f'{table}.parquet'
        path = os.path.join(output_dir, filename)
        row_count = db.conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

        if resume and os.path.exists(path) and _parquet_rows(db, path) == row_count:
            say(f'  {filename}: already written, skipping')
        else:
            say(f'  {filename}: writing {row_count:,} rows...')
            tmp = path + '.tmp'
            db.conn.execute(
                f'COPY (SELECT * FROM "{table}") TO {_sql_str(tmp)} '
                f'(FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL {compression_level})'
            )
            os.replace(tmp, path)

        tables[table] = {
            'file': filename,
            'sha256': _sha256(path),
            'size_bytes': os.path.getsize(path),
            'row_count': row_count,
        }

    load_rows = db.conn.execute(
        'SELECT table_name, year, source_file, checksum, row_count, loaded_at '
        'FROM _load_metadata ORDER BY table_name, year'
    ).fetchall()

    manifest = {
        'manifest_version': MANIFEST_VERSION,
        'generated_at': datetime.now().isoformat(),
        'pymaude_version': pymaude.__version__,
        'duckdb_version': _duckdb_version(),
        'checksum_algorithm': 'sha256',
        'compression': {'format': 'parquet', 'codec': 'zstd', 'level': compression_level},
        'tables': tables,
        'load_metadata': [
            {
                'table': r[0], 'year': r[1], 'source_file': r[2],
                'sha256': r[3], 'row_count': r[4], 'loaded_at': r[5].isoformat(),
            }
            for r in load_rows
        ],
        'source_url': None,  # optional: hand-edit to record where this archive is published
    }

    if include_raw:
        manifest['raw'] = _archive_raw(
            db, output_dir, sorted({r[2] for r in load_rows if r[2]}), resume, say,
        )

    manifest_path = os.path.join(output_dir, MANIFEST_NAME)
    with open(manifest_path + '.tmp', 'w') as f:
        json.dump(manifest, f, indent=2)
    os.replace(manifest_path + '.tmp', manifest_path)

    if db.verbose:
        total = sum(t['size_bytes'] for t in tables.values())
        if manifest.get('raw', {}).get('file'):
            total += manifest['raw']['size_bytes']
        print(f'Archive written to {output_dir} ({total / 1e9:.2f} GB)')
        print(f'  Tables : {len(tables)}')
        if include_raw:
            raw = manifest['raw']
            print(f'  Raw    : {len(raw["zips"])} zips'
                  + (f', {len(raw["missing"])} source files with no zip found' if raw['missing'] else ''))

    return manifest_path


def restore_archive(archive_dir, db_path, data_dir='./maude_data', verify=True,
                    restore_raw=False, memory_limit='4GB', verbose=True):
    """Implementation of MaudeDatabase.from_archive(); see that docstring."""
    from .database import MaudeDatabase

    manifest = _read_manifest(archive_dir)

    if verify:
        if verbose:
            print('Verifying archive checksums...')
        problems = verify_archive(archive_dir)
        if problems:
            raise ValueError('Archive failed verification:\n  ' + '\n  '.join(problems))

    db = MaudeDatabase(db_path, data_dir=data_dir, verbose=verbose, memory_limit=memory_limit)
    try:
        existing = [t for t in manifest['tables'] if db._table_exists(t)]
        if existing:
            raise FileExistsError(
                f'{db_path} already contains table(s) {existing}; restore into a new database file.'
            )

        for table, entry in manifest['tables'].items():
            if verbose:
                print(f'  Importing {table} ({entry["row_count"]:,} rows)...')
            path = os.path.join(archive_dir, entry['file'])
            db.conn.execute(
                f'CREATE TABLE "{table}" AS SELECT * FROM read_parquet({_sql_str(path)})'
            )
            actual = db.conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if actual != entry['row_count']:
                raise ValueError(
                    f'{table}: imported {actual:,} rows but the manifest records {entry["row_count"]:,}'
                )

        db.conn.execute('DELETE FROM _load_metadata')
        db.conn.executemany(
            'INSERT INTO _load_metadata VALUES (?, ?, ?, ?, ?, ?)',
            [
                (m['table'], m['year'], m['source_file'], m['sha256'],
                 m['row_count'], datetime.fromisoformat(m['loaded_at']))
                for m in manifest['load_metadata']
            ],
        )

        if verbose:
            print('  Building indexes...')
        db._create_indexes()
        db.conn.execute('CHECKPOINT')
    except BaseException:
        db.close()
        raise

    if restore_raw:
        extract_raw(archive_dir, data_dir, verbose=verbose)

    return db


def verify_archive(archive_dir, deep=False):
    """
    Check an archive directory against its manifest.

    Confirms every file the manifest lists exists with the recorded size and
    SHA-256. With deep=True, also hashes each zip inside raw.tar against its
    recorded checksum (reads all of raw.tar a second time).

    Returns:
        A list of human-readable problem strings — empty if the archive is intact.
    Raises:
        FileNotFoundError / ValueError if there is no readable manifest.
    """
    manifest = _read_manifest(archive_dir)
    problems = []

    def check(filename, sha256, size):
        path = os.path.join(archive_dir, filename)
        if not os.path.exists(path):
            problems.append(f'{filename}: missing')
            return False
        if os.path.getsize(path) != size:
            problems.append(f'{filename}: size {os.path.getsize(path):,} != recorded {size:,}')
            return False
        if _sha256(path) != sha256:
            problems.append(f'{filename}: SHA-256 mismatch')
            return False
        return True

    for entry in manifest['tables'].values():
        check(entry['file'], entry['sha256'], entry['size_bytes'])

    raw = manifest.get('raw')
    if raw and raw.get('file'):
        tar_ok = check(raw['file'], raw['sha256'], raw['size_bytes'])
        if deep and tar_ok:
            expected = {z['name']: z['sha256'] for z in raw['zips']}
            seen = set()
            with tarfile.open(os.path.join(archive_dir, raw['file'])) as tar:
                for member in tar:
                    if not member.isfile():
                        continue
                    seen.add(member.name)
                    if member.name not in expected:
                        problems.append(f'{raw["file"]}: unexpected member {member.name}')
                        continue
                    h = hashlib.sha256()
                    with tar.extractfile(member) as f:
                        for chunk in iter(lambda: f.read(1 << 20), b''):
                            h.update(chunk)
                    if h.hexdigest() != expected[member.name]:
                        problems.append(f'{raw["file"]}: {member.name} SHA-256 mismatch')
            for name in sorted(set(expected) - seen):
                problems.append(f'{raw["file"]}: member {name} missing')

    return problems


def extract_raw(archive_dir, data_dir='./maude_data', unzip=True, verbose=True):
    """
    Extract the FDA zips from an archive's raw.tar into data_dir, and (with
    unzip=True) unzip them there. After this, add_years(..., download=True)
    finds the zips cached locally and loads them without touching the network.

    Returns:
        The list of zip filenames written to data_dir.
    """
    manifest = _read_manifest(archive_dir)
    raw = manifest.get('raw')
    if not raw or not raw.get('file'):
        raise FileNotFoundError(f'{archive_dir} has no raw files (archived with include_raw=False?)')

    os.makedirs(data_dir, exist_ok=True)
    written = []
    with tarfile.open(os.path.join(archive_dir, raw['file'])) as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = os.path.basename(member.name)  # never trust paths from an archive
            dest = os.path.join(data_dir, name)
            if verbose:
                print(f'  Extracting {name}')
            with tar.extractfile(member) as src, open(dest, 'wb') as out:
                shutil.copyfileobj(src, out, 1 << 20)
            written.append(name)

    if unzip:
        for name in written:
            with zipfile.ZipFile(os.path.join(data_dir, name)) as z:
                z.extractall(data_dir)

    return written


# ── Private ───────────────────────────────────────────────────────────────────

def _archive_raw(db, output_dir, source_files, resume, say):
    """Bundle the zips behind `source_files` (the .txt names in _load_metadata)
    into raw.tar and return the manifest's 'raw' block."""
    zips, missing = _locate_zips(db.data_dir, source_files)
    if missing:
        say(f'  No zip found in {db.data_dir} for {len(missing)} source file(s) '
            f'(e.g. {missing[0]}); they will not be in raw.tar')

    if not zips:
        return {'file': None, 'sha256': None, 'size_bytes': None, 'zips': [], 'missing': missing}

    tar_path = os.path.join(output_dir, RAW_TAR_NAME)
    sizes = {name: os.path.getsize(os.path.join(db.data_dir, name)) for name in zips}

    if resume and os.path.exists(tar_path) and _tar_matches(tar_path, sizes):
        say(f'  {RAW_TAR_NAME}: already written, skipping')
        zip_hashes = {name: _sha256(os.path.join(db.data_dir, name)) for name in zips}
    else:
        say(f'  {RAW_TAR_NAME}: bundling {len(zips)} zips ({sum(sizes.values()) / 1e9:.2f} GB)...')
        zip_hashes = _write_tar(tar_path, db.data_dir, sorted(zips))

    return {
        'file': RAW_TAR_NAME,
        'sha256': _sha256(tar_path),
        'size_bytes': os.path.getsize(tar_path),
        'zips': [
            {'name': name, 'sha256': zip_hashes[name], 'size_bytes': sizes[name],
             'source_files': zips[name]}
            for name in sorted(zips)
        ],
        'missing': missing,
    }


def _locate_zips(data_dir, source_files):
    """Map each source .txt to the zip in data_dir that contains it.
    Returns ({zip_name: [source_file, ...]}, [source files with no zip])."""
    index = {}
    for fn in sorted(os.listdir(data_dir)):
        if not fn.lower().endswith('.zip'):
            continue
        try:
            with zipfile.ZipFile(os.path.join(data_dir, fn)) as z:
                for member in z.namelist():
                    index.setdefault(os.path.basename(member), fn)
        except zipfile.BadZipFile:
            continue
    lower = {k.lower(): v for k, v in index.items()}

    zips, missing = {}, []
    for source_file in source_files:
        zip_name = index.get(source_file) or lower.get(source_file.lower())
        if zip_name is None:
            missing.append(source_file)
        else:
            zips.setdefault(zip_name, []).append(source_file)
    return zips, missing


class _HashingReader:
    """File wrapper that hashes what's read, so a zip is checksummed in the
    same pass that copies it into the tar."""

    def __init__(self, f):
        self._f = f
        self.hash = hashlib.sha256()

    def read(self, n=-1):
        buf = self._f.read(n)
        self.hash.update(buf)
        return buf


def _write_tar(tar_path, data_dir, zip_names):
    """Write an uncompressed tar of the zips (to a .tmp name, then renamed
    into place). Returns {zip_name: sha256}."""
    hashes = {}
    tmp = tar_path + '.tmp'
    with tarfile.open(tmp, 'w', format=tarfile.GNU_FORMAT) as tar:
        for name in zip_names:
            src = os.path.join(data_dir, name)
            info = tar.gettarinfo(src, arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            with open(src, 'rb') as f:
                reader = _HashingReader(f)
                tar.addfile(info, reader)
            hashes[name] = reader.hash.hexdigest()
    os.replace(tmp, tar_path)
    return hashes


def _tar_matches(tar_path, sizes):
    """True if tar_path is a readable tar holding exactly these members at
    these sizes (header-only scan, so cheap even for a multi-GB tar)."""
    try:
        with tarfile.open(tar_path) as tar:
            found = {m.name: m.size for m in tar if m.isfile()}
    except (tarfile.TarError, OSError):
        return False
    return found == sizes


def _parquet_rows(db, path):
    try:
        return db.conn.execute(
            f'SELECT COUNT(*) FROM read_parquet({_sql_str(path)})'
        ).fetchone()[0]
    except Exception:
        return None


def _read_manifest(archive_dir):
    path = os.path.join(archive_dir, MANIFEST_NAME)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f'{path} not found — not a PyMAUDE archive, or the archive was never completed'
        )
    with open(path) as f:
        manifest = json.load(f)
    if manifest.get('manifest_version') != MANIFEST_VERSION:
        raise ValueError(
            f'Unsupported manifest_version {manifest.get("manifest_version")!r} '
            f'(this PyMAUDE reads version {MANIFEST_VERSION})'
        )
    return manifest


def _sha256(path, chunk_size=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()


def _sql_str(s):
    return "'" + s.replace("'", "''") + "'"


def _duckdb_version():
    import duckdb
    return duckdb.__version__


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
