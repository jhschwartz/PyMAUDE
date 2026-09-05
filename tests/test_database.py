"""Tests for MaudeDatabase core functionality."""

import os
import pytest
from pymaude import MaudeDatabase


class TestAddYears:
    def test_loads_master(self, db):
        result = db.query("SELECT COUNT(*) FROM master")
        assert result.iloc[0, 0] == 4

    def test_loads_device(self, db):
        result = db.query("SELECT COUNT(*) FROM device")
        assert result.iloc[0, 0] == 4

    def test_loads_text(self, db):
        result = db.query("SELECT COUNT(*) FROM text")
        assert result.iloc[0, 0] == 4

    def test_loads_patient(self, db):
        result = db.query("SELECT COUNT(*) FROM patient")
        # Patient fixture has 4 records; all are loaded (no year filter)
        assert result.iloc[0, 0] == 4

    def test_loads_problem(self, db):
        result = db.query("SELECT COUNT(*) FROM problem")
        assert result.iloc[0, 0] == 3

    def test_problem_dedup_on_two_file_load(self, tmp_path, data_dir):
        """Loading thru + current-year problem files should not create duplicates."""
        from datetime import datetime
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'dedup.duckdb'), data_dir=data_dir, verbose=False)
        current_year = datetime.now().year
        # Load prior years (triggers thru file) + current year (triggers foidevproblem.txt)
        db.add_years([2020, current_year], tables=['problem'])
        result = db.query("SELECT COUNT(*) FROM problem")
        # thru has 3 rows, current has 2 rows but 1 overlaps → expect 4 unique rows
        assert result.iloc[0, 0] == 4
        db.close()

    def test_device_name_concat_created(self, db):
        result = db.query("SELECT DEVICE_NAME_CONCAT FROM device LIMIT 1")
        assert 'DEVICE_NAME_CONCAT' in result.columns
        # Should be non-null and uppercase
        val = result.iloc[0, 0]
        assert val == val.upper()
        assert '|' in val

    def test_checksum_skip(self, tmp_path, data_dir):
        """Second add_years call on same data should be a no-op (checksum match)."""
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'ck.duckdb'), data_dir=data_dir, verbose=False)
        db.add_years(2020, tables=['device'])
        count_before = db.query("SELECT COUNT(*) FROM device").iloc[0, 0]
        db.add_years(2020, tables=['device'])
        count_after = db.query("SELECT COUNT(*) FROM device").iloc[0, 0]
        assert count_before == count_after
        db.close()

    def test_force_reload(self, tmp_path, data_dir):
        """force_reload=True should reload even on checksum match."""
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'fr.duckdb'), data_dir=data_dir, verbose=False)
        db.add_years(2020, tables=['device'])
        count_before = db.query("SELECT COUNT(*) FROM device").iloc[0, 0]
        db.add_years(2020, tables=['device'], force_reload=True)
        count_after = db.query("SELECT COUNT(*) FROM device").iloc[0, 0]
        assert count_before == count_after  # Same data → same row count
        db.close()

    def test_unknown_table_skipped(self, tmp_path, data_dir):
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'uk.duckdb'), data_dir=data_dir, verbose=False)
        # Should not raise; unknown table is skipped
        db.add_years(2020, tables=['nonexistent'])
        db.close()

    def test_future_year_skipped(self, tmp_path, data_dir):
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'fy.duckdb'), data_dir=data_dir, verbose=False)
        db.add_years(2099, tables=['device'])
        # No device table should be created
        assert not db._table_exists('device')
        db.close()

    def test_year_before_start_skipped(self, tmp_path, data_dir):
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'bs.duckdb'), data_dir=data_dir, verbose=False)
        db.add_years(1990, tables=['device'])  # device starts 2000
        assert not db._table_exists('device')
        db.close()

    def test_context_manager(self, tmp_path, data_dir):
        with MaudeDatabase(str(tmp_path / 'cm.duckdb'), data_dir=data_dir, verbose=False) as db:
            db.add_years(2020, tables=['device'])
            assert db._table_exists('device')

    def test_metadata_recorded(self, db):
        meta = db.query("SELECT * FROM _load_metadata WHERE table_name = 'device'")
        assert len(meta) >= 1
        assert meta['checksum'].iloc[0] is not None


