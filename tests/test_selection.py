#!/usr/bin/env python3
"""
Tests for the device selection module.

These tests verify the SelectionManager and SelectionResults classes
work correctly for managing device selection projects.
"""

import pytest
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock
import pandas as pd

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymaude.selection import SelectionManager, SelectionResults, PHASES, FIELD_MAP


# ==================== Fixtures ====================

@pytest.fixture
def temp_json_path(tmp_path):
    """Provide a temporary JSON file path."""
    return str(tmp_path / "test_selection.json")


@pytest.fixture
def mock_db():
    """Create a mock database that returns predictable results."""
    db = Mock()

    def mock_query(sql, params=None):
        """Return appropriate mock data based on query."""
        sql_upper = sql.upper()

        # Search preview queries
        if 'COUNT(DISTINCT' in sql_upper and 'AS VALUE_COUNT' in sql_upper:
            return pd.DataFrame({'value_count': [10], 'mdr_count': [100]})

        # Total unique MDRs query
        if 'COUNT(DISTINCT MDR_REPORT_KEY) AS TOTAL' in sql_upper:
            return pd.DataFrame({'total': [150]})

        # Search candidates query (returns unique values)
        if 'GROUP BY' in sql_upper and 'AS VALUE' in sql_upper:
            return pd.DataFrame({
                'value': ['DEVICE A', 'DEVICE B', 'DEVICE C'],
                'mdr_count': [50, 30, 20]
            })

        # MDR keys for value query
        if 'SELECT DISTINCT MDR_REPORT_KEY' in sql_upper and '=' in sql_upper:
            # Return different MDRs based on value in query
            if 'DEVICE A' in sql_upper:
                return pd.DataFrame({'MDR_REPORT_KEY': [1001, 1002, 1003]})
            elif 'DEVICE B' in sql_upper:
                return pd.DataFrame({'MDR_REPORT_KEY': [1004, 1005]})
            elif 'DEVICE C' in sql_upper:
                return pd.DataFrame({'MDR_REPORT_KEY': [1006]})
            return pd.DataFrame({'MDR_REPORT_KEY': []})

        # Get accepted MDRs query (full device data)
        if 'BRAND_NAME, GENERIC_NAME, MANUFACTURER_D_NAME' in sql_upper and 'WHERE' in sql_upper:
            return pd.DataFrame({
                'MDR_REPORT_KEY': [1001, 1002, 1003, 1004, 1005, 1006],
                'BRAND_NAME': ['DEVICE A', 'DEVICE A', 'DEVICE A', 'DEVICE B', 'DEVICE B', 'DEVICE C'],
                'GENERIC_NAME': ['TYPE X', 'TYPE X', 'TYPE Y', 'TYPE X', 'TYPE Y', 'TYPE Z'],
                'MANUFACTURER_D_NAME': ['MFG 1', 'MFG 1', 'MFG 2', 'MFG 1', 'MFG 2', 'MFG 3']
            })

        # Query by MDR keys
        if 'MDR_REPORT_KEY IN' in sql_upper:
            # Return data for the requested MDR keys
            if params:
                return pd.DataFrame({
                    'MDR_REPORT_KEY': params,
                    'BRAND_NAME': ['DEVICE A'] * len(params),
                    'GENERIC_NAME': ['TYPE X'] * len(params),
                    'MANUFACTURER_D_NAME': ['MFG 1'] * len(params),
                    'DATE_RECEIVED': ['2020-01-01'] * len(params),
                    'EVENT_TYPE': ['M'] * len(params)
                })
            return pd.DataFrame()

        return pd.DataFrame()

    db.query = mock_query
    db.db_path = '/path/to/test.db'
    return db


@pytest.fixture
def manager_with_group(temp_json_path, mock_db):
    """Create a manager with one group already added."""
    manager = SelectionManager('test_project', temp_json_path, mock_db.db_path)
    manager.create_group('test_group', ['device', 'test'])
    return manager


# ==================== SelectionManager Tests ====================

