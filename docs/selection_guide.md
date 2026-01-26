# Device Selection Guide

Interactive device selection for reproducible MAUDE analysis.

## Overview

The device selection system replaces manual brand name mapping with an interactive workflow that lets you:

1. **Discover** - Search across brand names, generic names, and manufacturers
2. **Decide** - Accept, reject, or defer each matching value
3. **Reproduce** - Save decisions to JSON for exact reproducibility

## Quick Start

```python
from pymaude import MaudeDatabase, SelectionManager
from pymaude.selection_widget import SelectionWidget

# Connect to database
db = MaudeDatabase('maude.db')

# Create selection project
manager = SelectionManager('my_project', 'selections.json', db.db_path)

# Launch interactive widget
widget = SelectionWidget(manager, db)
widget.display()

# In a separate cell (after completing selection):
results = widget.get_results()  # Prints progress, returns SelectionResults
df = results.to_df()
```

## Concepts

### Groups

A **group** represents a category of devices you want to analyze together. For example:
- `penumbra` - All Penumbra thrombectomy devices
- `inari` - All Inari Medical devices
- `boston_angiojet` - Boston Scientific AngioJet family

Each group has:
- **Keywords** - Search terms to find matching records
- **Decisions** - Your accept/reject/defer choices for each value
- **MDR snapshot** - Exact record IDs for reproducibility

### Phases

Selection proceeds in three phases per group:

1. **Brand Name** - Review matching `BRAND_NAME` values
2. **Generic Name** - Review matching `GENERIC_NAME` values (for undecided MDRs)
3. **Manufacturer** - Review matching `MANUFACTURER_D_NAME` values (for undecided MDRs)

### Decisions

For each unique value in a phase, choose:

| Decision | Effect |
|----------|--------|
| **Accept** | MDRs with this value are included in results. Won't appear in later phases. |
| **Reject** | MDRs with this value are excluded from results. Won't appear in later phases. |
| **Defer** | MDRs with this value will appear in the next phase for further review. |

**Cascade Logic**: Accepted and rejected MDRs are removed from subsequent phases. Deferred MDRs flow through to the next phase, giving you another chance to decide based on different field values.

### Example Workflow

Searching for Penumbra thrombectomy devices:

**Phase 1 (Brand Name):**
- Accept: `PENUMBRA LIGHTNING BOLT 7`, `PENUMBRA LIGHTNING FLASH`
- Reject: `PENUMBRA SMART COIL` (not thrombectomy)
- Defer: `PENUMBRA` (too generic, need more context)

**Phase 2 (Generic Name):**
- The deferred `PENUMBRA` MDRs appear here
- Accept: Those with `THROMBECTOMY CATHETER`
- Reject: Those with `EMBOLIZATION COIL`

**Phase 3 (Manufacturer):**
- Any remaining undecided MDRs appear here
- Final chance to accept/reject

**Multi-Deferred Review (Optional):**
- After phase 3, review MDRs deferred in 2+ phases
- See brand, generic, and manufacturer side-by-side
- Make final accept/reject decisions for ambiguous cases

## Widget Interface

### Main Screen

Shows all groups with status indicators:
- Draft - Group created but no decisions yet
- In Progress - Actively making decisions
- Complete - All phases finished

Actions:
- **+ Add New Group** - Create a new device group
- **Edit** - Continue making decisions
- **Rename** - Change group name
- **Delete** - Remove group
- **Save** - Persist to JSON file
- **Get Results** - Execute queries and get DataFrames

### Add Group Screen

1. Enter keywords (comma-separated)
2. Click **Search Preview** to see match counts
3. Enter group name
4. Click **Proceed to Selection**

### Selection Screen

- Radio buttons for Accept/Defer/Reject per value
- Bulk actions: Accept All, Defer All, Reject All
- MDR counts shown for each value
- Navigate with Back/Next Phase buttons

### Summary Screen

Shows final counts before finalization:
- Accepted values and MDR counts by phase
- Rejected values
- Deferred values (will be excluded with warning)

Click **Finalize Group** to snapshot MDR keys.

### Multi-Deferred Review Screen

After completing all three phases, you can review MDRs that were deferred multiple times:
- Shows brand name, generic name, and manufacturer side-by-side
- Indicates which phases each MDR was deferred in
- Use this to make final decisions on ambiguous records
- Navigate with pagination for large result sets

## Programmatic Usage

You can also use the SelectionManager without the widget:

