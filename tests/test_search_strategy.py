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
