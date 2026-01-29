#!/usr/bin/env python3
# create_project.py - Project generator for PyMAUDE analysis projects
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
Simple project generator for PyMAUDE analysis projects.

Creates standardized directory structure for systematic device analysis
following PRISMA/RECORD reporting guidelines.

Usage:
    python scripts/create_project.py <project_name> [author] [description]

Examples:
    python scripts/create_project.py thrombectomy
    python scripts/create_project.py thrombectomy "Jake"
    python scripts/create_project.py thrombectomy "Jake" "Analysis of thrombectomy devices"
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime


# Template contents for generated files
README_TEMPLATE = """# PyMAUDE Analysis: {project_name}

{description}

## Author
{author}

## Created
{date}

## Reproducibility

This project follows the [PRISMA 2020](https://www.prisma-statement.org/) and
[RECORD](https://www.record-statement.org/) reporting guidelines.

### To reproduce results:

1. Install pymaude: `pip install -e /path/to/pymaude`
2. Download MAUDE data (see notebooks for instructions)
3. Run: `python src/generate_manuscript_outputs.py`

## Project Structure

- `search_strategies/` - Search criteria (YAML format)
- `adjudication/` - Manual inclusion decisions (CSV format)
- `notebooks/` - Jupyter notebooks for exploration and analysis
- `outputs/` - Generated figures and tables
- `data/` - MAUDE data (gitignored)
- `references/` - Supporting documentation

## Search Strategy

See `search_strategies/{project_name}_v1.yaml` for device search criteria.

## Adjudication

Manual inclusion/exclusion decisions tracked in `adjudication/{project_name}_decisions.csv`.
"""

GITIGNORE_TEMPLATE = """# Data files (too large, store separately or via DVC)
data/raw/*.txt
data/raw/*.zip
data/raw/*.csv
data/interim/*.csv
*.csv.gz
*.db
*.sqlite

# Notebook outputs (can be regenerated)
notebooks/01_exploration/*.ipynb
notebooks/01_exploration/**/*.png
notebooks/01_exploration/**/*.csv
!notebooks/01_exploration/.gitkeep
!notebooks/01_exploration/README.md

# OS files
.DS_Store
__pycache__/
*.pyc
.ipynb_checkpoints/
"""

PYPROJECT_TEMPLATE = """[project]
name = "pymaude_{project_name}"
version = "0.1.0"
description = "{description}"
authors = [{author_str}]
readme = "README.md"
requires-python = ">=3.8"

dependencies = [
    "pymaude>=1.0.0",
    "pandas>=1.3.0",
    "matplotlib>=3.3.0",
    "jupyter>=1.0.0",
]
"""

SEARCH_STRATEGY_TEMPLATE = """name: {project_name}
description: {description}
version: "1.0.0"
author: {author}
created_at: "{date}"

search_rationale: |
  TODO: Document why these search terms were chosen.

  Consider:
  - Which device name variations exist?
  - What are common false positives?
  - How does this align with clinical definitions?

broad_criteria:
  - "TODO_search_term"
  # Example: [['argon', 'cleaner'], ['thrombectomy', 'rotational']]

narrow_criteria:
  - "TODO_search_term"
  # Example: [['argon', 'cleaner', 'thromb']]

known_variants: []
  # Example:
  # - device_name: "Argon Cleaner"
  #   generic_name: "Rotational Thrombectomy Catheter"
  #   manufacturer: "Rex Medical"
  #   canonical_id: "DEVICE_001"

exclusion_patterns: []
  # Example: ["ultrasonic", "dental", "insulin pump"]

inclusion_overrides: []
exclusion_overrides: []
"""

