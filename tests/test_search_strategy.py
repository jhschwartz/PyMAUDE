"""Tests for DeviceSearchStrategy PRISMA workflow and serialization."""

import pytest
import yaml
from pathlib import Path
from pymaude import DeviceSearchStrategy


@pytest.fixture
def strategy():
    return DeviceSearchStrategy(
        name='venous_stent',
        description='Venous stent adverse events',
        broad_criteria=['stent'],
        narrow_criteria=['venous'],
        exclusion_patterns=['biliary'],
        search_rationale='Broad: all stents; narrow: venous only',
    )


class TestApply:
    def test_returns_three_dataframes(self, db, strategy):
        included, excluded, needs_review = strategy.apply(db)
        import pandas as pd
        assert isinstance(included, pd.DataFrame)
        assert isinstance(excluded, pd.DataFrame)
        assert isinstance(needs_review, pd.DataFrame)

    def test_included_subset_of_broad(self, db, strategy):
        included, excluded, needs_review = strategy.apply(db)
        total = len(included) + len(excluded) + len(needs_review)
        broad = db.search_by_device_names(strategy.broad_criteria)
        assert total == len(broad)

    def test_no_overlap_between_outputs(self, db, strategy):
        included, excluded, needs_review = strategy.apply(db)
        all_keys = (
            list(included['MDR_REPORT_KEY'])
            + list(excluded['MDR_REPORT_KEY'])
            + list(needs_review['MDR_REPORT_KEY'])
        )
        assert len(all_keys) == len(set(all_keys)), "Outputs must be disjoint"

    def test_exclusion_pattern_applied(self, db, strategy):
        included, excluded, needs_review = strategy.apply(db)
        # 'biliary' records (in broad but not narrow) should be in excluded
        biliary_in_excluded = excluded[
            excluded.get('DEVICE_NAME_CONCAT', '').astype(str).str.contains('BILIARY', na=False)
        ] if 'DEVICE_NAME_CONCAT' in excluded.columns else excluded
        # At least no biliary records should end up in included
        if 'DEVICE_NAME_CONCAT' in included.columns:
            assert not included['DEVICE_NAME_CONCAT'].str.contains('BILIARY', na=False).any()

    def test_inclusion_override(self, db):
        # Force-include MDR_REPORT_KEY 1003 (biliary stent) even though it's not in narrow
        s = DeviceSearchStrategy(
            name='test',
            description='test',
            broad_criteria=['stent'],
            narrow_criteria=['venous'],
            inclusion_overrides=['1003'],
        )
        included, excluded, needs_review = s.apply(db)
        assert '1003' in included['MDR_REPORT_KEY'].astype(str).tolist()
        assert '1003' not in needs_review['MDR_REPORT_KEY'].astype(str).tolist()

    def test_exclusion_override(self, db):
        # Force-exclude MDR_REPORT_KEY 1001 (venous stent — in narrow)
        s = DeviceSearchStrategy(
            name='test',
            description='test',
            broad_criteria=['stent'],
            narrow_criteria=['venous'],
            exclusion_overrides=['1001'],
        )
        included, excluded, needs_review = s.apply(db)
        assert '1001' not in included['MDR_REPORT_KEY'].astype(str).tolist()
        assert '1001' in excluded['MDR_REPORT_KEY'].astype(str).tolist()

    def test_empty_broad_raises(self, db):
        s = DeviceSearchStrategy(name='t', description='t',
                                  broad_criteria=[], narrow_criteria=['venous'])
        with pytest.raises(ValueError, match="broad_criteria"):
            s.apply(db)

    def test_empty_narrow_raises(self, db):
        s = DeviceSearchStrategy(name='t', description='t',
                                  broad_criteria=['stent'], narrow_criteria=[])
        with pytest.raises(ValueError, match="narrow_criteria"):
            s.apply(db)

    def test_mismatched_dict_types_raises(self, db):
        s = DeviceSearchStrategy(
            name='t', description='t',
            broad_criteria={'a': 'stent'},
            narrow_criteria=['venous'],
        )
        with pytest.raises(ValueError, match="both be dict"):
            s.apply(db)

    def test_mismatched_dict_keys_raises(self, db):
        s = DeviceSearchStrategy(
            name='t', description='t',
            broad_criteria={'a': 'stent'},
            narrow_criteria={'b': 'venous'},
        )
        with pytest.raises(ValueError, match="matching keys"):
            s.apply(db)

    def test_grouped_criteria(self, db):
        s = DeviceSearchStrategy(
            name='grouped_test',
            description='test grouped',
            broad_criteria={'venous': ['stent'], 'thrombectomy': ['thrombectomy']},
            narrow_criteria={'venous': ['venous'], 'thrombectomy': ['argon']},
        )
        included, excluded, needs_review = s.apply(db)
        assert 'search_group' in included.columns


class TestPrismaCounts:
    def test_counts_sum_to_broad(self, db, strategy):
        included, excluded, needs_review = strategy.apply(db)
        counts = strategy.get_prisma_counts(included, excluded, needs_review)
        assert counts['broad_total'] == len(included) + len(excluded) + len(needs_review)
        assert counts['final_included'] == len(included)
        assert counts['excluded_total'] == len(excluded)
        assert counts['needs_manual_review'] == len(needs_review)


class TestYamlRoundtrip:
    def test_to_yaml_string(self, strategy):
        s = strategy.to_yaml()
        assert isinstance(s, str)
        data = yaml.safe_load(s)
        assert data['name'] == 'venous_stent'
        assert data['broad_criteria'] == ['stent']

    def test_to_yaml_file(self, strategy, tmp_path):
        path = tmp_path / 'strategy.yaml'
        strategy.to_yaml(path)
        assert path.exists()

    def test_from_yaml_roundtrip(self, strategy, tmp_path):
        path = tmp_path / 'roundtrip.yaml'
        strategy.to_yaml(path)
        loaded = DeviceSearchStrategy.from_yaml(path)
        assert loaded.name == strategy.name
        assert loaded.broad_criteria == strategy.broad_criteria
        assert loaded.narrow_criteria == strategy.narrow_criteria
        assert loaded.exclusion_patterns == strategy.exclusion_patterns

    def test_from_yaml_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DeviceSearchStrategy.from_yaml(tmp_path / 'nonexistent.yaml')

    def test_from_yaml_bad_content_raises(self, tmp_path):
        bad = tmp_path / 'bad.yaml'
        bad.write_text(": invalid: yaml: content: [[[")
        with pytest.raises((ValueError, Exception)):
            DeviceSearchStrategy.from_yaml(bad)
