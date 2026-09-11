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
    'device_problem': {
        'file_prefix': 'foidevproblem',
        'pattern_type': 'cumulative',       # foidevproblem_thru{year}.zip + foidevproblem.zip
        'current_year_prefix': 'foidevproblem',
        'thru_separator': '_',              # filename: foidevproblem_thru{year}.zip
        'start_year': 1993,                 # device problem codes predate the 2000 cutoff used elsewhere
        # No date_column: joins to master via MDR_REPORT_KEY only.
        # File has no header row and ships with either 2 or 3 columns
        # depending on release year (DATE_ADDED_FLAG was added later);
        # headerless_columns is sliced to the file's actual width in _load_all.
        'headerless_columns': ['MDR_REPORT_KEY', 'DEVICE_PROBLEM_CODE', 'DATE_ADDED_FLAG'],
        'description': 'Device problem codes',
    },
    'patient_problem': {
        'file_prefix': 'patientproblemcode',
        'pattern_type': 'cumulative',       # patientproblemcode_thru{year}.zip + patientproblemcode.zip
        'current_year_prefix': 'patientproblemcode',
        'thru_separator': '_',              # filename: patientproblemcode_thru{year}.zip
        # Confirmed against the real downloaded file (FDA's own summary page
        # undersells this — it describes a 2-column headerless file, but the
        # actual file has a header row and DATE_ADDED values from 1993-2026).
        'start_year': 1993,
        # No date_column: kept as a simple whole-file-load table like
        # device_problem/patient, even though the file's real DATE_ADDED
        # column could support per-year tracking — start_year above is only
        # a request-validation gate (see _validate()/_process_cumulative_table()).
        # File HAS a header row (MDR_REPORT_KEY|PATIENT_SEQUENCE_NO|
        # PROBLEM_CODE|DATE_ADDED|DATE_CHANGED) — unlike device_problem, this
        # is not headerless, so it loads via the normal header-driven path.
        # PROBLEM_CODE is renamed to PATIENT_PROBLEM_CODE for API consistency
        # with DEVICE_PROBLEM_CODE.
        'column_renames': {'PROBLEM_CODE': 'PATIENT_PROBLEM_CODE'},
        'description': 'Patient problem codes',
    },
}
