#!/usr/bin/env python3
"""
Tests for the SelectionWidget module.

These tests verify basic widget functionality.
More comprehensive widget testing is done in notebooks/test_selection_widget.ipynb.

Note: Tests require ipywidgets to be installed.
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import Mock
import pandas as pd

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymaude.selection import SelectionManager


# ==================== Fixtures ====================

@pytest.fixture
def temp_json_path(tmp_path):
    """Provide a temporary JSON file path."""
    return str(tmp_path / "test_selection.json")


@pytest.fixture
def mock_db():
    """Create a mock database for testing."""
    db = Mock()
    db.db_path = '/path/to/test.db'
    return db


@pytest.fixture
def manager(temp_json_path, mock_db):
    """Create a manager with one group."""
    manager = SelectionManager('test_project', temp_json_path, mock_db.db_path)
    manager.create_group('test_group', ['device', 'test'])
    return manager


# ==================== Widget Import Tests ====================

class TestWidgetImport:
    """Tests for widget module import behavior."""

    def test_import_sets_availability_flag(self):
        """Test that importing sets IPYWIDGETS_AVAILABLE flag."""
        from pymaude.selection_widget import IPYWIDGETS_AVAILABLE

        assert isinstance(IPYWIDGETS_AVAILABLE, bool)

    @pytest.mark.skipif(
        "ipywidgets" not in sys.modules,
        reason="ipywidgets not available"
    )
    def test_widget_creation_with_ipywidgets(self, manager, mock_db):
        """Test that widget can be created when ipywidgets is available."""
        from pymaude.selection_widget import SelectionWidget, IPYWIDGETS_AVAILABLE

        if IPYWIDGETS_AVAILABLE:
            widget = SelectionWidget(manager, mock_db)
            assert widget is not None


# ==================== Widget State Tests ====================

class TestWidgetState:
    """Tests for widget state management."""

    @pytest.fixture
    def widget(self, manager, mock_db):
        """Create a widget instance if ipywidgets is available."""
        try:
            from pymaude.selection_widget import SelectionWidget, IPYWIDGETS_AVAILABLE
            if not IPYWIDGETS_AVAILABLE:
                pytest.skip("ipywidgets not available")
            return SelectionWidget(manager, mock_db)
        except ImportError:
            pytest.skip("ipywidgets not available")

    def test_initial_state(self, widget):
        """Test that widget initializes with correct state."""
        assert widget.current_screen == 'main'
        assert widget.current_group is None
        assert widget.current_phase is None
        assert widget.results is None

    def test_manager_reference(self, widget, manager):
        """Test that widget maintains reference to manager."""
        assert widget.manager is manager

    def test_db_reference(self, widget, mock_db):
        """Test that widget maintains reference to database."""
        assert widget.db is mock_db


# ==================== Navigation Tests ====================

class TestWidgetNavigation:
    """Tests for widget navigation methods."""

    @pytest.fixture
    def widget(self, manager, mock_db):
        """Create a widget instance if ipywidgets is available."""
        try:
            from pymaude.selection_widget import SelectionWidget, IPYWIDGETS_AVAILABLE
            if not IPYWIDGETS_AVAILABLE:
                pytest.skip("ipywidgets not available")
            return SelectionWidget(manager, mock_db)
        except ImportError:
            pytest.skip("ipywidgets not available")

    def test_navigate_to_main(self, widget):
        """Test navigating to main screen."""
        widget.current_screen = 'selection'
        widget._navigate_to('main')

        assert widget.current_screen == 'main'
        assert widget.current_group is None

    def test_navigate_to_add_group(self, widget):
        """Test navigating to add group screen."""
        widget._navigate_to('add_group')

        assert widget.current_screen == 'add_group'

    def test_navigate_to_selection(self, widget):
        """Test navigating to selection screen."""
        widget._navigate_to('selection', group='test_group', phase='brand_name')

        assert widget.current_screen == 'selection'
        assert widget.current_group == 'test_group'
        assert widget.current_phase == 'brand_name'

    def test_navigate_to_multi_deferred(self, widget):
        """Test navigating to multi-deferred screen."""
        widget._navigate_to('multi_deferred', group='test_group')

        assert widget.current_screen == 'multi_deferred'
        assert widget.current_group == 'test_group'

    def test_navigate_to_summary(self, widget):
        """Test navigating to summary screen."""
        widget._navigate_to('summary', group='test_group')

        assert widget.current_screen == 'summary'
        assert widget.current_group == 'test_group'


# ==================== Home Button Tests ====================

class TestHomeButton:
    """Tests for Home button in add_group screen."""

    @pytest.fixture
    def widget(self, manager, mock_db):
        """Create a widget instance if ipywidgets is available."""
        try:
            from pymaude.selection_widget import SelectionWidget, IPYWIDGETS_AVAILABLE
            if not IPYWIDGETS_AVAILABLE:
                pytest.skip("ipywidgets not available")
            return SelectionWidget(manager, mock_db)
        except ImportError:
            pytest.skip("ipywidgets not available")

    def test_add_group_screen_has_home_button(self, widget):
        """Test that add_group screen contains a Home button."""
        screen = widget._build_add_group_screen()

        # Traverse widget tree to find buttons
        def find_buttons(w):
            buttons = []
            try:
                import ipywidgets as widgets
                if isinstance(w, widgets.Button):
                    buttons.append(w)
                if hasattr(w, 'children'):
                    for child in w.children:
                        buttons.extend(find_buttons(child))
            except ImportError:
                pass
            return buttons

        buttons = find_buttons(screen)
        button_descriptions = [b.description for b in buttons]

        # Should have Home button (with house emoji)
        assert any('Home' in desc for desc in button_descriptions), \
            f"Expected Home button in add_group screen, found: {button_descriptions}"

    def test_home_button_navigates_to_main(self, widget):
        """Test that clicking Home button navigates to main screen."""
        widget._navigate_to('add_group')
        assert widget.current_screen == 'add_group'

        screen = widget._build_add_group_screen()

        # Find and click Home button
        def find_home_button(w):
            try:
                import ipywidgets as widgets
                if isinstance(w, widgets.Button) and 'Home' in w.description:
                    return w
                if hasattr(w, 'children'):
                    for child in w.children:
                        result = find_home_button(child)
                        if result:
                            return result
            except ImportError:
                pass
            return None

        home_btn = find_home_button(screen)
        assert home_btn is not None

        # Simulate click (trigger the callback)
        for handler in home_btn._click_handlers.callbacks:
            handler(home_btn)

        assert widget.current_screen == 'main'

    def test_home_button_saves_before_navigating(self, widget, tmp_path, manager):
        """Test that clicking Home button saves the manager state."""
        import json

        widget._navigate_to('add_group')
        screen = widget._build_add_group_screen()

        # Find Home button
        def find_home_button(w):
            try:
                import ipywidgets as widgets
                if isinstance(w, widgets.Button) and 'Home' in w.description:
                    return w
                if hasattr(w, 'children'):
                    for child in w.children:
                        result = find_home_button(child)
                        if result:
                            return result
            except ImportError:
                pass
            return None

        home_btn = find_home_button(screen)

        # Click Home button
        for handler in home_btn._click_handlers.callbacks:
            handler(home_btn)

        # Verify that save was called (file should exist with current state)
        with open(manager.file_path, 'r') as f:
            saved_data = json.load(f)

        assert saved_data['name'] == manager.name
        assert 'test_group' in saved_data['groups']
