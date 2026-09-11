"""
Shared fixtures for PyMAUDE tests.

All fixtures use synthetic data that mimics the MAUDE pipe-delimited format.
No FDA downloads are required to run the test suite.
"""

import pytest
import os


# ── Synthetic MAUDE data fixtures ─────────────────────────────────────────────

MASTER_CSV = """\
MDR_REPORT_KEY|EVENT_KEY|DATE_RECEIVED|EVENT_TYPE|MANUFACTURER_G1_NAME|PMA_PMN_NUM
1001|2001|01/15/2020|D|MEDTRONIC|P180037
1002|2002|03/20/2020|IN|BOSTON SCIENTIFIC|K193456
1003|2003|06/10/2020|M|COOK MEDICAL|K201234
1004|2004|03/15/2020|M|ARGON MEDICAL|K150001
"""

DEVICE_CSV = """\
MDR_REPORT_KEY|BRAND_NAME|GENERIC_NAME|MANUFACTURER_D_NAME|DEVICE_REPORT_PRODUCT_CODE|DATE_RECEIVED
1001|VENOVO|VENOUS STENT|MEDTRONIC|NIQ|01/15/2020
1002|VICI|VENOUS STENT SYSTEM|BOSTON SCIENTIFIC|NIQ|03/20/2020
1003|ZILVER|BILIARY STENT|COOK MEDICAL|OCA|06/10/2020
1004|CLEANER XT|ROTATIONAL THROMBECTOMY SYSTEM|ARGON MEDICAL|GZC|03/15/2020
"""

TEXT_CSV = """\
MDR_REPORT_KEY|FOI_TEXT
1001|PATIENT DEVELOPED STENT MIGRATION AFTER IMPLANT
1002|DEVICE MALDEPLOYED DURING VENOUS STENT PLACEMENT
1003|STENT FRACTURED POST IMPLANTATION
1004|ROTATIONAL THROMBECTOMY DEVICE STALLED DURING USE
"""

PATIENT_CSV = """\
MDR_REPORT_KEY|SEQUENCE_NUMBER_OUTCOME|PATIENT_AGE|PATIENT_SEX|DATE_RECEIVED
1001|D|56 YR|Male|01/15/2020
1002|L|34 YR|Female|03/20/2020
1003|H|NA|Unknown|06/10/2020
1004|H; O|70 YR|Male|11/01/2019
"""

DEVICE_PROBLEMS_THRU_CSV = """\
1001|1546|
1002|2993|
1003|1546|
"""

# Overlaps with DEVICE_PROBLEMS_THRU_CSV on (1001, 1546); adds one new row.
DEVICE_PROBLEMS_CURRENT_CSV = """\
1001|1546|
1004|9999|
"""

# Unlike DEVICE_PROBLEMS_*, the real patientproblemcode files have a header
# row and 3 extra columns (PATIENT_SEQUENCE_NO, DATE_ADDED, DATE_CHANGED)
# alongside the code column, which ships as PROBLEM_CODE (renamed to
# PATIENT_PROBLEM_CODE via TABLE_METADATA's column_renames).
PATIENT_PROBLEMS_THRU_CSV = """\
MDR_REPORT_KEY|PATIENT_SEQUENCE_NO|PROBLEM_CODE|DATE_ADDED|DATE_CHANGED
1001|1|1029|2020/01/01 00:00:00|2020/01/01 00:00:00
1002|1|1030|2020/01/01 00:00:00|2020/01/01 00:00:00
1003|1|1029|2020/01/01 00:00:00|2020/01/01 00:00:00
"""

# Overlaps with PATIENT_PROBLEMS_THRU_CSV on (1001, 1029); adds one new row.
PATIENT_PROBLEMS_CURRENT_CSV = """\
MDR_REPORT_KEY|PATIENT_SEQUENCE_NO|PROBLEM_CODE|DATE_ADDED|DATE_CHANGED
1001|1|1029|2020/01/01 00:00:00|2020/01/01 00:00:00
1004|1|1099|2020/01/01 00:00:00|2020/01/01 00:00:00
"""


@pytest.fixture
def data_dir(tmp_path):
    """Write synthetic MAUDE CSV files to a temp directory."""
    d = tmp_path / 'maude_data'
    d.mkdir()

    # Master: cumulative file (mdrfoithru{year}.txt pattern)
    (d / 'mdrfoithru2020.txt').write_text(MASTER_CSV)

    # Device: yearly file
    (d / 'device2020.txt').write_text(DEVICE_CSV)
    # Also write a 2019 device file for multi-year tests
    (d / 'device2019.txt').write_text(DEVICE_CSV.replace('2020', '2019'))

    # Text: yearly file
    (d / 'foitext2020.txt').write_text(TEXT_CSV)

    # Patient: cumulative (no year suffix in filename pattern)
    (d / 'patientthru2020.txt').write_text(PATIENT_CSV)

    # Device problems: cumulative thru file + current-year file (no header row in real data)
    (d / 'foidevproblem_thru2025.txt').write_text(DEVICE_PROBLEMS_THRU_CSV)
    (d / 'foidevproblem.txt').write_text(DEVICE_PROBLEMS_CURRENT_CSV)

    # Patient problems: cumulative thru file + current-year file (no header row in real data)
    (d / 'patientproblemcode_thru2025.txt').write_text(PATIENT_PROBLEMS_THRU_CSV)
    (d / 'patientproblemcode.txt').write_text(PATIENT_PROBLEMS_CURRENT_CSV)

    return str(d)


@pytest.fixture
def db(tmp_path, data_dir):
    """MaudeDatabase pre-loaded with 2020 data across all tables."""
    from pymaude import MaudeDatabase
    database = MaudeDatabase(
        str(tmp_path / 'test.duckdb'),
        data_dir=data_dir,
        verbose=False,
    )
    database.add_years(2020, tables=['master', 'device', 'text', 'patient',
                                      'device_problem', 'patient_problem'])
    yield database
    database.close()
