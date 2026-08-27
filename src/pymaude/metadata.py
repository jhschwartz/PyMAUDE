# metadata.py - MAUDE table configuration
# Copyright (C) 2026 Jacob Schwartz <jaschwa@umich.edu>
# GNU GPL v3

FDA_BASE_URL = "https://www.accessdata.fda.gov/MAUDE/ftparea"
FDA_PREMARKET_URL = "https://www.accessdata.fda.gov/premarket/ftparea"

# Table metadata: file patterns, availability, and structure
TABLE_METADATA = {
    'master': {
        'file_prefix': 'mdrfoi',
        'pattern_type': 'cumulative',       # mdrfoithru{year}.zip
        'current_year_prefix': 'mdrfoi',    # mdrfoi.zip for current year
        'start_year': 2000,
        'date_column': 'DATE_RECEIVED',
        'description': 'Master records (adverse event reports)',
    },
    'device': {
        'file_prefix': 'foidev',
        'pattern_type': 'yearly',           # device{year}.zip (special naming)
        'current_year_prefix': 'device',    # device.zip for current year
        'start_year': 2000,
        'date_column': 'DATE_RECEIVED',
        'description': 'Device information',
    },
    'text': {
        'file_prefix': 'foitext',
        'pattern_type': 'yearly',           # foitext{year}.zip
        'current_year_prefix': 'foitext',
        'start_year': 2000,
        'description': 'Event narrative text (FOI_TEXT)',
    },
    'patient': {
        'file_prefix': 'patient',
        'pattern_type': 'cumulative',       # patientthru{year}.zip
        'current_year_prefix': 'patient',
        'start_year': 2000,
        # No date_column: patient table has no date field; joins to master via MDR_REPORT_KEY.
        # The entire cumulative file is loaded (no year filtering possible).
        'description': 'Patient demographics and outcomes',
        'size_warning': (
            'Patient data is distributed as a single large cumulative file. '
            'All historical data will be downloaded and loaded.'
        ),
    },
    'problems': {
        'file_prefix': 'foidevproblem',
        'pattern_type': 'single',           # foidevproblem.zip (one file, all years)
        'start_year': 2019,
        'description': 'Device problem codes (available from 2019)',
    },
}
