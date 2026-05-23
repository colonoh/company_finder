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
Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------------------------------------
D           ACME STARTUP INC                                              0001234567  2024-01-15  edgar/data/1234567/0001234567-24-000001-index.htm
D/A         BIG FUND LP                                                   0009876543  2024-01-16  edgar/data/9876543/0009876543-24-000002-index.htm
10-K        SOME PUBLIC CO                                                0001111111  2024-01-17  edgar/data/1111111/0001111111-24-000003-index.htm
C           CROWD CORP                                                    0002222222  2024-01-18  edgar/data/2222222/0002222222-24-000004-index.htm
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


from importer import index_filename_to_xml_url, parse_form_d_xml

SAMPLE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <primaryIssuer>
    <cik>0001234567</cik>
    <entityName>ACME STARTUP INC</entityName>
    <issuerAddress>
      <street1>123 Main St</street1>
      <city>San Francisco</city>
      <stateOrCountry>CA</stateOrCountry>
      <zipCode>94105</zipCode>
    </issuerAddress>
  </primaryIssuer>
  <offeringData>
    <typeOfFiling>
      <dateOfFirstSale><value>2024-01-10</value></dateOfFirstSale>
    </typeOfFiling>
    <offeringSalesAmounts>
      <totalOfferingAmount>1000000</totalOfferingAmount>
    </offeringSalesAmounts>
  </offeringData>
</edgarSubmission>
"""

MINIMAL_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <primaryIssuer>
    <entityName>MINIMAL CORP</entityName>
    <issuerAddress>
      <city>Austin</city>
      <stateOrCountry>TX</stateOrCountry>
    </issuerAddress>
  </primaryIssuer>
  <offeringData/>
</edgarSubmission>
"""


def test_index_filename_to_xml_url():
    filename = "edgar/data/1234567/0001234567-24-000001-index.htm"
    url = index_filename_to_xml_url(filename)
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/1234567"
        "/000123456724000001/0001234567-24-000001.xml"
    )


def test_index_filename_to_xml_url_txt():
    filename = "edgar/data/1650200/0001062993-21-003673.txt"
    url = index_filename_to_xml_url(filename)
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/1650200"
        "/000106299321003673/primary_doc.xml"
    )


def test_parse_form_d_xml_full():
    result = parse_form_d_xml(SAMPLE_XML)
    assert result["name"] == "ACME STARTUP INC"
    assert result["street1"] == "123 Main St"
    assert result["city"] == "San Francisco"
    assert result["state"] == "CA"
    assert result["zip"] == "94105"
    assert result["offering_amount"] == 1000000.0
    assert result["date_of_first_sale"] == "2024-01-10"


def test_parse_form_d_xml_missing_fields():
    result = parse_form_d_xml(MINIMAL_XML)
    assert result["name"] == "MINIMAL CORP"
    assert result["street1"] is None
    assert result["offering_amount"] is None
    assert result["date_of_first_sale"] is None


def test_parse_form_d_xml_invalid_returns_none():
    assert parse_form_d_xml("not xml at all") is None


import db
from unittest.mock import patch, MagicMock
from importer import import_quarter


def _make_mock_client(idx_text: str, xml_text: str) -> MagicMock:
    mock_idx = MagicMock()
    mock_idx.raise_for_status = MagicMock()
    mock_idx.text = idx_text

    mock_xml = MagicMock()
    mock_xml.raise_for_status = MagicMock()
    mock_xml.text = xml_text

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = [mock_idx, mock_xml]
    return mock_client


IDX_ONE_FILING = """\
Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------------------------------------
D           ACME STARTUP INC                                              0001234567  2024-01-15  edgar/data/1234567/0001234567-24-000001-index.htm
"""

XML_ONE_FILING = """\
<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <primaryIssuer>
    <entityName>ACME STARTUP INC</entityName>
    <issuerAddress>
      <street1>123 Main St</street1>
      <city>San Francisco</city>
      <stateOrCountry>CA</stateOrCountry>
      <zipCode>94105</zipCode>
    </issuerAddress>
  </primaryIssuer>
  <offeringData>
    <typeOfFiling><dateOfFirstSale><value>2024-01-10</value></dateOfFirstSale></typeOfFiling>
    <offeringSalesAmounts><totalOfferingAmount>1000000</totalOfferingAmount></offeringSalesAmounts>
  </offeringData>
</edgarSubmission>
"""


def test_import_quarter_inserts_company(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    mock_client = _make_mock_client(IDX_ONE_FILING, XML_ONE_FILING)
    with patch("importer.httpx.Client", return_value=mock_client):
        count = import_quarter("2024Q1", "Test test@test.com", db_path=db_path)

    assert count == 1
    with db.get_connection(db_path) as conn:
        company = db.get_company(conn, "0001234567")
    assert company["name"] == "ACME STARTUP INC"
    assert company["state"] == "CA"
    assert company["form_type"] == "D"


def test_import_quarter_records_completed_run(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    mock_client = _make_mock_client(IDX_ONE_FILING, XML_ONE_FILING)
    with patch("importer.httpx.Client", return_value=mock_client):
        import_quarter("2024Q1", "Test test@test.com", db_path=db_path)

    with db.get_connection(db_path) as conn:
        completed = db.get_completed_quarters(conn)
    assert "2024Q1" in completed


def test_import_quarter_skips_bad_xml(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    idx_two = IDX_ONE_FILING.replace(
        "0001234567-24-000001-index.htm",
        "0001234567-24-000001-index.htm\n"
        "D           BAD XML CORP                                                  0009999999  2024-01-16  edgar/data/9999999/0009999999-24-000001-index.htm",
    )
    mock_bad_xml = MagicMock()
    mock_bad_xml.raise_for_status = MagicMock()
    mock_bad_xml.text = "not valid xml <<<"

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    good_xml_resp = MagicMock()
    good_xml_resp.raise_for_status = MagicMock()
    good_xml_resp.text = XML_ONE_FILING

    idx_resp = MagicMock()
    idx_resp.raise_for_status = MagicMock()
    idx_resp.text = idx_two

    mock_client.get.side_effect = [idx_resp, good_xml_resp, mock_bad_xml]

    with patch("importer.httpx.Client", return_value=mock_client):
        count = import_quarter("2024Q1", "Test test@test.com", db_path=db_path)

    assert count == 1  # only the good one counted
