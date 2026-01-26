# selection.py - Device Selection Manager for MAUDE Analysis
# Copyright (C) 2026 Jacob Schwartz <jaschwa@umich.edu>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Device Selection Manager for reproducible MAUDE analysis.

This module provides interactive device selection through an accept/defer/reject
workflow, replacing the hierarchical_brand_standardization approach with a more
flexible and reproducible system.

Usage:
    from pymaude import MaudeDatabase, SelectionManager

    db = MaudeDatabase('maude.db')

    # Create new selection project
    manager = SelectionManager('venous_thrombectomy', 'selections.json', db.db_path)

    # Add a group
    manager.create_group('penumbra', ['penumbra', 'lightning'])

    # Search for candidates
    candidates = manager.search_candidates(db, 'penumbra', 'brand_name')

    # Set decisions
    manager.set_decision('penumbra', 'brand_name', 'PENUMBRA LIGHTNING BOLT 7', 'accept')
    manager.set_decision('penumbra', 'brand_name', 'PENUMBRA SMART COIL', 'reject')

    # Advance through phases and finalize
    manager.advance_phase('penumbra')
    # ... continue through generic_name and manufacturer phases
    manager.finalize_group('penumbra', db)

    # Get results
    results = manager.get_results(db)
    df = results['penumbra']  # DataFrame for penumbra group
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Iterator, Any, Union

import pandas as pd


# Constants
SCHEMA_VERSION = "1.0"
PHASES = ['brand_name', 'generic_name', 'manufacturer']
FIELD_MAP = {
    'brand_name': 'BRAND_NAME',
    'generic_name': 'GENERIC_NAME',
    'manufacturer': 'MANUFACTURER_D_NAME'
}
VALID_DECISIONS = {'accept', 'reject', 'defer'}