```python
from pymaude import MaudeDatabase, SelectionManager

db = MaudeDatabase('maude.db')
manager = SelectionManager('my_project', 'selections.json', db.db_path)

# Create group
manager.create_group('penumbra', ['penumbra', 'lightning'])

# Search for candidates
candidates = manager.search_candidates(db, 'penumbra', 'brand_name')
print(candidates)

# Set decisions
manager.set_decision('penumbra', 'brand_name', 'PENUMBRA LIGHTNING BOLT 7', 'accept')
manager.set_decision('penumbra', 'brand_name', 'PENUMBRA SMART COIL', 'reject')

# Or bulk decisions
manager.set_decisions_bulk('penumbra', 'brand_name', {
    'PENUMBRA LIGHTNING FLASH': 'accept',
    'PENUMBRA': 'defer'
})

# Advance through phases
manager.advance_phase('penumbra')  # to generic_name
# ... make more decisions ...
manager.advance_phase('penumbra')  # to manufacturer
manager.advance_phase('penumbra')  # to finalized

# Finalize with MDR snapshot
result = manager.finalize_group(db, 'penumbra')
print(f"Captured {result['mdr_count']} MDRs")

# Save
manager.save()
```

## Getting Results

### From Widget

After completing selection in the widget, get results in a separate cell:

```python
# Prints progress for each group
results = widget.get_results()
```

### Using Decisions (Default)

Re-runs the query based on your decisions. Adapts to FDA database updates.

```python
results = manager.get_results(db, mode='decisions')

# With progress output
results = manager.get_results(db, mode='decisions', verbose=True)
```

### Using Snapshot

Uses the exact MDR keys captured at finalization. Guarantees identical results.

```python
results = manager.get_results(db, mode='snapshot')
```

### Working with Results

```python
# Access single group
df = results['penumbra']

# Iterate over groups
for group_name in results:
    print(f"{group_name}: {len(results[group_name])} records")

# Combine all groups
combined_df = results.to_df()

# Quick summary
print(results.summary)
```

### Integration with Analysis Helpers

Results work seamlessly with existing analysis methods:

```python
# Per-group analysis
trends = db.trends_for(results['penumbra'])
breakdown = db.event_type_breakdown_for(results['penumbra'])

# Combined analysis
all_data = results.to_df()
db.summarize_by_brand(all_data, group_column='selection_group')
```

## JSON File Format

Selections are saved to a JSON file with this structure:

```json
{
  "name": "my_project",
  "version": "1.0",
  "created_at": "2026-01-22T10:00:00Z",
  "updated_at": "2026-01-22T14:30:00Z",
  "database_path": "maude.db",
  "groups": {
    "penumbra": {
      "keywords": ["penumbra", "lightning"],
      "status": "complete",
      "current_phase": "finalized",
      "decisions": {
        "brand_name": {
          "accepted": ["PENUMBRA LIGHTNING BOLT 7"],
          "rejected": ["PENUMBRA SMART COIL"],
          "deferred": []
        },
        "generic_name": { ... },
        "manufacturer": { ... }
      },
      "mdr_keys_snapshot": [1001, 1002, 1003]
    }
  }
}
```

## Group Management

### Rename a Group

```python
manager.rename_group('old_name', 'new_name')
```

Useful when you discover during selection that a different name is more appropriate.

### Merge Groups

```python
manager.merge_groups(['clottriever_xl', 'clottriever_bold'], 'clottriever_all')
```

Combines keywords and decisions from multiple groups. Useful when you discover that devices can't be reliably distinguished.

### Reset a Phase

```python
manager.reset_phase('penumbra', 'brand_name')
```

Clears all decisions for a phase, letting you start over.

### Review Multi-Deferred MDRs

Find MDRs that were deferred in multiple phases for further review:

```python
# Get MDRs deferred in 2+ phases
multi_deferred = manager.get_multi_deferred_mdrs(db, 'penumbra', min_deferrals=2)

# Returns DataFrame with columns:
# - MDR_REPORT_KEY
# - BRAND_NAME, GENERIC_NAME, MANUFACTURER_D_NAME
# - defer_count (number of phases where deferred)
# - deferred_phases (list of phase names)

print(multi_deferred)
```

This is useful for identifying ambiguous records that need manual review.

## Best Practices

1. **Start broad, then narrow** - Use general keywords first, then reject non-relevant matches

2. **Use defer strategically** - When a value is too generic (e.g., just "PENUMBRA"), defer it to see if generic_name or manufacturer provides more context

3. **Save frequently** - The widget auto-saves, but call `manager.save()` explicitly in programmatic usage

4. **Use snapshot mode for publications** - Guarantees exact reproducibility regardless of FDA updates

5. **Document your decisions** - The JSON file serves as an audit trail, but consider adding notes in your analysis notebook

## Troubleshooting

### "No matching MDRs found"

- Check spelling of keywords
- Try broader search terms
- Verify database has device table loaded

### Widget doesn't display

- Ensure ipywidgets is installed: `pip install ipywidgets`
- May need to enable widget extension in JupyterLab

### Results don't match expected counts

- Check for deferred values that were excluded
- Use `mode='snapshot'` for exact reproducibility
- Verify all phases were completed
