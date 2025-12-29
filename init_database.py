#!/usr/bin/env python3
"""
MAUDE Database Initializer

This script helps researchers download and initialize a MAUDE SQLite database
for use in external SQLite tools (DB Browser, DBeaver, SQLiteStudio, etc.).

Usage:
    # Interactive mode (prompts for input)
    python init_database.py

    # Non-interactive mode (command-line arguments)
    python init_database.py --years 2015-2024 --tables device,text --output maude.db

Copyright (C) 2024 Jacob Schwartz, University of Michigan Medical School
Licensed under GPL v3
"""

import argparse
import os
import sys
from maude_db import MaudeDatabase


def estimate_download_size(years, tables):
    """
    Estimate download size based on years and tables.

    Args:
        years: List of years or year range
        tables: List of table names

    Returns:
        String with estimated size
    """
    # Rough estimates (MB per year)
    size_per_year = {
        'device': 45,
        'text': 45,
        'patient': 10,
        'master': 50  # Note: master is typically not year-specific
    }

    # Parse years to get count
    if isinstance(years, str):
        if '-' in years:
            start, end = years.split('-')
            year_count = int(end) - int(start) + 1
        elif years == 'all':
            year_count = 30  # Approximate
        elif years == 'latest':
            year_count = 1
        else:
            year_count = 1
    elif isinstance(years, list):
        year_count = len(years)
    else:
        year_count = 1

    total_mb = sum(size_per_year.get(table, 40) * year_count for table in tables)

    if total_mb < 1024:
        return f"~{total_mb} MB"
    else:
        return f"~{total_mb / 1024:.1f} GB"


def parse_table_selection(selection):
    """
    Parse user's table selection input.

    Args:
        selection: String like "1,2", "all", or "1"

    Returns:
        List of table names
    """
    available_tables = {
        '1': 'device',
        '2': 'text',
        '3': 'patient'
    }

    selection = selection.strip().lower()

    if selection == 'all':
        return ['device', 'text', 'patient']

    selected_tables = []
    for num in selection.split(','):
        num = num.strip()
        if num in available_tables:
            selected_tables.append(available_tables[num])

    # Always include device table if not already included
    if 'device' not in selected_tables:
        selected_tables.insert(0, 'device')

    return selected_tables


def interactive_mode():
    """
    Run in interactive mode with prompts.

    Returns:
        Tuple of (years, tables, output_path)
    """
    print("=" * 60)
    print("MAUDE Database Initializer".center(60))
    print("=" * 60)
    print()

    # Get year range
    print("Enter the year range to download:")
    print("  Examples:")
    print("    Single year: 2024")
    print("    Range: 2015-2024")
    print("    List: 2020,2021,2022")
    print("    Special: 'latest' (most recent year) or 'all' (all available)")
    print()

    while True:
        years = input("Year range: ").strip()
        if years:
            break
        print("  Error: Year range is required.")

    print()

    # Get table selection
    print("Select tables to download:")
    print("  1. device (device information - recommended, always included)")
    print("  2. text (event narratives)")
    print("  3. patient (patient demographics)")
    print()
    print("  Enter numbers (comma-separated, e.g., '1,2') or 'all':")

    while True:
        selection = input("Tables: ").strip()
        if selection:
            tables = parse_table_selection(selection)
            break
        print("  Error: Table selection is required.")

    print()

    # Get database filename
    default_db = 'maude.db'
    output = input(f"Database filename [{default_db}]: ").strip()
    if not output:
        output = default_db

    # Add .db extension if not present
    if not output.endswith('.db'):
        output += '.db'

    print()
    print("=" * 60)
    print("Configuration Summary".center(60))
    print("=" * 60)
    print(f"  Years: {years}")
    print(f"  Tables: {', '.join(tables)}")
    print(f"  Output: {output}")
    print(f"  Estimated download: {estimate_download_size(years, tables)}")
    print()

    # Confirm
    proceed = input("Proceed? [Y/n]: ").strip().lower()
    if proceed and proceed not in ['y', 'yes', '']:
        print("\nCancelled.")
        sys.exit(0)

    return years, tables, output


