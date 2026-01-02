# metadata.py - MAUDE Database Metadata Configuration
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
MAUDE database table metadata and configuration.

Defines file patterns, availability, and characteristics for each MAUDE table type.
"""

# Table metadata defining file patterns, availability, and characteristics
TABLE_METADATA = {
    'master': {
        'file_prefix': 'mdrfoi',
        'pattern_type': 'cumulative',  # Uses mdrfoithru{year}.zip
        'start_year': 1991,
        'current_year_prefix': 'mdrfoi',  # For current year: mdrfoi.zip
        'size_category': 'large',
        'description': 'Master records (adverse event reports)',
        'date_column': 'DATE_RECEIVED'  # For filtering cumulative files
    },
    'device': {
        'file_prefix': 'foidev',
        'pattern_type': 'yearly',  # Uses foidev{year}.zip
        'start_year': 1998,
        'current_year_prefix': 'device',  # For current year: device.zip
        'size_category': 'medium',
        'description': 'Device information',
        'date_column': 'DATE_RECEIVED'  # For filtering when force_refresh is used
    },
    'text': {
        'file_prefix': 'foitext',
        'pattern_type': 'yearly',  # Uses foitext{year}.zip
        'start_year': 1996,
        'current_year_prefix': 'foitext',  # For current year: foitext.zip
        'size_category': 'medium',
        'description': 'Event narrative text'
    },
    'patient': {
        'file_prefix': 'patient',
        'pattern_type': 'cumulative',  # Uses patientthru{year}.zip
        'start_year': 1996,
        'current_year_prefix': 'patient',  # For current year: patient.zip
        'size_category': 'very_large',
        'description': 'Patient demographics',
        'size_warning': 'Patient data is distributed as a single large file (117MB compressed, 841MB uncompressed). All data will be downloaded even if you only need specific years.'
        # Note: Patient table doesn't have a date column for filtering - it joins to master via mdr_report_key
    },
    'problems': {
        'file_prefix': 'foidevproblem',
        'pattern_type': 'yearly',
        'start_year': 2019,  # Approximate - recent years only
        'current_year_prefix': 'foidevproblem',
        'size_category': 'small',
        'description': 'Device problem codes'
    }
}

# Legacy mapping (for backwards compatibility)
TABLE_FILES = {
    'master': 'mdrfoi',
    'device': 'foidev',
    'patient': 'patient',
    'text': 'foitext',
    'problems': 'foidevproblem'
}

# FDA base URL for MAUDE data downloads
FDA_BASE_URL = "https://www.accessdata.fda.gov/MAUDE/ftparea"