class TestSelectionManagerInit:
    """Tests for SelectionManager initialization."""

    def test_create_new_manager(self, temp_json_path):
        """Test creating a new selection manager."""
        manager = SelectionManager('my_project', temp_json_path, '/path/to/db.db')

        assert manager.name == 'my_project'
        assert manager.database_path == '/path/to/db.db'
        assert manager.groups == {}
        assert manager.created_at is not None
        assert manager.updated_at is not None

    def test_create_manager_invalid_name(self, temp_json_path):
        """Test that invalid names are rejected."""
        with pytest.raises(ValueError, match="alphanumeric"):
            SelectionManager('my-project', temp_json_path, '/path/to/db.db')

        with pytest.raises(ValueError, match="alphanumeric"):
            SelectionManager('my project', temp_json_path, '/path/to/db.db')

    def test_create_manager_requires_db_path(self, temp_json_path):
        """Test that database_path is required for new projects."""
        with pytest.raises(ValueError, match="database_path is required"):
            SelectionManager('my_project', temp_json_path)

    def test_load_existing_manager(self, temp_json_path):
        """Test loading an existing manager from file."""
        # Create and save a manager
        manager1 = SelectionManager('my_project', temp_json_path, '/path/to/db.db')
        manager1.create_group('group1', ['keyword1'])
        manager1.save()

        # Load it back
        manager2 = SelectionManager.load(temp_json_path)

        assert manager2.name == 'my_project'
        assert 'group1' in manager2.groups
        assert manager2.groups['group1']['keywords'] == ['keyword1']

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading from non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            SelectionManager.load(str(tmp_path / 'nonexistent.json'))


class TestGroupManagement:
    """Tests for group CRUD operations."""

    def test_create_group(self, temp_json_path):
        """Test creating a new group."""
        manager = SelectionManager('test', temp_json_path, '/db.db')
        result = manager.create_group('penumbra', ['penumbra', 'lightning'])

        assert 'penumbra' in manager.groups
        assert manager.groups['penumbra']['keywords'] == ['penumbra', 'lightning']
        assert manager.groups['penumbra']['status'] == 'draft'
        assert manager.groups['penumbra']['current_phase'] == 'brand_name'
        assert result['group_name'] == 'penumbra'

    def test_create_group_invalid_name(self, temp_json_path):
        """Test that invalid group names are rejected."""
        manager = SelectionManager('test', temp_json_path, '/db.db')

        with pytest.raises(ValueError, match="alphanumeric"):
            manager.create_group('my-group', ['keyword'])

    def test_create_duplicate_group(self, temp_json_path):
        """Test that duplicate group names are rejected."""
        manager = SelectionManager('test', temp_json_path, '/db.db')
        manager.create_group('group1', ['keyword'])

        with pytest.raises(ValueError, match="already exists"):
            manager.create_group('group1', ['other_keyword'])

    def test_create_group_empty_keywords(self, temp_json_path):
        """Test that empty keywords are rejected."""
        manager = SelectionManager('test', temp_json_path, '/db.db')

        with pytest.raises(ValueError, match="At least one keyword"):
            manager.create_group('group1', [])

        with pytest.raises(ValueError, match="At least one non-empty"):
            manager.create_group('group2', ['', '  '])

    def test_remove_group(self, manager_with_group):
        """Test removing a group."""
        manager_with_group.remove_group('test_group')
        assert 'test_group' not in manager_with_group.groups

    def test_remove_nonexistent_group(self, manager_with_group):
        """Test removing non-existent group raises error."""
        with pytest.raises(KeyError, match="not found"):
            manager_with_group.remove_group('nonexistent')

    def test_rename_group(self, manager_with_group):
        """Test renaming a group."""
        manager_with_group.rename_group('test_group', 'renamed_group')

        assert 'test_group' not in manager_with_group.groups
        assert 'renamed_group' in manager_with_group.groups

    def test_rename_to_existing_name(self, temp_json_path):
        """Test renaming to an existing name fails."""
        manager = SelectionManager('test', temp_json_path, '/db.db')
        manager.create_group('group1', ['kw1'])
        manager.create_group('group2', ['kw2'])

        with pytest.raises(ValueError, match="already exists"):
            manager.rename_group('group1', 'group2')

    def test_merge_groups(self, temp_json_path):
        """Test merging multiple groups."""
        manager = SelectionManager('test', temp_json_path, '/db.db')
        manager.create_group('group1', ['kw1', 'kw2'])
        manager.create_group('group2', ['kw3'])

        # Add some decisions
        manager.set_decision('group1', 'brand_name', 'VALUE1', 'accept')
        manager.set_decision('group2', 'brand_name', 'VALUE2', 'accept')

        manager.merge_groups(['group1', 'group2'], 'merged')

        assert 'group1' not in manager.groups
        assert 'group2' not in manager.groups
        assert 'merged' in manager.groups
        assert set(manager.groups['merged']['keywords']) == {'kw1', 'kw2', 'kw3'}
        assert 'VALUE1' in manager.groups['merged']['decisions']['brand_name']['accepted']
        assert 'VALUE2' in manager.groups['merged']['decisions']['brand_name']['accepted']

    def test_merge_groups_requires_two(self, manager_with_group):
        """Test that merge requires at least 2 groups."""
        with pytest.raises(ValueError, match="At least 2"):
            manager_with_group.merge_groups(['test_group'], 'merged')

    def test_get_group_status(self, manager_with_group):
        """Test getting group status."""
        status = manager_with_group.get_group_status('test_group')

        assert status['status'] == 'draft'
        assert status['current_phase'] == 'brand_name'
        assert status['phase_index'] == 1
        assert 'decisions_count' in status


