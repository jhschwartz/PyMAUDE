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

        # Store results after Get Results is clicked
        self.results = None

        # Main container
        self.container = widgets.VBox()

    def display(self):
        """Render the widget in the notebook."""
        self._refresh()
        display(self.container)

    def get_results(self, mode: str = 'decisions'):
        """
        Get results programmatically (blocking).

        Use this in a separate cell after widget.display() to ensure
        results are available even with "Run All".

        Args:
            mode: 'decisions' to re-run from decisions (adapts to FDA updates)
                  'snapshot' to use mdr_keys_snapshot (exact reproducibility)

        Returns:
            SelectionResults object

        Example:
            widget = SelectionWidget(manager, db)
            widget.display()

            # In next cell:
            results = widget.get_results()
            df = results.to_df()
        """
        self.results = self.manager.get_results(self.db, mode=mode, verbose=True)
        return self.results

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
        elif self.current_screen == 'multi_deferred':
            self.container.children = [self._build_multi_deferred_screen(self.current_group)]
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

        self._status_output = widgets.Output()

        # Instruction for getting results
        results_hint = widgets.HTML(
            "<p style='color: gray; font-size: 12px; margin-top: 10px;'>"
            "When done selecting, run <code>results = widget.get_results()</code> in the next cell.</p>"
        )

        return widgets.VBox([
            header,
            add_btn,
            widgets.HTML("<hr style='margin: 10px 0;'>"),
            widgets.VBox(group_cards),
            widgets.HTML("<hr style='margin: 10px 0;'>"),
            widgets.HBox([save_btn]),
            self._status_output,
            results_hint
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

        # Event count display (only for finalized groups)
        event_info = ""
        if status['is_finalized'] and status.get('event_count') is not None:
            event_info = f" | <strong>{status['event_count']:,} events</strong>"
        elif status['is_finalized'] and status['mdr_count'] is not None:
            # Fallback for older snapshots without event_count
            event_info = f" | <strong>{status['mdr_count']:,} MDRs</strong>"

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
                    {status_text}{event_info} |
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

        # Group name input
        self._group_name_input = widgets.Text(
            placeholder='Group name (e.g., penumbra)',
            layout=widgets.Layout(width='200px')
        )
        group_name_section = widgets.VBox([
            widgets.HTML("<b>Group name:</b>"),
            self._group_name_input
        ])

        # Output area for error messages
        self._add_group_output = widgets.Output()

        # Buttons
        home_btn = widgets.Button(description='🏠 Home')
        home_btn.on_click(self._on_home_from_add_group)

        proceed_btn = widgets.Button(
            description='Proceed to Selection',
            button_style='primary'
        )
        proceed_btn.on_click(self._on_proceed_click)

        return widgets.VBox([
            header,
            keywords_label,
            self._keywords_input,
            group_name_section,
            widgets.HBox([home_btn, proceed_btn]),
            self._add_group_output
        ])

    def _on_proceed_click(self, _):
        """Handle proceed button click."""
        keywords_text = self._keywords_input.value.strip()
        group_name = self._group_name_input.value.strip()

        if not keywords_text:
            with self._add_group_output:
                clear_output()
                print("Please enter keywords first.")
            return

        if not group_name:
            with self._add_group_output:
                clear_output()
                print("Please enter a group name.")
            return

        keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]

        try:
            self.manager.create_group(group_name, keywords)
            self.manager.save()
            self._navigate_to('selection', group=group_name, phase='brand_name')
        except ValueError as e:
            with self._add_group_output:
                clear_output()
                print(f"Error: {e}")

    def _on_home_from_add_group(self, _):
        """Handle Home button click from add group screen - creates group if valid, then saves."""
        keywords_text = self._keywords_input.value.strip()
        group_name = self._group_name_input.value.strip()

        # If user entered valid keywords and group name, create the group before going home
        if keywords_text and group_name:
            keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]
            if keywords:
                try:
                    self.manager.create_group(group_name, keywords)
                except ValueError:
                    # Group might already exist or name invalid - that's ok, just save and go home
                    pass

        self.manager.save()
        self._navigate_to('main')

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

        # Create content container that will be updated
        content_container = widgets.VBox([
            widgets.HTML("<p><i>Loading... querying database</i></p>")
        ])

        # Create the outer container
        outer = widgets.VBox([phase_header, content_container])

        # Create loading indicator (hidden initially)
        loading_indicator = widgets.HBox([
            widgets.HTML(
                "<div style='display: flex; align-items: center; padding: 20px;'>"
                "<div style='border: 4px solid #f3f3f3; border-top: 4px solid #3498db; "
                "border-radius: 50%; width: 24px; height: 24px; "
                "animation: spin 1s linear infinite; margin-right: 12px;'></div>"
                "<span style='font-size: 16px;'>Searching database... this may take a minute</span>"
                "</div>"
                "<style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>"
            )
        ])

        # Define function to load content after display
        def load_content(btn=None):
            import time
            # Disable button and show spinner
            if btn:
                btn.disabled = True
                btn.description = 'Searching...'
            content_container.children = [loading_indicator]

            try:
                candidates_df = self.manager.search_candidates(self.db, group_name, field)
                content = self._build_selection_content(group_name, field, candidates_df)
                content_container.children = [content]
                # Force a slight delay and layout refresh to ensure UI updates
                time.sleep(0.1)
                content_container.layout.visibility = 'hidden'
                content_container.layout.visibility = 'visible'
            except Exception as e:
                # Re-enable button on error
                if btn:
                    btn.disabled = False
                    btn.description = 'Load Candidates'
                err_back_btn = widgets.Button(description='Back')
                err_back_btn.on_click(lambda _: self._navigate_to('main'))
                retry_btn = widgets.Button(description='Retry', button_style='warning')
                retry_btn.on_click(load_content)
                content_container.children = [
                    widgets.HTML(f"<p style='color: red;'><b>Error loading candidates:</b> {e}</p>"),
                    widgets.HBox([retry_btn, err_back_btn])
                ]

        # Add a "Load" button that triggers the search
        load_btn = widgets.Button(
            description='Load Candidates',
            button_style='primary',
            icon='search'
        )
        load_btn.on_click(load_content)

        back_btn = widgets.Button(description='Back')
        # Go to previous phase, not main screen
        if PHASES.index(field) == 0:
            back_btn.on_click(lambda _: self._navigate_to('main'))
        else:
            back_btn.on_click(lambda _: self._go_back_phase(group_name))

        content_container.children = [
            widgets.HTML("<p>Click 'Load Candidates' to search the database.</p>"),
            widgets.HBox([load_btn, back_btn])
        ]

        return outer

    def _build_selection_content(
        self,
        group_name: str,
        field: str,
        candidates_df
    ) -> widgets.VBox:
        """Build the actual selection content once candidates are loaded."""

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
                no_candidates,
                widgets.HBox([back_btn, next_btn])
            ])

        # Pagination settings
        PAGE_SIZE = 1000
        self._current_page = 0
        self._filter_text = ''

        # Store candidate data for lazy widget creation
        self._candidates_data = []
        for _, row in candidates_df.iterrows():
            value = row['value']
            count = row['mdr_count']
            current_decision = row['decision']

            # Determine initial decision
            if current_decision in ('accept', 'reject', 'defer'):
                initial_decision = current_decision
            else:
                # Undecided - default to defer and save it
                initial_decision = 'defer'
                self.manager.set_decision(group_name, field, value, 'defer')

            self._candidates_data.append({
                'value': value,
                'count': count,
                'decision': initial_decision
            })

        # Save after setting initial deferrals
        self.manager.save()

        # Track created widgets (created lazily)
        self._decision_widgets = {}

        # Filter input
        filter_input = widgets.Text(
            placeholder='Filter values...',
            layout=widgets.Layout(width='200px')
        )

        # Pagination controls
        self._page_label = widgets.HTML()
        prev_btn = widgets.Button(description='< Prev', disabled=True)
        next_page_btn = widgets.Button(description='Next >')

        # Container for decision rows
        self._decisions_container = widgets.VBox(
            [],
            layout=widgets.Layout(
                max_height='400px',
                overflow_y='auto',
                border='1px solid #ddd',
                padding='10px'
            )
        )

        def get_filtered_data():
            """Get candidates matching current filter."""
            if not self._filter_text:
                return self._candidates_data
            filter_lower = self._filter_text.lower()
            return [c for c in self._candidates_data if filter_lower in c['value'].lower()]

        def create_row_widget(candidate):
            """Create a row widget for a candidate (lazy creation)."""
            value = candidate['value']
            count = candidate['count']

            # Check if already created
            if value in self._decision_widgets:
                toggle = self._decision_widgets[value]
            else:
                # Create toggle buttons
                initial_value = candidate['decision'].capitalize()
                toggle = widgets.ToggleButtons(
                    options=['Accept', 'Defer', 'Reject'],
                    value=initial_value,
                    button_style='',
                    layout=widgets.Layout(width='auto'),
                    style={'button_width': '60px'}
                )
                self._decision_widgets[value] = toggle

                # Handle change
                def on_change(change, v=value, f=field, g=group_name):
                    if change['name'] == 'value':
                        decision = change['new'].lower()
                        self.manager.set_decision(g, f, v, decision)
                        self.manager.save()
                        self._update_counts(g, f)

                toggle.observe(on_change, names='value')

            label = widgets.HTML(
                f"<span style='font-family: monospace; margin-left: 10px;'><b>{value}</b></span> "
                f"<span style='color: gray;'>({count} MDRs)</span>"
            )
            return widgets.HBox(
                [toggle, label],
                layout=widgets.Layout(overflow='visible', min_height='32px')
            )

        def render_page():
            """Render the current page of results."""
            filtered = get_filtered_data()
            total = len(filtered)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

            # Clamp page
            self._current_page = max(0, min(self._current_page, total_pages - 1))

            start = self._current_page * PAGE_SIZE
            end = min(start + PAGE_SIZE, total)
            page_data = filtered[start:end]

            # Create widgets for this page
            rows = [create_row_widget(c) for c in page_data]
            self._decisions_container.children = rows

            # Update pagination controls
            self._page_label.value = f"<b>Page {self._current_page + 1} of {total_pages}</b> ({total} items)"
            prev_btn.disabled = (self._current_page == 0)
            next_page_btn.disabled = (self._current_page >= total_pages - 1)

        def on_filter_change(change):
            if change['name'] == 'value':
                self._filter_text = change['new']
                self._current_page = 0
                render_page()

        def on_prev(_):
            self._current_page -= 1
            render_page()

        def on_next(_):
            self._current_page += 1
            render_page()

        filter_input.observe(on_filter_change, names='value')
        prev_btn.on_click(on_prev)
        next_page_btn.on_click(on_next)

        # Bulk action buttons
        accept_all_btn = widgets.Button(description='Accept All Visible')
        defer_all_btn = widgets.Button(description='Defer All Visible')
        reject_all_btn = widgets.Button(description='Reject All Visible')

        def accept_all(_):
            filtered = get_filtered_data()
            start = self._current_page * PAGE_SIZE
            end = min(start + PAGE_SIZE, len(filtered))
            for c in filtered[start:end]:
                if c['value'] in self._decision_widgets:
                    self._decision_widgets[c['value']].value = 'Accept'

        def defer_all(_):
            filtered = get_filtered_data()
            start = self._current_page * PAGE_SIZE
            end = min(start + PAGE_SIZE, len(filtered))
            for c in filtered[start:end]:
                if c['value'] in self._decision_widgets:
                    self._decision_widgets[c['value']].value = 'Defer'

        def reject_all(_):
            filtered = get_filtered_data()
            start = self._current_page * PAGE_SIZE
            end = min(start + PAGE_SIZE, len(filtered))
            for c in filtered[start:end]:
                if c['value'] in self._decision_widgets:
                    self._decision_widgets[c['value']].value = 'Reject'

        accept_all_btn.on_click(accept_all)
        defer_all_btn.on_click(defer_all)
        reject_all_btn.on_click(reject_all)

        # Initial render
        render_page()

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
            next_btn.description = 'Review Deferred'
            next_btn.on_click(lambda _: self._navigate_to('multi_deferred', group=group_name))
        else:
            next_btn.on_click(lambda _: self._advance_phase(group_name))

        return widgets.VBox([
            widgets.HBox([filter_input, prev_btn, self._page_label, next_page_btn]),
            widgets.HBox([accept_all_btn, defer_all_btn, reject_all_btn]),
            self._decisions_container,
            self._count_display,
            widgets.HBox([back_btn, next_btn])
        ])

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

    # ==================== Multi-Deferred Review Screen ====================

    def _build_multi_deferred_screen(self, group_name: str) -> widgets.VBox:
        """Build the screen for reviewing MDRs deferred in multiple phases."""
        header = widgets.HTML(
            f"<h3>Group: {group_name} - Multi-Deferred Review</h3>"
            f"<p style='color: gray;'>Review MDRs that were deferred in 2+ phases. "
            f"These are cases where brand, generic, and/or manufacturer alone weren't "
            f"enough to decide - seeing all three together may help.</p>"
        )

        # Create content container
        content_container = widgets.VBox([
            widgets.HTML("<p><i>Loading multi-deferred MDRs...</i></p>")
        ])

        outer = widgets.VBox([header, content_container])

        # Loading indicator
        loading_indicator = widgets.HBox([
            widgets.HTML(
                "<div style='display: flex; align-items: center; padding: 20px;'>"
                "<div style='border: 4px solid #f3f3f3; border-top: 4px solid #3498db; "
                "border-radius: 50%; width: 24px; height: 24px; "
                "animation: spin 1s linear infinite; margin-right: 12px;'></div>"
                "<span style='font-size: 16px;'>Finding multi-deferred MDRs...</span>"
                "</div>"
                "<style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>"
            )
        ])

        def load_content(btn=None):
            import time
            if btn:
                btn.disabled = True
                btn.description = 'Loading...'
            content_container.children = [loading_indicator]

            try:
                multi_df = self.manager.get_multi_deferred_mdrs(self.db, group_name, min_deferrals=2)
                content = self._build_multi_deferred_content(group_name, multi_df)
                content_container.children = [content]
                time.sleep(0.1)
                content_container.layout.visibility = 'hidden'
                content_container.layout.visibility = 'visible'
            except Exception as e:
                if btn:
                    btn.disabled = False
                    btn.description = 'Load'
                err_back = widgets.Button(description='Back')
                err_back.on_click(lambda _: self._navigate_to('selection', group=group_name, phase=PHASES[-1]))
                retry_btn = widgets.Button(description='Retry', button_style='warning')
                retry_btn.on_click(load_content)
                content_container.children = [
                    widgets.HTML(f"<p style='color: red;'><b>Error:</b> {e}</p>"),
                    widgets.HBox([retry_btn, err_back])
                ]

        load_btn = widgets.Button(description='Load MDRs', button_style='primary')
        load_btn.on_click(load_content)

        back_btn = widgets.Button(description='Back')
        back_btn.on_click(lambda _: self._navigate_to('selection', group=group_name, phase=PHASES[-1]))

        content_container.children = [
            widgets.HTML("<p>Click 'Load MDRs' to find MDRs deferred in multiple phases.</p>"),
            widgets.HBox([load_btn, back_btn])
        ]

        return outer

    def _build_multi_deferred_content(self, group_name: str, multi_df) -> widgets.VBox:
        """Build the content for multi-deferred review."""
        if len(multi_df) == 0:
            no_items = widgets.HTML(
                "<p style='font-style: italic; color: green;'>"
                "No MDRs were deferred in multiple phases. You can proceed to summary.</p>"
            )
            next_btn = widgets.Button(description='View Summary', button_style='primary')
            next_btn.on_click(lambda _: self._navigate_to('summary', group=group_name))

            back_btn = widgets.Button(description='Back')
            back_btn.on_click(lambda _: self._navigate_to('selection', group=group_name, phase=PHASES[-1]))

            return widgets.VBox([no_items, widgets.HBox([back_btn, next_btn])])

        # Group by unique (brand, generic, manufacturer) combinations
        grouped = multi_df.groupby(
            ['BRAND_NAME', 'GENERIC_NAME', 'MANUFACTURER_D_NAME'],
            dropna=False
        ).agg({
            'MDR_REPORT_KEY': list,
            'defer_count': 'first'
        }).reset_index()

        grouped['mdr_count'] = grouped['MDR_REPORT_KEY'].apply(len)
        grouped = grouped.sort_values(['defer_count', 'mdr_count'], ascending=[False, False])

        # Pagination
        PAGE_SIZE = 10
        self._md_current_page = 0
        self._md_data = grouped.to_dict('records')
        self._md_decisions = {}  # (brand, generic, mfr) -> 'accept' | 'reject'

        # Container for rows
        self._md_container = widgets.VBox(
            [],
            layout=widgets.Layout(
                max_height='500px',
                overflow_y='auto',
                border='1px solid #ddd',
                padding='10px'
            )
        )

        # Page controls
        self._md_page_label = widgets.HTML()
        prev_btn = widgets.Button(description='< Prev', disabled=True)
        next_page_btn = widgets.Button(description='Next >')

        def render_md_page():
            total = len(self._md_data)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            self._md_current_page = max(0, min(self._md_current_page, total_pages - 1))

            start = self._md_current_page * PAGE_SIZE
            end = min(start + PAGE_SIZE, total)
            page_data = self._md_data[start:end]

            rows = []
            for item in page_data:
                brand = item['BRAND_NAME'] or '(none)'
                generic = item['GENERIC_NAME'] or '(none)'
                mfr = item['MANUFACTURER_D_NAME'] or '(none)'
                mdr_count = item['mdr_count']
                defer_count = item['defer_count']

                key = (item['BRAND_NAME'], item['GENERIC_NAME'], item['MANUFACTURER_D_NAME'])

                # Decision toggle
                current = self._md_decisions.get(key, 'defer')
                toggle = widgets.ToggleButtons(
                    options=['Accept', 'Defer', 'Reject'],
                    value=current.capitalize(),
                    button_style='',
                    layout=widgets.Layout(width='auto'),
                    style={'button_width': '60px'}
                )

                def on_change(change, k=key):
                    if change['name'] == 'value':
                        self._md_decisions[k] = change['new'].lower()

                toggle.observe(on_change, names='value')

                # Info label
                label = widgets.HTML(
                    f"<div style='margin-left: 10px; font-family: monospace;'>"
                    f"<b>Brand:</b> {brand}<br>"
                    f"<b>Generic:</b> {generic}<br>"
                    f"<b>Manufacturer:</b> {mfr}<br>"
                    f"<span style='color: gray;'>({mdr_count} MDRs, deferred in {defer_count} phases)</span>"
                    f"</div>"
                )

                row = widgets.HBox(
                    [toggle, label],
                    layout=widgets.Layout(
                        border_bottom='1px solid #eee',
                        padding='5px 0',
                        overflow='visible'
                    )
                )
                rows.append(row)

            self._md_container.children = rows
            self._md_page_label.value = f"<b>Page {self._md_current_page + 1} of {total_pages}</b> ({total} unique combinations)"
            prev_btn.disabled = (self._md_current_page == 0)
            next_page_btn.disabled = (self._md_current_page >= total_pages - 1)

        def on_prev(_):
            self._md_current_page -= 1
            render_md_page()

        def on_next(_):
            self._md_current_page += 1
            render_md_page()

        prev_btn.on_click(on_prev)
        next_page_btn.on_click(on_next)

        # Bulk actions
        accept_all_btn = widgets.Button(description='Accept All Visible')
        reject_all_btn = widgets.Button(description='Reject All Visible')

        def accept_all_visible(_):
            start = self._md_current_page * PAGE_SIZE
            end = min(start + PAGE_SIZE, len(self._md_data))
            for item in self._md_data[start:end]:
                key = (item['BRAND_NAME'], item['GENERIC_NAME'], item['MANUFACTURER_D_NAME'])
                self._md_decisions[key] = 'accept'
            render_md_page()

        def reject_all_visible(_):
            start = self._md_current_page * PAGE_SIZE
            end = min(start + PAGE_SIZE, len(self._md_data))
            for item in self._md_data[start:end]:
                key = (item['BRAND_NAME'], item['GENERIC_NAME'], item['MANUFACTURER_D_NAME'])
                self._md_decisions[key] = 'reject'
            render_md_page()

        accept_all_btn.on_click(accept_all_visible)
        reject_all_btn.on_click(reject_all_visible)

        # Initial render
        render_md_page()

        # Navigation
        back_btn = widgets.Button(description='Back')
        back_btn.on_click(lambda _: self._navigate_to('selection', group=group_name, phase=PHASES[-1]))

        next_btn = widgets.Button(description='Save & View Summary', button_style='primary')

        def save_and_continue(_):
            # Apply decisions to the actual group
            # For accepted: mark all three field values as accepted
            # For rejected: mark all three field values as rejected
            group = self.manager.groups[group_name]

            for (brand, generic, mfr), decision in self._md_decisions.items():
                if decision == 'accept':
                    # Move from deferred to accepted in each phase
                    if brand and brand in group['decisions']['brand_name']['deferred']:
                        group['decisions']['brand_name']['deferred'].remove(brand)
                        group['decisions']['brand_name']['accepted'].append(brand)
                    if generic and generic in group['decisions']['generic_name']['deferred']:
                        group['decisions']['generic_name']['deferred'].remove(generic)
                        group['decisions']['generic_name']['accepted'].append(generic)
                    if mfr and mfr in group['decisions']['manufacturer']['deferred']:
                        group['decisions']['manufacturer']['deferred'].remove(mfr)
                        group['decisions']['manufacturer']['accepted'].append(mfr)
                elif decision == 'reject':
                    # Move from deferred to rejected in each phase
                    if brand and brand in group['decisions']['brand_name']['deferred']:
                        group['decisions']['brand_name']['deferred'].remove(brand)
                        group['decisions']['brand_name']['rejected'].append(brand)
                    if generic and generic in group['decisions']['generic_name']['deferred']:
                        group['decisions']['generic_name']['deferred'].remove(generic)
                        group['decisions']['generic_name']['rejected'].append(generic)
                    if mfr and mfr in group['decisions']['manufacturer']['deferred']:
                        group['decisions']['manufacturer']['deferred'].remove(mfr)
                        group['decisions']['manufacturer']['rejected'].append(mfr)

            self.manager.save()
            self._navigate_to('summary', group=group_name)

        next_btn.on_click(save_and_continue)

        # Count summary
        count_html = widgets.HTML(
            f"<p><b>{len(multi_df)} MDRs</b> in <b>{len(grouped)} unique combinations</b> "
            f"were deferred in multiple phases.</p>"
        )

        return widgets.VBox([
            count_html,
            widgets.HBox([prev_btn, self._md_page_label, next_page_btn]),
            widgets.HBox([accept_all_btn, reject_all_btn]),
            self._md_container,
            widgets.HBox([back_btn, next_btn])
        ])

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
        back_btn = widgets.Button(description='Back')
        back_btn.on_click(lambda _: self._navigate_to('multi_deferred', group=group_name))

        self._finish_btn = widgets.Button(
            description='Finish & Save',
            button_style='success'
        )
        self._finish_btn.on_click(lambda _: self._on_finish(group_name))

        self._finish_output = widgets.Output()

        return widgets.VBox([
            header,
            summary_html,
            warning,
            widgets.HBox([back_btn, self._finish_btn]),
            self._finish_output
        ])

    def _on_finish(self, group_name: str):
        """Handle finish button click - finalize and return to main."""
        # Show loading state immediately
        self._finish_btn.disabled = True
        self._finish_btn.description = 'Saving...'

        with self._finish_output:
            clear_output()
            print("Finalizing group and capturing MDR keys...")

        try:
            result = self.manager.finalize_group(self.db, group_name)
            self.manager.save()
            with self._finish_output:
                clear_output()
                print(f"Group finalized!")
                print(f"  - {result['event_count']} events captured ({result['mdr_count']} unique MDRs)")
                if result['pending_count'] > 0:
                    print(f"  - {result['pending_count']} deferred values excluded")
        except Exception as e:
            with self._finish_output:
                clear_output()
                print(f"Error finalizing: {e}")
            # Re-enable button on error
            self._finish_btn.disabled = False
            self._finish_btn.description = 'Finish & Save'
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