class TestQueryDevice:
    def test_brand_name(self, db):
        result = db.query_device(brand_name='Venovo')
        assert len(result) == 1
        assert result['BRAND_NAME'].iloc[0].upper() == 'VENOVO'

    def test_brand_name_case_insensitive(self, db):
        result = db.query_device(brand_name='venovo')
        assert len(result) == 1

    def test_generic_name(self, db):
        result = db.query_device(generic_name='Venous Stent')
        assert len(result) == 1

    def test_product_code(self, db):
        result = db.query_device(product_code='NIQ')
        assert len(result) == 2

    def test_manufacturer(self, db):
        result = db.query_device(manufacturer_name='Medtronic')
        assert len(result) == 1

    def test_and_logic(self, db):
        result = db.query_device(product_code='NIQ', manufacturer_name='Medtronic')
        assert len(result) == 1

    def test_date_filter_start(self, db):
        result = db.query_device(product_code='NIQ', start_date='2020-03-01')
        assert len(result) == 1  # Only the March record

    def test_date_filter_end(self, db):
        result = db.query_device(product_code='NIQ', end_date='2020-02-01')
        assert len(result) == 1  # Only the January record

    def test_no_match_returns_empty(self, db):
        result = db.query_device(brand_name='NONEXISTENT_DEVICE_XYZ')
        assert len(result) == 0

    def test_no_params_raises(self, db):
        with pytest.raises(ValueError, match="At least one device field"):
            db.query_device()

    def test_returns_joined_columns(self, db):
        result = db.query_device(brand_name='Venovo')
        # Should have columns from both master and device
        assert 'MDR_REPORT_KEY' in result.columns
        assert 'DATE_RECEIVED' in result.columns
        assert 'BRAND_NAME' in result.columns
        assert 'EVENT_TYPE' in result.columns


class TestGetNarratives:
    def test_basic_fetch(self, db):
        result = db.get_narratives([1001, 1002])
        assert len(result) == 2
        assert set(result['MDR_REPORT_KEY'].astype(str).tolist()) == {'1001', '1002'}

    def test_empty_input(self, db):
        result = db.get_narratives([])
        assert len(result) == 0
        assert 'FOI_TEXT' in result.columns

    def test_missing_key_not_returned(self, db):
        result = db.get_narratives([9999])
        assert len(result) == 0


class TestGetTrendsByYear:
    def test_basic_trends(self, db):
        results = db.query_device(product_code='NIQ')
        trends = db.get_trends_by_year(results)
        assert 'year' in trends.columns
        assert 'event_count' in trends.columns
        assert trends['event_count'].sum() == 2

    def test_empty_input(self, db):
        results = db.query_device(brand_name='NONEXISTENT_XYZ')
        trends = db.get_trends_by_year(results)
        assert len(trends) == 0

    def test_grouped_trends(self, db):
        results = db.search_by_device_names({'stents': 'stent', 'thrombectomy': 'thrombectomy'})
        if 'search_group' in results.columns:
            trends = db.get_trends_by_year(results)
            assert 'search_group' in trends.columns

    def test_wrong_type_raises(self, db):
        with pytest.raises(TypeError):
            db.get_trends_by_year("not a dataframe")


class TestEnrich:
    def test_enrich_patient(self, db):
        results = db.query_device(brand_name='Venovo')
        enriched = db.enrich_with_patient_data(results)
        assert 'SEQUENCE_NUMBER_OUTCOME' in enriched.columns

    def test_enrich_problems(self, db):
        results = db.query_device(product_code='NIQ')
        enriched = db.enrich_with_problems(results)
        assert 'DEVICE_PROBLEM_CODE' in enriched.columns

    def test_enrich_empty_input(self, db):
        results = db.query_device(brand_name='NONEXISTENT_XYZ')
        enriched = db.enrich_with_patient_data(results)
        assert len(enriched) == 0


class TestInfo:
    def test_info_runs(self, db, capsys):
        db.info()
        captured = capsys.readouterr()
        assert 'master' in captured.out
        assert 'device' in captured.out


class TestYearParsing:
    def test_int(self, tmp_path, data_dir):
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'yp.duckdb'), data_dir=data_dir, verbose=False)
        years = db._parse_year_range(2020)
        assert years == [2020]
        db.close()

    def test_string_range(self, tmp_path, data_dir):
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'yr.duckdb'), data_dir=data_dir, verbose=False)
        years = db._parse_year_range('2019-2021')
        assert years == [2019, 2020, 2021]
        db.close()

    def test_list(self, tmp_path, data_dir):
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'yl.duckdb'), data_dir=data_dir, verbose=False)
        years = db._parse_year_range([2018, 2020])
        assert years == [2018, 2020]
        db.close()