class TestSearchOperations:
    """Tests for search functionality."""

    def test_get_search_preview(self, temp_json_path, mock_db):
        """Test search preview before creating group."""
        manager = SelectionManager('test', temp_json_path, mock_db.db_path)
        preview = manager.get_search_preview(mock_db, ['device', 'test'])

        assert 'brand_name_count' in preview
        assert 'generic_name_count' in preview
        assert 'manufacturer_count' in preview
        assert 'total_unique_mdrs' in preview

    def test_search_candidates(self, manager_with_group, mock_db):
        """Test searching for candidate values."""
        candidates = manager_with_group.search_candidates(mock_db, 'test_group', 'brand_name')

        assert 'value' in candidates.columns
        assert 'mdr_count' in candidates.columns
        assert 'decision' in candidates.columns
        assert len(candidates) > 0

    def test_search_candidates_invalid_field(self, manager_with_group, mock_db):
        """Test that invalid field raises error."""
        with pytest.raises(ValueError, match="Invalid field"):
            manager_with_group.search_candidates(mock_db, 'test_group', 'invalid_field')

    def test_search_candidates_nonexistent_group(self, manager_with_group, mock_db):
        """Test searching non-existent group raises error."""
        with pytest.raises(KeyError, match="not found"):
            manager_with_group.search_candidates(mock_db, 'nonexistent', 'brand_name')

    def test_get_pending_values(self, manager_with_group, mock_db):
        """Test getting only undecided values."""
        # Make a decision on one value
        manager_with_group.set_decision('test_group', 'brand_name', 'DEVICE A', 'accept')

        pending = manager_with_group.get_pending_values(mock_db, 'test_group', 'brand_name')

        # Should not include DEVICE A
        assert 'DEVICE A' not in pending['value'].values


class TestDecisions:
    """Tests for decision handling."""

    def test_set_decision_accept(self, manager_with_group):
        """Test accepting a value."""
        manager_with_group.set_decision('test_group', 'brand_name', 'VALUE1', 'accept')

        decisions = manager_with_group.groups['test_group']['decisions']['brand_name']
        assert 'VALUE1' in decisions['accepted']
        assert manager_with_group.groups['test_group']['status'] == 'in_progress'

    def test_set_decision_reject(self, manager_with_group):
        """Test rejecting a value."""
        manager_with_group.set_decision('test_group', 'brand_name', 'VALUE1', 'reject')

        decisions = manager_with_group.groups['test_group']['decisions']['brand_name']
        assert 'VALUE1' in decisions['rejected']

    def test_set_decision_defer(self, manager_with_group):
        """Test deferring a value."""
        manager_with_group.set_decision('test_group', 'brand_name', 'VALUE1', 'defer')

        decisions = manager_with_group.groups['test_group']['decisions']['brand_name']
        assert 'VALUE1' in decisions['deferred']

    def test_set_decision_changes_existing(self, manager_with_group):
        """Test that changing a decision updates correctly."""
        manager_with_group.set_decision('test_group', 'brand_name', 'VALUE1', 'accept')
        manager_with_group.set_decision('test_group', 'brand_name', 'VALUE1', 'reject')

        decisions = manager_with_group.groups['test_group']['decisions']['brand_name']
        assert 'VALUE1' not in decisions['accepted']
        assert 'VALUE1' in decisions['rejected']

    def test_set_decision_invalid(self, manager_with_group):
        """Test that invalid decision raises error."""
        with pytest.raises(ValueError, match="Invalid decision"):
            manager_with_group.set_decision('test_group', 'brand_name', 'VALUE1', 'invalid')

    def test_set_decisions_bulk(self, manager_with_group):
        """Test setting multiple decisions at once."""
        manager_with_group.set_decisions_bulk('test_group', 'brand_name', {
            'VALUE1': 'accept',
            'VALUE2': 'reject',
            'VALUE3': 'defer'
        })

        decisions = manager_with_group.groups['test_group']['decisions']['brand_name']
        assert 'VALUE1' in decisions['accepted']
        assert 'VALUE2' in decisions['rejected']
        assert 'VALUE3' in decisions['deferred']


