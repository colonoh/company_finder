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
