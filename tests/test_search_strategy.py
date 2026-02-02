#!/usr/bin/env python3
"""
Tests for DeviceSearchStrategy and AdjudicationLog classes.

Tests cover:
- DeviceSearchStrategy YAML serialization/deserialization
- Search strategy application with MaudeDatabase
- Manual decision tracking
- PRISMA count generation
- AdjudicationLog CSV operations
- Edge cases and error handling
"""

import pytest
import tempfile
import yaml
import csv
from pathlib import Path
from datetime import datetime
import pandas as pd
import sqlite3

from pymaude import MaudeDatabase, DeviceSearchStrategy
from pymaude.adjudication import AdjudicationLog, AdjudicationRecord


class TestDeviceSearchStrategy:
    """Test DeviceSearchStrategy class."""

    def test_init_basic(self):
        """Test basic initialization."""
        strategy = DeviceSearchStrategy(
            name="test_device",
            description="Test device strategy"
        )
        assert strategy.name == "test_device"
        assert strategy.description == "Test device strategy"
        assert strategy.version == "1.0.0"
        assert isinstance(strategy.created_at, datetime)
        assert isinstance(strategy.updated_at, datetime)

    def test_yaml_roundtrip(self, tmp_path):
        """Test YAML save and load preserves data."""
        # Create strategy
        strategy = DeviceSearchStrategy(
            name="thrombectomy",
            description="Rotational thrombectomy devices",
            broad_criteria=[['argon', 'cleaner'], 'angiojet'],
            narrow_criteria=[['argon', 'cleaner', 'thromb']],
            exclusion_patterns=['ultrasonic', 'dental'],
            search_rationale="Test rationale"
        )

        # Save to YAML
        yaml_path = tmp_path / "strategy.yaml"
        strategy.to_yaml(yaml_path)

        # Verify file exists
        assert yaml_path.exists()

        # Load from YAML
        loaded = DeviceSearchStrategy.from_yaml(yaml_path)

        # Verify key fields
        assert loaded.name == strategy.name
        assert loaded.description == strategy.description
        assert loaded.broad_criteria == strategy.broad_criteria
        assert loaded.narrow_criteria == strategy.narrow_criteria
        assert loaded.exclusion_patterns == strategy.exclusion_patterns
        assert loaded.search_rationale == strategy.search_rationale

    def test_yaml_to_string(self):
        """Test YAML generation without writing to file."""
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test strategy"
        )

        yaml_str = strategy.to_yaml()
        assert isinstance(yaml_str, str)
        assert 'name: test' in yaml_str
        assert 'description: Test strategy' in yaml_str

    def test_add_manual_decision(self):
        """Test manual decision tracking."""
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test"
        )

        # Add inclusion
        strategy.add_manual_decision('1234567', 'include', 'Matches criteria')
        assert '1234567' in strategy.inclusion_overrides
        assert '1234567' not in strategy.exclusion_overrides

        # Add exclusion
        strategy.add_manual_decision('7654321', 'exclude', 'False positive')
        assert '7654321' in strategy.exclusion_overrides
        assert '7654321' not in strategy.inclusion_overrides

        # Switch from include to exclude
        strategy.add_manual_decision('1234567', 'exclude', 'Changed mind')
        assert '1234567' not in strategy.inclusion_overrides
        assert '1234567' in strategy.exclusion_overrides

    def test_add_manual_decision_invalid(self):
        """Test validation of decision values."""
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test"
        )

        with pytest.raises(ValueError, match="must be 'include' or 'exclude'"):
            strategy.add_manual_decision('1234567', 'invalid', 'Test')

    def test_sync_from_adjudication(self, tmp_path):
        """Test syncing decisions from AdjudicationLog."""
        from pymaude.adjudication import AdjudicationLog

        # Create adjudication log with decisions
        log_path = tmp_path / "test_adjudication.csv"
        log = AdjudicationLog(log_path)
        log.add('1234567', 'include', 'Matches criteria', 'Reviewer1')
        log.add('2345678', 'include', 'Also matches', 'Reviewer1')
        log.add('7654321', 'exclude', 'False positive', 'Reviewer2')
        log.add('8765432', 'exclude', 'Not a match', 'Reviewer2')
        log.to_csv()

        # Create strategy and sync
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test"
        )
        summary = strategy.sync_from_adjudication(log)

        # Verify overrides were synced
        assert set(strategy.inclusion_overrides) == {'1234567', '2345678'}
        assert set(strategy.exclusion_overrides) == {'7654321', '8765432'}

        # Verify summary
        assert summary['inclusions_added'] == 2
        assert summary['exclusions_added'] == 2
        assert summary['total_synced'] == 4


    def test_sync_from_adjudication_log_add_list_mdr(self, tmp_path):
        """Test syncing decisions from AdjudicationLog."""
        from pymaude.adjudication import AdjudicationLog

        # Create adjudication log with decisions
        log_path = tmp_path / "test_adjudication.csv"
        log = AdjudicationLog(log_path)
        log.add(['1234567', '2345678', '98760987'], 'include', 'Matches criteria', 'Reviewer1')
        log.add(['7654321', '8765432', '321'], 'exclude', 'False positive', 'Reviewer2')
        log.to_csv()

        # Create strategy and sync
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test"
        )
        summary = strategy.sync_from_adjudication(log)

        # Verify overrides were synced
        assert set(strategy.inclusion_overrides) == {'1234567', '2345678', '98760987'}
        assert set(strategy.exclusion_overrides) == {'7654321', '8765432', '321'}

        # Verify summary
        assert summary['inclusions_added'] == 3
        assert summary['exclusions_added'] == 3
        assert summary['total_synced'] == 6


    def test_sync_from_adjudication_replaces_existing(self, tmp_path):
        """Test that sync replaces (not appends) existing overrides."""
        from pymaude.adjudication import AdjudicationLog

        # Create strategy with existing overrides
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test",
            inclusion_overrides=['OLD123'],
            exclusion_overrides=['OLD456']
        )

        # Create adjudication log with NEW decisions
        log_path = tmp_path / "test_adjudication.csv"
        log = AdjudicationLog(log_path)
        log.add('NEW789', 'include', 'New decision', 'Reviewer')
        log.to_csv()

        # Sync should replace, not append
        strategy.sync_from_adjudication(log)

        assert strategy.inclusion_overrides == ['NEW789']
        assert strategy.exclusion_overrides == []

    def test_sync_from_adjudication_invalid_input(self):
        """Test validation of input to sync_from_adjudication."""
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test"
        )

        with pytest.raises(ValueError, match="must be an AdjudicationLog instance"):
            strategy.sync_from_adjudication("not a log")

    def test_get_prisma_counts(self):
        """Test PRISMA count generation."""
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test",
            inclusion_overrides=['111', '222'],
            exclusion_overrides=['333']
        )

        # Create mock DataFrames
        included_df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3, 4, 5],
            'BRAND_NAME': ['Device A'] * 5
        })
        excluded_df = pd.DataFrame({
            'MDR_REPORT_KEY': [6, 7, 8],
            'BRAND_NAME': ['Device B'] * 3
        })
        needs_review_df = pd.DataFrame({
            'MDR_REPORT_KEY': [9, 10],
            'BRAND_NAME': ['Device C'] * 2
        })

        counts = strategy.get_prisma_counts(included_df, excluded_df, needs_review_df)

        assert counts['broad_matches'] == 10  # 5 + 3 + 2
        assert counts['final_included'] == 5
        assert counts['final_excluded'] == 3
        assert counts['needs_manual_review'] == 2
        assert counts['manual_inclusions'] == 2
        assert counts['manual_exclusions'] == 1

    def test_apply_validation(self):
        """Test apply() validates inputs."""
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test",
            broad_criteria=[['test']],
            narrow_criteria=[['test']]
        )

        # Test with non-MaudeDatabase object
        with pytest.raises(ValueError, match="must be a MaudeDatabase instance"):
            strategy.apply("not a database")

    def test_apply_empty_criteria(self, tmp_path):
        """Test apply() validates criteria are not empty."""
        # Create minimal test database
        db_path = tmp_path / "test.db"
        db = MaudeDatabase(db_path)

        strategy = DeviceSearchStrategy(
            name="test",
            description="Test"
        )

        with pytest.raises(ValueError, match="broad_criteria cannot be empty"):
            strategy.apply(db)


