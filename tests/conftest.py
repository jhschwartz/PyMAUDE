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
MDR_REPORT_KEY|SEQUENCE_NUMBER_OUTCOME|DATE_RECEIVED
1001|D|01/15/2020
1002|IN|03/20/2020
1003|H|06/10/2020
1004|H;IN|11/01/2019
"""

PROBLEMS_THRU_CSV = """\
1001|1546|
1002|2993|
1003|1546|
"""

# Overlaps with PROBLEMS_THRU_CSV on (1001, 1546); adds one new row.
PROBLEMS_CURRENT_CSV = """\
1001|1546|
1004|9999|
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

    # Problems: cumulative thru file + current-year file (no header row in real data)
    (d / 'foidevproblem_thru2025.txt').write_text(PROBLEMS_THRU_CSV)
    (d / 'foidevproblem.txt').write_text(PROBLEMS_CURRENT_CSV)

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
    database.add_years(2020, tables=['master', 'device', 'text', 'patient', 'problem'])
    yield database
    database.close()