class SelectionManager:
    """
    Manages device selection projects for reproducible MAUDE analysis.

    A selection project contains multiple "groups" (e.g., device manufacturers
    or device families), each with search keywords and user decisions about
    which field values to accept, reject, or defer.

    The workflow proceeds in three phases per group:
    1. brand_name - Review matching brand names
    2. generic_name - Review matching generic names (for undecided MDRs)
    3. manufacturer - Review matching manufacturers (for undecided MDRs)

    At each phase, values can be:
    - accepted: MDRs with this value are included in results
    - rejected: MDRs with this value are excluded from results
    - deferred: MDRs with this value will appear in the next phase

    Attributes:
        name (str): Project identifier (e.g., 'venous_thrombectomy')
        file_path (Path): Path to JSON persistence file
        database_path (str): Path to associated MAUDE database
        groups (dict): Group configurations and decisions
        created_at (str): Project creation timestamp (ISO format)
        updated_at (str): Last modification timestamp (ISO format)

    Example:
        >>> manager = SelectionManager('my_project', 'selections.json')
        >>> manager.create_group('penumbra', ['penumbra', 'lightning'])
        >>> candidates = manager.search_candidates(db, 'penumbra', 'brand_name')
        >>> manager.set_decision('penumbra', 'brand_name', 'PENUMBRA BOLT', 'accept')
    """

    def __init__(
        self,
        name: str,
        file_path: Optional[str] = None,
        database_path: Optional[str] = None
    ):
        """
        Initialize a new SelectionManager or load existing project.

        Args:
            name: Project identifier (alphanumeric and underscores only)
            file_path: Path to JSON file for persistence. If exists, loads state.
                       If None, defaults to '{name}.selection.json'
            database_path: Path to MAUDE database. Required for new projects,
                          loaded from file for existing projects.

        Raises:
            ValueError: If name contains invalid characters
            FileNotFoundError: If loading existing project and file doesn't exist
        """
        # Validate name
        if not re.match(r'^[a-zA-Z0-9_]+$', name):
            raise ValueError(
                f"Project name must contain only alphanumeric characters and underscores. "
                f"Got: '{name}'"
            )

        self.name = name
        self.file_path = Path(file_path) if file_path else Path(f"{name}.selection.json")

        # Try to load existing project
        if self.file_path.exists():
            self._load()
            # Allow override of database_path if provided
            if database_path:
                self.database_path = database_path
        else:
            # Create new project
            if database_path is None:
                raise ValueError(
                    "database_path is required when creating a new selection project"
                )
            self.database_path = database_path
            self.created_at = datetime.utcnow().isoformat() + 'Z'
            self.updated_at = self.created_at
            self.groups: Dict[str, dict] = {}

    # ==================== Group Management ====================

    def create_group(self, group_name: str, keywords: List[str]) -> dict:
        """
        Create a new group with search keywords.

        Args:
            group_name: Identifier for this group (alphanumeric and underscores)
            keywords: List of search terms to match against device fields

        Returns:
            dict with group configuration (for preview purposes)

        Raises:
            ValueError: If group_name is invalid or already exists
            ValueError: If keywords list is empty

        Example:
            >>> manager.create_group('penumbra', ['penumbra', 'lightning'])
            {'group_name': 'penumbra', 'keywords': ['penumbra', 'lightning'], ...}
        """
        # Validate group name
        if not re.match(r'^[a-zA-Z0-9_]+$', group_name):
            raise ValueError(
                f"Group name must contain only alphanumeric characters and underscores. "
                f"Got: '{group_name}'"
            )

        if group_name in self.groups:
            raise ValueError(f"Group '{group_name}' already exists")

        if not keywords or len(keywords) == 0:
            raise ValueError("At least one keyword is required")

        # Clean keywords
        keywords = [kw.strip() for kw in keywords if kw.strip()]
        if not keywords:
            raise ValueError("At least one non-empty keyword is required")

        # Create group structure
        self.groups[group_name] = {
            'keywords': keywords,
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'status': 'draft',
            'current_phase': 'brand_name',
            'decisions': {
                'brand_name': {'accepted': [], 'rejected': [], 'deferred': []},
                'generic_name': {'accepted': [], 'rejected': [], 'deferred': []},
                'manufacturer': {'accepted': [], 'rejected': [], 'deferred': []}
            },
            'mdr_keys_snapshot': None,
            'snapshot_timestamp': None,
            'notes': ''
        }

        self._touch()
        return {'group_name': group_name, **self.groups[group_name]}

    def remove_group(self, group_name: str) -> None:
        """
        Remove a group from the project.

        Args:
            group_name: Name of the group to remove

        Raises:
            KeyError: If group doesn't exist
        """
        if group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not found")

        del self.groups[group_name]
        self._touch()

    def rename_group(self, old_name: str, new_name: str) -> None:
        """
        Rename an existing group.

        Args:
            old_name: Current group name
            new_name: New group name (alphanumeric and underscores)

        Raises:
            KeyError: If old_name doesn't exist
            ValueError: If new_name is invalid or already exists
        """
        if old_name not in self.groups:
            raise KeyError(f"Group '{old_name}' not found")

        if not re.match(r'^[a-zA-Z0-9_]+$', new_name):
            raise ValueError(
                f"Group name must contain only alphanumeric characters and underscores. "
                f"Got: '{new_name}'"
            )

        if new_name in self.groups and new_name != old_name:
            raise ValueError(f"Group '{new_name}' already exists")

        if old_name != new_name:
            self.groups[new_name] = self.groups.pop(old_name)
            self._touch()

    def merge_groups(self, source_groups: List[str], target_name: str) -> None:
        """
        Merge multiple groups into one.

        Combines keywords and decisions from all source groups. Useful when
        you discover during selection that separate groups should be combined
        (e.g., ClotTriever XL and ClotTriever BOLD can't be reliably distinguished).

        Args:
            source_groups: List of group names to merge
            target_name: Name for the merged group (can be one of the source names)

        Raises:
            ValueError: If fewer than 2 source groups provided
            KeyError: If any source group doesn't exist
            ValueError: If target_name is invalid
        """
        if len(source_groups) < 2:
            raise ValueError("At least 2 source groups are required for merge")

        for name in source_groups:
            if name not in self.groups:
                raise KeyError(f"Group '{name}' not found")

        if not re.match(r'^[a-zA-Z0-9_]+$', target_name):
            raise ValueError(
                f"Target name must contain only alphanumeric characters and underscores. "
                f"Got: '{target_name}'"
            )

        # Combine keywords (deduplicated)
        combined_keywords = []
        seen_keywords = set()
        for name in source_groups:
            for kw in self.groups[name]['keywords']:
                if kw.lower() not in seen_keywords:
                    combined_keywords.append(kw)
                    seen_keywords.add(kw.lower())

        # Combine decisions
        combined_decisions = {
            'brand_name': {'accepted': [], 'rejected': [], 'deferred': []},
            'generic_name': {'accepted': [], 'rejected': [], 'deferred': []},
            'manufacturer': {'accepted': [], 'rejected': [], 'deferred': []}
        }

        for name in source_groups:
            for phase in PHASES:
                for decision_type in ['accepted', 'rejected', 'deferred']:
                    values = self.groups[name]['decisions'][phase][decision_type]
                    for v in values:
                        if v not in combined_decisions[phase][decision_type]:
                            combined_decisions[phase][decision_type].append(v)

        # Determine merged status (use earliest phase among sources)
        phases_order = ['brand_name', 'generic_name', 'manufacturer', 'finalized']
        earliest_phase = 'finalized'
        for name in source_groups:
            phase = self.groups[name]['current_phase']
            if phases_order.index(phase) < phases_order.index(earliest_phase):
                earliest_phase = phase

        merged_status = 'complete' if earliest_phase == 'finalized' else 'in_progress'
        if all(self.groups[n]['status'] == 'draft' for n in source_groups):
            merged_status = 'draft'

        # Remove source groups (except target if it's one of them)
        for name in source_groups:
            if name != target_name:
                del self.groups[name]

        # Create or update target group
        self.groups[target_name] = {
            'keywords': combined_keywords,
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'status': merged_status,
            'current_phase': earliest_phase,
            'decisions': combined_decisions,
            'mdr_keys_snapshot': None,  # Invalidate snapshot after merge
            'snapshot_timestamp': None,
            'notes': f"Merged from: {', '.join(source_groups)}"
        }

        self._touch()

    def get_group_status(self, group_name: str) -> dict:
        """
        Get the current status of a group.

        Args:
            group_name: Name of the group

        Returns:
            dict with status information:
            - status: 'draft', 'in_progress', or 'complete'
            - current_phase: Current phase name
            - phase_index: Current phase number (1-3, or 4 if finalized)
            - decisions_count: Dict of counts per phase and decision type
            - is_finalized: Whether group has been finalized with MDR snapshot

        Raises:
            KeyError: If group doesn't exist
        """
        if group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not found")

        group = self.groups[group_name]

        # Count decisions per phase
        decisions_count = {}
        for phase in PHASES:
            decisions_count[phase] = {
                'accepted': len(group['decisions'][phase]['accepted']),
                'rejected': len(group['decisions'][phase]['rejected']),
                'deferred': len(group['decisions'][phase]['deferred'])
            }

        phase_index = PHASES.index(group['current_phase']) + 1 if group['current_phase'] in PHASES else 4

        # MDR count from snapshot (if finalized)
        mdr_count = len(group['mdr_keys_snapshot']) if group['mdr_keys_snapshot'] is not None else None

        # Event count from snapshot (if available - may be None for older snapshots)
        event_count = group.get('event_count_snapshot')

        return {
            'status': group['status'],
            'current_phase': group['current_phase'],
            'phase_index': phase_index,
            'decisions_count': decisions_count,
            'is_finalized': group['mdr_keys_snapshot'] is not None,
            'mdr_count': mdr_count,
            'event_count': event_count,
            'keywords': group['keywords']
        }

    # ==================== Search ====================

    def get_search_preview(
        self,
        db,
        keywords: List[str],
        progress_callback: Optional[Any] = None
    ) -> dict:
        """
        Preview search results before creating a group.

        Args:
            db: MaudeDatabase instance
            keywords: List of search terms
            progress_callback: Optional callback function(step: int, message: str)
                              for progress updates. Steps are 1-4.

        Returns:
            dict with counts:
            - brand_name_count: Unique brand names matching
            - brand_name_mdrs: Total MDRs via brand name
            - generic_name_count: Unique generic names matching
            - generic_name_mdrs: Total MDRs via generic name
            - manufacturer_count: Unique manufacturers matching
            - manufacturer_mdrs: Total MDRs via manufacturer
            - total_unique_mdrs: Approximate unique MDRs across all fields
        """
        preview = {}

        # Build keyword conditions
        conditions = self._build_keyword_conditions(keywords)

        field_labels = {
            'brand_name': 'brand names',
            'generic_name': 'generic names',
            'manufacturer': 'manufacturers'
        }

        step = 0
        for field, sql_col in FIELD_MAP.items():
            step += 1
            if progress_callback:
                progress_callback(step, f"Querying {field_labels[field]}...")

            sql = f"""
                SELECT COUNT(DISTINCT {sql_col}) as value_count,
                       COUNT(DISTINCT MDR_REPORT_KEY) as mdr_count
                FROM device
                WHERE ({conditions})
                  AND {sql_col} IS NOT NULL
            """
            result = db.query(sql)
            preview[f'{field}_count'] = int(result['value_count'].iloc[0])
            preview[f'{field}_mdrs'] = int(result['mdr_count'].iloc[0])

        # Get total unique MDRs
        step += 1
        if progress_callback:
            progress_callback(step, "Counting total unique MDRs...")

        sql = f"""
            SELECT COUNT(DISTINCT MDR_REPORT_KEY) as total
            FROM device
            WHERE ({conditions})
        """
        result = db.query(sql)
        preview['total_unique_mdrs'] = int(result['total'].iloc[0])

        return preview

    def search_candidates(
        self,
        db,
        group_name: str,
        field: str,
        progress_callback: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Search for unique field values matching group keywords.

        Returns values that need decisions in the specified phase, excluding
        MDRs already decided in previous phases. Also includes field values
        for MDRs that were deferred in previous phases (even if they don't
        match keywords).

        Args:
            db: MaudeDatabase instance
            group_name: Name of the group to search
            field: One of 'brand_name', 'generic_name', 'manufacturer'

        Returns:
            DataFrame with columns:
            - value: The unique field value (e.g., 'PENUMBRA LIGHTNING BOLT 7')
            - mdr_count: Number of MDRs with this value
            - decision: Current decision for this value ('accept', 'reject', 'defer', or None)

        Raises:
            KeyError: If group doesn't exist
            ValueError: If field is invalid
        """
        if group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not found")

        if field not in FIELD_MAP:
            raise ValueError(f"Invalid field: {field}. Must be one of {list(FIELD_MAP.keys())}")

        group = self.groups[group_name]
        sql_col = FIELD_MAP[field]
        field_label = field.replace('_', ' ')

        # Build keyword conditions - only search the current field, not all fields
        conditions = self._build_keyword_conditions(group['keywords'], field=field)

        # Step 1: Get MDRs excluded by decisions (accepted/rejected) in previous phases
        if progress_callback:
            progress_callback(1, "Checking previous decisions...")
        excluded_mdrs = self._get_excluded_mdrs(db, group_name, up_to_phase=field)

        # Step 2: Get MDRs deferred in previous phases - these MUST appear in this phase
        if progress_callback:
            progress_callback(2, "Finding deferred items...")
        deferred_mdrs = self._get_deferred_mdrs(db, group_name, up_to_phase=field)

        # Build exclusion clause
        exclude_clause = ""
        params = []
        if excluded_mdrs:
            placeholders = ','.join('?' * len(excluded_mdrs))
            exclude_clause = f"AND MDR_REPORT_KEY NOT IN ({placeholders})"
            params = list(excluded_mdrs)

        # Step 3: Query for values matching keywords (excluding decided MDRs)
        if progress_callback:
            progress_callback(3, f"Searching {field_label}s...")
        import sys
        import time as _time
        print(f"[SelectionManager] Searching {field_label}s for group '{group_name}'...", flush=True)
        print(f"[SelectionManager] Keywords: {group['keywords']}", file=sys.stderr, flush=True)
        _start = _time.time()
        sql_keywords = f"""
            SELECT {sql_col} as value,
                   COUNT(DISTINCT MDR_REPORT_KEY) as mdr_count
            FROM device
            WHERE ({conditions})
              AND {sql_col} IS NOT NULL
              {exclude_clause}
            GROUP BY {sql_col}
        """

        if params:
            result_keywords = db.query(sql_keywords, params=params)
        else:
            result_keywords = db.query(sql_keywords)
        _elapsed = _time.time() - _start
        print(f"[SelectionManager] Query completed in {_elapsed:.1f}s, found {len(result_keywords)} unique values", flush=True)

        # Query 2: Find values for deferred MDRs (may not match keywords)
        # Only needed if there are deferred MDRs and we're past the first phase
        result_deferred = pd.DataFrame(columns=['value', 'mdr_count'])
        if deferred_mdrs:
            # Remove any deferred MDRs that are also excluded (shouldn't happen, but safety)
            deferred_only = deferred_mdrs - excluded_mdrs
            if deferred_only:
                deferred_placeholders = ','.join('?' * len(deferred_only))
                sql_deferred = f"""
                    SELECT {sql_col} as value,
                           COUNT(DISTINCT MDR_REPORT_KEY) as mdr_count
                    FROM device
                    WHERE MDR_REPORT_KEY IN ({deferred_placeholders})
                      AND {sql_col} IS NOT NULL
                    GROUP BY {sql_col}
                """
                result_deferred = db.query(sql_deferred, params=list(deferred_only))

        # Combine results, merging counts for any overlapping values
        if len(result_deferred) > 0:
            # Create a dict of value -> mdr_count for keyword results
            keyword_counts = dict(zip(result_keywords['value'], result_keywords['mdr_count']))
            deferred_counts = dict(zip(result_deferred['value'], result_deferred['mdr_count']))

            # Merge: for values in both, take the keyword count (deferred MDRs are subset)
            # For values only in deferred, add them
            all_values = set(keyword_counts.keys()) | set(deferred_counts.keys())
            merged_data = []
            for v in all_values:
                # Use keyword count if available, otherwise deferred count
                count = keyword_counts.get(v, deferred_counts.get(v, 0))
                merged_data.append({'value': v, 'mdr_count': count})

            result = pd.DataFrame(merged_data)
            result = result.sort_values('mdr_count', ascending=False).reset_index(drop=True)
        else:
            result = result_keywords

        # Add current decision status
        decisions = group['decisions'][field]

        def get_decision(value):
            if value in decisions['accepted']:
                return 'accept'
            elif value in decisions['rejected']:
                return 'reject'
            elif value in decisions['deferred']:
                return 'defer'
            return None

        result['decision'] = result['value'].apply(get_decision)

        return result

    def get_pending_values(self, db, group_name: str, field: str) -> pd.DataFrame:
        """
        Get values that still need a decision in the current phase.

        Convenience wrapper around search_candidates that filters to undecided values.

        Args:
            db: MaudeDatabase instance
            group_name: Name of the group
            field: Phase field name

        Returns:
            DataFrame of undecided values (where decision is None)
        """
        candidates = self.search_candidates(db, group_name, field)
        return candidates[candidates['decision'].isna()]

    # ==================== Decisions ====================

    def set_decision(
        self,
        group_name: str,
        field: str,
        value: str,
        decision: str
    ) -> None:
        """
        Set the decision for a single field value.

        Args:
            group_name: Name of the group
            field: One of 'brand_name', 'generic_name', 'manufacturer'
            value: The field value to decide on
            decision: One of 'accept', 'reject', 'defer'

        Raises:
            KeyError: If group doesn't exist
            ValueError: If field or decision is invalid
        """
        if group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not found")

        if field not in FIELD_MAP:
            raise ValueError(f"Invalid field: {field}")

        if decision not in VALID_DECISIONS:
            raise ValueError(f"Invalid decision: {decision}. Must be one of {VALID_DECISIONS}")

        group = self.groups[group_name]
        decisions = group['decisions'][field]

        # Remove from any existing decision list
        for d_type in ['accepted', 'rejected', 'deferred']:
            if value in decisions[d_type]:
                decisions[d_type].remove(value)

        # Add to appropriate list
        decision_map = {'accept': 'accepted', 'reject': 'rejected', 'defer': 'deferred'}
        decisions[decision_map[decision]].append(value)

        # Update status
        if group['status'] == 'draft':
            group['status'] = 'in_progress'

        self._touch()

    def set_decisions_bulk(
        self,
        group_name: str,
        field: str,
        decisions: Dict[str, str]
    ) -> None:
        """
        Set decisions for multiple values at once.

        Args:
            group_name: Name of the group
            field: One of 'brand_name', 'generic_name', 'manufacturer'
            decisions: Dict mapping values to decisions
                       e.g., {'PENUMBRA BOLT': 'accept', 'PENUMBRA COIL': 'reject'}

        Raises:
            KeyError: If group doesn't exist
            ValueError: If field or any decision is invalid
        """
        for value, decision in decisions.items():
            self.set_decision(group_name, field, value, decision)

    # ==================== Phase Navigation ====================

    def advance_phase(self, group_name: str) -> str:
        """
        Advance to the next phase.

        Args:
            group_name: Name of the group

        Returns:
            Name of the new phase (or 'finalized' if complete)

        Raises:
            KeyError: If group doesn't exist
            ValueError: If group is already finalized
        """
        if group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not found")

        group = self.groups[group_name]
        current = group['current_phase']

        if current == 'finalized':
            raise ValueError(f"Group '{group_name}' is already finalized")

        if current not in PHASES:
            raise ValueError(f"Invalid current phase: {current}")

        current_idx = PHASES.index(current)

        if current_idx < len(PHASES) - 1:
            group['current_phase'] = PHASES[current_idx + 1]
        else:
            group['current_phase'] = 'finalized'
            group['status'] = 'complete'

        self._touch()
        return group['current_phase']

    def go_back_phase(self, group_name: str) -> str:
        """
        Go back to the previous phase.

        Args:
            group_name: Name of the group

        Returns:
            Name of the new phase

        Raises:
            KeyError: If group doesn't exist
            ValueError: If already at first phase
        """
        if group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not found")

        group = self.groups[group_name]
        current = group['current_phase']

        if current == 'finalized':
            group['current_phase'] = PHASES[-1]
            group['status'] = 'in_progress'
            # Invalidate snapshot when un-finalizing
            group['mdr_keys_snapshot'] = None
            group['snapshot_timestamp'] = None
        elif current == PHASES[0]:
            raise ValueError(f"Already at first phase: {current}")
        else:
            current_idx = PHASES.index(current)
            group['current_phase'] = PHASES[current_idx - 1]

        self._touch()
        return group['current_phase']

    def reset_phase(self, group_name: str, field: str) -> None:
        """
        Clear all decisions for a specific phase.

        Args:
            group_name: Name of the group
            field: Phase to reset

        Raises:
            KeyError: If group doesn't exist
            ValueError: If field is invalid
        """
        if group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not found")

        if field not in FIELD_MAP:
            raise ValueError(f"Invalid field: {field}")

        group = self.groups[group_name]
        group['decisions'][field] = {
            'accepted': [],
            'rejected': [],
            'deferred': []
        }

        # Invalidate snapshot
        group['mdr_keys_snapshot'] = None
        group['snapshot_timestamp'] = None

        self._touch()

    # ==================== Finalization ====================

    def finalize_group(self, db, group_name: str) -> dict:
        """
        Finalize a group by capturing MDR key snapshot.

        This creates a snapshot of the exact MDR_REPORT_KEYs that match
        the current decisions, enabling exact reproducibility even if
        the FDA updates the database.

        Args:
            db: MaudeDatabase instance
            group_name: Name of the group to finalize

        Returns:
            dict with finalization summary:
            - mdr_count: Number of unique MDRs in snapshot
            - event_count: Number of rows (events) returned by query
            - pending_count: Number of still-deferred values (excluded)

        Raises:
            KeyError: If group doesn't exist
        """
        if group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not found")

        group = self.groups[group_name]

        # Get accepted MDR keys
        mdr_keys = self._get_accepted_mdrs(db, group_name)

        # Query to get actual row count (MDRs can have multiple device rows)
        df = self._query_by_mdr_keys(db, list(mdr_keys))
        event_count = len(df)

        # Count pending (deferred values that never got decided)
        pending_count = 0
        for phase in PHASES:
            pending_count += len(group['decisions'][phase]['deferred'])

        # Store snapshot
        group['mdr_keys_snapshot'] = sorted(list(mdr_keys))
        group['event_count_snapshot'] = event_count
        group['snapshot_timestamp'] = datetime.utcnow().isoformat() + 'Z'
        group['current_phase'] = 'finalized'
        group['status'] = 'complete'

        self._touch()

        return {
            'mdr_count': len(mdr_keys),
            'event_count': event_count,
            'pending_count': pending_count
        }

    def get_results(
        self,
        db,
        mode: str = 'decisions',
        groups: Optional[List[str]] = None,
        verbose: bool = False
    ) -> 'SelectionResults':
        """
        Execute queries and return results for all or specified groups.

        Args:
            db: MaudeDatabase instance
            mode: 'decisions' to re-run from decisions (adapts to FDA updates)
                  'snapshot' to use mdr_keys_snapshot (exact reproducibility)
            groups: Optional list of group names. If None, includes all groups.
            verbose: If True, print progress messages

        Returns:
            SelectionResults object with per-group DataFrames

        Raises:
            ValueError: If mode is invalid
            ValueError: If mode='snapshot' but group has no snapshot
        """
        if mode not in ('decisions', 'snapshot'):
            raise ValueError(f"Invalid mode: {mode}. Must be 'decisions' or 'snapshot'")

        target_groups = groups if groups else list(self.groups.keys())
        results_data = {}
        total_groups = len(target_groups)

        if verbose:
            print(f"Getting results for {total_groups} group(s)...", flush=True)

        for i, group_name in enumerate(target_groups, 1):
            if group_name not in self.groups:
                raise KeyError(f"Group '{group_name}' not found")

            if verbose:
                print(f"  [{i}/{total_groups}] Processing '{group_name}'...", end=' ', flush=True)

            group = self.groups[group_name]

            if mode == 'snapshot':
                if group['mdr_keys_snapshot'] is None:
                    raise ValueError(
                        f"Group '{group_name}' has no snapshot. "
                        "Finalize the group first or use mode='decisions'."
                    )
                mdr_keys = group['mdr_keys_snapshot']
                df = self._query_by_mdr_keys(db, mdr_keys)
            else:
                mdr_keys = self._get_accepted_mdrs(db, group_name)
                df = self._query_by_mdr_keys(db, list(mdr_keys))

            # Add group identifier
            df['selection_group'] = group_name
            results_data[group_name] = df

            if verbose:
                unique_mdrs = df['MDR_REPORT_KEY'].nunique() if 'MDR_REPORT_KEY' in df.columns else len(df)
                if unique_mdrs != len(df):
                    print(f"done ({unique_mdrs} MDRs, {len(df)} rows)", flush=True)
                else:
                    print(f"done ({len(df)} MDRs)", flush=True)

        if verbose:
            print("All groups complete!", flush=True)

        return SelectionResults(results_data, self)

    # ==================== Persistence ====================

    def save(self) -> None:
        """
        Save the current state to JSON file.

        The file is saved atomically by writing to a temp file first.
        """
        data = {
            'name': self.name,
            'version': SCHEMA_VERSION,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'database_path': self.database_path,
            'groups': self.groups
        }

        # Write atomically
        temp_path = self.file_path.with_suffix('.json.tmp')
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
        temp_path.replace(self.file_path)

    @classmethod
    def load(cls, file_path: str) -> 'SelectionManager':
        """
        Load a SelectionManager from a JSON file.

        Args:
            file_path: Path to the JSON file

        Returns:
            SelectionManager instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Selection file not found: {file_path}")

        with open(path, 'r') as f:
            data = json.load(f)

        if 'name' not in data:
            raise ValueError("Invalid selection file: missing 'name' field")

        # Create instance with file path
        manager = cls.__new__(cls)
        manager.name = data['name']
        manager.file_path = path
        manager.created_at = data.get('created_at', datetime.utcnow().isoformat() + 'Z')
        manager.updated_at = data.get('updated_at', manager.created_at)
        manager.database_path = data.get('database_path', '')
        manager.groups = data.get('groups', {})

        return manager

    def _load(self) -> None:
        """Load state from file_path."""
        with open(self.file_path, 'r') as f:
            data = json.load(f)

        self.created_at = data.get('created_at', datetime.utcnow().isoformat() + 'Z')
        self.updated_at = data.get('updated_at', self.created_at)
        self.database_path = data.get('database_path', '')
        self.groups = data.get('groups', {})

    def _touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow().isoformat() + 'Z'

    # ==================== Internal Helpers ====================

    def _build_keyword_conditions(self, keywords: List[str], field: str = None) -> str:
        """
        Build SQL WHERE conditions for keyword matching.

        Args:
            keywords: List of search terms
            field: If specified, only search this field (e.g., 'brand_name').
                   If None, search all fields.
        """
        conditions = []
        for kw in keywords:
            # Escape single quotes and % for SQL
            kw_escaped = kw.replace("'", "''").replace("%", "\\%")
            if field:
                # Search only the specified field
                # LIKE is case-insensitive by default in SQLite for ASCII
                sql_col = FIELD_MAP[field]
                conditions.append(f"{sql_col} LIKE '%{kw_escaped}%'")
            else:
                # Search all fields
                for sql_col in FIELD_MAP.values():
                    conditions.append(f"{sql_col} LIKE '%{kw_escaped}%'")
        return ' OR '.join(conditions)

    def _get_excluded_mdrs(
        self,
        db,
        group_name: str,
        up_to_phase: str
    ) -> Set[int]:
        """
        Get MDR_REPORT_KEYs that have been decided (accepted or rejected)
        in phases before the specified phase.
        """
        group = self.groups[group_name]
        excluded = set()

        for phase in PHASES:
            if phase == up_to_phase:
                break

            decisions = group['decisions'][phase]

            # Get MDRs for accepted values
            for value in decisions['accepted']:
                mdrs = self._get_mdrs_for_value(db, group_name, phase, value)
                excluded.update(mdrs)

            # Get MDRs for rejected values
            for value in decisions['rejected']:
                mdrs = self._get_mdrs_for_value(db, group_name, phase, value)
                excluded.update(mdrs)

        return excluded

    def _get_deferred_mdrs(
        self,
        db,
        group_name: str,
        up_to_phase: str
    ) -> Set[int]:
        """
        Get MDR_REPORT_KEYs that have been deferred in phases before the specified phase.
        These MDRs should appear in subsequent phases even if their field values
        don't match the keywords.
        """
        group = self.groups[group_name]
        deferred = set()

        for phase in PHASES:
            if phase == up_to_phase:
                break

            decisions = group['decisions'][phase]

            # Get MDRs for deferred values
            for value in decisions['deferred']:
                mdrs = self._get_mdrs_for_value(db, group_name, phase, value)
                deferred.update(mdrs)

        return deferred

    def get_multi_deferred_mdrs(
        self,
        db,
        group_name: str,
        min_deferrals: int = 2
    ) -> pd.DataFrame:
        """
        Get MDRs that were deferred in multiple phases.

        Returns a DataFrame with columns:
        - MDR_REPORT_KEY
        - BRAND_NAME
        - GENERIC_NAME
        - MANUFACTURER_D_NAME
        - defer_count (number of phases where this MDR's values were deferred)
        - deferred_phases (list of phase names where deferred)

        Args:
            db: MaudeDatabase instance
            group_name: Name of the group
            min_deferrals: Minimum number of phases with deferrals (default 2)
        """
        if group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not found")

        group = self.groups[group_name]

        # For each phase, get MDRs whose field value was deferred
        # Use batched query instead of one query per value for performance
        phase_deferred = {}  # phase -> set of MDR keys
        for phase in PHASES:
            decisions = group['decisions'][phase]
            deferred_values = decisions['deferred']

            if not deferred_values:
                phase_deferred[phase] = set()
                continue

            # Batch query: get all MDRs for all deferred values in one query
            sql_col = FIELD_MAP[phase]
            conditions = self._build_keyword_conditions(group['keywords'])

            # Build IN clause with escaped values
            escaped_values = [v.replace("'", "''") for v in deferred_values]
            in_clause = ','.join(f"'{v}'" for v in escaped_values)

            sql = f"""
                SELECT DISTINCT MDR_REPORT_KEY
                FROM device
                WHERE ({conditions})
                  AND {sql_col} IN ({in_clause})
            """
            result = db.query(sql)
            phase_deferred[phase] = set(result['MDR_REPORT_KEY'].tolist())

        # Find MDRs deferred in multiple phases
        from collections import Counter
        mdr_defer_counts = Counter()
        mdr_defer_phases = {}  # mdr -> list of phases

        for phase, mdrs in phase_deferred.items():
            for mdr in mdrs:
                mdr_defer_counts[mdr] += 1
                if mdr not in mdr_defer_phases:
                    mdr_defer_phases[mdr] = []
                mdr_defer_phases[mdr].append(phase)

        # Filter to those with min_deferrals or more
        multi_deferred = {
            mdr for mdr, count in mdr_defer_counts.items()
            if count >= min_deferrals
        }

        if not multi_deferred:
            return pd.DataFrame(columns=[
                'MDR_REPORT_KEY', 'BRAND_NAME', 'GENERIC_NAME',
                'MANUFACTURER_D_NAME', 'defer_count', 'deferred_phases'
            ])

        # Get the field values for these MDRs
        placeholders = ','.join('?' * len(multi_deferred))
        conditions = self._build_keyword_conditions(group['keywords'])

        sql = f"""
            SELECT DISTINCT MDR_REPORT_KEY, BRAND_NAME, GENERIC_NAME, MANUFACTURER_D_NAME
            FROM device
            WHERE MDR_REPORT_KEY IN ({placeholders})
              AND ({conditions})
        """
        result = db.query(sql, params=list(multi_deferred))

        # Add defer info
        result['defer_count'] = result['MDR_REPORT_KEY'].apply(
            lambda x: mdr_defer_counts[x]
        )
        result['deferred_phases'] = result['MDR_REPORT_KEY'].apply(
            lambda x: mdr_defer_phases.get(x, [])
        )

        # Sort by defer_count descending, then by brand name
        result = result.sort_values(
            ['defer_count', 'BRAND_NAME'],
            ascending=[False, True]
        ).reset_index(drop=True)

        return result

    def _get_mdrs_for_value(
        self,
        db,
        group_name: str,
        field: str,
        value: str
    ) -> Set[int]:
        """Get MDR_REPORT_KEYs that match a specific field value."""
        group = self.groups[group_name]
        sql_col = FIELD_MAP[field]
        conditions = self._build_keyword_conditions(group['keywords'])

        # Escape value for SQL
        value_escaped = value.replace("'", "''")

        sql = f"""
            SELECT DISTINCT MDR_REPORT_KEY
            FROM device
            WHERE ({conditions})
              AND {sql_col} = '{value_escaped}'
        """
        result = db.query(sql)
        return set(result['MDR_REPORT_KEY'].tolist())

    def _get_accepted_mdrs(self, db, group_name: str) -> Set[int]:
        """
        Get all MDR_REPORT_KEYs that should be included based on decisions.

        Logic:
        1. Start with all MDRs matching keywords
        2. For each phase, include MDRs for accepted values
        3. Exclude MDRs for rejected values
        4. Deferred values in final phase are excluded
        """
        group = self.groups[group_name]
        conditions = self._build_keyword_conditions(group['keywords'])

        # Get all matching MDRs
        sql = f"""
            SELECT DISTINCT MDR_REPORT_KEY, BRAND_NAME, GENERIC_NAME, MANUFACTURER_D_NAME
            FROM device
            WHERE ({conditions})
        """
        all_mdrs_df = db.query(sql)

        accepted_mdrs = set()
        rejected_mdrs = set()

        # Process each phase
        for phase in PHASES:
            sql_col = FIELD_MAP[phase]
            decisions = group['decisions'][phase]

            # Process accepted values
            for value in decisions['accepted']:
                matching = all_mdrs_df[all_mdrs_df[sql_col] == value]['MDR_REPORT_KEY']
                for mdr in matching:
                    if mdr not in rejected_mdrs:
                        accepted_mdrs.add(int(mdr))

            # Process rejected values
            for value in decisions['rejected']:
                matching = all_mdrs_df[all_mdrs_df[sql_col] == value]['MDR_REPORT_KEY']
                for mdr in matching:
                    rejected_mdrs.add(int(mdr))
                    accepted_mdrs.discard(int(mdr))

        return accepted_mdrs

    def _query_by_mdr_keys(self, db, mdr_keys: List[int]) -> pd.DataFrame:
        """Query master+device tables for specific MDR_REPORT_KEYs."""
        if not mdr_keys:
            # Return empty DataFrame with expected columns
            return pd.DataFrame(columns=['MDR_REPORT_KEY', 'BRAND_NAME', 'GENERIC_NAME',
                                         'MANUFACTURER_D_NAME', 'DATE_RECEIVED', 'EVENT_TYPE'])

        placeholders = ','.join('?' * len(mdr_keys))

        # Get available columns from device table to avoid querying non-existent columns
        # Try to get table info; fall back to basic columns if that fails
        try:
            table_info = db.query("PRAGMA table_info(device)")
            device_columns = set(table_info['name'].str.upper())
        except Exception:
            device_columns = {'BRAND_NAME', 'GENERIC_NAME', 'MANUFACTURER_D_NAME'}

        # Build device column list - only include columns that exist
        desired_device_cols = [
            'BRAND_NAME', 'GENERIC_NAME', 'MANUFACTURER_D_NAME',
            'DEVICE_REPORT_PRODUCT_CODE', 'MODEL_NUMBER'
        ]
        available_device_cols = [
            f'd.{col}' for col in desired_device_cols
            if col in device_columns
        ]

        # Ensure we have at least the core columns
        if not available_device_cols:
            available_device_cols = ['d.BRAND_NAME', 'd.GENERIC_NAME', 'd.MANUFACTURER_D_NAME']

        device_cols_str = ', '.join(available_device_cols)

        sql = f"""
            SELECT m.*, {device_cols_str}
            FROM master m
            JOIN device d ON m.MDR_REPORT_KEY = d.MDR_REPORT_KEY
            WHERE m.MDR_REPORT_KEY IN ({placeholders})
        """
        return db.query(sql, params=mdr_keys)


class SelectionResults:
    """
    DataFrame-compatible container for grouped query results.

    Provides dict-like access to per-group DataFrames while offering
    convenience methods for combined analysis. Compatible with existing
    analysis_helpers.py methods.

    Usage:
        results = manager.get_results(db)

        # Access single group
        penumbra_df = results['penumbra']

        # Iterate over groups
        for group_name in results:
            print(f"{group_name}: {len(results[group_name])} records")

        # Combine all groups
        combined_df = results.to_df()

        # Quick summary
        print(results.summary)
    """

    def __init__(self, data: Dict[str, pd.DataFrame], manager: SelectionManager):
        """
        Initialize SelectionResults.

        Args:
            data: Dict mapping group names to DataFrames
            manager: The SelectionManager that created these results
        """
        self._data = data
        self._manager = manager

    def __getitem__(self, group_name: str) -> pd.DataFrame:
        """
        Access a group's DataFrame by name.

        Args:
            group_name: Name of the group

        Returns:
            DataFrame for the specified group

        Raises:
            KeyError: If group not in results
        """
        if group_name not in self._data:
            raise KeyError(f"Group '{group_name}' not in results. Available: {list(self._data.keys())}")
        return self._data[group_name]

    def __iter__(self) -> Iterator[str]:
        """Iterate over group names."""
        return iter(self._data.keys())

    def __len__(self) -> int:
        """Return number of groups."""
        return len(self._data)

    def __repr__(self) -> str:
        """String representation."""
        groups_str = ', '.join(f"{k}({len(v)})" for k, v in self._data.items())
        return f"SelectionResults({groups_str})"

    def to_df(self, include_group_column: bool = True) -> pd.DataFrame:
        """
        Combine all groups into a single DataFrame.

        Args:
            include_group_column: If True, adds 'selection_group' column

        Returns:
            Combined DataFrame with all groups
        """
        if not self._data:
            return pd.DataFrame()

        dfs = list(self._data.values())
        combined = pd.concat(dfs, ignore_index=True)

        if not include_group_column and 'selection_group' in combined.columns:
            combined = combined.drop(columns=['selection_group'])

        return combined

    @property
    def groups(self) -> List[str]:
        """List of group names in results."""
        return list(self._data.keys())

    @property
    def summary(self) -> pd.DataFrame:
        """
        Quick summary of counts per group with overlap detection.

        Returns:
            DataFrame with columns:
            - group: Group name
            - mdr_count: Total MDRs in group
            - unique_mdrs: MDRs not in any previous group
            - overlap_count: MDRs also in previous groups
        """
        data = []
        seen_mdrs: Set[int] = set()

        for group_name, df in self._data.items():
            if 'MDR_REPORT_KEY' in df.columns:
                group_mdrs = set(df['MDR_REPORT_KEY'].dropna().astype(int))
            else:
                group_mdrs = set()

            overlap = group_mdrs & seen_mdrs
            unique = group_mdrs - seen_mdrs

            data.append({
                'group': group_name,
                'mdr_count': len(df),
                'unique_mdrs': len(unique),
                'overlap_count': len(overlap)
            })

            seen_mdrs.update(group_mdrs)

        return pd.DataFrame(data)

    def filter(
        self,
        groups: Optional[List[str]] = None,
        **kwargs
    ) -> 'SelectionResults':
        """
        Filter results by groups or DataFrame conditions.

        Args:
            groups: List of group names to include. If None, includes all.
            **kwargs: Column filters applied to each group's DataFrame
                      e.g., EVENT_TYPE='D' filters to deaths

        Returns:
            New SelectionResults with filtered data
        """
        filtered_data = {}

        target_groups = groups if groups else list(self._data.keys())

        for group_name in target_groups:
            if group_name not in self._data:
                continue

            df = self._data[group_name].copy()

            # Apply column filters
            for col, val in kwargs.items():
                if col in df.columns:
                    df = df[df[col] == val]

            filtered_data[group_name] = df

        return SelectionResults(filtered_data, self._manager)
