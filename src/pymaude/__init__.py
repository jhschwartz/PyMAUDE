# PyMAUDE - FDA MAUDE Database Interface (DuckDB backend)
# Copyright (C) 2026 Jacob Schwartz <jaschwa@umich.edu>
# MIT License

from .database import MaudeDatabase
from .archive import verify_archive, extract_raw
from .metadata import TABLE_METADATA, FDA_BASE_URL

__version__ = '0.3.0'
__author__ = 'Jacob Schwartz <jaschwa@umich.edu>'
__all__ = [
    'MaudeDatabase',
    'TABLE_METADATA',
    'FDA_BASE_URL',
    'verify_archive',
    'extract_raw',
]