class TestAdjudicationLog:
    """Test AdjudicationLog class."""

    def test_init_new_log(self, tmp_path):
        """Test creating new adjudication log."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)
        assert log.path == log_path
        assert len(log.records) == 0

    def test_add_decisions(self, tmp_path):
        """Test adding adjudication decisions."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        log.add('1234567', 'include', 'Matches device', 'Jake')
        log.add('7654321', 'exclude', 'False positive', 'Jake')

        assert len(log.records) == 2
        assert log.get_inclusion_keys() == {'1234567'}
        assert log.get_exclusion_keys() == {'7654321'}

    def test_add_invalid_decision(self, tmp_path):
        """Test error handling for invalid decisions."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        with pytest.raises(ValueError, match="must be 'include' or 'exclude'"):
            log.add('1234567', 'invalid_decision', 'Test', 'Jake')

    def test_csv_roundtrip(self, tmp_path):
        """Test CSV save and load preserves data."""
        log_path = tmp_path / "adjudication.csv"

        # Create and populate log
        log = AdjudicationLog(log_path)
        log.add('1234567', 'include', 'Test reason', 'Jake', '1.0.0', 'Device A')
        log.add('7654321', 'exclude', 'False positive', 'Sarah', '1.0.0', 'Device B')
        log.to_csv()

        # Verify file exists
        assert log_path.exists()

        # Load from CSV
        loaded = AdjudicationLog.from_csv(log_path)

        assert len(loaded.records) == 2
        assert loaded.records[0].mdr_report_key == '1234567'
        assert loaded.records[0].decision == 'include'
        assert loaded.records[0].reviewer == 'Jake'
        assert loaded.records[1].mdr_report_key == '7654321'
        assert loaded.records[1].decision == 'exclude'
        assert loaded.records[1].reviewer == 'Sarah'

    def test_from_csv_nonexistent(self, tmp_path):
        """Test error when loading nonexistent CSV."""
        log_path = tmp_path / "nonexistent.csv"

        with pytest.raises(FileNotFoundError):
            AdjudicationLog.from_csv(log_path)

    def test_get_statistics(self, tmp_path):
        """Test statistics generation."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        log.add('1234567', 'include', 'Test', 'Jake')
        log.add('7654321', 'exclude', 'Test', 'Jake')
        log.add('1111111', 'include', 'Test', 'Sarah')

        stats = log.get_statistics()
        assert stats['total_decisions'] == 3
        assert stats['inclusions'] == 2
        assert stats['exclusions'] == 1
        assert set(stats['reviewers']) == {'Jake', 'Sarah'}
        assert isinstance(stats['date_range'], tuple)
        assert len(stats['date_range']) == 2

    def test_get_statistics_empty(self, tmp_path):
        """Test statistics with empty log."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        stats = log.get_statistics()
        assert stats['total_decisions'] == 0
        assert stats['inclusions'] == 0
        assert stats['exclusions'] == 0
        assert stats['reviewers'] == []
        assert stats['date_range'] == (None, None)

    def test_to_dataframe(self, tmp_path):
        """Test conversion to DataFrame."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        log.add('1234567', 'include', 'Test', 'Jake')
        log.add('7654321', 'exclude', 'Test', 'Sarah')

        df = log.to_dataframe()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert 'mdr_report_key' in df.columns
        assert 'decision' in df.columns
        assert 'reviewer' in df.columns
        assert df['mdr_report_key'].tolist() == ['1234567', '7654321']

    def test_to_dataframe_empty(self, tmp_path):
        """Test DataFrame conversion with empty log."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        df = log.to_dataframe()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert 'mdr_report_key' in df.columns

    def test_include_remaining_basic(self, tmp_path):
        """Test include_remaining with all undecided rows."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        # Create mock needs_review DataFrame
        needs_review = pd.DataFrame({
            'MDR_REPORT_KEY': ['1111111', '2222222', '3333333'],
            'BRAND_NAME': ['Device A', 'Device B', 'Device C']
        })

        # Include all remaining
        count = log.include_remaining(needs_review, 'Test bulk include', 'Jake', 'v1.0')

        assert count == 3
        assert len(log.records) == 3
        assert log.get_inclusion_keys() == {'1111111', '2222222', '3333333'}
        assert len(log.get_exclusion_keys()) == 0

    def test_exclude_remaining_basic(self, tmp_path):
        """Test exclude_remaining with all undecided rows."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        # Create mock needs_review DataFrame
        needs_review = pd.DataFrame({
            'MDR_REPORT_KEY': ['1111111', '2222222', '3333333'],
            'GENERIC_NAME': ['Generic A', 'Generic B', 'Generic C']
        })

        # Exclude all remaining
        count = log.exclude_remaining(needs_review, 'Test bulk exclude', 'Jake', 'v1.0')

        assert count == 3
        assert len(log.records) == 3
        assert log.get_exclusion_keys() == {'1111111', '2222222', '3333333'}
        assert len(log.get_inclusion_keys()) == 0

    def test_include_remaining_with_prior_decisions(self, tmp_path):
        """Test include_remaining skips already-decided rows."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        # Create mock needs_review DataFrame
        needs_review = pd.DataFrame({
            'MDR_REPORT_KEY': ['1111111', '2222222', '3333333', '4444444'],
            'BRAND_NAME': ['Device A', 'Device B', 'Device C', 'Device D']
        })

        # Add some prior decisions
        log.add('1111111', 'include', 'Manual review', 'Jake')
        log.add('3333333', 'exclude', 'Manual review', 'Jake')

        # Include remaining (should skip 1111111 and 3333333)
        count = log.include_remaining(needs_review, 'Bulk include remaining', 'Jake', 'v1.0')

        assert count == 2  # Only 2222222 and 4444444
        assert len(log.records) == 4  # 2 prior + 2 new
        assert log.get_inclusion_keys() == {'1111111', '2222222', '4444444'}
        assert log.get_exclusion_keys() == {'3333333'}

    def test_exclude_remaining_with_prior_decisions(self, tmp_path):
        """Test exclude_remaining skips already-decided rows."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        # Create mock needs_review DataFrame
        needs_review = pd.DataFrame({
            'MDR_REPORT_KEY': ['1111111', '2222222', '3333333', '4444444'],
            'GENERIC_NAME': ['Generic A', 'Generic B', 'Generic C', 'Generic D']
        })

        # Add some prior decisions
        log.add('2222222', 'include', 'Manual review', 'Jake')
        log.add('4444444', 'exclude', 'Manual review', 'Jake')

        # Exclude remaining (should skip 2222222 and 4444444)
        count = log.exclude_remaining(needs_review, 'Bulk exclude remaining', 'Jake', 'v1.0')

        assert count == 2  # Only 1111111 and 3333333
        assert len(log.records) == 4  # 2 prior + 2 new
        assert log.get_inclusion_keys() == {'2222222'}
        assert log.get_exclusion_keys() == {'3333333', '1111111', '4444444'}

    def test_remaining_with_device_info_column(self, tmp_path):
        """Test extracting device info from specified column."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        # Create mock needs_review DataFrame
        needs_review = pd.DataFrame({
            'MDR_REPORT_KEY': ['1111111', '2222222'],
            'BRAND_NAME': ['Venovo', 'Zilver Vena'],
            'GENERIC_NAME': ['Venous Stent', 'Venous Stent']
        })

        # Include with device_info_column
        count = log.include_remaining(
            needs_review,
            'Known venous stent brands',
            'Jake',
            'v1.0',
            device_info_column='BRAND_NAME'
        )

        assert count == 2
        assert log.records[0].device_info == 'Venovo'
        assert log.records[1].device_info == 'Zilver Vena'

    def test_remaining_empty_dataframe(self, tmp_path):
        """Test handling empty needs_review DataFrame."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        # Create empty DataFrame with correct columns
        needs_review = pd.DataFrame(columns=['MDR_REPORT_KEY', 'BRAND_NAME'])

        # Should handle gracefully
        count = log.include_remaining(needs_review, 'Test empty', 'Jake', 'v1.0')

        assert count == 0
        assert len(log.records) == 0

    def test_remaining_missing_column(self, tmp_path):
        """Test error when MDR_REPORT_KEY column missing."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        # Create DataFrame without MDR_REPORT_KEY
        needs_review = pd.DataFrame({
            'SOME_OTHER_KEY': ['1111111', '2222222'],
            'BRAND_NAME': ['Device A', 'Device B']
        })

        # Should raise ValueError
        with pytest.raises(ValueError, match="must contain 'MDR_REPORT_KEY'"):
            log.include_remaining(needs_review, 'Test', 'Jake')

        with pytest.raises(ValueError, match="must contain 'MDR_REPORT_KEY'"):
            log.exclude_remaining(needs_review, 'Test', 'Jake')


