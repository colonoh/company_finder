import logging
import time
import xml.etree.ElementTree as ET
from datetime import date

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

import db

logger = logging.getLogger(__name__)
EDGAR_BASE = "https://www.sec.gov"


def get_quarter_index_url(year: int, qtr: int) -> str:
    return f"{EDGAR_BASE}/Archives/edgar/full-index/{year}/QTR{qtr}/form.idx"


def get_quarters_in_range(num_quarters: int = 20) -> list[str]:
    today = date.today()
    qtr = (today.month - 1) // 3 + 1
    year = today.year
    # Step back one: current quarter is still in progress
    qtr -= 1
    if qtr == 0:
        qtr, year = 4, year - 1

    quarters = []
    for _ in range(num_quarters):
        quarters.append(f"{year}Q{qtr}")
        qtr -= 1
        if qtr == 0:
            qtr, year = 4, year - 1
    return quarters


def parse_form_idx(content: str) -> list[dict]:
    lines = content.splitlines()
    header_line = None
    data_start = 0
    for i, line in enumerate(lines):
        if "Form Type" in line and "CIK" in line and "Filename" in line:
            header_line = line
            data_start = i + 2  # skip header + separator line
            break
    if header_line is None:
        return []

    col_form = header_line.index("Form Type")
    col_cik = header_line.index("CIK")
    col_date = header_line.index("Date Filed")
    col_file = header_line.index("Filename")

    results = []
    for line in lines[data_start:]:
        if not line.strip():
            continue
        form_type = line[col_form:col_cik].strip()
        if form_type not in ("D", "D/A", "C"):
            continue
        results.append({
            "company_name": line[:col_form].strip(),
            "form_type": form_type,
            "cik": line[col_cik:col_date].strip(),
            "filed_date": line[col_date:col_file].strip(),
            "filename": line[col_file:].strip(),
        })
    return results


def index_filename_to_xml_url(filename: str) -> str:
    # edgar/data/{cik}/{accession}-index.htm
    # → https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodashes}/{accession}.xml
    without_index = filename.replace("-index.htm", "")
    parts = without_index.split("/")
    cik = parts[2]
    accession = parts[3]
    accession_nodashes = accession.replace("-", "")
    return f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{accession_nodashes}/{accession}.xml"


def _text(root: ET.Element, path: str) -> str | None:
    el = root.find(path)
    return el.text.strip() if el is not None and el.text else None


def parse_form_d_xml(xml_content: str) -> dict | None:
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.warning("XML parse error: %s", e)
        return None

    amount_text = _text(root, ".//offeringSalesAmounts/totalOfferingAmount")
    return {
        "name": _text(root, ".//primaryIssuer/entityName"),
        "street1": _text(root, ".//primaryIssuer/issuerAddress/street1"),
        "city": _text(root, ".//primaryIssuer/issuerAddress/city"),
        "state": _text(root, ".//primaryIssuer/issuerAddress/stateOrCountry"),
        "zip": _text(root, ".//primaryIssuer/issuerAddress/zipCode"),
        "offering_amount": float(amount_text) if amount_text else None,
        "date_of_first_sale": _text(root, ".//typeOfFiling/dateOfFirstSale/value"),
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch(client: httpx.Client, url: str) -> httpx.Response:
    response = client.get(url)
    response.raise_for_status()
    return response


def import_quarter(quarter: str, user_agent: str, db_path: str = None) -> int:
    year = int(quarter[:4])
    qtr = int(quarter[5])
    index_url = get_quarter_index_url(year, qtr)
    headers = {"User-Agent": user_agent}
    filings_processed = 0

    with db.get_connection(db_path) as conn:
        try:
            with httpx.Client(headers=headers, timeout=30) as client:
                response = _fetch(client, index_url)
                filings = parse_form_idx(response.text)
                logger.info("Quarter %s: %d D/C filings in index", quarter, len(filings))

                for filing in filings:
                    xml_url = index_filename_to_xml_url(filing["filename"])
                    try:
                        xml_resp = _fetch(client, xml_url)
                        parsed = parse_form_d_xml(xml_resp.text)
                        if parsed is None:
                            continue
                        db.upsert_company(conn, {
                            "cik": filing["cik"],
                            "form_type": filing["form_type"],
                            "filed_date": filing["filed_date"],
                            **parsed,
                        })
                        filings_processed += 1
                        time.sleep(0.1)  # respect SEC 10 req/sec limit
                    except Exception as e:
                        logger.warning("Skipping %s: %s", filing["filename"], e)

            db.record_import_run(conn, quarter, "completed", filings_processed)
        except Exception as e:
            db.record_import_run(conn, quarter, "failed", filings_processed)
            raise

    return filings_processed