PRISMA_CHECKLIST_TEMPLATE = """# PRISMA 2020 Checklist: {project_name}

Generated: {date}

## TITLE
- [ ] Identify the report as a systematic review

## ABSTRACT
- [ ] See PRISMA 2020 for Abstracts checklist
- [ ] Structured summary (objectives, eligibility, results, conclusions)

## INTRODUCTION

### Rationale
- [ ] Describe the rationale for the review in the context of existing knowledge (Section 3)

### Objectives
- [ ] Provide an explicit statement of all objectives or research questions (Section 4)

## METHODS

### Eligibility criteria
- [ ] Specify inclusion and exclusion criteria for the review (Section 5)
- **Location**: `search_strategies/{project_name}_v1.yaml`

### Information sources
- [ ] Specify all databases, registers, websites, organisations, reference lists searched (Section 6)
- **Source**: FDA MAUDE Database
- **Date range**: [FILL IN AFTER DATA DOWNLOAD]
- **Download date**: [FILL IN AFTER DATA DOWNLOAD]
- **Last updated**: [FILL IN IF USING update() METHOD]

### Search strategy
- [ ] Present full search strategies for all databases/registers (Section 7)
- **Location**: `search_strategies/{project_name}_v1.yaml`
- [ ] Boolean criteria documented (broad_criteria, narrow_criteria)
- [ ] Exclusion patterns documented

### Selection process
- [ ] Specify methods for screening and selecting studies (Section 8)
- Manual adjudication documented in: `adjudication/{project_name}_decisions.csv`
- [ ] Number of reviewers: [FILL IN]
- [ ] Reconciliation process: [FILL IN]

### Data collection process
- [ ] Specify methods for collecting data from reports (Section 9)
- Uses `MaudeDatabase.query_device()` and enrichment methods
- [ ] Data items extracted documented in analysis notebooks

### Data items
- [ ] List and define all outcomes and other variables (Section 10a)
- [ ] Document EVENT_KEY deduplication strategy
- [ ] Document handling of multi-patient reports
- MAUDE fields used: [FILL IN - e.g., EVENT_TYPE, DATE_RECEIVED, FOI_TEXT]

### Study risk of bias assessment
- [ ] Specify methods for assessing risk of bias (Section 11)
- For MAUDE: Consider reporting biases, data quality issues
- See: `references/` directory for data quality notes

### Effect measures
- [ ] Specify effect measures used (Section 12)
- For adverse event analysis: rates, proportions, trends
- Statistical tests: [FILL IN]

### Synthesis methods
- [ ] Describe methods for synthesis (Section 13a)
- Analysis code: `src/generate_manuscript_outputs.py`
- Notebooks: `notebooks/03_analysis/`

### Reporting bias assessment
- [ ] Methods for assessing reporting biases (Section 14)

### Certainty assessment
- [ ] Methods for assessing certainty of evidence (Section 15)

## RESULTS

### Study selection
- [ ] PRISMA flow diagram showing study selection process (Section 16a)
- [ ] Cite study characteristics excluded and reasons (Section 16b)
- Use `DeviceSearchStrategy.get_prisma_counts()` for counts

### Study characteristics
- [ ] Cite characteristics of included studies (Section 17)
- Device characteristics: brand names, manufacturers, product codes
- Temporal distribution: Date range of reports

### Risk of bias in studies
- [ ] Present assessments of risk of bias (Section 18)

### Results of individual studies
- [ ] Present results of all studies (Section 19)

### Results of syntheses
- [ ] Present synthesis results (Section 20a)
- Figures: `outputs/figures/`
- Tables: `outputs/tables/`

### Reporting biases
- [ ] Present assessment of reporting biases (Section 21)

### Certainty of evidence
- [ ] Present certainty assessment results (Section 22)

## DISCUSSION

### Discussion
- [ ] Interpret results in context of other evidence (Section 23a)
- [ ] Discuss limitations (Section 23b)
- MAUDE-specific limitations:
  - [ ] Voluntary reporting system
  - [ ] Data quality issues (~90% device info, ~25% outcomes)
  - [ ] Multiple reports per event (~8% EVENT_KEY duplication)

## OTHER INFORMATION

### Registration and protocol
- [ ] Registration information and protocol location (Section 24a)

### Support
- [ ] Funding sources and support (Section 25)

### Competing interests
- [ ] Competing interests declaration (Section 26)

### Availability of data, code, and materials
- [ ] Statement on availability (Section 27)
- Code repository: [FILL IN]
- Data source: FDA MAUDE (public)
- Analysis code: `src/generate_manuscript_outputs.py`

---

## RECORD Extension (for routinely collected health data)

### Data source
- [ ] Data source(s) described (RECORD 1.1)
- FDA MAUDE: Manufacturer and User Facility Device Experience database

### Code lists
- [ ] Code lists provided or accessibility described (RECORD 1.2, 1.3)
- Device search criteria: `search_strategies/{project_name}_v1.yaml`
- Problem codes: FDA MAUDE problem code dictionary

### Data cleaning
- [ ] Data cleaning methods described (RECORD 1.4)
- See: `notebooks/02_search_development/`
- Documented in: `adjudication/{project_name}_decisions.csv`

### Linkage methods
- [ ] Linkage methods described if multiple data sources (RECORD 1.5)
- MAUDE linkage: MDR_REPORT_KEY joins master/device/patient/text tables

---

## Notes

This checklist should be completed before manuscript submission.
Update bracketed [FILL IN] sections as analysis progresses.

For full PRISMA 2020 guidance, see: http://www.prisma-statement.org/
For RECORD guidance, see: https://www.record-statement.org/
"""

