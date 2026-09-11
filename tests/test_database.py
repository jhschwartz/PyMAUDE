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

    def test_loads_device_problem(self, db):
        result = db.query("SELECT COUNT(*) FROM device_problem")
        assert result.iloc[0, 0] == 3

    def test_device_problem_dedup_on_two_file_load(self, tmp_path, data_dir):
        """Loading thru + current-year device_problem files should not create duplicates."""
        from datetime import datetime
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'dedup.duckdb'), data_dir=data_dir, verbose=False)
        current_year = datetime.now().year
        # Load prior years (triggers thru file) + current year (triggers foidevproblem.txt)
        db.add_years([2020, current_year], tables=['device_problem'])
        result = db.query("SELECT COUNT(*) FROM device_problem")
        # thru has 3 rows, current has 2 rows but 1 overlaps → expect 4 unique rows
        assert result.iloc[0, 0] == 4
        db.close()

    def test_loads_patient_problem(self, db):
        result = db.query("SELECT COUNT(*) FROM patient_problem")
        assert result.iloc[0, 0] == 3

    def test_patient_problem_dedup_on_two_file_load(self, tmp_path, data_dir):
        """Loading thru + current-year patient_problem files should not create duplicates."""
        from datetime import datetime
        from pymaude import MaudeDatabase
        db = MaudeDatabase(str(tmp_path / 'dedup_pp.duckdb'), data_dir=data_dir, verbose=False)
        current_year = datetime.now().year
        # Load prior years (triggers thru file) + current year (triggers patientproblemcode.txt)
        db.add_years([2020, current_year], tables=['patient_problem'])
        result = db.query("SELECT COUNT(*) FROM patient_problem")
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

    def test_all_years_sentinel_tables_recorded_once_not_per_year(self, db):
        """patient/device_problem/patient_problem have no date_column, so a
        thru-file load must be recorded once (under the _ALL_YEARS
        sentinel), not once per calendar year — recording it per-year
        previously multiplied the recorded row count by ~25x and corrupted
        archive()'s manifest."""
        for table in ('patient', 'device_problem', 'patient_problem'):
            meta = db.query(
                f"SELECT year, row_count FROM _load_metadata WHERE table_name = '{table}'"
            )
            actual = db.query(f"SELECT COUNT(*) FROM {table}").iloc[0, 0]
            assert len(meta) == 1
            assert meta['year'].iloc[0] == MaudeDatabase._ALL_YEARS
            assert meta['row_count'].iloc[0] == actual

    def test_device_problem_dedup_metadata_accurate(self, tmp_path, data_dir):
        """After loading both the thru-file and the current-year increment,
        recorded row counts (sentinel entry + current-year entry) should sum
        to exactly the table's actual row count."""
        from datetime import datetime
        db = MaudeDatabase(str(tmp_path / 'dedup2.duckdb'), data_dir=data_dir, verbose=False)
        current_year = datetime.now().year
        db.add_years([2020, current_year], tables=['device_problem'])
        entries = db.query(
            "SELECT year, row_count FROM _load_metadata WHERE table_name = 'device_problem'"
        )
        actual = db.query("SELECT COUNT(*) FROM device_problem").iloc[0, 0]
        assert len(entries) == 2
        assert entries['row_count'].sum() == actual == 4
        db.close()

    def test_patient_problem_dedup_metadata_accurate(self, tmp_path, data_dir):
        """After loading both the thru-file and the current-year increment,
        recorded row counts (sentinel entry + current-year entry) should sum
        to exactly the table's actual row count."""
        from datetime import datetime
        db = MaudeDatabase(str(tmp_path / 'dedup2_pp.duckdb'), data_dir=data_dir, verbose=False)
        current_year = datetime.now().year
        db.add_years([2020, current_year], tables=['patient_problem'])
        entries = db.query(
            "SELECT year, row_count FROM _load_metadata WHERE table_name = 'patient_problem'"
        )
        actual = db.query("SELECT COUNT(*) FROM patient_problem").iloc[0, 0]
        assert len(entries) == 2
        assert entries['row_count'].sum() == actual == 4
        db.close()

    def test_recorded_matches_actual_with_out_of_range_year(self, tmp_path):
        """A stray pre-start_year date in a cumulative source file (real MAUDE
        data has these, e.g. a report dated 1900) must still be recorded in
        _load_metadata, since _load_all loads the whole file unfiltered — the
        row physically ends up in the table either way."""
        d = tmp_path / 'maude_data'
        d.mkdir()
        master_csv = (
            "MDR_REPORT_KEY|EVENT_KEY|DATE_RECEIVED|EVENT_TYPE|MANUFACTURER_G1_NAME|PMA_PMN_NUM\n"
            "1001|2001|01/15/2020|D|MEDTRONIC|P180037\n"
            "1005|2005|09/23/1900|D|OLDCO|K999999\n"
        )
        (d / 'mdrfoithru2020.txt').write_text(master_csv)
        db = MaudeDatabase(str(tmp_path / 'stale.duckdb'), data_dir=str(d), verbose=False)
        db.add_years(2020, tables=['master'])
        recorded = db.query(
            "SELECT sum(row_count) FROM _load_metadata WHERE table_name = 'master'"
        ).iloc[0, 0]
        actual = db.query("SELECT COUNT(*) FROM master").iloc[0, 0]
        assert recorded == actual == 2
        years = set(db.query(
            "SELECT year FROM _load_metadata WHERE table_name = 'master'"
        )['year'])
        assert years == {1900, 2020}
        db.close()


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

    def test_enrich_device_problems(self, db):
        results = db.query_device(product_code='NIQ')
        enriched = db.enrich_with_device_problems(results)
        assert 'DEVICE_PROBLEM_CODE' in enriched.columns

    def test_enrich_patient_problems(self, db):
        results = db.query_device(product_code='NIQ')
        enriched = db.enrich_with_patient_problems(results)
        assert 'PATIENT_PROBLEM_CODE' in enriched.columns

    def test_enrich_empty_input(self, db):
        results = db.query_device(brand_name='NONEXISTENT_XYZ')
        enriched = db.enrich_with_patient_data(results)
        assert len(enriched) == 0


