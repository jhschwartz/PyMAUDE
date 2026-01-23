# selection_widget.py - Jupyter Widget for Device Selection
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
Jupyter Widget for interactive device selection.

This module provides a widget-based interface for the SelectionManager,
enabling researchers to interactively select device records through
an accept/defer/reject workflow directly in Jupyter notebooks.

Usage:
    from pymaude import MaudeDatabase, SelectionManager
    from pymaude.selection_widget import SelectionWidget

    db = MaudeDatabase('maude.db')
    manager = SelectionManager('my_project', 'selections.json', db.db_path)

    widget = SelectionWidget(manager, db)
    widget.display()
"""

from __future__ import annotations
from typing import Optional, List, Dict, Callable, Any, TYPE_CHECKING

try:
    import ipywidgets as widgets
    from IPython.display import display, clear_output
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False
    widgets = None  # type: ignore

from .selection import SelectionManager, PHASES, FIELD_MAP


class SelectionWidget:
    """
    Interactive Jupyter widget for device selection workflow.

    Wraps SelectionManager with a user-friendly interface for:
    - Creating and managing device groups
    - Reviewing and deciding on field values (accept/defer/reject)
    - Navigating the cascade workflow (brand_name -> generic_name -> manufacturer)
    - Viewing summaries and exporting results

    The widget auto-saves decisions to the JSON file, so state is preserved
    across kernel restarts.

    Attributes:
        manager (SelectionManager): The underlying selection manager
        db: MaudeDatabase instance for queries
        current_screen (str): Current screen being displayed
        current_group (str): Currently selected group (if any)

    Example:
        >>> widget = SelectionWidget(manager, db)
        >>> widget.display()
    """

    def __init__(self, manager: SelectionManager, db):
        """
        Initialize the selection widget.

        Args:
            manager: SelectionManager instance
            db: MaudeDatabase instance

        Raises:
            ImportError: If ipywidgets is not installed
        """
        if not IPYWIDGETS_AVAILABLE:
            raise ImportError(
                "ipywidgets is required for SelectionWidget. "
                "Install with: pip install ipywidgets"
            )

        self.manager = manager
        self.db = db

        # UI state
        self.current_screen = 'main'
        self.current_group: Optional[str] = None
        self.current_phase: Optional[str] = None

        # For filter functionality
        self._all_decision_rows: List[tuple] = []  # (value, row_widget)
        self._decision_widgets: Dict[str, Any] = {}
        self._count_display: Optional[Any] = None

        # Main container
        self.container = widgets.VBox()

    def display(self):
        """Render the widget in the notebook."""
        self._refresh()
        display(self.container)

    def _refresh(self):
        """Rebuild the current screen."""
        if self.current_screen == 'main':
            self.container.children = [self._build_main_screen()]
        elif self.current_screen == 'add_group':
            self.container.children = [self._build_add_group_screen()]
        elif self.current_screen == 'selection':
            self.container.children = [
                self._build_selection_screen(self.current_group, self.current_phase)
            ]
        elif self.current_screen == 'summary':
            self.container.children = [self._build_summary_screen(self.current_group)]
        elif self.current_screen == 'rename':
            self.container.children = [self._build_rename_screen(self.current_group)]

    def _navigate_to(self, screen: str, group: str = None, phase: str = None):
        """Navigate to a different screen."""
        self.current_screen = screen
        self.current_group = group
        self.current_phase = phase
        self._refresh()

    # ==================== Main Screen ====================

    def _build_main_screen(self) -> widgets.VBox:
        """Build the main group list view."""
        # Header
        header = widgets.HTML(
            f"<h2 style='margin-bottom: 5px;'>Device Selection: {self.manager.name}</h2>"
            f"<p style='color: gray; margin-top: 0;'>Database: {self.manager.database_path}</p>"
        )

        # Add group button
        add_btn = widgets.Button(
            description='+ Add New Group',
            button_style='success',
            layout=widgets.Layout(width='150px')
        )
        add_btn.on_click(lambda _: self._navigate_to('add_group'))

        # Group cards
        group_cards = []
        for group_name in self.manager.groups:
            card = self._build_group_card(group_name)
            group_cards.append(card)

        if not group_cards:
            no_groups = widgets.HTML(
                "<p style='color: gray; font-style: italic;'>"
                "No groups yet. Click 'Add New Group' to get started.</p>"
            )
            group_cards = [no_groups]

        # Action buttons
        save_btn = widgets.Button(description='Save', button_style='primary')
        save_btn.on_click(self._on_save_click)

        results_btn = widgets.Button(description='Get Results')
        results_btn.on_click(self._on_get_results_click)

        self._status_output = widgets.Output()

        return widgets.VBox([
            header,
            add_btn,
            widgets.HTML("<hr style='margin: 10px 0;'>"),
            widgets.VBox(group_cards),
            widgets.HTML("<hr style='margin: 10px 0;'>"),
            widgets.HBox([save_btn, results_btn]),
            self._status_output
        ])

    def _build_group_card(self, group_name: str) -> widgets.HBox:
        """Build a card for a single group."""
        status = self.manager.get_group_status(group_name)
        group = self.manager.groups[group_name]

        # Status indicator
        if status['is_finalized']:
            status_icon = "&#9989;"  # checkmark
            status_text = "Complete"
        elif status['status'] == 'in_progress':
            status_icon = "&#9998;"  # pencil
            phase_name = status['current_phase'].replace('_', ' ').title()
            status_text = f"In Progress ({phase_name})"
        else:
            status_icon = "&#9711;"  # circle
            status_text = "Draft"

        # Count decisions
        total_accepted = sum(
            status['decisions_count'][p]['accepted'] for p in PHASES
        )
        total_rejected = sum(
            status['decisions_count'][p]['rejected'] for p in PHASES
        )

        # Info section
        info_html = widgets.HTML(f"""
            <div style='padding: 10px; background: #f8f9fa; border-radius: 5px; margin: 5px 0;'>
                <div style='font-weight: bold; font-size: 16px;'>
                    {status_icon} {group_name}
                </div>
                <div style='color: gray; font-size: 12px;'>
                    Keywords: {', '.join(group['keywords'][:3])}{'...' if len(group['keywords']) > 3 else ''}
                </div>
                <div style='font-size: 12px;'>
                    {status_text} |
                    <span style='color: green;'>{total_accepted} accepted</span> |
                    <span style='color: red;'>{total_rejected} rejected</span>
                </div>
            </div>
        """)

        # Action buttons
        edit_btn = widgets.Button(description='Edit', layout=widgets.Layout(width='60px'))
        edit_btn.on_click(lambda _, g=group_name: self._on_edit_group(g))

        rename_btn = widgets.Button(description='Rename', layout=widgets.Layout(width='70px'))
        rename_btn.on_click(lambda _, g=group_name: self._navigate_to('rename', group=g))

        delete_btn = widgets.Button(
            description='Delete',
            button_style='danger',
            layout=widgets.Layout(width='70px')
        )
        delete_btn.on_click(lambda _, g=group_name: self._on_delete_group(g))

        return widgets.HBox([
            info_html,
            widgets.VBox([edit_btn, rename_btn, delete_btn])
        ])

    def _on_edit_group(self, group_name: str):
        """Handle edit group button click."""
        status = self.manager.get_group_status(group_name)
        phase = status['current_phase']

        if phase == 'finalized':
            # Go back to last phase to allow editing
            self.manager.go_back_phase(group_name)
            phase = self.manager.groups[group_name]['current_phase']

        self._navigate_to('selection', group=group_name, phase=phase)

    def _on_delete_group(self, group_name: str):
        """Handle delete group button click."""
        self.manager.remove_group(group_name)
        self.manager.save()
        self._refresh()

    def _on_save_click(self, _):
        """Handle save button click."""
        self.manager.save()
        with self._status_output:
            clear_output()
            print("Saved!")

    def _on_get_results_click(self, _):
        """Handle get results button click."""
        with self._status_output:
            clear_output()
            if not self.manager.groups:
                print("No groups defined yet.")
                return

            try:
                results = self.manager.get_results(self.db, mode='decisions')
                print("Results retrieved successfully!")
                print(f"\nSummary:\n{results.summary}")
                print(f"\nAccess with: results['group_name'] or results.to_df()")
            except Exception as e:
                print(f"Error getting results: {e}")

    # ==================== Add Group Screen ====================

    def _build_add_group_screen(self) -> widgets.VBox:
        """Build the add group screen."""
        header = widgets.HTML("<h3>Add New Group</h3>")

        # Keywords input
        keywords_label = widgets.HTML("<b>Keywords</b> (comma-separated):")
        self._keywords_input = widgets.Textarea(
            placeholder='e.g., penumbra, lightning',
            layout=widgets.Layout(width='400px', height='60px')
        )

        # Preview button and area
        preview_btn = widgets.Button(description='Search Preview')
        self._preview_output = widgets.Output()
        preview_btn.on_click(self._on_preview_click)

        # Group name input (shown after preview)
        self._group_name_input = widgets.Text(
            placeholder='Group name (e.g., penumbra)',
            layout=widgets.Layout(width='200px')
        )
        group_name_section = widgets.VBox([
            widgets.HTML("<b>Group name:</b>"),
            self._group_name_input
        ])

        # Buttons
        cancel_btn = widgets.Button(description='Cancel')
        cancel_btn.on_click(lambda _: self._navigate_to('main'))

        proceed_btn = widgets.Button(
            description='Proceed to Selection',
            button_style='primary'
        )
        proceed_btn.on_click(self._on_proceed_click)

        return widgets.VBox([
            header,
            keywords_label,
            self._keywords_input,
            preview_btn,
            self._preview_output,
            widgets.HTML("<hr>"),
            group_name_section,
            widgets.HBox([cancel_btn, proceed_btn])
        ])

    def _on_preview_click(self, _):
        """Handle preview button click."""
        with self._preview_output:
            clear_output()
            keywords_text = self._keywords_input.value.strip()
            if not keywords_text:
                print("Please enter at least one keyword.")
                return

            keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]

            print("Searching...")
            try:
                preview = self.manager.get_search_preview(self.db, keywords)
                print(f"\nPreview Results:")
                print(f"  - {preview['brand_name_count']} unique brand names ({preview['brand_name_mdrs']} MDRs)")
                print(f"  - {preview['generic_name_count']} unique generic names ({preview['generic_name_mdrs']} MDRs)")
                print(f"  - {preview['manufacturer_count']} unique manufacturers ({preview['manufacturer_mdrs']} MDRs)")
                print(f"  - ~{preview['total_unique_mdrs']} unique MDRs total")

                if preview['total_unique_mdrs'] == 0:
                    print("\nNo matches found. Try different keywords.")
            except Exception as e:
                print(f"Error: {e}")

    def _on_proceed_click(self, _):
        """Handle proceed button click."""
        keywords_text = self._keywords_input.value.strip()
        group_name = self._group_name_input.value.strip()

        if not keywords_text:
            with self._preview_output:
                clear_output()
                print("Please enter keywords first.")
            return

        if not group_name:
            with self._preview_output:
                clear_output()
                print("Please enter a group name.")
            return

        keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]

        try:
            self.manager.create_group(group_name, keywords)
            self.manager.save()
            self._navigate_to('selection', group=group_name, phase='brand_name')
        except ValueError as e:
            with self._preview_output:
                clear_output()
                print(f"Error: {e}")

    # ==================== Selection Screen ====================

    def _build_selection_screen(self, group_name: str, field: str) -> widgets.VBox:
        """Build the decision interface for a phase."""
        group = self.manager.groups[group_name]

        # Phase indicator
        phase_idx = PHASES.index(field) + 1
        field_display = field.replace('_', ' ').title()
        phase_header = widgets.HTML(
            f"<h3>Group: {group_name} - {field_display} Review ({phase_idx}/3)</h3>"
        )

        # Get candidates
        try:
            candidates_df = self.manager.search_candidates(self.db, group_name, field)
        except Exception as e:
            return widgets.VBox([
                phase_header,
                widgets.HTML(f"<p style='color: red;'>Error loading candidates: {e}</p>"),
                widgets.Button(description='Back', on_click=lambda _: self._navigate_to('main'))
            ])

        if len(candidates_df) == 0:
            # No candidates in this phase
            no_candidates = widgets.HTML(
                "<p style='font-style: italic;'>No undecided values in this phase.</p>"
            )

            next_btn = widgets.Button(description='Next Phase', button_style='primary')
            next_btn.on_click(lambda _: self._advance_phase(group_name))

            back_btn = widgets.Button(description='Back')
            back_btn.on_click(lambda _: self._go_back_phase(group_name))

            return widgets.VBox([
                phase_header,
                no_candidates,
                widgets.HBox([back_btn, next_btn])
            ])

        # Filter input with functionality
        filter_input = widgets.Text(
            placeholder='Filter values...',
            layout=widgets.Layout(width='200px')
        )
        filter_input.observe(
            lambda change: self._on_filter_change(change),
            names='value'
        )

        # Bulk action buttons
        accept_all_btn = widgets.Button(description='Accept All Visible')
        defer_all_btn = widgets.Button(description='Defer All Visible')
        reject_all_btn = widgets.Button(description='Reject All Visible')

        # Decision widgets for each value
        self._decision_widgets = {}
        self._all_decision_rows = []

        for _, row in candidates_df.iterrows():
            value = row['value']
            count = row['mdr_count']
            current_decision = row['decision']

            # Determine initial selection
            if current_decision == 'accept':
                initial_value = 'Accept'
            elif current_decision == 'reject':
                initial_value = 'Reject'
            elif current_decision == 'defer':
                initial_value = 'Defer'
            else:
                # Undecided - default to defer and save it
                initial_value = 'Defer'
                self.manager.set_decision(group_name, field, value, 'defer')

            # Create HORIZONTAL toggle buttons instead of vertical radio
            toggle = widgets.ToggleButtons(
                options=['Accept', 'Defer', 'Reject'],
                value=initial_value,
                button_style='',
                layout=widgets.Layout(width='auto'),
                style={'button_width': '70px'}
            )

            # Store reference
            self._decision_widgets[value] = toggle

            # Handle change with count update
            def on_change(change, v=value, f=field, g=group_name):
                if change['name'] == 'value':
                    decision = change['new'].lower()
                    self.manager.set_decision(g, f, v, decision)
                    self.manager.save()
                    self._update_counts(g, f)

            toggle.observe(on_change, names='value')

            # Create row with value label
            label = widgets.HTML(
                f"<span style='font-family: monospace; margin-left: 10px;'><b>{value}</b></span> "
                f"<span style='color: gray;'>({count} MDRs)</span>"
            )
            row_widget = widgets.HBox([toggle, label])
            self._all_decision_rows.append((value, row_widget))

        # Save after setting initial deferrals for undecided values
        self.manager.save()

        # Container for decision rows (will be filtered)
        self._decisions_container = widgets.VBox(
            [row for _, row in self._all_decision_rows],
            layout=widgets.Layout(
                max_height='400px',
                overflow_y='auto',
                border='1px solid #ddd',
                padding='10px'
            )
        )

        # Wire up bulk actions
        def accept_all(_):
            for value, toggle in self._decision_widgets.items():
                # Only change visible ones
                if any(value == v for v, row in self._all_decision_rows
                       if row in self._decisions_container.children):
                    toggle.value = 'Accept'

        def defer_all(_):
            for value, toggle in self._decision_widgets.items():
                if any(value == v for v, row in self._all_decision_rows
                       if row in self._decisions_container.children):
                    toggle.value = 'Defer'

        def reject_all(_):
            for value, toggle in self._decision_widgets.items():
                if any(value == v for v, row in self._all_decision_rows
                       if row in self._decisions_container.children):
                    toggle.value = 'Reject'

        accept_all_btn.on_click(accept_all)
        defer_all_btn.on_click(defer_all)
        reject_all_btn.on_click(reject_all)

        # Count display (dynamic)
        self._count_display = widgets.HTML()
        self._update_counts(group_name, field)

        # Navigation buttons
        back_btn = widgets.Button(description='Back')
        if PHASES.index(field) == 0:
            back_btn.on_click(lambda _: self._navigate_to('main'))
        else:
            back_btn.on_click(lambda _: self._go_back_phase(group_name))

        next_btn = widgets.Button(description='Next Phase', button_style='primary')
        if PHASES.index(field) == len(PHASES) - 1:
            next_btn.description = 'View Summary'
            next_btn.on_click(lambda _: self._navigate_to('summary', group=group_name))
        else:
            next_btn.on_click(lambda _: self._advance_phase(group_name))

        return widgets.VBox([
            phase_header,
            widgets.HBox([filter_input]),
            widgets.HBox([accept_all_btn, defer_all_btn, reject_all_btn]),
            self._decisions_container,
            self._count_display,
            widgets.HBox([back_btn, next_btn])
        ])

    def _on_filter_change(self, change):
        """Handle filter input change."""
        filter_text = change['new'].lower()

        if not filter_text:
            # Show all rows
            visible_rows = [row for _, row in self._all_decision_rows]
        else:
            # Filter rows by value
            visible_rows = [
                row for value, row in self._all_decision_rows
                if filter_text in value.lower()
            ]

        self._decisions_container.children = visible_rows

    def _update_counts(self, group_name: str, field: str):
        """Update the decision counts display."""
        if self._count_display is None:
            return

        decisions = self.manager.groups[group_name]['decisions'][field]
        accepted = len(decisions['accepted'])
        deferred = len(decisions['deferred'])
        rejected = len(decisions['rejected'])

        self._count_display.value = (
            f"<p>Accepted: <b style='color:green;'>{accepted}</b> | "
            f"Deferred: <b style='color:orange;'>{deferred}</b> | "
            f"Rejected: <b style='color:red;'>{rejected}</b></p>"
        )

    def _advance_phase(self, group_name: str):
        """Advance to next phase."""
        new_phase = self.manager.advance_phase(group_name)
        self.manager.save()

        if new_phase == 'finalized':
            self._navigate_to('summary', group=group_name)
        else:
            self._navigate_to('selection', group=group_name, phase=new_phase)

    def _go_back_phase(self, group_name: str):
        """Go back to previous phase."""
        try:
            new_phase = self.manager.go_back_phase(group_name)
            self.manager.save()
            self._navigate_to('selection', group=group_name, phase=new_phase)
        except ValueError:
            self._navigate_to('main')

    # ==================== Summary Screen ====================

    def _build_summary_screen(self, group_name: str) -> widgets.VBox:
        """Build the summary screen before finalization."""
        group = self.manager.groups[group_name]

        header = widgets.HTML(f"<h3>Group: {group_name} - Summary</h3>")

        # Collect stats
        total_accepted = 0
        total_rejected = 0
        total_deferred = 0
        phase_details = []

        for phase in PHASES:
            decisions = group['decisions'][phase]
            accepted = len(decisions['accepted'])
            rejected = len(decisions['rejected'])
            deferred = len(decisions['deferred'])

            total_accepted += accepted
            total_rejected += rejected
            total_deferred += deferred

            phase_name = phase.replace('_', ' ').title()
            phase_details.append(
                f"  {phase_name}: {accepted} accepted, {rejected} rejected, {deferred} deferred"
            )

        summary_html = widgets.HTML(f"""
            <div style='padding: 15px; background: #f8f9fa; border-radius: 5px;'>
                <p><b>Total Decisions:</b></p>
                <ul>
                    <li style='color: green;'>Accepted: {total_accepted} values</li>
                    <li style='color: red;'>Rejected: {total_rejected} values</li>
                    <li style='color: orange;'>Deferred: {total_deferred} values</li>
                </ul>
                <p><b>By Phase:</b></p>
                <pre>{'<br>'.join(phase_details)}</pre>
            </div>
        """)

        # Warning if still has deferred
        warning = widgets.HTML("")
        if total_deferred > 0:
            # Show which values are still deferred
            deferred_values = []
            for phase in PHASES:
                for v in group['decisions'][phase]['deferred']:
                    deferred_values.append(f"  - {v} (from {phase.replace('_', ' ')})")

            warning = widgets.HTML(
                f"<div style='background: #fff3cd; padding: 10px; border-radius: 5px; margin: 10px 0;'>"
                f"<p style='color: #856404; font-weight: bold;'>"
                f"&#9888; Warning: {total_deferred} values are still deferred:</p>"
                f"<pre style='color: #856404;'>{'<br>'.join(deferred_values[:10])}"
                f"{'<br>...' if len(deferred_values) > 10 else ''}</pre>"
                f"<p style='color: #856404;'>These will be <b>EXCLUDED</b> from results.</p>"
                f"</div>"
            )

        # Single "Finish" button instead of separate finalize/done
        back_btn = widgets.Button(description='Back to Edit')
        back_btn.on_click(lambda _: self._navigate_to('selection', group=group_name, phase=PHASES[-1]))

        finish_btn = widgets.Button(
            description='Finish & Save',
            button_style='success'
        )
        finish_btn.on_click(lambda _: self._on_finish(group_name))

        self._finish_output = widgets.Output()

        return widgets.VBox([
            header,
            summary_html,
            warning,
            widgets.HBox([back_btn, finish_btn]),
            self._finish_output
        ])

    def _on_finish(self, group_name: str):
        """Handle finish button click - finalize and return to main."""
        with self._finish_output:
            clear_output()
            try:
                result = self.manager.finalize_group(self.db, group_name)
                self.manager.save()
                print(f"Group finalized!")
                print(f"  - {result['mdr_count']} MDRs captured")
                if result['pending_count'] > 0:
                    print(f"  - {result['pending_count']} deferred values excluded")
            except Exception as e:
                print(f"Error finalizing: {e}")
                return

        # Return to main screen
        self._navigate_to('main')

    # ==================== Rename Screen ====================

    def _build_rename_screen(self, group_name: str) -> widgets.VBox:
        """Build the rename group screen."""
        header = widgets.HTML(f"<h3>Rename Group: {group_name}</h3>")

        self._rename_input = widgets.Text(
            value=group_name,
            placeholder='New group name',
            layout=widgets.Layout(width='200px')
        )

        self._rename_output = widgets.Output()

        cancel_btn = widgets.Button(description='Cancel')
        cancel_btn.on_click(lambda _: self._navigate_to('main'))

        save_btn = widgets.Button(description='Save', button_style='primary')
        save_btn.on_click(lambda _: self._on_rename_save(group_name))

        return widgets.VBox([
            header,
            widgets.HTML("<b>New name:</b>"),
            self._rename_input,
            widgets.HBox([cancel_btn, save_btn]),
            self._rename_output
        ])

    def _on_rename_save(self, old_name: str):
        """Handle rename save button click."""
        new_name = self._rename_input.value.strip()

        with self._rename_output:
            clear_output()
            try:
                self.manager.rename_group(old_name, new_name)
                self.manager.save()
                self._navigate_to('main')
            except (ValueError, KeyError) as e:
                print(f"Error: {e}")
