# adjudication.py - Manual adjudication tracking for systematic reviews
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
Manual adjudication tracking for MAUDE systematic reviews.

This module provides CSV-based tracking of inclusion/exclusion decisions
during systematic device review, supporting PRISMA 2020 and RECORD reporting.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Set, Tuple
import pandas as pd
import csv


@dataclass
class AdjudicationRecord:
    """
    Single adjudication decision record.

    Tracks manual inclusion/exclusion decisions for MAUDE reports
    during systematic review following PRISMA/RECORD guidelines.

    Attributes:
        mdr_report_key: FDA MAUDE report identifier
        decision: "include" or "exclude"
        reason: Brief explanation for decision
        reviewer: Name/ID of person making decision
        date: Timestamp of decision
        strategy_version: Version of DeviceSearchStrategy used
        device_info: Optional device details for reference
    """
    mdr_report_key: str
    decision: str  # "include" or "exclude"
    reason: str
    reviewer: str
    date: datetime = field(default_factory=datetime.now)
    strategy_version: str = ""
    device_info: str = ""  # Optional: brand/generic name for context


class AdjudicationLog:
    """
    Manages manual adjudication decisions for systematic device review.

    Provides CSV-based storage for tracking inclusion/exclusion decisions
    during MAUDE data curation. Supports PRISMA reporting requirements.

    Attributes:
        path: Path to CSV file storing decisions
        records: List of AdjudicationRecord objects

    Examples:
        # Create new log
        log = AdjudicationLog('adjudication/my_devices.csv')

        # Add decisions
        log.add('1234567', 'include', 'Matches device criteria', 'Jake')
        log.add('7654321', 'exclude', 'Ultrasonic cleaner (false positive)', 'Jake')

        # Save to CSV
        log.to_csv()

        # Load existing log
        log = AdjudicationLog.from_csv('adjudication/my_devices.csv')

        # Get decisions
        include_keys = log.get_inclusion_keys()  # Set of MDR_REPORT_KEYs
        exclude_keys = log.get_exclusion_keys()  # Set of MDR_REPORT_KEYs

    Note:
        CSV format for git-friendly diffs and Excel compatibility.
        Columns: mdr_report_key, decision, reason, reviewer, date, strategy_version, device_info

    References:
        PRISMA 2020: Selection process documentation (Item 16b)
        RECORD: Transparent code list development (Item 1.2, 1.3)
    """

    def __init__(self, path: Path):
        """
        Initialize adjudication log.

        Args:
            path: Path to CSV file (created if doesn't exist)
        """
        self.path = Path(path)
        self.records: List[AdjudicationRecord] = []

        # Load existing records if file exists
        if self.path.exists():
            self._load_from_csv()

    def add(self, mdr_key: str, decision: str, reason: str, reviewer: str,
            strategy_version: str = "", device_info: str = "") -> None:
        """
        Add adjudication decision.

        Args:
            mdr_key: MDR_REPORT_KEY
            decision: "include" or "exclude"
            reason: Explanation for decision
            reviewer: Name/ID of reviewer
            strategy_version: Optional version of search strategy
            device_info: Optional device name/info for context

        Raises:
            ValueError: If decision is not "include" or "exclude"
        """
        if decision not in ("include", "exclude"):
            raise ValueError(f"decision must be 'include' or 'exclude', got: {decision}")

        record = AdjudicationRecord(
            mdr_report_key=str(mdr_key),
            decision=decision,
            reason=reason,
            reviewer=reviewer,
            date=datetime.now(),
            strategy_version=strategy_version,
            device_info=device_info
        )
        self.records.append(record)

    def to_csv(self) -> None:
        """
        Save all records to CSV file.

        Creates parent directories if they don't exist.
        """
        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Write CSV with header
        with open(self.path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'mdr_report_key', 'decision', 'reason', 'reviewer',
                'date', 'strategy_version', 'device_info'
            ])

            for record in self.records:
                writer.writerow([
                    record.mdr_report_key,
                    record.decision,
                    record.reason,
                    record.reviewer,
                    record.date.isoformat(),
                    record.strategy_version,
                    record.device_info
                ])

    @classmethod
    def from_csv(cls, path: Path) -> "AdjudicationLog":
        """
        Load adjudication log from CSV.

        Args:
            path: Path to CSV file

        Returns:
            AdjudicationLog instance with loaded records

        Raises:
            FileNotFoundError: If CSV doesn't exist
        """
        if not Path(path).exists():
            raise FileNotFoundError(f"Adjudication log not found: {path}")

        log = cls(path)
        return log

    def _load_from_csv(self) -> None:
        """
        Internal: Load records from CSV file.

        Parses CSV and populates self.records list.
        """
        self.records = []

        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Parse date string back to datetime
                    try:
                        date = datetime.fromisoformat(row['date'])
                    except (ValueError, KeyError):
                        # Fallback for malformed dates
                        date = datetime.now()

                    record = AdjudicationRecord(
                        mdr_report_key=row.get('mdr_report_key', ''),
                        decision=row.get('decision', ''),
                        reason=row.get('reason', ''),
                        reviewer=row.get('reviewer', ''),
                        date=date,
                        strategy_version=row.get('strategy_version', ''),
                        device_info=row.get('device_info', '')
                    )
                    self.records.append(record)
        except (csv.Error, KeyError) as e:
            raise ValueError(f"Failed to parse adjudication CSV: {e}")

    def get_inclusion_keys(self) -> Set[str]:
        """
        Get set of MDR_REPORT_KEYs marked for inclusion.

        Returns:
            Set of report keys (as strings)
        """
        return {record.mdr_report_key for record in self.records
                if record.decision == 'include'}

    def get_exclusion_keys(self) -> Set[str]:
        """
        Get set of MDR_REPORT_KEYs marked for exclusion.

        Returns:
            Set of report keys (as strings)
        """
        return {record.mdr_report_key for record in self.records
                if record.decision == 'exclude'}

    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert log to DataFrame for analysis.

        Returns:
            DataFrame with columns matching AdjudicationRecord fields
        """
        if not self.records:
            # Return empty DataFrame with correct columns
            return pd.DataFrame(columns=[
                'mdr_report_key', 'decision', 'reason', 'reviewer',
                'date', 'strategy_version', 'device_info'
            ])

        data = []
        for record in self.records:
            data.append({
                'mdr_report_key': record.mdr_report_key,
                'decision': record.decision,
                'reason': record.reason,
                'reviewer': record.reviewer,
                'date': record.date,
                'strategy_version': record.strategy_version,
                'device_info': record.device_info
            })

        return pd.DataFrame(data)

    def get_statistics(self) -> dict:
        """
        Get summary statistics for PRISMA reporting.

        Returns:
            Dictionary with:
            - total_decisions: Total records
            - inclusions: Count of includes
            - exclusions: Count of excludes
            - reviewers: List of unique reviewer names
            - date_range: Tuple of (earliest, latest) decision dates
        """
        if not self.records:
            return {
                'total_decisions': 0,
                'inclusions': 0,
                'exclusions': 0,
                'reviewers': [],
                'date_range': (None, None)
            }

        inclusions = sum(1 for r in self.records if r.decision == 'include')
        exclusions = sum(1 for r in self.records if r.decision == 'exclude')
        reviewers = sorted(set(r.reviewer for r in self.records))

        dates = [r.date for r in self.records]
        date_range = (min(dates), max(dates))

        return {
            'total_decisions': len(self.records),
            'inclusions': inclusions,
            'exclusions': exclusions,
            'reviewers': reviewers,
            'date_range': date_range
        }
