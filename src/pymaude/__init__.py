# __init__.py - MAUDE Database Package
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
PyMAUDE - FDA MAUDE Database Interface

A Python package for downloading, managing, and querying FDA MAUDE
(Manufacturer and User Facility Device Experience) database.

Usage:
    from pymaude import MaudeDatabase

    db = MaudeDatabase('maude.db')
    db.add_years('2015-2024', tables=['master', 'device'], download=True)
    results = db.query_device(device_name='thrombectomy')

For interactive device selection:
    from pymaude import MaudeDatabase, SelectionManager
    from pymaude.selection_widget import SelectionWidget

    db = MaudeDatabase('maude.db')
    manager = SelectionManager('my_project', 'selections.json', db.db_path)
    widget = SelectionWidget(manager, db)
    widget.display()
"""

from .database import MaudeDatabase
from .metadata import TABLE_METADATA, TABLE_FILES, FDA_BASE_URL
from .selection import SelectionManager, SelectionResults

__version__ = '1.0.0'
__author__ = 'Jacob Schwartz <jaschwa@umich.edu>'
__all__ = [
    'MaudeDatabase',
    'TABLE_METADATA',
    'TABLE_FILES',
    'FDA_BASE_URL',
    'SelectionManager',
    'SelectionResults',
]