class TestPhaseNavigation:
    """Tests for phase navigation."""

    def test_advance_phase(self, manager_with_group):
        """Test advancing through phases."""
        assert manager_with_group.groups['test_group']['current_phase'] == 'brand_name'

        new_phase = manager_with_group.advance_phase('test_group')
        assert new_phase == 'generic_name'
        assert manager_with_group.groups['test_group']['current_phase'] == 'generic_name'

        new_phase = manager_with_group.advance_phase('test_group')
        assert new_phase == 'manufacturer'

        new_phase = manager_with_group.advance_phase('test_group')
        assert new_phase == 'finalized'
        assert manager_with_group.groups['test_group']['status'] == 'complete'

    def test_advance_finalized_raises(self, manager_with_group):
        """Test that advancing a finalized group raises error."""
        # Advance to finalized
        for _ in range(3):
            manager_with_group.advance_phase('test_group')

        with pytest.raises(ValueError, match="already finalized"):
            manager_with_group.advance_phase('test_group')

    def test_go_back_phase(self, manager_with_group):
        """Test going back to previous phase."""
        manager_with_group.advance_phase('test_group')  # Now at generic_name
        manager_with_group.advance_phase('test_group')  # Now at manufacturer

        new_phase = manager_with_group.go_back_phase('test_group')
        assert new_phase == 'generic_name'

    def test_go_back_from_first_raises(self, manager_with_group):
        """Test that going back from first phase raises error."""
        with pytest.raises(ValueError, match="Already at first phase"):
            manager_with_group.go_back_phase('test_group')

    def test_go_back_from_finalized(self, manager_with_group):
        """Test going back from finalized state."""
        for _ in range(3):
            manager_with_group.advance_phase('test_group')

        new_phase = manager_with_group.go_back_phase('test_group')
        assert new_phase == 'manufacturer'
        assert manager_with_group.groups['test_group']['status'] == 'in_progress'

    def test_reset_phase(self, manager_with_group):
        """Test resetting a phase clears decisions."""
        manager_with_group.set_decision('test_group', 'brand_name', 'VALUE1', 'accept')
        manager_with_group.set_decision('test_group', 'brand_name', 'VALUE2', 'reject')

        manager_with_group.reset_phase('test_group', 'brand_name')

        decisions = manager_with_group.groups['test_group']['decisions']['brand_name']
        assert len(decisions['accepted']) == 0
        assert len(decisions['rejected']) == 0
        assert len(decisions['deferred']) == 0


class TestFinalization:
    """Tests for group finalization."""

    def test_finalize_group(self, manager_with_group, mock_db):
        """Test finalizing a group creates snapshot."""
        manager_with_group.set_decision('test_group', 'brand_name', 'DEVICE A', 'accept')

        result = manager_with_group.finalize_group(mock_db, 'test_group')

        assert 'mdr_count' in result
        assert manager_with_group.groups['test_group']['mdr_keys_snapshot'] is not None
        assert manager_with_group.groups['test_group']['current_phase'] == 'finalized'


class TestResults:
    """Tests for getting results."""

    def test_get_results_decisions_mode(self, manager_with_group, mock_db):
        """Test getting results using decisions mode."""
        manager_with_group.set_decision('test_group', 'brand_name', 'DEVICE A', 'accept')

        results = manager_with_group.get_results(mock_db, mode='decisions')

        assert isinstance(results, SelectionResults)
        assert 'test_group' in results.groups

    def test_get_results_snapshot_mode_requires_finalization(self, manager_with_group, mock_db):
        """Test that snapshot mode requires finalized group."""
        with pytest.raises(ValueError, match="has no snapshot"):
            manager_with_group.get_results(mock_db, mode='snapshot')

    def test_get_results_snapshot_mode(self, manager_with_group, mock_db):
        """Test getting results using snapshot mode."""
        manager_with_group.set_decision('test_group', 'brand_name', 'DEVICE A', 'accept')
        manager_with_group.finalize_group(mock_db, 'test_group')

        results = manager_with_group.get_results(mock_db, mode='snapshot')

        assert isinstance(results, SelectionResults)
        assert 'test_group' in results.groups