def download_and_initialize(years, tables, output_path, verbose=True):
    """
    Download data and initialize database.

    Args:
        years: Year range (string, int, or list)
        tables: List of table names
        output_path: Path to output database file
        verbose: Whether to print progress
    """
    print()
    print("=" * 60)
    print("Downloading and Initializing Database".center(60))
    print("=" * 60)
    print()

    # Check if database already exists
    if os.path.exists(output_path):
        print(f"Warning: {output_path} already exists.")
        overwrite = input("Overwrite? [y/N]: ").strip().lower()
        if overwrite not in ['y', 'yes']:
            print("\nCancelled. Please specify a different filename.")
            sys.exit(0)
        os.remove(output_path)

    # Create database and download
    db = MaudeDatabase(output_path, verbose=verbose)

    try:
        db.add_years(
            years=years,
            tables=tables,
            download=True,
            data_dir='./maude_data',
            strict=False
        )

        print()
        print("=" * 60)
        print("Success!".center(60))
        print("=" * 60)
        print()

        # Show database info
        db.info()

        print()
        print("=" * 60)
        print("Next Steps".center(60))
        print("=" * 60)
        print()
        print(f"1. Open {output_path} in a SQLite tool:")
        print("   - DB Browser for SQLite (free): https://sqlitebrowser.org/")
        print("   - DBeaver: https://dbeaver.io/")
        print("   - DataGrip, SQLiteStudio, or any SQLite client")
        print()
        print("2. Read the SQLite usage guide:")
        print("   docs/sqlite_guide.md")
        print()
        print("3. Try example queries:")
        print("   examples/example_queries.sql")
        print()
        print("4. Or use the Python API (see docs/getting_started.md)")
        print()

    except Exception as e:
        print(f"\nError during download: {e}")
        print("\nTroubleshooting:")
        print("  - Check your internet connection")
        print("  - Verify the year range is valid")
        print("  - See docs/troubleshooting.md for more help")
        sys.exit(1)
    finally:
        db.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Initialize a MAUDE database for SQLite tool usage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (default)
  python init_database.py

  # Non-interactive mode
  python init_database.py --years 2015-2024 --tables device,text --output maude.db

  # Download all tables for recent years
  python init_database.py --years 2020-2024 --tables all --output research.db

  # Download just device table for one year
  python init_database.py --years 2024 --tables device --output test.db
        """
    )

    parser.add_argument(
        '-y', '--years',
        type=str,
        help='Year range (e.g., 2024, 2015-2024, latest, all)'
    )

    parser.add_argument(
        '-t', '--tables',
        type=str,
        help='Comma-separated table list (device,text,patient) or "all"'
    )

    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output database filename (default: maude.db)'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress progress messages'
    )

    args = parser.parse_args()

    # Determine mode
    if args.years and args.tables:
        # Non-interactive mode
        years = args.years

        # Parse tables
        if args.tables.lower() == 'all':
            tables = ['device', 'text', 'patient']
        else:
            tables = [t.strip() for t in args.tables.split(',')]
            # Ensure device is included
            if 'device' not in tables:
                tables.insert(0, 'device')

        output = args.output if args.output else 'maude.db'
        if not output.endswith('.db'):
            output += '.db'

        verbose = not args.quiet

    else:
        # Interactive mode
        if args.years or args.tables or args.output:
            print("Error: For non-interactive mode, provide both --years and --tables")
            print("Run 'python init_database.py --help' for usage.")
            sys.exit(1)

        years, tables, output = interactive_mode()
        verbose = True

    # Download and initialize
    download_and_initialize(years, tables, output, verbose=verbose)


if __name__ == '__main__':
    main()
