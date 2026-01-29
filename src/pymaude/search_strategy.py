# search_strategy.py - Reproducible device search strategies
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
Reproducible device search strategies for MAUDE systematic reviews.

This module provides the DeviceSearchStrategy class for documenting,
versioning, and applying device search criteria following PRISMA 2020
and RECORD reporting guidelines.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Tuple, Union, Any
from datetime import datetime
from pathlib import Path
import yaml
import pandas as pd


@dataclass
class DeviceSearchStrategy:
    """
    Encapsulates a reproducible search strategy for a device class.

    This class enables documentation of search criteria following PRISMA 2020
    and RECORD reporting guidelines for systematic reviews of administrative data.

    The search strategy tracks:
    - Boolean search criteria (broad and narrow searches)
    - Known device name variants for documentation
    - Exclusion patterns for false positives
    - Manual inclusion/exclusion overrides
    - Version history and rationale

    Attributes:
        name: Identifier for this search strategy (e.g., "rotational_thrombectomy")
        description: Human-readable description of device category
        version: Semantic version (e.g., "1.0.0")
        author: Strategy author name
        created_at: Creation timestamp (auto-generated)
        updated_at: Last modification timestamp (auto-generated)
        broad_criteria: Boolean search (list format) for initial broad search
        narrow_criteria: Boolean search (list format) for refined search
        known_variants: Device name variants for documentation
        exclusion_patterns: Known false positive patterns
        inclusion_overrides: MDR_REPORT_KEYs to force-include
        exclusion_overrides: MDR_REPORT_KEYs to force-exclude
        search_rationale: Documentation of why these criteria were chosen

    Examples:
        # Create strategy
        strategy = DeviceSearchStrategy(
            name="rotational_thrombectomy",
            description="Rotational thrombectomy devices",
            broad_criteria=[['argon', 'cleaner'], ['thrombectomy', 'rotational']],
            narrow_criteria=[['argon', 'cleaner', 'thromb'], ['rex', 'cleaner']],
            search_rationale="Focus on Argon Cleaner devices..."
        )

        # Apply to database
        included, excluded, needs_review = strategy.apply(db)

        # Save for reproducibility
        strategy.to_yaml('strategies/my_strategy.yaml')

        # Load existing strategy
        strategy = DeviceSearchStrategy.from_yaml('strategies/my_strategy.yaml')

    Note:
        Boolean search criteria use PyMAUDE's list format:
        - OR: ['term1', 'term2']
        - AND: [['term1', 'term2']]
        - Complex: [['argon', 'cleaner'], 'angiojet']
          Equivalent to: (argon AND cleaner) OR angiojet

    References:
        PRISMA 2020: https://www.prisma-statement.org/
        RECORD: https://www.record-statement.org/
    """

    # Metadata
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Search criteria (list format matching MaudeDatabase.search_by_device_names)
    broad_criteria: Union[List, str] = field(default_factory=list)
    narrow_criteria: Union[List, str] = field(default_factory=list)

    # Known device variants (for documentation/future fuzzy matching)
    known_variants: List[Dict[str, str]] = field(default_factory=list)
    # Format: [{"device_name": "...", "generic_name": "...", "manufacturer": "...", "canonical_id": "..."}]

    # Exclusion patterns (known false positives - substring matches)
    exclusion_patterns: List[str] = field(default_factory=list)

    # Manual overrides (MDR_REPORT_KEY strings)
    inclusion_overrides: List[str] = field(default_factory=list)
    exclusion_overrides: List[str] = field(default_factory=list)

    # Documentation
    search_rationale: str = ""

    def apply(self, db, name_column: str = "DEVICE_NAME_CONCAT",
              start_date: Optional[str] = None, end_date: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Apply search strategy to a MaudeDatabase.

        Workflow (following PRISMA):
        1. Broad search → candidate reports
        2. Narrow search → refined subset
        3. Calculate difference → reports needing manual review
        4. Apply exclusion patterns → remove false positives
        5. Apply manual overrides → honor adjudication decisions

        Args:
            db: MaudeDatabase instance
            name_column: Column for substring matching (default: DEVICE_NAME_CONCAT)
            start_date: Optional start date (YYYY-MM-DD)
            end_date: Optional end date (YYYY-MM-DD)

        Returns:
            Tuple of (included, excluded, needs_review) DataFrames:
            - included: Reports definitively included (narrow + manual inclusions)
            - excluded: Reports definitively excluded (false positives + manual exclusions)
            - needs_review: Reports requiring manual adjudication (broad - narrow - excluded)

        Raises:
            ValueError: If search criteria are empty or invalid
        """
        from .database import MaudeDatabase

        # Validate database instance
        if not isinstance(db, MaudeDatabase):
            raise ValueError(f"db must be a MaudeDatabase instance, got {type(db).__name__}")

        # Validate criteria
        if not self.broad_criteria:
            raise ValueError("broad_criteria cannot be empty")
        if not self.narrow_criteria:
            raise ValueError("narrow_criteria cannot be empty")

        # Step 1: Broad search
        broad_results = db.search_by_device_names(
            self.broad_criteria,
            start_date=start_date,
            end_date=end_date,
            deduplicate_events=True
        )

        # Step 2: Narrow search
        narrow_results = db.search_by_device_names(
            self.narrow_criteria,
            start_date=start_date,
            end_date=end_date,
            deduplicate_events=True
        )

        # Step 3: Calculate difference (reports in broad but not narrow)
        narrow_keys = set(narrow_results['MDR_REPORT_KEY'].astype(str))
        needs_review = broad_results[
            ~broad_results['MDR_REPORT_KEY'].astype(str).isin(narrow_keys)
        ].copy()

        # Step 4: Apply exclusion patterns
        excluded_list = []
        if self.exclusion_patterns:
            # Check concatenated name column if available
            if name_column in needs_review.columns:
                for pattern in self.exclusion_patterns:
                    mask = needs_review[name_column].astype(str).str.contains(
                        pattern, case=False, na=False
                    )
                    excluded_list.append(needs_review[mask])
                    needs_review = needs_review[~mask]
            else:
                # Fallback: check BRAND_NAME, GENERIC_NAME, MANUFACTURER_D_NAME
                for pattern in self.exclusion_patterns:
                    mask = pd.Series([False] * len(needs_review), index=needs_review.index)

                    for col in ['BRAND_NAME', 'GENERIC_NAME', 'MANUFACTURER_D_NAME']:
                        if col in needs_review.columns:
                            mask |= needs_review[col].astype(str).str.contains(
                                pattern, case=False, na=False
                            )

                    excluded_list.append(needs_review[mask])
                    needs_review = needs_review[~mask]

        # Combine all excluded reports
        if excluded_list:
            excluded = pd.concat(excluded_list, ignore_index=True)
        else:
            excluded = pd.DataFrame(columns=broad_results.columns)

        # Step 5: Apply manual overrides
        included = narrow_results.copy()

        # Add manually included reports
        if self.inclusion_overrides:
            inclusion_keys = set(str(k) for k in self.inclusion_overrides)
            manual_includes = needs_review[
                needs_review['MDR_REPORT_KEY'].astype(str).isin(inclusion_keys)
            ]
            if len(manual_includes) > 0:
                included = pd.concat([included, manual_includes], ignore_index=True)
                needs_review = needs_review[
                    ~needs_review['MDR_REPORT_KEY'].astype(str).isin(inclusion_keys)
                ]

        # Move manually excluded reports to excluded
        if self.exclusion_overrides:
            exclusion_keys = set(str(k) for k in self.exclusion_overrides)

            # Check both needs_review and included for manual exclusions
            manual_excludes_from_review = needs_review[
                needs_review['MDR_REPORT_KEY'].astype(str).isin(exclusion_keys)
            ]
            manual_excludes_from_included = included[
                included['MDR_REPORT_KEY'].astype(str).isin(exclusion_keys)
            ]

            if len(manual_excludes_from_review) > 0:
                excluded = pd.concat([excluded, manual_excludes_from_review], ignore_index=True)
                needs_review = needs_review[
                    ~needs_review['MDR_REPORT_KEY'].astype(str).isin(exclusion_keys)
                ]

            if len(manual_excludes_from_included) > 0:
                excluded = pd.concat([excluded, manual_excludes_from_included], ignore_index=True)
                included = included[
                    ~included['MDR_REPORT_KEY'].astype(str).isin(exclusion_keys)
                ]

        return included, excluded, needs_review

    def to_yaml(self, path: Optional[Path] = None) -> str:
        """
        Export strategy to YAML format for version control.

        Args:
            path: Optional file path to write YAML. If None, returns string.

        Returns:
            YAML string representation
        """
        # Convert dataclass to dict
        data = asdict(self)

        # Convert datetime objects to ISO 8601 strings for YAML serialization
        data['created_at'] = self.created_at.isoformat()
        data['updated_at'] = self.updated_at.isoformat()

        # Generate YAML string
        yaml_str = yaml.dump(
            data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False
        )

        # Write to file if path provided
        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(yaml_str)

        return yaml_str

    @classmethod
    def from_yaml(cls, path: Path) -> "DeviceSearchStrategy":
        """
        Load strategy from YAML file.

        Args:
            path: Path to YAML file

        Returns:
            DeviceSearchStrategy instance

        Raises:
            FileNotFoundError: If YAML file doesn't exist
            ValueError: If YAML format is invalid
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Strategy file not found: {path}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            # Convert datetime strings back to datetime objects
            if 'created_at' in data and isinstance(data['created_at'], str):
                data['created_at'] = datetime.fromisoformat(data['created_at'])
            if 'updated_at' in data and isinstance(data['updated_at'], str):
                data['updated_at'] = datetime.fromisoformat(data['updated_at'])

            return cls(**data)

        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML file: {e}")
        except TypeError as e:
            raise ValueError(f"Invalid YAML format: {e}")

    def add_manual_decision(self, mdr_key: str, decision: str, reason: str = ""):
        """
        Record a manual inclusion/exclusion decision.

        Args:
            mdr_key: MDR_REPORT_KEY as string
            decision: "include" or "exclude"
            reason: Brief explanation for documentation (not stored in strategy)

        Raises:
            ValueError: If decision is not "include" or "exclude"

        Note:
            Updates inclusion_overrides or exclusion_overrides list.
            Updates updated_at timestamp.
            For detailed decision tracking, use AdjudicationLog.
        """
        if decision not in ("include", "exclude"):
            raise ValueError(f"decision must be 'include' or 'exclude', got: {decision}")

        mdr_key = str(mdr_key)

        if decision == "include":
            if mdr_key not in self.inclusion_overrides:
                self.inclusion_overrides.append(mdr_key)
            # Remove from exclusions if present
            if mdr_key in self.exclusion_overrides:
                self.exclusion_overrides.remove(mdr_key)
        else:  # exclude
            if mdr_key not in self.exclusion_overrides:
                self.exclusion_overrides.append(mdr_key)
            # Remove from inclusions if present
            if mdr_key in self.inclusion_overrides:
                self.inclusion_overrides.remove(mdr_key)

        self.updated_at = datetime.now()

    def get_prisma_counts(self, included_df: pd.DataFrame, excluded_df: pd.DataFrame,
                          needs_review_df: pd.DataFrame) -> Dict[str, int]:
        """
        Generate counts for PRISMA flow diagram reporting.

        See PRISMA 2020 Item 16a for reporting requirements.

        Args:
            included_df: DataFrame of included reports
            excluded_df: DataFrame of excluded reports
            needs_review_df: DataFrame of reports needing review

        Returns:
            Dictionary with keys:
            - broad_matches: Count from broad search
            - narrow_matches: Count from narrow search
            - needs_manual_review: Count needing adjudication
            - manual_inclusions: Count of inclusion overrides
            - manual_exclusions: Count of exclusion overrides
            - final_included: Final count after all filters
            - final_excluded: Final excluded count
            - excluded_by_patterns: Count excluded by pattern matching
        """
        # Calculate counts
        broad_matches = len(included_df) + len(excluded_df) + len(needs_review_df)
        narrow_matches = len(included_df)  # Before manual adjustments

        # Count manual overrides applied
        manual_inclusions = len(self.inclusion_overrides) if self.inclusion_overrides else 0
        manual_exclusions = len(self.exclusion_overrides) if self.exclusion_overrides else 0

        # Pattern-based exclusions (rough estimate from excluded_df)
        excluded_by_patterns = len(excluded_df) - manual_exclusions

        return {
            'broad_matches': broad_matches,
            'narrow_matches': narrow_matches - manual_exclusions,  # Narrow before manual exclusions
            'needs_manual_review': len(needs_review_df),
            'manual_inclusions': manual_inclusions,
            'manual_exclusions': manual_exclusions,
            'final_included': len(included_df),
            'final_excluded': len(excluded_df),
            'excluded_by_patterns': max(0, excluded_by_patterns)
        }