class TestFilterByOutcome:
    def test_matches_single_code(self, db):
        results = db.query_device(product_code='NIQ')  # 1001 (D), 1002 (L)
        enriched = db.enrich_with_patient_data(results)
        deaths = db.filter_by_outcome(enriched, 'D')
        assert set(deaths['MDR_REPORT_KEY'].astype(str)) == {'1001'}

    def test_matches_within_multi_code_field(self, db):
        results = db.query_device(product_code='GZC')  # 1004, outcome "H; O"
        enriched = db.enrich_with_patient_data(results)
        matched = db.filter_by_outcome(enriched, 'O')
        assert set(matched['MDR_REPORT_KEY'].astype(str)) == {'1004'}

    def test_list_of_codes_is_or(self, db):
        results = db.query_device(product_code='NIQ')
        enriched = db.enrich_with_patient_data(results)
        matched = db.filter_by_outcome(enriched, ['D', 'L'])
        assert set(matched['MDR_REPORT_KEY'].astype(str)) == {'1001', '1002'}

    def test_missing_column_raises(self, db):
        results = db.query_device(product_code='NIQ')
        with pytest.raises(ValueError, match='SEQUENCE_NUMBER_OUTCOME'):
            db.filter_by_outcome(results, 'D')


class TestFilterByPatient:
    def test_age_min(self, db):
        results = db.query_device(product_code='NIQ')  # 1001 (56 YR), 1002 (34 YR)
        enriched = db.enrich_with_patient_data(results)
        older = db.filter_by_patient(enriched, age_min=50)
        assert set(older['MDR_REPORT_KEY'].astype(str)) == {'1001'}

    def test_age_max(self, db):
        results = db.query_device(product_code='NIQ')
        enriched = db.enrich_with_patient_data(results)
        younger = db.filter_by_patient(enriched, age_max=40)
        assert set(younger['MDR_REPORT_KEY'].astype(str)) == {'1002'}

    def test_sex_case_insensitive(self, db):
        results = db.query_device(product_code='NIQ')
        enriched = db.enrich_with_patient_data(results)
        males = db.filter_by_patient(enriched, sex='male')
        assert set(males['MDR_REPORT_KEY'].astype(str)) == {'1001'}

    def test_unparseable_age_excluded(self, db):
        results = db.query_device(product_code='OCA')  # 1003, PATIENT_AGE='NA'
        enriched = db.enrich_with_patient_data(results)
        filtered = db.filter_by_patient(enriched, age_min=0)
        assert len(filtered) == 0

    def test_missing_columns_raises(self, db):
        results = db.query_device(product_code='NIQ')
        with pytest.raises(ValueError, match='PATIENT_AGE'):
            db.filter_by_patient(results, age_min=0)