GENERATE_OUTPUTS_TEMPLATE = '''#!/usr/bin/env python3
"""
Generate all manuscript outputs from MAUDE data.

This script reproduces all figures and tables for the manuscript.
Run this script to ensure results are up-to-date before publication.

Usage:
    python src/generate_manuscript_outputs.py

Author: {author}
Date: {date}
"""

from pathlib import Path
import sys

# Add pymaude to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymaude import MaudeDatabase
from pymaude.search_strategy import DeviceSearchStrategy
from pymaude.adjudication import AdjudicationLog


def main():
    """Main pipeline for generating manuscript outputs."""

    # Configuration
    db_path = "data/processed/maude.db"
    strategy_path = "search_strategies/{project_name}_v1.yaml"
    adjudication_path = "adjudication/{project_name}_decisions.csv"

    print("=" * 60)
    print("PyMAUDE Analysis: {project_name}")
    print("=" * 60)

    # TODO: Implement analysis pipeline
    # 1. Load database
    # 2. Load search strategy
    # 3. Apply search strategy
    # 4. Load adjudication decisions
    # 5. Generate figures
    # 6. Generate tables
    # 7. Save outputs to outputs/

    print("\\nTODO: Implement analysis pipeline")
    print("See notebooks/03_analysis/ for prototype code")


if __name__ == "__main__":
    main()
'''

NOTEBOOK_README_TEMPLATE = """# {folder_name}

{description}

## TODO: Add Starter Notebook Code

Future implementation will add template notebooks with:
- Database connection code
- Search strategy loading
- Common analysis patterns
- Visualization examples

For now, create notebooks manually following examples in PyMAUDE documentation.
"""