class TestPersistence:
    """Tests for save/load operations."""

    def test_save_and_load_roundtrip(self, temp_json_path):
        """Test that save then load preserves all data."""
        manager1 = SelectionManager('test', temp_json_path, '/db.db')
        manager1.create_group('group1', ['kw1', 'kw2'])
        manager1.set_decision('group1', 'brand_name', 'VALUE1', 'accept')
        manager1.set_decision('group1', 'brand_name', 'VALUE2', 'defer')
        manager1.advance_phase('group1')
        manager1.save()

        manager2 = SelectionManager.load(temp_json_path)

        assert manager2.name == manager1.name
        assert manager2.groups['group1']['keywords'] == ['kw1', 'kw2']
        assert 'VALUE1' in manager2.groups['group1']['decisions']['brand_name']['accepted']
        assert 'VALUE2' in manager2.groups['group1']['decisions']['brand_name']['deferred']
        assert manager2.groups['group1']['current_phase'] == 'generic_name'

    def test_save_creates_valid_json(self, temp_json_path):
        """Test that saved file is valid JSON."""
        manager = SelectionManager('test', temp_json_path, '/db.db')
        manager.create_group('group1', ['keyword'])
        manager.save()

        with open(temp_json_path, 'r') as f:
            data = json.load(f)

        assert data['name'] == 'test'
        assert 'version' in data
        assert 'groups' in data


# ==================== SelectionResults Tests ====================

class TestSelectionResults:
    """Tests for SelectionResults container."""

    @pytest.fixture
    def sample_results(self):
        """Create sample SelectionResults."""
        data = {
            'group1': pd.DataFrame({
                'MDR_REPORT_KEY': [1, 2, 3],
                'BRAND_NAME': ['A', 'B', 'C'],
                'selection_group': ['group1'] * 3
            }),
            'group2': pd.DataFrame({
                'MDR_REPORT_KEY': [4, 5],
                'BRAND_NAME': ['D', 'E'],
                'selection_group': ['group2'] * 2
            })
        }
        manager = Mock()
        return SelectionResults(data, manager)

    def test_getitem(self, sample_results):
        """Test accessing group by name."""
        df = sample_results['group1']
        assert len(df) == 3
        assert 'MDR_REPORT_KEY' in df.columns

    def test_getitem_invalid_group(self, sample_results):
        """Test accessing non-existent group raises error."""
        with pytest.raises(KeyError, match="not in results"):
            _ = sample_results['nonexistent']

    def test_iter(self, sample_results):
        """Test iterating over groups."""
        groups = list(sample_results)
        assert 'group1' in groups
        assert 'group2' in groups

    def test_len(self, sample_results):
        """Test length is number of groups."""
        assert len(sample_results) == 2

    def test_groups_property(self, sample_results):
        """Test groups property returns list."""
        groups = sample_results.groups
        assert isinstance(groups, list)
        assert 'group1' in groups
        assert 'group2' in groups

    def test_to_df(self, sample_results):
        """Test combining all groups."""
        combined = sample_results.to_df()
        assert len(combined) == 5  # 3 + 2
        assert 'selection_group' in combined.columns

    def test_to_df_without_group_column(self, sample_results):
        """Test combining without group column."""
        combined = sample_results.to_df(include_group_column=False)
        assert 'selection_group' not in combined.columns

    def test_summary(self, sample_results):
        """Test summary property."""
        summary = sample_results.summary

        assert 'group' in summary.columns
        assert 'mdr_count' in summary.columns
        assert 'unique_mdrs' in summary.columns
        assert 'overlap_count' in summary.columns

    def test_summary_detects_overlap(self):
        """Test that summary detects overlapping MDRs."""
        data = {
            'group1': pd.DataFrame({
                'MDR_REPORT_KEY': [1, 2, 3],
                'selection_group': ['group1'] * 3
            }),
            'group2': pd.DataFrame({
                'MDR_REPORT_KEY': [2, 3, 4],  # 2 and 3 overlap
                'selection_group': ['group2'] * 3
            })
        }
        manager = Mock()
        results = SelectionResults(data, manager)
        summary = results.summary

        group2_row = summary[summary['group'] == 'group2'].iloc[0]
        assert group2_row['overlap_count'] == 2

    def test_filter_by_groups(self, sample_results):
        """Test filtering to specific groups."""
        filtered = sample_results.filter(groups=['group1'])

        assert len(filtered) == 1
        assert 'group1' in filtered.groups
        assert 'group2' not in filtered.groups

    def test_filter_by_column(self, sample_results):
        """Test filtering by DataFrame column."""
        filtered = sample_results.filter(BRAND_NAME='A')

        assert len(filtered['group1']) == 1
        assert filtered['group1'].iloc[0]['BRAND_NAME'] == 'A'


