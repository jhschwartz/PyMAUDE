"""Tests for search_by_device_names and related search logic."""

import pytest
import pandas as pd
from pymaude import MaudeDatabase


class TestSearchByDeviceNames:
    def test_single_term(self, db):
        result = db.search_by_device_names('venous')
        assert len(result) >= 1
        # All results should contain 'VENOUS' somewhere in concat field
        assert all('VENOUS' in str(v) for v in result['DEVICE_NAME_CONCAT'])

    def test_or_list(self, db):
        result = db.search_by_device_names(['venous', 'biliary'])
        # Venous stent (x2) + biliary stent (x1)
        assert len(result) >= 2

    def test_and_logic(self, db):
        result = db.search_by_device_names([['argon', 'thrombectomy']])
        assert len(result) >= 1
        assert all('ARGON' in str(v) and 'THROMBECTOMY' in str(v)
                   for v in result['DEVICE_NAME_CONCAT'])

    def test_and_or_combined(self, db):
        # (argon AND thrombectomy) OR venous
        result = db.search_by_device_names([['argon', 'thrombectomy'], 'venous'])
        assert len(result) >= 2

    def test_case_insensitive(self, db):
        lower = db.search_by_device_names('VENOUS')
        upper = db.search_by_device_names('venous')
        assert len(lower) == len(upper)

    def test_no_match_empty(self, db):
        result = db.search_by_device_names('xyznonexistent999')
        assert len(result) == 0

    def test_date_filter_start(self, db):
        all_venous = db.search_by_device_names('venous')
        filtered = db.search_by_device_names('venous', start_date='2020-03-01')
        assert len(filtered) <= len(all_venous)

    def test_date_filter_end(self, db):
        all_venous = db.search_by_device_names('venous')
        filtered = db.search_by_device_names('venous', end_date='2020-02-01')
        assert len(filtered) <= len(all_venous)

    def test_returns_joined_columns(self, db):
        result = db.search_by_device_names('venous')
        assert 'MDR_REPORT_KEY' in result.columns
        assert 'DATE_RECEIVED' in result.columns
        assert 'DEVICE_NAME_CONCAT' in result.columns


class TestGroupedSearch:
    def test_dict_returns_group_column(self, db):
        result = db.search_by_device_names({
            'stents': 'stent',
            'thrombectomy': 'thrombectomy',
        })
        assert 'search_group' in result.columns

    def test_dict_group_labels(self, db):
        result = db.search_by_device_names({
            'stents': 'stent',
            'thrombectomy': 'thrombectomy',
        })
        groups = set(result['search_group'].unique())
        assert groups.issubset({'stents', 'thrombectomy'})

    def test_dict_no_duplicate_reports(self, db):
        # Records matching multiple groups should only appear once (first group wins)
        result = db.search_by_device_names({
            'all': 'stent',
            'also_all': 'stent',
        })
        assert result['MDR_REPORT_KEY'].is_unique

    def test_dict_none_group_skipped(self, db):
        result = db.search_by_device_names({
            'stents': 'stent',
            'skip_me': None,
        })
        assert 'skip_me' not in result.get('search_group', pd.Series()).values

    def test_custom_group_column_name(self, db):
        result = db.search_by_device_names(
            {'a': 'stent'},
            group_column='device_class',
        )
        assert 'device_class' in result.columns

    def test_all_none_returns_empty(self, db):
        result = db.search_by_device_names({'a': None, 'b': None})
        assert len(result) == 0


class TestNormalizeCriteria:
    """Unit tests for the internal criteria normalizer."""

    def test_string(self, db):
        assert db._normalize_criteria('term') == [['term']]

    def test_flat_list(self, db):
        assert db._normalize_criteria(['a', 'b']) == [['a'], ['b']]

    def test_nested_list(self, db):
        assert db._normalize_criteria([['a', 'b'], 'c']) == [['a', 'b'], ['c']]

    def test_empty_list_raises(self, db):
        with pytest.raises(ValueError):
            db._normalize_criteria([])

    def test_empty_and_group_raises(self, db):
        with pytest.raises(ValueError):
            db._normalize_criteria([[]])

    def test_invalid_type_raises(self, db):
        with pytest.raises(ValueError):
            db._normalize_criteria(123)

    def test_non_string_term_raises(self, db):
        with pytest.raises(ValueError):
            db._normalize_criteria([[1, 2]])
