# search_strategy.py - Reproducible device search strategies for MAUDE
# Copyright (C) 2026 Jacob Schwartz <jaschwa@umich.edu>
# GNU GPL v3

"""
DeviceSearchStrategy: document, version, and apply PRISMA-compliant search criteria.

Implements the broad→narrow search workflow described in PRISMA 2020 / RECORD
guidelines for systematic reviews of administrative data. Strategies are
serializable to YAML for version control and reproducibility.

Usage:
    strategy = DeviceSearchStrategy(
        name='rotational_thrombectomy',
        description='Rotational thrombectomy devices',
        broad_criteria=[['argon', 'cleaner'], 'thrombectomy'],
        narrow_criteria=[['argon', 'cleaner']],
        search_rationale='Focus on Argon Cleaner; broad search adds generic thrombectomy terms',
    )
    included, excluded, needs_review = strategy.apply(db)
    strategy.to_yaml('strategies/rotational_thrombectomy_v1.yaml')
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd
import yaml


@dataclass
class DeviceSearchStrategy:
    """
    Encapsulates a reproducible PRISMA-compliant search strategy.

    Workflow (apply()):
        1. Broad search  → candidate reports
        2. Narrow search → refined subset
        3. Difference    → needs_review (in broad, not in narrow)
        4. Exclusion patterns applied to needs_review
        5. Manual inclusion/exclusion overrides applied

    Criteria formats (for broad_criteria and narrow_criteria):
        'term'                  → substring match on any name field
        ['a', 'b']              → 'a' OR 'b'
        [['a', 'b'], 'c']       → (a AND b) OR c
        {'g1': [...], 'g2': ...} → grouped; result includes search_group column.
                                   Both broad and narrow must use matching group keys.

    Attributes:
        name:               Short identifier (e.g., 'rotational_thrombectomy').
        description:        Human-readable description of device category.
        version:            Semantic version string.
        author:             Strategy author name.
        created_at:         Creation timestamp (auto-set).
        updated_at:         Last modification timestamp (auto-set).
        broad_criteria:     Initial wide search to maximize recall.
        narrow_criteria:    Refined search for high-precision subset.
        known_variants:     Device name variants for documentation.
        exclusion_patterns: Substrings to auto-exclude from needs_review.
        inclusion_overrides: MDR_REPORT_KEYs to force-include.
        exclusion_overrides: MDR_REPORT_KEYs to force-exclude.
        search_rationale:   Narrative justification for the search design.
    """

    name: str
    description: str
    version: str = '1.0.0'
    author: str = ''
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    broad_criteria: Union[List, str, Dict] = field(default_factory=list)
    narrow_criteria: Union[List, str, Dict] = field(default_factory=list)

    # Known device name variants — for documentation / manual review support.
    # Format: [{'brand_name': '...', 'generic_name': '...', 'manufacturer': '...'}]
    known_variants: List[Dict[str, str]] = field(default_factory=list)

    exclusion_patterns: List[str] = field(default_factory=list)
    inclusion_overrides: List[str] = field(default_factory=list)
    exclusion_overrides: List[str] = field(default_factory=list)
    search_rationale: str = ''

    def apply(self, db, start_date=None, end_date=None):
        """
        Apply this strategy to a MaudeDatabase following the PRISMA workflow.

        Args:
            db:         MaudeDatabase instance.
            start_date: Optional date filter (YYYY-MM-DD).
            end_date:   Optional date filter (YYYY-MM-DD).

        Returns:
            Tuple of (included, excluded, needs_review) DataFrames.
            - included:      Definitively included (narrow + manual inclusions).
            - excluded:      Definitively excluded (patterns + manual exclusions).
            - needs_review:  In broad but not narrow; requires manual adjudication.

            When using dict criteria, all DataFrames include a 'search_group' column.
        """
        if not self.broad_criteria:
            raise ValueError("broad_criteria cannot be empty")
        if not self.narrow_criteria:
            raise ValueError("narrow_criteria cannot be empty")

        # Validate that broad and narrow use the same format (both dict or both non-dict).
        if isinstance(self.broad_criteria, dict) != isinstance(self.narrow_criteria, dict):
            raise ValueError(
                "broad_criteria and narrow_criteria must both be dict (grouped) "
                "or both be list/string (standard)."
            )
        if isinstance(self.broad_criteria, dict):
            broad_keys = set(self.broad_criteria)
            narrow_keys = set(self.narrow_criteria)
            if broad_keys != narrow_keys:
                raise ValueError(
                    f"Grouped criteria must have matching keys. "
                    f"broad has {sorted(broad_keys)}, narrow has {sorted(narrow_keys)}"
                )

        broad = db.search_by_device_names(self.broad_criteria, start_date, end_date)
        narrow = db.search_by_device_names(self.narrow_criteria, start_date, end_date)

        narrow_keys = set(narrow['MDR_REPORT_KEY'].astype(str))
        needs_review = broad[
            ~broad['MDR_REPORT_KEY'].astype(str).isin(narrow_keys)
        ].copy()

        # Apply exclusion patterns to needs_review.
        excluded_frames = []
        name_col = 'DEVICE_NAME_CONCAT' if 'DEVICE_NAME_CONCAT' in needs_review.columns else None

        for pattern in self.exclusion_patterns:
            if name_col:
                mask = (needs_review[name_col]
                        .astype(str)
                        .str.contains(pattern, case=False, na=False))
            else:
                mask = pd.Series(False, index=needs_review.index)
                for col in ['BRAND_NAME', 'GENERIC_NAME', 'MANUFACTURER_D_NAME']:
                    if col in needs_review.columns:
                        mask |= (needs_review[col]
                                 .astype(str)
                                 .str.contains(pattern, case=False, na=False))
            excluded_frames.append(needs_review[mask])
            needs_review = needs_review[~mask]

        excluded = (
            pd.concat(excluded_frames, ignore_index=True)
            if excluded_frames
            else pd.DataFrame(columns=broad.columns)
        )
        included = narrow.copy()

        # Manual inclusion overrides: pull matching rows out of needs_review → included.
        if self.inclusion_overrides:
            keys = set(str(k) for k in self.inclusion_overrides)
            to_include = needs_review[needs_review['MDR_REPORT_KEY'].astype(str).isin(keys)]
            if len(to_include):
                included = pd.concat([included, to_include], ignore_index=True)
                needs_review = needs_review[
                    ~needs_review['MDR_REPORT_KEY'].astype(str).isin(keys)
                ]

        # Manual exclusion overrides: pull matching rows from needs_review + included → excluded.
        if self.exclusion_overrides:
            keys = set(str(k) for k in self.exclusion_overrides)
            exc_from_review = needs_review[needs_review['MDR_REPORT_KEY'].astype(str).isin(keys)]
            exc_from_included = included[included['MDR_REPORT_KEY'].astype(str).isin(keys)]
            excluded = pd.concat([excluded, exc_from_review, exc_from_included], ignore_index=True)
            needs_review = needs_review[~needs_review['MDR_REPORT_KEY'].astype(str).isin(keys)]
            included = included[~included['MDR_REPORT_KEY'].astype(str).isin(keys)]

        return included, excluded, needs_review

    def get_prisma_counts(self, included, excluded, needs_review):
        """
        Summarize counts for PRISMA flow diagram reporting.

        Args:
            included:     DataFrame of included reports (from apply()).
            excluded:     DataFrame of excluded reports (from apply()).
            needs_review: DataFrame needing manual adjudication (from apply()).

        Returns:
            Dict with keys: broad_total, needs_manual_review, excluded_total, final_included.
        """
        return {
            'broad_total': len(included) + len(excluded) + len(needs_review),
            'needs_manual_review': len(needs_review),
            'excluded_total': len(excluded),
            'final_included': len(included),
        }

    def to_yaml(self, path=None):
        """
        Serialize strategy to YAML for version control.

        Args:
            path: Optional file path. If None, returns YAML string.

        Returns:
            YAML string (and writes file if path provided).
        """
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        data['updated_at'] = self.updated_at.isoformat()
        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True,
                             sort_keys=False)
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(yaml_str, encoding='utf-8')
        return yaml_str

    @classmethod
    def from_yaml(cls, path):
        """
        Load a strategy from a YAML file.

        Args:
            path: Path to YAML file.

        Returns:
            DeviceSearchStrategy instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the YAML is malformed.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Strategy file not found: {path}")
        try:
            data = yaml.safe_load(p.read_text(encoding='utf-8'))
            for ts_field in ('created_at', 'updated_at'):
                if ts_field in data and isinstance(data[ts_field], str):
                    data[ts_field] = datetime.fromisoformat(data[ts_field])
            return cls(**data)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML: {e}") from e
        except TypeError as e:
            raise ValueError(f"Invalid YAML structure: {e}") from e
