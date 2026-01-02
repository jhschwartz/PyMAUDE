#!/usr/bin/env python3
"""
Example: Using Helper Query Methods

This example demonstrates the new helper methods that operate on query results.
These methods reduce boilerplate code and make common analysis tasks easier.

Usage:
    python using_helper_methods.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maude_db import MaudeDatabase


def main():
    print("="*60)
    print("Helper Query Methods Example")
    print("="*60)

    # Initialize database
    db = MaudeDatabase('maude_helper_demo.db', verbose=True)

    # Download some data (using 1998 for fast demo)
    print("\n1. Downloading sample data (1998)...")
    db.add_years(
        years=1998,
        tables=['device', 'text'],
        download=True,
        data_dir='./maude_data'
    )

    # Query for a specific device type
    device_type = 'catheter'
    print(f"\n2. Querying for '{device_type}' devices...")
    results = db.query_device(device_name=device_type)
    print(f"   Found {len(results):,} events")

    if len(results) == 0:
        print("\n   No results found. Try a different device name.")
        db.close()
        return

    # Use helper methods on the results
    print(f"\n3. Using helper methods on query results...")

    # Get event type breakdown
    print("\n   a) Event Type Breakdown:")
    breakdown = db.event_type_breakdown_for(results)
    print(f"      Total events: {breakdown['total']:,}")
    print(f"      Deaths: {breakdown['deaths']:,}")
    print(f"      Injuries: {breakdown['injuries']:,}")
    print(f"      Malfunctions: {breakdown['malfunctions']:,}")

    # Get date range summary
    print("\n   b) Date Range Summary:")
    date_summary = db.date_range_summary_for(results)
    print(f"      First event: {date_summary['first_date']}")
    print(f"      Last event: {date_summary['last_date']}")
    print(f"      Span: {date_summary['total_days']} days")

    # Get top manufacturers
    print("\n   c) Top 5 Manufacturers:")
    top_mfg = db.top_manufacturers_for(results, n=5)
    for idx, row in top_mfg.iterrows():
        print(f"      {idx+1}. {row['manufacturer']}: {row['event_count']} events")

    # Get yearly trends
    print("\n   d) Yearly Trends:")
    trends = db.trends_for(results)
    print(trends.to_string(index=False))

    # Get narratives (just first 3 for demo)
    print(f"\n   e) Sample Narratives (first 3):")
    sample_results = results.head(3)
    narratives = db.get_narratives_for(sample_results)

    if len(narratives) > 0:
        for idx, row in narratives.iterrows():
            text = row['FOI_TEXT']
            # Truncate long narratives
            if len(text) > 150:
                text = text[:150] + "..."
            print(f"\n      Event {row['MDR_REPORT_KEY']}:")
            print(f"      {text}")

    # Comparison: Old way vs New way
    print("\n" + "="*60)
    print("Code Comparison: Old Way vs New Way")
    print("="*60)

    print("\nOLD WAY (more verbose):")
    print("  results = db.query_device(device_name='catheter')")
    print("  keys = results['MDR_REPORT_KEY'].tolist()")
    print("  narratives = db.get_narratives(keys)")
    print("")
    print("  total = len(results)")
    print("  deaths = results['EVENT_TYPE'].str.contains('Death').sum()")
    print("  # ... more manual aggregation ...")

    print("\nNEW WAY (cleaner):")
    print("  results = db.query_device(device_name='catheter')")
    print("  narratives = db.get_narratives_for(results)")
    print("  breakdown = db.event_type_breakdown_for(results)")
    print("  trends = db.trends_for(results)")
    print("  top_mfg = db.top_manufacturers_for(results, n=5)")

    # Clean up
    db.close()

    print("\n" + "="*60)
    print("Demo complete!")
    print("="*60)


if __name__ == '__main__':
    main()