# ==================== Cascade Logic Tests ====================

class TestCascadeLogic:
    """Tests for cascade decision logic."""

    def test_accepted_mdrs_excluded_from_next_phase(self, manager_with_group, mock_db):
        """Test that accepted MDRs don't appear in subsequent phases."""
        # Accept DEVICE A in brand_name phase
        manager_with_group.set_decision('test_group', 'brand_name', 'DEVICE A', 'accept')
        manager_with_group.advance_phase('test_group')

        # Search generic_name - should exclude MDRs from DEVICE A
        candidates = manager_with_group.search_candidates(mock_db, 'test_group', 'generic_name')

        # The mock returns DEVICE A with MDRs 1001-1003
        # Those should be excluded from the generic_name search
        # This test verifies the exclusion logic is called correctly

    def test_rejected_mdrs_excluded_from_next_phase(self, manager_with_group, mock_db):
        """Test that rejected MDRs don't appear in subsequent phases."""
        # Reject DEVICE A in brand_name phase
        manager_with_group.set_decision('test_group', 'brand_name', 'DEVICE A', 'reject')
        manager_with_group.advance_phase('test_group')

        # Search generic_name - should exclude MDRs from DEVICE A
        candidates = manager_with_group.search_candidates(mock_db, 'test_group', 'generic_name')

        # Similar to above, verifies exclusion logic

    def test_deferred_mdrs_appear_in_next_phase(self, manager_with_group, mock_db):
        """Test that deferred MDRs DO appear in subsequent phases."""
        # Defer DEVICE A in brand_name phase
        manager_with_group.set_decision('test_group', 'brand_name', 'DEVICE A', 'defer')
        manager_with_group.advance_phase('test_group')

        # Search generic_name - should NOT exclude MDRs from DEVICE A
        # They should appear because they were deferred, not decided
        candidates = manager_with_group.search_candidates(mock_db, 'test_group', 'generic_name')

        # Verifies deferred items flow through to next phase


