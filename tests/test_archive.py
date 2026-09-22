"""Tests for MaudeDatabase.archive() / from_archive() and pymaude.archive helpers.

Everything runs on the synthetic fixtures from conftest.py; the `zipped_data`
fixture additionally packs each fixture .txt into a zip, like FDA's downloads.
"""

import json
import os
import tarfile
import zipfile

import pytest

from pymaude import MaudeDatabase, TABLE_METADATA, extract_raw, verify_archive

TABLES = list(TABLE_METADATA)


@pytest.fixture
def zipped_data(data_dir):
    """Zip every fixture .txt (as FDA ships them: one txt inside one zip).
    One zip is deliberately named unlike its contents, so archiving has to
    look inside zips rather than guess names. Returns {zip name: txt name}."""
    zips = {}
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith('.txt'):
            continue
        zip_name = 'device_release.zip' if fn == 'device2020.txt' else fn[:-4] + '.zip'
        with zipfile.ZipFile(os.path.join(data_dir, zip_name), 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(os.path.join(data_dir, fn), arcname=fn)
        zips[zip_name] = fn
    return zips


@pytest.fixture
def archived(db, zipped_data, tmp_path):
    """(archive_dir, manifest) for a full archive of the fixture database."""
    out = tmp_path / 'archive'
    manifest_path = db.archive(str(out))
    return out, json.loads(open(manifest_path).read())


def _sha256(path):
    from pymaude.archive import _sha256 as sha
    return sha(str(path))


class TestArchive:
    def test_writes_expected_files(self, archived):
        out, manifest = archived
        assert sorted(os.listdir(out)) == sorted(
            [f'{t}.parquet' for t in TABLES] + ['raw.tar', 'manifest.json']
        )
        assert manifest['manifest_version'] == 2
        assert manifest['compression'] == {'format': 'parquet', 'codec': 'zstd', 'level': 3}

    def test_manifest_records_tables(self, db, archived):
        out, manifest = archived
        assert set(manifest['tables']) == set(TABLES)
        for table, entry in manifest['tables'].items():
            assert entry['row_count'] == db.query(f'SELECT COUNT(*) FROM {table}').iloc[0, 0]
            assert entry['sha256'] == _sha256(out / entry['file'])
            assert entry['size_bytes'] == os.path.getsize(out / entry['file'])

    def test_manifest_records_load_metadata(self, db, archived):
        _, manifest = archived
        expected = db.query('SELECT COUNT(*) FROM _load_metadata').iloc[0, 0]
        assert len(manifest['load_metadata']) == expected
        assert {m['source_file'] for m in manifest['load_metadata']} >= {'device2020.txt', 'mdrfoithru2020.txt'}

    def test_raw_tar_members_are_byte_identical_to_source_zips(self, data_dir, archived):
        out, manifest = archived
        raw = manifest['raw']
        assert raw['missing'] == []
        assert raw['sha256'] == _sha256(out / 'raw.tar')
        with tarfile.open(out / 'raw.tar') as tar:
            names = {m.name for m in tar}
            assert names == {z['name'] for z in raw['zips']}
            for z in raw['zips']:
                assert z['sha256'] == _sha256(os.path.join(data_dir, z['name']))
                assert tar.extractfile(z['name']).read() == open(os.path.join(data_dir, z['name']), 'rb').read()

    def test_raw_maps_source_files_to_zips_by_content(self, archived):
        _, manifest = archived
        by_zip = {z['name']: z['source_files'] for z in manifest['raw']['zips']}
        assert by_zip['device_release.zip'] == ['device2020.txt']

    def test_raw_tar_includes_per_year_zip_alongside_legacy_zip(self, tmp_path):
        """A legacy file with rows dated in a later year must not hide that
        year's own per-year zip from raw.tar."""
        d = tmp_path / 'maude_data'
        d.mkdir()
        hdr = ('MDR_REPORT_KEY|BRAND_NAME|GENERIC_NAME|MANUFACTURER_D_NAME|'
               'DEVICE_REPORT_PRODUCT_CODE|DATE_RECEIVED\n')
        contents = {
            'foidevthru1997.txt': hdr + '1|A|B|C|X|03/01/1997\n2|A|B|C|X|03/01/2012\n',
            'device2012.txt': hdr + '3|A|B|C|X|05/01/2012\n',
        }
        for fn, text in contents.items():
            (d / fn).write_text(text)
            with zipfile.ZipFile(d / (fn[:-4] + '.zip'), 'w') as z:
                z.write(d / fn, arcname=fn)
        db = MaudeDatabase(str(tmp_path / 'legacy.duckdb'), data_dir=str(d), verbose=False)
        db.add_years([1997, 2012], tables=['device'])
        manifest = json.loads(open(db.archive(str(tmp_path / 'archive'))).read())
        db.close()
        assert {z['name'] for z in manifest['raw']['zips']} == {
            'foidevthru1997.zip', 'device2012.zip'}

    def test_missing_zip_is_recorded_not_fatal(self, db, zipped_data, data_dir, tmp_path):
        os.remove(os.path.join(data_dir, 'device_release.zip'))
        out = tmp_path / 'archive'
        manifest = json.loads(open(db.archive(str(out))).read())
        assert 'device2020.txt' in manifest['raw']['missing']
        assert 'device_release.zip' not in {z['name'] for z in manifest['raw']['zips']}

    def test_no_zips_at_all(self, db, tmp_path):
        """The bare fixture has only .txt files: the archive still succeeds,
        with an empty raw block and no raw.tar."""
        out = tmp_path / 'archive'
        manifest = json.loads(open(db.archive(str(out))).read())
        assert manifest['raw']['file'] is None
        assert manifest['raw']['missing']
        assert not (out / 'raw.tar').exists()

    def test_include_raw_false(self, db, zipped_data, tmp_path):
        out = tmp_path / 'archive'
        manifest = json.loads(open(db.archive(str(out), include_raw=False)).read())
        assert 'raw' not in manifest
        assert not (out / 'raw.tar').exists()
        assert verify_archive(str(out)) == []
        with pytest.raises(FileNotFoundError):
            extract_raw(str(out), str(tmp_path / 'x'))

    def test_only_loaded_tables_are_archived(self, tmp_path, data_dir):
        db = MaudeDatabase(str(tmp_path / 'small.duckdb'), data_dir=data_dir, verbose=False)
        db.add_years(2020, tables=['master'])
        out = tmp_path / 'archive'
        manifest = json.loads(open(db.archive(str(out), include_raw=False)).read())
        db.close()
        assert set(manifest['tables']) == {'master'}
        assert sorted(os.listdir(out)) == ['manifest.json', 'master.parquet']

    def test_no_tmp_files_left_behind(self, archived):
        out, _ = archived
        assert not [f for f in os.listdir(out) if f.endswith('.tmp')]

    def test_rejects_non_empty_directory(self, db, archived):
        out, _ = archived
        with pytest.raises(FileExistsError):
            db.archive(str(out))

    def test_rejects_resume_with_overwrite(self, db, tmp_path):
        with pytest.raises(ValueError):
            db.archive(str(tmp_path / 'a'), resume=True, overwrite=True)

    @pytest.mark.parametrize('level', [0, 23, 'high', 3.5])
    def test_rejects_invalid_compression_level(self, db, tmp_path, level):
        with pytest.raises(ValueError):
            db.archive(str(tmp_path / 'a'), compression_level=level)

    def test_overwrite_replaces_archive(self, db, archived):
        out, _ = archived
        db.conn.execute("DELETE FROM master WHERE MDR_REPORT_KEY = '1004'")
        manifest = json.loads(open(db.archive(str(out), overwrite=True)).read())
        assert manifest['tables']['master']['row_count'] == 3
        assert verify_archive(str(out)) == []


class TestResume:
    def test_resume_skips_complete_files_and_rewrites_missing_ones(self, db, archived):
        out, _ = archived
        keep = out / 'master.parquet'
        before = keep.stat().st_mtime_ns
        os.remove(out / 'manifest.json')  # interrupted before the manifest
        os.remove(out / 'text.parquet')
        os.remove(out / 'raw.tar')

        manifest = json.loads(open(db.archive(str(out), resume=True)).read())

        assert keep.stat().st_mtime_ns == before  # untouched
        assert (out / 'text.parquet').exists() and (out / 'raw.tar').exists()
        assert manifest['tables']['master']['sha256'] == _sha256(keep)
        assert verify_archive(str(out)) == []

    def test_resume_skips_complete_raw_tar(self, db, archived):
        out, _ = archived
        before = (out / 'raw.tar').stat().st_mtime_ns
        db.archive(str(out), resume=True)
        assert (out / 'raw.tar').stat().st_mtime_ns == before

    def test_resume_rewrites_file_with_stale_row_count(self, db, archived):
        out, _ = archived
        db.conn.execute("DELETE FROM master WHERE MDR_REPORT_KEY = '1004'")
        manifest = json.loads(open(db.archive(str(out), resume=True)).read())
        assert manifest['tables']['master']['row_count'] == 3
        assert verify_archive(str(out)) == []

    def test_resume_clears_stale_tmp_files(self, db, archived):
        out, _ = archived
        (out / 'text.parquet.tmp').write_bytes(b'half written')
        db.archive(str(out), resume=True)
        assert not (out / 'text.parquet.tmp').exists()


class TestVerify:
    def test_intact_archive(self, archived):
        out, _ = archived
        assert verify_archive(str(out)) == []
        assert verify_archive(str(out), deep=True) == []

    def test_no_manifest(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            verify_archive(str(tmp_path))

    def test_unsupported_manifest_version(self, archived):
        out, manifest = archived
        manifest['manifest_version'] = 1
        (out / 'manifest.json').write_text(json.dumps(manifest))
        with pytest.raises(ValueError):
            verify_archive(str(out))

    def test_detects_corrupted_parquet(self, archived):
        out, _ = archived
        path = out / 'master.parquet'
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0xFF  # same size, different content
        path.write_bytes(bytes(data))
        problems = verify_archive(str(out))
        assert problems == ['master.parquet: SHA-256 mismatch']

    def test_detects_missing_file(self, archived):
        out, _ = archived
        os.remove(out / 'device.parquet')
        assert verify_archive(str(out)) == ['device.parquet: missing']

    def test_detects_truncated_tar(self, archived):
        out, _ = archived
        path = out / 'raw.tar'
        path.write_bytes(path.read_bytes()[:-1024])
        problems = verify_archive(str(out))
        assert len(problems) == 1 and problems[0].startswith('raw.tar: size')

    def test_deep_detects_member_checksum_mismatch(self, archived):
        out, manifest = archived
        manifest['raw']['zips'][0]['sha256'] = '0' * 64
        (out / 'manifest.json').write_text(json.dumps(manifest))
        assert verify_archive(str(out)) == []  # shallow check can't see inside the tar
        problems = verify_archive(str(out), deep=True)
        assert problems == [f'raw.tar: {manifest["raw"]["zips"][0]["name"]} SHA-256 mismatch']


class TestFromArchive:
    def _restore(self, out, tmp_path, **kwargs):
        kwargs.setdefault('data_dir', str(tmp_path / 'restored_data'))
        kwargs.setdefault('verbose', False)
        return MaudeDatabase.from_archive(str(out), str(tmp_path / 'restored.duckdb'), **kwargs)

    def test_round_trip_tables_are_identical(self, db, archived, tmp_path):
        out, _ = archived
        restored = self._restore(out, tmp_path)
        try:
            for table in TABLES:
                # Same rows, values and column types (DataFrame equality checks all three).
                assert db.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] > 0
                assert db.conn.execute(f'SELECT * FROM {table}').description == \
                    restored.conn.execute(f'SELECT * FROM {table}').description
                a = db.query(f'SELECT * FROM {table} ORDER BY ALL')
                b = restored.query(f'SELECT * FROM {table} ORDER BY ALL')
                assert a.equals(b)
        finally:
            restored.close()

    def test_round_trip_restores_load_metadata(self, db, archived, tmp_path):
        out, _ = archived
        restored = self._restore(out, tmp_path)
        try:
            cols = 'table_name, year, source_file, checksum, row_count, loaded_at'
            a = db.query(f'SELECT {cols} FROM _load_metadata ORDER BY ALL')
            b = restored.query(f'SELECT {cols} FROM _load_metadata ORDER BY ALL')
            assert a.equals(b)
        finally:
            restored.close()

    def test_round_trip_restores_indexes(self, archived, tmp_path):
        out, _ = archived
        restored = self._restore(out, tmp_path)
        try:
            names = {r[0] for r in restored.conn.execute('SELECT index_name FROM duckdb_indexes()').fetchall()}
            assert 'idx_master_mdr_report_key' in names
            assert 'idx_text_mdr_report_key' in names
        finally:
            restored.close()

    def test_restored_db_is_queryable_and_add_years_is_a_no_op(self, archived, data_dir, tmp_path):
        out, _ = archived
        restored = self._restore(out, tmp_path, data_dir=data_dir)
        try:
            assert len(restored.search_by_device_names(['venovo'])) == 1
            loaded_at = restored.query("SELECT loaded_at FROM _load_metadata WHERE table_name = 'master'")
            restored.add_years(2020, tables=['master'])  # checksums match -> nothing reloaded
            assert restored.query('SELECT COUNT(*) FROM master').iloc[0, 0] == 4
            assert restored.query(
                "SELECT loaded_at FROM _load_metadata WHERE table_name = 'master'"
            ).equals(loaded_at)
        finally:
            restored.close()

    def test_refuses_existing_tables(self, db, archived):
        out, _ = archived
        with pytest.raises(FileExistsError):
            MaudeDatabase.from_archive(str(out), db.db_path, data_dir=db.data_dir, verbose=False)

    def test_refuses_corrupted_archive(self, archived, tmp_path):
        out, _ = archived
        path = out / 'patient.parquet'
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0xFF
        path.write_bytes(bytes(data))
        with pytest.raises(ValueError, match='patient.parquet'):
            self._restore(out, tmp_path)

    def test_restore_raw_extracts_zips_and_txt(self, archived, tmp_path):
        out, manifest = archived
        restore_dir = tmp_path / 'restored_data'
        restored = self._restore(out, tmp_path, restore_raw=True)
        try:
            # Only zips behind loaded source files are archived (not device2019's).
            assert not (restore_dir / 'device2019.zip').exists()
            for z in manifest['raw']['zips']:
                assert (restore_dir / z['name']).exists()
                for source_file in z['source_files']:
                    assert (restore_dir / source_file).exists()
        finally:
            restored.close()

    def test_extract_raw_without_unzip(self, archived, tmp_path):
        out, manifest = archived
        dest = tmp_path / 'raw_out'
        names = extract_raw(str(out), str(dest), unzip=False, verbose=False)
        assert set(names) == {z['name'] for z in manifest['raw']['zips']}
        assert not any(f.endswith('.txt') for f in os.listdir(dest))