class TestDeviceSearchStrategyGrouped:
    """Test DeviceSearchStrategy with grouped (dict) criteria."""

    def test_mixed_criteria_raises_error(self):
        """Test error when broad is dict but narrow is list."""
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test",
            broad_criteria={'mechanical': [['argon', 'cleaner']]},
            narrow_criteria=[['argon', 'cleaner', 'thromb']]  # List, not dict
        )

        # Create minimal test database
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            db = MaudeDatabase(db_path)

            with pytest.raises(ValueError, match="must both be dict.*or both be list"):
                strategy.apply(db)

    def test_dict_criteria_matching_keys_required(self):
        """Test error when broad/narrow have different keys."""
        strategy = DeviceSearchStrategy(
            name="test",
            description="Test",
            broad_criteria={'mechanical': [['argon']], 'aspiration': ['penumbra']},
            narrow_criteria={'mechanical': [['argon', 'cleaner']]}  # Missing 'aspiration'
        )

        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            db = MaudeDatabase(db_path)

            with pytest.raises(ValueError, match="must have matching group keys"):
                strategy.apply(db)

    def test_grouped_yaml_roundtrip(self, tmp_path):
        """Test YAML save/load with dict criteria."""
        strategy = DeviceSearchStrategy(
            name="thrombectomy_grouped",
            description="Grouped thrombectomy devices",
            broad_criteria={
                'mechanical': [['argon', 'cleaner'], 'angiojet'],
                'aspiration': 'penumbra'
            },
            narrow_criteria={
                'mechanical': [['argon', 'cleaner', 'thromb']],
                'aspiration': [['penumbra', 'indigo']]
            },
            exclusion_patterns=['dental']
        )

        # Save to YAML
        yaml_path = tmp_path / "grouped_strategy.yaml"
        strategy.to_yaml(yaml_path)

        # Load from YAML
        loaded = DeviceSearchStrategy.from_yaml(yaml_path)

        # Verify dict structure preserved
        assert isinstance(loaded.broad_criteria, dict)
        assert isinstance(loaded.narrow_criteria, dict)
        assert set(loaded.broad_criteria.keys()) == {'mechanical', 'aspiration'}
        assert set(loaded.narrow_criteria.keys()) == {'mechanical', 'aspiration'}
        assert loaded.broad_criteria['mechanical'] == [['argon', 'cleaner'], 'angiojet']
        assert loaded.narrow_criteria['aspiration'] == [['penumbra', 'indigo']]

    def test_grouped_with_none_criteria(self):
        """Test that None criteria is valid for grouped searches."""
        # This should not raise - None means 'match nothing' for that group
        strategy = DeviceSearchStrategy(
            name="test_none",
            description="Test None criteria",
            broad_criteria={
                'mechanical': [['argon', 'cleaner']],
                'aspiration': 'penumbra'
            },
            narrow_criteria={
                'mechanical': [['argon', 'cleaner', 'thromb']],
                'aspiration': None  # Match nothing for narrow aspiration
            }
        )

        assert strategy.broad_criteria['aspiration'] == 'penumbra'
        assert strategy.narrow_criteria['aspiration'] is None

    def test_grouped_with_none_yaml_roundtrip(self, tmp_path):
        """Test YAML save/load preserves None criteria."""
        strategy = DeviceSearchStrategy(
            name="test_none_yaml",
            description="Test None in YAML",
            broad_criteria={
                'group1': [['term1', 'term2']],
                'group2': 'other'
            },
            narrow_criteria={
                'group1': [['term1', 'term2', 'specific']],
                'group2': None  # Match nothing
            }
        )

        # Save to YAML
        yaml_path = tmp_path / "none_strategy.yaml"
        strategy.to_yaml(yaml_path)

        # Load from YAML
        loaded = DeviceSearchStrategy.from_yaml(yaml_path)

        # Verify None is preserved (YAML stores as null)
        assert loaded.narrow_criteria['group2'] is None
        assert loaded.narrow_criteria['group1'] == [['term1', 'term2', 'specific']]


