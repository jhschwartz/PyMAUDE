# metadata.py - MAUDE table configuration
# Copyright (C) 2026 Jacob Schwartz <jaschwa@umich.edu>
# MIT License

FDA_BASE_URL = "https://www.accessdata.fda.gov/MAUDE/ftparea"
FDA_PREMARKET_URL = "https://www.accessdata.fda.gov/premarket/ftparea"

# Table metadata: file patterns, availability, and structure
TABLE_METADATA = {
    'master': {
        'file_prefix': 'mdrfoi',
        'pattern_type': 'cumulative',       # mdrfoithru{year}.zip
        'current_year_prefix': 'mdrfoi',    # mdrfoi.zip for current year
        'start_year': 1991,
        'date_column': 'DATE_RECEIVED',
        'description': 'Master records (adverse event reports)',
    },
    'device': {
        'file_prefix': 'foidev',
        'pattern_type': 'yearly',           # device{year}.zip (special naming)
        'current_year_prefix': 'device',    # device.zip for current year
        'start_year': 1991,
        'legacy_cumulative_thru': 1997,     # 1991-1997 ship as one foidevthru1997.zip;
                                             # 1998-1999 as foidev{year}.zip; 2000+ as device{year}.zip
        'date_column': 'DATE_RECEIVED',
        'description': 'Device information',
    },
    'text': {
        'file_prefix': 'foitext',
        'pattern_type': 'yearly',           # foitext{year}.zip
        'current_year_prefix': 'foitext',
        'start_year': 1996,                 # foitextthru1995.zip (pre-1996, cumulative) not yet supported
        'description': 'Event narrative text (FOI_TEXT)',
    },
    'patient': {
        'file_prefix': 'patient',
        'pattern_type': 'cumulative',       # patientthru{year}.zip
        'current_year_prefix': 'patient',
        'start_year': 1991,
        # No date_column: patient table has no date field; joins to master via MDR_REPORT_KEY.
        # The entire cumulative file is loaded (no year filtering possible).
        'description': 'Patient demographics and outcomes',
        'size_warning': (
            'Patient data is distributed as a single large cumulative file. '
            'All historical data will be downloaded and loaded.'
        ),
    },
    'problem': {
        'file_prefix': 'foidevproblem',
        'pattern_type': 'cumulative',       # foidevproblem_thru{year}.zip + foidevproblem.zip
        'current_year_prefix': 'foidevproblem',
        'thru_separator': '_',              # filename: foidevproblem_thru{year}.zip
        'start_year': 1993,                 # device problem codes predate the 2000 cutoff used elsewhere
        'description': 'Device problem codes',
    },
}