def create_project(project_name: str, author: str = "", description: str = ""):
    """Generate a new PyMAUDE analysis project."""

    # Validate project name (basic sanitation)
    if not project_name.replace('_', '').isalnum():
        print(f"Error: project_name must be alphanumeric (underscores allowed)")
        sys.exit(1)

    # Determine base directory (relative to current location)
    base_dir = Path("./studies")
    base_dir.mkdir(parents=True, exist_ok=True)

    project_dir = base_dir / f"pymaude_{project_name}"

    if project_dir.exists():
        print(f"Error: {project_dir} already exists")
        sys.exit(1)

    print(f"Creating PyMAUDE project: {project_name}")
    print(f"Location: {project_dir}")
    print()

    # Create directory structure
    dirs = [
        "data/raw",
        "data/interim",
        "data/processed",
        "search_strategies",
        "adjudication",
        "notebooks/01_exploration",
        "notebooks/02_search_development",
        "notebooks/03_analysis",
        "src",
        "outputs/figures",
        "outputs/tables",
        "references",
    ]

    for d in dirs:
        dir_path = project_dir / d
        dir_path.mkdir(parents=True, exist_ok=True)
        (dir_path / ".gitkeep").touch()
        print(f"  Created: {d}/")

    # Generate template files
    date = datetime.now().strftime("%Y-%m-%d")
    author_str = f'{{name = "{author}", email = ""}}' if author else ''

    templates = {
        "README.md": README_TEMPLATE,
        ".gitignore": GITIGNORE_TEMPLATE,
        "pyproject.toml": PYPROJECT_TEMPLATE,
        f"search_strategies/{project_name}_v1.yaml": SEARCH_STRATEGY_TEMPLATE,
        "PRISMA_checklist.md": PRISMA_CHECKLIST_TEMPLATE,
        "src/generate_manuscript_outputs.py": GENERATE_OUTPUTS_TEMPLATE,
    }

    for filename, template in templates.items():
        file_path = project_dir / filename
        content = template.format(
            project_name=project_name,
            author=author,
            description=description,
            date=date,
            author_str=author_str,
        )
        file_path.write_text(content)
        print(f"  Created: {filename}")

    # Create notebook README files
    notebook_readmes = {
        "notebooks/01_exploration/README.md": ("Exploratory Analysis",
            "Messy exploration and initial data inspection. Outputs gitignored."),
        "notebooks/02_search_development/README.md": ("Search Development",
            "Develop and refine device search criteria."),
        "notebooks/03_analysis/README.md": ("Final Analysis",
            "Clean analysis notebooks for manuscript figures/tables."),
    }

    for path, (folder_name, desc) in notebook_readmes.items():
        readme_path = project_dir / path
        content = NOTEBOOK_README_TEMPLATE.format(folder_name=folder_name, description=desc)
        readme_path.write_text(content)
        print(f"  Created: {path}")

    # Create empty adjudication CSV with header
    adj_csv = project_dir / "adjudication" / f"{project_name}_decisions.csv"
    adj_csv.write_text("mdr_report_key,decision,reason,reviewer,date,strategy_version,device_info\n")
    print(f"  Created: adjudication/{project_name}_decisions.csv")

    # Initialize git repository
    print("\n  Initializing git repository...")
    result = subprocess.run(
        ["git", "init"],
        cwd=project_dir,
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("  ✓ Git repository initialized")
    else:
        print(f"  ⚠ Git init failed: {result.stderr}")

    # Print next steps
    print("\n" + "=" * 60)
    print("Project created successfully!")
    print("=" * 60)
    print(f"\nNext steps:")
    print(f"  1. cd {project_dir}")
    print(f"  2. Edit search_strategies/{project_name}_v1.yaml")
    print(f"  3. Create initial git commit:")
    print(f"     git add .")
    print(f'     git commit -m "Initial project structure"')
    print(f"  4. Start exploring in notebooks/01_exploration/")
    print(f"  5. Review PRISMA_checklist.md for reporting requirements")


def main():
    """Entry point for create_project script."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/create_project.py <project_name> [author] [description]")
        print("\nExamples:")
        print("  python scripts/create_project.py thrombectomy")
        print('  python scripts/create_project.py thrombectomy "Jake"')
        print('  python scripts/create_project.py thrombectomy "Jake" "Thrombectomy device analysis"')
        sys.exit(1)

    name = sys.argv[1]
    author = sys.argv[2] if len(sys.argv) > 2 else ""
    desc = sys.argv[3] if len(sys.argv) > 3 else f"PyMAUDE analysis of {name} devices"

    create_project(name, author, desc)


if __name__ == "__main__":
    main()