class TestAdjudicationLogGrouped:
    """Test AdjudicationLog with search_group tracking."""

    def test_add_with_search_group(self, tmp_path):
        """Test adding decision with search_group."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        log.add('1234567', 'include', 'Matches device', 'Jake',
                strategy_version='1.0.0', device_info='Device A', search_group='mechanical')

        assert len(log.records) == 1
        assert log.records[0].search_group == 'mechanical'

    def test_csv_roundtrip_with_search_group(self, tmp_path):
        """Test CSV save/load preserves search_group."""
        log_path = tmp_path / "adjudication.csv"

        # Create and populate log with search groups
        log = AdjudicationLog(log_path)
        log.add('1234567', 'include', 'Test', 'Jake', search_group='mechanical')
        log.add('7654321', 'exclude', 'Test', 'Sarah', search_group='aspiration')
        log.to_csv()

        # Load from CSV
        loaded = AdjudicationLog.from_csv(log_path)

        assert len(loaded.records) == 2
        assert loaded.records[0].search_group == 'mechanical'
        assert loaded.records[1].search_group == 'aspiration'

    def test_backward_compatibility_old_csv(self, tmp_path):
        """Test loading old CSV without search_group column."""
        log_path = tmp_path / "old_adjudication.csv"

        # Create old-style CSV without search_group column
        with open(log_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'mdr_report_key', 'decision', 'reason', 'reviewer',
                'date', 'strategy_version', 'device_info'
            ])
            writer.writerow([
                '1234567', 'include', 'Test reason', 'Jake',
                '2024-01-01T12:00:00', '1.0.0', 'Device A'
            ])

        # Load should work without error, search_group defaults to empty string
        log = AdjudicationLog.from_csv(log_path)
        assert len(log.records) == 1
        assert log.records[0].search_group == ''

    def test_to_dataframe_includes_search_group(self, tmp_path):
        """Test DataFrame export includes search_group column."""
        log_path = tmp_path / "adjudication.csv"
        log = AdjudicationLog(log_path)

        log.add('1234567', 'include', 'Test', 'Jake', search_group='mechanical')
        log.add('7654321', 'exclude', 'Test', 'Sarah', search_group='aspiration')

        df = log.to_dataframe()
        assert 'search_group' in df.columns
        assert df['search_group'].tolist() == ['mechanical', 'aspiration']

    def test_empty_log_dataframe_has_search_group_column(self, tmp_path):
        """Test that empty log DataFrame includes search_group column."""
        log_path = tmp_path / "empty.csv"
        log = AdjudicationLog(log_path)

        df = log.to_dataframe()
        assert 'search_group' in df.columns
        assert len(df) == 0


# Optional: Integration test with real database (marked as integration test)
@pytest.mark.integration
class TestSearchStrategyIntegration:
    """Integration tests with real MaudeDatabase."""

    def test_apply_with_real_database(self, tmp_path):
        """Test apply() with a real database containing test data."""
        # This test would need a real or mock MAUDE database
        # Skipping detailed implementation for now
        pytest.skip("Integration test requires real MAUDE data")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
