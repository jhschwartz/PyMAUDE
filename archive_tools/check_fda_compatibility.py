#!/usr/bin/env python3
# check_fda_compatibility.py - Verify FDA MAUDE site compatibility
# Copyright (C) 2024 Jacob Schwartz, University of Michigan Medical School
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
Check if the FDA MAUDE website structure is compatible with PyMAUDE library.

This script verifies that:
1. FDA base URL is accessible
2. Expected file patterns are still valid
3. Files can be downloaded and parsed
4. Data structure matches expectations

Exits with code 0 if compatible, 1 if incompatible.

Usage:
    python check_fda_compatibility.py              # Full check with test download
    python check_fda_compatibility.py --quick      # Quick check (HEAD requests only)
    python check_fda_compatibility.py --json       # Output JSON for GitHub Actions
"""

import argparse
import sys
import json
import requests
import zipfile
import io
import pandas as pd
from datetime import datetime
from pathlib import Path

# Add parent directory to path to import pymaude
sys.path.insert(0, str(Path(__file__).parent.parent))
from pymaude import MaudeDatabase


class CompatibilityChecker:
    """Check FDA MAUDE site compatibility with PyMAUDE library."""

    def __init__(self, verbose=True, quick=False):
        self.verbose = verbose
        self.quick = quick
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'compatible': True,
            'checks': {},
            'warnings': [],
            'errors': []
        }
        self.db = MaudeDatabase(':memory:', verbose=False)

    def log(self, message, level='INFO'):
        """Log message if verbose mode enabled."""
        if self.verbose:
            prefix = {
                'INFO': '  ',
                'SUCCESS': '  ✓',
                'WARNING': '  ⚠',
                'ERROR': '  ✗'
            }.get(level, '  ')
            print(f"{prefix} {message}")

    def check_base_url(self):
        """Verify FDA base URL is accessible."""
        check_name = 'base_url_accessible'
        self.log("Checking FDA base URL accessibility...")

        try:
            url = self.db.base_url
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.head(url, headers=headers, timeout=10, allow_redirects=False)

            if response.status_code in [200, 301, 302]:
                self.log(f"Base URL accessible: {url}", 'SUCCESS')
                self.results['checks'][check_name] = {
                    'status': 'pass',
                    'url': url,
                    'status_code': response.status_code
                }
                return True
            else:
                self.log(f"Base URL returned status {response.status_code}", 'ERROR')
                self.results['errors'].append(f"Base URL status: {response.status_code}")
                self.results['checks'][check_name] = {
                    'status': 'fail',
                    'url': url,
                    'status_code': response.status_code
                }
                return False

        except Exception as e:
            self.log(f"Cannot access base URL: {e}", 'ERROR')
            self.results['errors'].append(f"Base URL error: {str(e)}")
            self.results['checks'][check_name] = {
                'status': 'fail',
                'error': str(e)
            }
            return False

    def check_file_patterns(self):
        """Verify expected file naming patterns still work."""
        check_name = 'file_patterns_valid'
        self.log("Checking file naming patterns...")

        test_cases = [
            # (year, table, expected_filename)
            (2023, 'master', 'mdrfoithru2023.zip'),
            (2023, 'device', 'device2023.zip'),
            (2023, 'text', 'foitext2023.zip'),
            (2000, 'device', 'device2000.zip'),  # First year with new schema
        ]

        all_passed = True
        pattern_results = []

        for year, table, expected_filename in test_cases:
            url, filename = self.db._construct_file_url(table, year)

            if filename == expected_filename:
                self.log(f"{table} {year}: {filename}", 'SUCCESS')
                pattern_results.append({
                    'year': year,
                    'table': table,
                    'expected': expected_filename,
                    'actual': filename,
                    'status': 'pass'
                })
            else:
                self.log(f"{table} {year}: Expected {expected_filename}, got {filename}", 'WARNING')
                self.results['warnings'].append(
                    f"Pattern mismatch for {table} {year}: expected {expected_filename}, got {filename}"
                )
                pattern_results.append({
                    'year': year,
                    'table': table,
                    'expected': expected_filename,
                    'actual': filename,
                    'status': 'warning'
                })
                all_passed = False

        self.results['checks'][check_name] = {
            'status': 'pass' if all_passed else 'warning',
            'tests': pattern_results
        }

        return all_passed

    def check_file_availability(self):
        """Check if expected files are available on FDA server."""
        check_name = 'files_available'
        self.log("Checking file availability...")

        # Test with a known historical year and current year - 1
        current_year = datetime.now().year
        test_years = [2023, current_year - 1]
        test_tables = ['master', 'device']

        availability_results = []
        all_available = True

        for year in test_years:
            for table in test_tables:
                url, filename = self.db._construct_file_url(table, year)

                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    response = requests.head(url, headers=headers, timeout=10, allow_redirects=False)
                    available = response.status_code == 200

                    if available:
                        self.log(f"{filename}: Available", 'SUCCESS')
                        availability_results.append({
                            'year': year,
                            'table': table,
                            'filename': filename,
                            'status': 'available',
                            'status_code': response.status_code
                        })
                    else:
                        self.log(f"{filename}: Not found (HTTP {response.status_code})", 'WARNING')
                        self.results['warnings'].append(
                            f"{filename} not available (HTTP {response.status_code})"
                        )
                        availability_results.append({
                            'year': year,
                            'table': table,
                            'filename': filename,
                            'status': 'unavailable',
                            'status_code': response.status_code
                        })
                        all_available = False

                except Exception as e:
                    self.log(f"{filename}: Error checking availability: {e}", 'ERROR')
                    self.results['errors'].append(f"Error checking {filename}: {str(e)}")
                    availability_results.append({
                        'year': year,
                        'table': table,
                        'filename': filename,
                        'status': 'error',
                        'error': str(e)
                    })
                    all_available = False

        self.results['checks'][check_name] = {
            'status': 'pass' if all_available else 'warning',
            'tests': availability_results
        }

        return all_available

    def check_download_and_parse(self):
        """Download and parse a small file to verify format compatibility."""
        if self.quick:
            self.log("Skipping download test (quick mode)")
            return True

        check_name = 'download_and_parse'
        self.log("Testing file download and parsing (using 2000 device data)...")

        try:
            # Use 2000 as it's the first year supported (post-schema change)
            year = 2000
            table = 'device'
            url, filename = self.db._construct_file_url(table, year)

            # Download file
            self.log(f"Downloading {filename}...")
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; MAUDE-DB-Compatibility-Check)'}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # Extract zip
            self.log("Extracting archive...")
            zip_data = io.BytesIO(response.content)
            with zipfile.ZipFile(zip_data, 'r') as zip_ref:
                # Get the text file (should be .txt file in the zip)
                txt_files = [f for f in zip_ref.namelist() if f.endswith('.txt')]

                if not txt_files:
                    self.log("No .txt file found in archive", 'ERROR')
                    self.results['errors'].append("No .txt file in downloaded archive")
                    self.results['checks'][check_name] = {
                        'status': 'fail',
                        'error': 'No .txt file in archive'
                    }
                    return False

                # Read and parse the file
                self.log(f"Parsing {txt_files[0]}...")
                with zip_ref.open(txt_files[0]) as f:
                    # Read first chunk
                    df = pd.read_csv(
                        f,
                        sep='|',
                        encoding='latin1',
                        on_bad_lines='skip',
                        nrows=100,
                        low_memory=False
                    )

                    # Verify expected columns exist
                    expected_columns = ['MDR_REPORT_KEY', 'GENERIC_NAME']
                    missing_columns = [col for col in expected_columns if col not in df.columns]

                    if missing_columns:
                        self.log(f"Missing expected columns: {missing_columns}", 'ERROR')
                        self.results['errors'].append(f"Missing columns: {missing_columns}")
                        self.results['checks'][check_name] = {
                            'status': 'fail',
                            'year': year,
                            'table': table,
                            'filename': filename,
                            'error': f"Missing columns: {missing_columns}",
                            'found_columns': list(df.columns)
                        }
                        return False

                    self.log(f"Successfully parsed {len(df)} rows with {len(df.columns)} columns", 'SUCCESS')
                    self.results['checks'][check_name] = {
                        'status': 'pass',
                        'year': year,
                        'table': table,
                        'filename': filename,
                        'rows_tested': len(df),
                        'columns_found': list(df.columns)
                    }
                    return True

        except Exception as e:
            self.log(f"Download/parse test failed: {e}", 'ERROR')
            self.results['errors'].append(f"Download/parse error: {str(e)}")
            self.results['checks'][check_name] = {
                'status': 'fail',
                'error': str(e)
            }
            return False

    def run_all_checks(self):
        """Run all compatibility checks."""
        if self.verbose:
            print("="*70)
            print("FDA MAUDE COMPATIBILITY CHECK")
            print("="*70)
            print(f"Timestamp: {self.results['timestamp']}")
            print(f"Mode: {'Quick (HEAD requests only)' if self.quick else 'Full (includes test download)'}")
            print()

        # Run checks in order
        checks = [
            ("Base URL Accessibility", self.check_base_url),
            ("File Naming Patterns", self.check_file_patterns),
            ("File Availability", self.check_file_availability),
            ("Download and Parse", self.check_download_and_parse),
        ]

        for check_name, check_func in checks:
            if self.verbose:
                print(f"\n{check_name}")
                print("-" * 70)

            passed = check_func()

            if not passed and check_func != self.check_file_patterns:
                # Critical failure (non-pattern issues)
                if check_func == self.check_base_url or check_func == self.check_download_and_parse:
                    self.results['compatible'] = False

        # Summary
        if self.verbose:
            print("\n" + "="*70)
            print("COMPATIBILITY CHECK RESULTS")
            print("="*70)

            if self.results['compatible']:
                print("\n✓ FDA MAUDE site is COMPATIBLE with PyMAUDE library")
            else:
                print("\n✗ FDA MAUDE site is INCOMPATIBLE with PyMAUDE library")

            if self.results['warnings']:
                print(f"\n⚠ Warnings ({len(self.results['warnings'])}):")
                for warning in self.results['warnings']:
                    print(f"  - {warning}")

            if self.results['errors']:
                print(f"\n✗ Errors ({len(self.results['errors'])}):")
                for error in self.results['errors']:
                    print(f"  - {error}")

            print()

        return self.results['compatible']


def main():
    parser = argparse.ArgumentParser(
        description='Check FDA MAUDE website compatibility with PyMAUDE library',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--quick', action='store_true',
                        help='Quick check (HEAD requests only, no downloads)')
    parser.add_argument('--json', action='store_true',
                        help='Output results as JSON')
    parser.add_argument('--quiet', action='store_true',
                        help='Suppress all output except JSON (if --json specified)')

    args = parser.parse_args()

    # Disable verbose output if JSON mode is enabled (to ensure valid JSON output)
    verbose = not args.quiet and not args.json

    checker = CompatibilityChecker(verbose=verbose, quick=args.quick)
    compatible = checker.run_all_checks()

    # Output JSON if requested
    if args.json:
        print(json.dumps(checker.results, indent=2))

    # Exit with appropriate code
    sys.exit(0 if compatible else 1)


if __name__ == '__main__':
    main()