class TestFilterByDeviceProblem:
    def test_matches_code(self, db):
        results = db.query_device(product_code='NIQ')  # 1001, 1002
        enriched = db.enrich_with_device_problems(results)
        filtered = db.filter_by_device_problem(enriched, '1546')
        assert set(filtered['MDR_REPORT_KEY'].astype(str)) == {'1001'}

    def test_list_of_codes_is_or(self, db):
        results = db.search_by_device_names('stent')  # 1001, 1002, 1003
        enriched = db.enrich_with_device_problems(results)
        filtered = db.filter_by_device_problem(enriched, ['1546', '2993'])
        assert set(filtered['MDR_REPORT_KEY'].astype(str)) == {'1001', '1002', '1003'}

    def test_missing_column_raises(self, db):
        results = db.query_device(product_code='NIQ')
        with pytest.raises(ValueError, match='DEVICE_PROBLEM_CODE'):
            db.filter_by_device_problem(results, '1546')


class TestFilterByPatientProblem:
    def test_matches_code(self, db):
        results = db.query_device(product_code='NIQ')  # 1001, 1002
        enriched = db.enrich_with_patient_problems(results)
        filtered = db.filter_by_patient_problem(enriched, '1029')
        assert set(filtered['MDR_REPORT_KEY'].astype(str)) == {'1001'}

    def test_list_of_codes_is_or(self, db):
        results = db.search_by_device_names('stent')  # 1001, 1002, 1003
        enriched = db.enrich_with_patient_problems(results)
        filtered = db.filter_by_patient_problem(enriched, ['1029', '1030'])
        assert set(filtered['MDR_REPORT_KEY'].astype(str)) == {'1001', '1002', '1003'}

    def test_missing_column_raises(self, db):
        results = db.query_device(product_code='NIQ')
        with pytest.raises(ValueError, match='PATIENT_PROBLEM_CODE'):
            db.filter_by_patient_problem(results, '1029')


class TestFilterByNarrative:
    def test_matches_term(self, db):
        results = db.query_device(product_code='NIQ')  # 1001, 1002
        filtered = db.filter_by_narrative(results, 'migration')
        assert set(filtered['MDR_REPORT_KEY'].astype(str)) == {'1001'}

    def test_case_insensitive(self, db):
        results = db.query_device(product_code='NIQ')
        filtered = db.filter_by_narrative(results, 'MIGRATION')
        assert set(filtered['MDR_REPORT_KEY'].astype(str)) == {'1001'}

    def test_no_match_returns_empty(self, db):
        results = db.query_device(product_code='NIQ')
        filtered = db.filter_by_narrative(results, 'nonexistent_term_xyz')
        assert len(filtered) == 0

    def test_empty_input(self, db):
        results = db.query_device(brand_name='NONEXISTENT_XYZ')
        filtered = db.filter_by_narrative(results, 'anything')
        assert len(filtered) == 0


class TestInfo:
    def test_info_runs(self, db, capsys):
        db.info()
        captured = capsys.readouterr()
        assert 'master' in captured.out
        assert 'device' in captured.out

    def test_info_does_not_show_sentinel_year(self, db, capsys):
        """patient/device_problem/patient_problem are recorded under the
        internal _ALL_YEARS=0 sentinel; info() must not leak that as a
        displayed year."""
        db.info()
        captured = capsys.readouterr()
        patient_line = next(l for l in captured.out.splitlines() if l.strip().startswith('patient'))
        assert 'FDA docs:' in patient_line
        assert '(0' not in patient_line


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
