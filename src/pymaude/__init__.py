# PyMAUDE - FDA MAUDE Database Interface (DuckDB backend)
# Copyright (C) 2026 Jacob Schwartz <jaschwa@umich.edu>
# GNU GPL v3

from .database import MaudeDatabase
from .search_strategy import DeviceSearchStrategy
from .metadata import TABLE_METADATA, FDA_BASE_URL

__version__ = '2.0.0'
__author__ = 'Jacob Schwartz <jaschwa@umich.edu>'
__all__ = [
    'MaudeDatabase',
    'DeviceSearchStrategy',
    'TABLE_METADATA',
    'FDA_BASE_URL',
]
