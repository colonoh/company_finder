import pytest
from datetime import date
from importer import get_quarter_index_url, get_quarters_in_range, parse_form_idx


def test_get_quarter_index_url():
    assert get_quarter_index_url(2024, 1) == \
        "https://www.sec.gov/Archives/edgar/full-index/2024/QTR1/form.idx"
    assert get_quarter_index_url(2023, 4) == \
        "https://www.sec.gov/Archives/edgar/full-index/2023/QTR4/form.idx"


def test_get_quarters_in_range_count():
    assert len(get_quarters_in_range(20)) == 20


def test_get_quarters_in_range_excludes_current():
    today = date.today()
    current = f"{today.year}Q{(today.month - 1) // 3 + 1}"
    assert current not in get_quarters_in_range(4)


def test_get_quarters_in_range_oldest_first_when_reversed():
    quarters = get_quarters_in_range(4)
    # Most recent is first; reversed gives oldest first
    assert quarters[0] > quarters[-1]


SAMPLE_FORM_IDX = """\
Company Name                                                   Form Type   CIK         Date Filed  Filename
------------------------------------------------------------------------------------------------------------------------------------------------
ACME STARTUP INC                                               D           0001234567  2024-01-15  edgar/data/1234567/0001234567-24-000001-index.htm
BIG FUND LP                                                    D/A         0009876543  2024-01-16  edgar/data/9876543/0009876543-24-000002-index.htm
SOME PUBLIC CO                                                 10-K        0001111111  2024-01-17  edgar/data/1111111/0001111111-24-000003-index.htm
CROWD CORP                                                     C           0002222222  2024-01-18  edgar/data/2222222/0002222222-24-000004-index.htm
"""


def test_parse_form_idx_filters_d_and_c():
    results = parse_form_idx(SAMPLE_FORM_IDX)
    assert len(results) == 3
    assert {r["form_type"] for r in results} == {"D", "D/A", "C"}


def test_parse_form_idx_extracts_fields():
    results = parse_form_idx(SAMPLE_FORM_IDX)
    acme = next(r for r in results if "ACME" in r["company_name"])
    assert acme["cik"] == "0001234567"
    assert acme["filed_date"] == "2024-01-15"
    assert acme["filename"] == "edgar/data/1234567/0001234567-24-000001-index.htm"


def test_parse_form_idx_empty_content():
    assert parse_form_idx("") == []
