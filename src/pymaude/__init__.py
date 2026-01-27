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

    # Basic setup
    db = MaudeDatabase('maude.db')
    db.add_years('2015-2024', tables=['master', 'device'], download=True)

    # Simple query
    results = db.query_device(device_name='thrombectomy')

    # Boolean search with AND/OR logic
    db.create_search_index()  # One-time setup for fast searches
    results = db.search_by_device_names([['argon', 'cleaner'], ['angiojet']])
"""

from .database import MaudeDatabase
from .metadata import TABLE_METADATA, TABLE_FILES, FDA_BASE_URL

__version__ = '1.0.0'
__author__ = 'Jacob Schwartz <jaschwa@umich.edu>'
__all__ = [
    'MaudeDatabase',
    'TABLE_METADATA',
    'TABLE_FILES',
    'FDA_BASE_URL',
]