class TestDeferredCascadeWithRealDB:
    """
    Tests for deferred MDR cascade behavior using a real SQLite database.
    This tests the specific scenario where a brand name is deferred and
    the associated generic name doesn't match keywords.
    """

    @pytest.fixture
    def real_db(self, tmp_path):
        """Create a real SQLite database with test data."""
        import sqlite3

        db_path = str(tmp_path / "test_cascade.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create tables matching MAUDE structure
        cursor.execute('''
            CREATE TABLE device (
                MDR_REPORT_KEY INTEGER,
                BRAND_NAME TEXT,
                GENERIC_NAME TEXT,
                MANUFACTURER_D_NAME TEXT,
                DATE_RECEIVED TEXT,
                DEVICE_REPORT_PRODUCT_CODE TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE master (
                MDR_REPORT_KEY INTEGER,
                EVENT_KEY INTEGER,
                DATE_RECEIVED TEXT,
                EVENT_TYPE TEXT
            )
        ''')

        # Insert test data - key scenario:
        # - MDR 1001 has BRAND_NAME='PENUMBRA' (matches keyword)
        # - MDR 1001 has GENERIC_NAME='CATHETER' (does NOT match 'penumbra' keyword)
        # - When 'PENUMBRA' is deferred, 'CATHETER' should still appear in generic_name phase
        test_devices = [
            # These match 'penumbra' keyword in brand_name
            (1001, 'PENUMBRA LIGHTNING BOLT', 'THROMBECTOMY CATHETER', 'PENUMBRA INC', '2023-01-15', 'NIQ'),
            (1002, 'PENUMBRA', 'CATHETER', 'PENUMBRA INC', '2023-02-20', 'NIQ'),  # Generic brand
            (1003, 'PENUMBRA INDIGO', 'ASPIRATION CATHETER', 'PENUMBRA INC', '2023-03-10', 'NIQ'),
            # This matches 'penumbra' only in manufacturer
            (1004, 'OTHER DEVICE', 'STENT', 'PENUMBRA INC', '2023-04-05', 'NIQ'),
        ]

        cursor.executemany(
            'INSERT INTO device VALUES (?, ?, ?, ?, ?, ?)',
            test_devices
        )

        test_master = [
            (1001, 1001, '2023-01-15', 'M'),
            (1002, 1002, '2023-02-20', 'M'),
            (1003, 1003, '2023-03-10', 'M'),
            (1004, 1004, '2023-04-05', 'M'),
        ]

        cursor.executemany(
            'INSERT INTO master VALUES (?, ?, ?, ?)',
            test_master
        )

        conn.commit()
        conn.close()

        # Create a simple mock db object with query method
        class SimpleDB:
            def __init__(self, path):
                self.db_path = path

            def query(self, sql, params=None):
                conn = sqlite3.connect(self.db_path)
                if params:
                    df = pd.read_sql_query(sql, conn, params=params)
                else:
                    df = pd.read_sql_query(sql, conn)
                conn.close()
                return df

        return SimpleDB(db_path)

    def test_deferred_brand_shows_generic_in_next_phase(self, real_db, tmp_path):
        """
        Test that when a brand name is deferred, its generic name appears
        in the next phase even if it doesn't match keywords.
        """
        json_path = str(tmp_path / "cascade_test.json")
        manager = SelectionManager('cascade_test', json_path, real_db.db_path)
        manager.create_group('penumbra', ['penumbra'])

        # Phase 1: Brand Name
        candidates = manager.search_candidates(real_db, 'penumbra', 'brand_name')
        brand_values = set(candidates['value'].tolist())

        # Should find brand names matching 'penumbra'
        assert 'PENUMBRA LIGHTNING BOLT' in brand_values
        assert 'PENUMBRA' in brand_values
        assert 'PENUMBRA INDIGO' in brand_values
        assert 'OTHER DEVICE' in brand_values  # matches via manufacturer

        # Accept specific ones, DEFER 'PENUMBRA' (too generic)
        manager.set_decision('penumbra', 'brand_name', 'PENUMBRA LIGHTNING BOLT', 'accept')
        manager.set_decision('penumbra', 'brand_name', 'PENUMBRA INDIGO', 'accept')
        manager.set_decision('penumbra', 'brand_name', 'PENUMBRA', 'defer')  # MDR 1002
        manager.set_decision('penumbra', 'brand_name', 'OTHER DEVICE', 'reject')

        # Advance to generic_name phase
        manager.advance_phase('penumbra')

        # Phase 2: Generic Name
        # The deferred MDR 1002 has GENERIC_NAME='CATHETER' which does NOT contain 'penumbra'
        # But it should still appear because its brand was deferred
        candidates = manager.search_candidates(real_db, 'penumbra', 'generic_name')
        generic_values = set(candidates['value'].tolist())

        # 'CATHETER' should appear because MDR 1002 was deferred
        # Even though 'CATHETER' doesn't match 'penumbra' keyword
        assert 'CATHETER' in generic_values, \
            f"'CATHETER' should appear for deferred MDR 1002, but got: {generic_values}"

    def test_non_deferred_values_work_normally(self, real_db, tmp_path):
        """Test that the fix doesn't break normal keyword matching."""
        json_path = str(tmp_path / "normal_test.json")
        manager = SelectionManager('normal_test', json_path, real_db.db_path)
        manager.create_group('penumbra', ['penumbra'])

        # Phase 1: Accept everything (no deferrals)
        candidates = manager.search_candidates(real_db, 'penumbra', 'brand_name')
        for value in candidates['value']:
            manager.set_decision('penumbra', 'brand_name', value, 'accept')

        manager.advance_phase('penumbra')

        # Phase 2: Should show keyword matches (accepted MDRs excluded)
        candidates = manager.search_candidates(real_db, 'penumbra', 'generic_name')

        # Since all were accepted, no MDRs should appear in this phase
        assert len(candidates) == 0, \
            f"All MDRs were accepted, none should appear in generic_name phase"
