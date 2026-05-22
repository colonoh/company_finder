# Company Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-hosted web tool that ingests SEC EDGAR Form D/C filings quarterly, displays them in a browsable/filterable UI, and lets the user annotate companies with interest level.

**Architecture:** Single Docker container running a FastAPI web app (Jinja2 server-rendered HTML) alongside an APScheduler background scheduler. SQLite stores company data, enrichment metadata, user annotations, and import history. On first startup the scheduler runs a one-time historical import of 20 quarters; thereafter a quarterly job keeps data current.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Jinja2, python-multipart, APScheduler, httpx, tenacity, SQLite (stdlib sqlite3), pytest

---

## File Map

| File | Responsibility |
|---|---|
| `db.py` | Schema creation, connection management, all query helpers |
| `importer.py` | EDGAR index fetching, form.idx parsing, Form D XML fetching/parsing, quarter import orchestration |
| `scheduler.py` | APScheduler setup, job definitions, startup/shutdown |
| `app.py` | FastAPI app, route handlers, Jinja2 rendering |
| `templates/base.html` | Base HTML layout |
| `templates/index.html` | Company list with filters |
| `templates/company.html` | Company detail view |
| `Dockerfile` | Container build |
| `docker-compose.yml` | Service definition |
| `requirements.txt` | Python dependencies |
| `tests/test_db.py` | Database layer tests |
| `tests/test_importer.py` | Parsing and import logic tests |
| `tests/test_app.py` | Route tests |

---

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py`
- Create: `data/.gitkeep`
- Create: `templates/.gitkeep`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.0
uvicorn==0.30.6
jinja2==3.1.4
python-multipart==0.0.9
apscheduler==3.10.4
httpx==0.27.2
tenacity==9.0.0
pytest==8.3.3
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p data
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create docker-compose.yml**

```yaml
services:
  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    env_file:
      - .env
    restart: unless-stopped
```

- [ ] **Step 4: Create .env.example**

```
EDGAR_USER_AGENT=YourName your@email.com
DATABASE_PATH=/app/data/companies.db
```

- [ ] **Step 5: Create .gitignore**

```
data/*.db
.env
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 6: Create directory placeholders**

```bash
mkdir -p tests data templates
touch tests/__init__.py data/.gitkeep templates/.gitkeep
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt Dockerfile docker-compose.yml .env.example .gitignore tests/__init__.py data/.gitkeep templates/.gitkeep
git commit -m "chore: project scaffold"
```

---

### Task 2: Database Layer

**Files:**
- Create: `db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for schema and upsert_company**

Create `tests/test_db.py`:

```python
import pytest
from db import init_db, get_connection, upsert_company, get_company, get_companies


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def test_init_db_creates_tables(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert tables == {"companies", "company_enrichment", "user_annotations", "import_runs"}


def _sample_company(**overrides):
    base = {
        "cik": "0001234567", "name": "Acme Startup", "street1": "123 Main St",
        "city": "San Francisco", "state": "CA", "zip": "94105",
        "form_type": "D", "filed_date": "2024-01-15",
        "offering_amount": 1000000.0, "date_of_first_sale": "2024-01-10",
    }
    return {**base, **overrides}


def test_upsert_company_inserts_new(db_path):
    with get_connection(db_path) as conn:
        upsert_company(conn, _sample_company())
        row = get_company(conn, "0001234567")
    assert row["name"] == "Acme Startup"
    assert row["state"] == "CA"


def test_upsert_company_updates_existing(db_path):
    with get_connection(db_path) as conn:
        upsert_company(conn, _sample_company())
    with get_connection(db_path) as conn:
        upsert_company(conn, _sample_company(name="Updated Name", offering_amount=2000000.0))
        row = get_company(conn, "0001234567")
    assert row["name"] == "Updated Name"
    assert row["offering_amount"] == 2000000.0


def test_upsert_company_preserves_first_imported_at(db_path):
    with get_connection(db_path) as conn:
        upsert_company(conn, _sample_company())
        row1 = get_company(conn, "0001234567")
    with get_connection(db_path) as conn:
        upsert_company(conn, _sample_company(name="Updated"))
        row2 = get_company(conn, "0001234567")
    assert row1["first_imported_at"] == row2["first_imported_at"]


def test_get_companies_filters_by_state(db_path):
    with get_connection(db_path) as conn:
        upsert_company(conn, _sample_company(cik="0000000001", name="CA Corp", state="CA"))
        upsert_company(conn, _sample_company(cik="0000000002", name="NY Corp", state="NY", city="New York"))
        results = get_companies(conn, state="CA")
    assert len(results) == 1
    assert results[0]["name"] == "CA Corp"


def test_get_companies_filter_unreviewed(db_path):
    from db import upsert_annotation
    with get_connection(db_path) as conn:
        upsert_company(conn, _sample_company(cik="0000000001", name="Reviewed"))
        upsert_company(conn, _sample_company(cik="0000000002", name="Unreviewed"))
        upsert_annotation(conn, "0000000001", interest_level=2)
        results = get_companies(conn, interest_level="unreviewed")
    assert len(results) == 1
    assert results[0]["name"] == "Unreviewed"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_db.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Create db.py**

```python
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_path() -> str:
    return os.getenv("DATABASE_PATH", "data/companies.db")


def init_db(db_path: str = None) -> None:
    path = db_path or _default_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with get_connection(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS companies (
                cik TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                street1 TEXT,
                city TEXT,
                state TEXT,
                zip TEXT,
                form_type TEXT,
                filed_date TEXT,
                offering_amount REAL,
                date_of_first_sale TEXT,
                first_imported_at TEXT NOT NULL,
                last_updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS company_enrichment (
                cik TEXT PRIMARY KEY,
                website TEXT,
                employee_count INTEGER,
                description TEXT,
                industry TEXT,
                enrichment_status TEXT DEFAULT 'pending',
                enriched_at TEXT,
                last_updated_at TEXT,
                FOREIGN KEY (cik) REFERENCES companies(cik)
            );
            CREATE TABLE IF NOT EXISTS user_annotations (
                cik TEXT PRIMARY KEY,
                interest_level TEXT,
                commute_time TEXT,
                notes TEXT,
                last_updated_at TEXT NOT NULL,
                FOREIGN KEY (cik) REFERENCES companies(cik)
            );
            CREATE TABLE IF NOT EXISTS import_runs (
                quarter TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                filings_processed INTEGER DEFAULT 0,
                imported_at TEXT NOT NULL
            );
        """)


@contextmanager
def get_connection(db_path: str = None):
    path = db_path or _default_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_company(conn: sqlite3.Connection, company: dict) -> None:
    now = _now()
    conn.execute("""
        INSERT INTO companies
            (cik, name, street1, city, state, zip, form_type, filed_date,
             offering_amount, date_of_first_sale, first_imported_at, last_updated_at)
        VALUES
            (:cik, :name, :street1, :city, :state, :zip, :form_type, :filed_date,
             :offering_amount, :date_of_first_sale, :now, :now)
        ON CONFLICT(cik) DO UPDATE SET
            name = excluded.name,
            street1 = excluded.street1,
            city = excluded.city,
            state = excluded.state,
            zip = excluded.zip,
            form_type = excluded.form_type,
            filed_date = excluded.filed_date,
            offering_amount = excluded.offering_amount,
            date_of_first_sale = excluded.date_of_first_sale,
            last_updated_at = excluded.last_updated_at
    """, {**company, "now": now})


def get_company(conn: sqlite3.Connection, cik: str):
    return conn.execute("""
        SELECT c.*, ua.interest_level, ua.notes, ua.commute_time,
               ce.website, ce.employee_count, ce.description, ce.industry
        FROM companies c
        LEFT JOIN user_annotations ua ON c.cik = ua.cik
        LEFT JOIN company_enrichment ce ON c.cik = ce.cik
        WHERE c.cik = ?
    """, (cik,)).fetchone()


def get_companies(conn: sqlite3.Connection, state: str = None, interest_level: str = None) -> list:
    query = """
        SELECT c.*, ua.interest_level, ua.notes
        FROM companies c
        LEFT JOIN user_annotations ua ON c.cik = ua.cik
        WHERE 1=1
    """
    params = []
    if state:
        query += " AND c.state = ?"
        params.append(state)
    if interest_level == "unreviewed":
        query += " AND ua.interest_level IS NULL"
    elif interest_level == "not_interested":
        query += " AND ua.interest_level = 0"
    elif interest_level == "interested":
        query += " AND ua.interest_level >= 1"
    query += " ORDER BY c.filed_date DESC"
    return conn.execute(query, params).fetchall()


def upsert_annotation(conn: sqlite3.Connection, cik: str, interest_level: int | None = None) -> None:
    now = _now()
    conn.execute("""
        INSERT INTO user_annotations (cik, interest_level, last_updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(cik) DO UPDATE SET
            interest_level = excluded.interest_level,
            last_updated_at = excluded.last_updated_at
    """, (cik, interest_level, now))


def record_import_run(conn: sqlite3.Connection, quarter: str, status: str, filings_processed: int = 0) -> None:
    now = _now()
    conn.execute("""
        INSERT INTO import_runs (quarter, status, filings_processed, imported_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(quarter) DO UPDATE SET
            status = excluded.status,
            filings_processed = excluded.filings_processed,
            imported_at = excluded.imported_at
    """, (quarter, status, filings_processed, now))


def get_completed_quarters(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT quarter FROM import_runs WHERE status = 'completed'").fetchall()
    return {row["quarter"] for row in rows}
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_db.py -v
```
Expected: All tests `PASSED`

- [ ] **Step 5: Write and run remaining db tests**

Add to `tests/test_db.py`:

```python
from db import upsert_annotation, record_import_run, get_completed_quarters


def test_upsert_annotation_sets_interest(db_path):
    with get_connection(db_path) as conn:
        upsert_company(conn, _sample_company())
        upsert_annotation(conn, "0001234567", interest_level=3)
        row = get_company(conn, "0001234567")
    assert row["interest_level"] == 3


def test_upsert_annotation_overwrites(db_path):
    with get_connection(db_path) as conn:
        upsert_company(conn, _sample_company())
        upsert_annotation(conn, "0001234567", interest_level=3)
        upsert_annotation(conn, "0001234567", interest_level=0)
        row = get_company(conn, "0001234567")
    assert row["interest_level"] == 0


def test_record_import_run_completed(db_path):
    with get_connection(db_path) as conn:
        record_import_run(conn, "2024Q1", "completed", 42)
        record_import_run(conn, "2024Q2", "failed", 0)
        completed = get_completed_quarters(conn)
    assert "2024Q1" in completed
    assert "2024Q2" not in completed
```

```bash
pytest tests/test_db.py -v
```
Expected: All tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: database schema and query helpers"
```

---

### Task 3: Form Index Parsing

**Files:**
- Create: `importer.py`
- Create: `tests/test_importer.py`

- [ ] **Step 1: Write failing tests for quarter utilities**

Create `tests/test_importer.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_importer.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'importer'`

- [ ] **Step 3: Create importer.py with quarter utilities**

Create `importer.py`:

```python
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
```

- [ ] **Step 4: Run quarter utility tests**

```bash
pytest tests/test_importer.py -v
```
Expected: All 4 tests `PASSED`

- [ ] **Step 5: Write failing tests for parse_form_idx**

Add to `tests/test_importer.py`:

```python
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
```

- [ ] **Step 6: Run to verify failure**

```bash
pytest tests/test_importer.py::test_parse_form_idx_filters_d_and_c tests/test_importer.py::test_parse_form_idx_extracts_fields tests/test_importer.py::test_parse_form_idx_empty_content -v
```
Expected: `FAILED` — `ImportError` on `parse_form_idx`

- [ ] **Step 7: Implement parse_form_idx**

Add to `importer.py`:

```python
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
```

- [ ] **Step 8: Run all importer tests**

```bash
pytest tests/test_importer.py -v
```
Expected: All tests `PASSED`

- [ ] **Step 9: Commit**

```bash
git add importer.py tests/test_importer.py
git commit -m "feat: quarter index URL generation and form.idx parsing"
```

---

### Task 4: Form D XML URL Derivation and Parsing

**Files:**
- Modify: `importer.py`
- Modify: `tests/test_importer.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_importer.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_importer.py::test_index_filename_to_xml_url tests/test_importer.py::test_parse_form_d_xml_full tests/test_importer.py::test_parse_form_d_xml_missing_fields tests/test_importer.py::test_parse_form_d_xml_invalid_returns_none -v
```
Expected: `FAILED` — `ImportError`

- [ ] **Step 3: Implement XML URL and parser**

Add to `importer.py`:

```python
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
```

**Important:** The XML element paths above match the Form D v1.4 schema. Before running a full import, verify them by fetching one real filing XML from EDGAR and comparing. If EDGAR returns a different structure, adjust the `_text(root, ...)` paths accordingly.

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```
Expected: All tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add importer.py tests/test_importer.py
git commit -m "feat: Form D XML URL derivation and field parsing"
```

---

### Task 5: Quarter Import Orchestration

**Files:**
- Modify: `importer.py`
- Modify: `tests/test_importer.py`

- [ ] **Step 1: Write failing test for import_quarter**

Add to `tests/test_importer.py`:

```python
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
Company Name                                                   Form Type   CIK         Date Filed  Filename
------------------------------------------------------------------------------------------------------------------------------------------------
ACME STARTUP INC                                               D           0001234567  2024-01-15  edgar/data/1234567/0001234567-24-000001-index.htm
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
        "BAD XML CORP                                                   D           0009999999  2024-01-16  edgar/data/9999999/0009999999-24-000001-index.htm",
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
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_importer.py::test_import_quarter_inserts_company tests/test_importer.py::test_import_quarter_records_completed_run tests/test_importer.py::test_import_quarter_skips_bad_xml -v
```
Expected: `FAILED` — `ImportError` on `import_quarter`

- [ ] **Step 3: Implement import_quarter**

Add to `importer.py`:

```python
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
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```
Expected: All tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add importer.py tests/test_importer.py
git commit -m "feat: quarter import with rate limiting, retry, and error handling"
```

---

### Task 6: Scheduler

**Files:**
- Create: `scheduler.py`

No unit tests — the scheduler coordinates already-tested functions. Verified by the Docker smoke test in Task 10.

- [ ] **Step 1: Create scheduler.py**

```python
import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

import db
import importer

logger = logging.getLogger(__name__)
_scheduler = BackgroundScheduler()


def _db_path() -> str:
    return os.getenv("DATABASE_PATH", "data/companies.db")


def _user_agent() -> str:
    return os.getenv("EDGAR_USER_AGENT", "CompanyFinder user@example.com")


def _run_historical_import() -> None:
    quarters = importer.get_quarters_in_range(20)
    with db.get_connection(_db_path()) as conn:
        completed = db.get_completed_quarters(conn)
    pending = [q for q in reversed(quarters) if q not in completed]
    if not pending:
        logger.info("Historical import: all quarters complete")
        return
    logger.info("Historical import: %d quarters pending", len(pending))
    for quarter in pending:
        try:
            count = importer.import_quarter(quarter, _user_agent(), db_path=_db_path())
            logger.info("Imported %s: %d filings", quarter, count)
        except Exception as e:
            logger.error("Failed %s: %s", quarter, e)


def _run_quarterly_import() -> None:
    quarters = importer.get_quarters_in_range(1)
    if not quarters:
        return
    quarter = quarters[0]
    try:
        count = importer.import_quarter(quarter, _user_agent(), db_path=_db_path())
        logger.info("Quarterly import %s: %d filings", quarter, count)
    except Exception as e:
        logger.error("Quarterly import %s failed: %s", quarter, e)


def start_scheduler() -> None:
    db.init_db(_db_path())
    if os.getenv("TESTING"):
        logger.info("Scheduler disabled in test mode")
        return
    _scheduler.add_job(_run_historical_import, "date")
    _scheduler.add_job(
        _run_quarterly_import,
        "cron",
        month="1,4,7,10",
        day=5,
        hour=2,
        minute=0,
    )
    _scheduler.start()
    logger.info("Scheduler started")


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
```

- [ ] **Step 2: Commit**

```bash
git add scheduler.py
git commit -m "feat: APScheduler with historical and quarterly import jobs"
```

---

### Task 7: Company List Route and Templates

**Files:**
- Create: `app.py`
- Create: `templates/base.html`
- Create: `templates/index.html`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_app.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def db_path(tmp_path):
    import db
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test test@test.com")
    monkeypatch.setenv("TESTING", "1")
    import app
    return TestClient(app.app)


def _sample_company(**overrides):
    return {
        "cik": "0001234567", "name": "Acme Startup", "street1": "1 Main St",
        "city": "San Francisco", "state": "CA", "zip": "94105",
        "form_type": "D", "filed_date": "2024-01-15",
        "offering_amount": 1000000.0, "date_of_first_sale": "2024-01-10",
        **overrides,
    }


def test_index_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Company Finder" in response.text


def test_index_shows_companies(client, db_path):
    import db
    with db.get_connection(db_path) as conn:
        db.upsert_company(conn, _sample_company())
    response = client.get("/")
    assert "Acme Startup" in response.text


def test_index_filters_by_state(client, db_path):
    import db
    with db.get_connection(db_path) as conn:
        db.upsert_company(conn, _sample_company(cik="0000000001", name="CA Corp", state="CA"))
        db.upsert_company(conn, _sample_company(cik="0000000002", name="NY Corp", state="NY", city="New York"))
    response = client.get("/?state=CA")
    assert "CA Corp" in response.text
    assert "NY Corp" not in response.text
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_app.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Create app.py**

```python
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import db
import scheduler

templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start_scheduler()
    yield
    scheduler.shutdown_scheduler()


app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def index(request: Request, state: str = None, interest_level: str = None):
    with db.get_connection() as conn:
        companies = db.get_companies(conn, state=state, interest_level=interest_level)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "companies": companies, "state": state, "interest_level": interest_level},
    )
```

- [ ] **Step 4: Create templates/base.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Company Finder</title>
  <style>
    body { font-family: sans-serif; max-width: 1200px; margin: 0 auto; padding: 1rem; color: #333; }
    h1 { border-bottom: 2px solid #0066cc; padding-bottom: 0.5rem; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #ddd; }
    th { background: #f5f5f5; font-weight: 600; }
    tr:hover { background: #fafafa; }
    .filters { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.5rem; }
    .badge { padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }
    .level-0 { background: #f8d7da; color: #721c24; }
    .level-1 { background: #fff3cd; color: #856404; }
    .level-2 { background: #d1ecf1; color: #0c5460; }
    .level-3 { background: #d4edda; color: #155724; }
    a { color: #0066cc; text-decoration: none; }
    a:hover { text-decoration: underline; }
    button { cursor: pointer; padding: 2px 8px; }
    .action-form { display: inline; }
  </style>
</head>
<body>
  <h1>Company Finder</h1>
  {% block content %}{% endblock %}
</body>
</html>
```

- [ ] **Step 5: Create templates/index.html**

```html
{% extends "base.html" %}
{% block content %}
<form class="filters" method="get" action="/">
  <label>State:
    <input name="state" value="{{ state or '' }}" placeholder="e.g. CA" style="width:5rem">
  </label>
  <label>Interest:
    <select name="interest_level">
      <option value="">All</option>
      <option value="unreviewed" {% if interest_level == 'unreviewed' %}selected{% endif %}>Unreviewed</option>
      <option value="not_interested" {% if interest_level == 'not_interested' %}selected{% endif %}>Not interested (0)</option>
      <option value="interested" {% if interest_level == 'interested' %}selected{% endif %}>Interested (1+)</option>
    </select>
  </label>
  <button type="submit">Filter</button>
  <a href="/">Clear</a>
</form>

<table>
  <thead>
    <tr>
      <th>Company</th>
      <th>State</th>
      <th>City</th>
      <th>Form</th>
      <th>Filed</th>
      <th>Offering ($)</th>
      <th>Interest</th>
      <th>Mark</th>
    </tr>
  </thead>
  <tbody>
  {% for co in companies %}
    <tr>
      <td><a href="/companies/{{ co.cik }}">{{ co.name }}</a></td>
      <td>{{ co.state or '—' }}</td>
      <td>{{ co.city or '—' }}</td>
      <td>{{ co.form_type }}</td>
      <td>{{ co.filed_date }}</td>
      <td>{{ "${:,.0f}".format(co.offering_amount) if co.offering_amount else '—' }}</td>
      <td>
        {% if co.interest_level is not none %}
          <span class="badge level-{{ co.interest_level }}">{{ co.interest_level }}</span>
        {% endif %}
      </td>
      <td>
        <form class="action-form" method="post" action="/companies/{{ co.cik }}/annotate">
          <select name="interest_level">
            {% for lvl in [0, 1, 2, 3] %}
              <option value="{{ lvl }}" {% if co.interest_level == lvl %}selected{% endif %}>{{ lvl }}</option>
            {% endfor %}
          </select>
          <button type="submit">Save</button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="8" style="text-align:center;color:#888">No companies found.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_app.py -v
```
Expected: All 3 tests `PASSED`

- [ ] **Step 7: Commit**

```bash
git add app.py templates/base.html templates/index.html tests/test_app.py
git commit -m "feat: company list route with filter UI"
```

---

### Task 8: Annotate Route

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_app.py`:

```python
def test_annotate_sets_interest_level(client, db_path):
    import db
    with db.get_connection(db_path) as conn:
        db.upsert_company(conn, _sample_company())

    response = client.post(
        "/companies/0001234567/annotate",
        data={"interest_level": "3"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with db.get_connection(db_path) as conn:
        row = db.get_company(conn, "0001234567")
    assert row["interest_level"] == 3


def test_annotate_overwrites_interest_level(client, db_path):
    import db
    with db.get_connection(db_path) as conn:
        db.upsert_company(conn, _sample_company())
        db.upsert_annotation(conn, "0001234567", interest_level=3)

    client.post(
        "/companies/0001234567/annotate",
        data={"interest_level": "0"},
        follow_redirects=False,
    )

    with db.get_connection(db_path) as conn:
        row = db.get_company(conn, "0001234567")
    assert row["interest_level"] == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_app.py::test_annotate_sets_interest_level tests/test_app.py::test_annotate_overwrites_interest_level -v
```
Expected: `FAILED` — 404 or 405 (route not defined)

- [ ] **Step 3: Add annotate route to app.py**

Add to `app.py`:

```python
@app.post("/companies/{cik}/annotate")
def annotate(cik: str, interest_level: int = Form(...)):
    with db.get_connection() as conn:
        db.upsert_annotation(conn, cik, interest_level=interest_level)
    return RedirectResponse(url="/", status_code=303)
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```
Expected: All tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: annotate route for setting company interest level"
```

---

### Task 9: Company Detail Route and Template

**Files:**
- Modify: `app.py`
- Create: `templates/company.html`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_app.py`:

```python
def test_company_detail_returns_200(client, db_path):
    import db
    with db.get_connection(db_path) as conn:
        db.upsert_company(conn, _sample_company())
    response = client.get("/companies/0001234567")
    assert response.status_code == 200
    assert "Acme Startup" in response.text
    assert "San Francisco" in response.text


def test_company_detail_404_unknown(client):
    response = client.get("/companies/9999999999")
    assert response.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_app.py::test_company_detail_returns_200 tests/test_app.py::test_company_detail_404_unknown -v
```
Expected: `FAILED` — 404 (route not defined)

- [ ] **Step 3: Add detail route to app.py**

Add to `app.py`:

```python
@app.get("/companies/{cik}", response_class=HTMLResponse)
def company_detail(request: Request, cik: str):
    with db.get_connection() as conn:
        company = db.get_company(conn, cik)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return templates.TemplateResponse(
        "company.html",
        {"request": request, "company": company},
    )
```

- [ ] **Step 4: Create templates/company.html**

```html
{% extends "base.html" %}
{% block content %}
<p><a href="/">← Back to list</a></p>
<h2>{{ company.name }}</h2>

<table style="width:auto;min-width:400px">
  <tr><th>CIK</th><td>{{ company.cik }}</td></tr>
  <tr><th>Address</th><td>
    {{ company.street1 or '' }}{% if company.street1 %}, {% endif %}
    {{ company.city or '—' }}, {{ company.state or '' }} {{ company.zip or '' }}
  </td></tr>
  <tr><th>Form Type</th><td>{{ company.form_type }}</td></tr>
  <tr><th>Filed Date</th><td>{{ company.filed_date }}</td></tr>
  <tr><th>First Sale</th><td>{{ company.date_of_first_sale or '—' }}</td></tr>
  <tr><th>Offering Amount</th><td>{{ "${:,.0f}".format(company.offering_amount) if company.offering_amount else '—' }}</td></tr>
  {% if company.website %}
  <tr><th>Website</th><td><a href="{{ company.website }}" target="_blank">{{ company.website }}</a></td></tr>
  {% endif %}
  {% if company.description %}
  <tr><th>Description</th><td>{{ company.description }}</td></tr>
  {% endif %}
</table>

<h3>My Notes</h3>
{% if company.interest_level is not none %}
  <p>Current: <span class="badge level-{{ company.interest_level }}">{{ company.interest_level }}</span></p>
{% endif %}
<form method="post" action="/companies/{{ company.cik }}/annotate" style="display:flex;gap:0.5rem;align-items:center">
  <label>Rating (0 = no interest, 3 = very interesting):
    <select name="interest_level">
      {% for lvl in [0, 1, 2, 3] %}
        <option value="{{ lvl }}" {% if company.interest_level == lvl %}selected{% endif %}>
          {{ lvl }} — {{ ['No interest', 'Mild interest', 'Interesting', 'Very interesting'][lvl] }}
        </option>
      {% endfor %}
    </select>
  </label>
  <button type="submit">Save</button>
</form>
{% endblock %}
```

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```
Expected: All tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add app.py templates/company.html tests/test_app.py
git commit -m "feat: company detail route and template"
```

---

### Task 10: Docker Smoke Test

No automated tests — manual verification only.

- [ ] **Step 1: Copy .env.example to .env and set your details**

```bash
cp .env.example .env
```

Edit `.env`:
```
EDGAR_USER_AGENT=Steve steve.j.warner@gmail.com
DATABASE_PATH=/app/data/companies.db
```

- [ ] **Step 2: Build and start**

```bash
docker compose up --build
```
Expected: Container builds successfully. Logs show:
```
INFO:scheduler:Scheduler started
INFO:scheduler:Historical import: 20 quarters pending
INFO:importer:Quarter 2021Q2: N D/C filings in index
...
```

- [ ] **Step 3: Verify web UI loads**

Open `http://localhost:8000`.
Expected: "Company Finder" page renders. Shows "No companies found" initially — correct while the background import runs.

- [ ] **Step 4: Manually trigger one quarter to verify end-to-end**

In a second terminal (while the container is running):
```bash
docker compose exec web python -c "
import os, importer
count = importer.import_quarter('2024Q1', os.getenv('EDGAR_USER_AGENT'))
print(f'Imported {count} filings')
"
```
Expected: `Imported N filings` where N > 0.

Reload `http://localhost:8000` — companies appear in the list.

- [ ] **Step 5: Verify XML field paths against a real filing**

In the same exec session:
```bash
docker compose exec web python -c "
import httpx, os
client = httpx.Client(headers={'User-Agent': os.getenv('EDGAR_USER_AGENT')})
# Fetch one real Form D XML and print it
import db, sqlite3
conn = sqlite3.connect(os.getenv('DATABASE_PATH'))
row = conn.execute('SELECT cik, filed_date FROM companies LIMIT 1').fetchone()
print('CIK:', row[0])
"
```
Then fetch `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=D&count=1` in your browser and inspect one XML file. Confirm that the element paths in `parse_form_d_xml` (`//primaryIssuer/entityName`, etc.) match the actual structure. If they differ, update `importer.py` and re-run tests.

- [ ] **Step 6: Verify filters and annotation**

- Filter by state `CA` — only California companies shown
- Click 👍 on a company — badge appears
- Filter by `Interesting` — only marked companies shown
- Filter by `Unreviewed` — marked company excluded
- Click company name — detail page shows all fields

- [ ] **Step 7: Verify persistence across restart**

```bash
docker compose down
docker compose up
```
Expected: All companies and annotations still present after restart.

- [ ] **Step 8: Commit**

```bash
git add .env.example
git commit -m "chore: verified docker deployment end-to-end"
```

---

## Notes for Implementer

**XML schema verification (Task 4):** The element paths in `parse_form_d_xml` are based on the Form D v1.4 schema. Fetch a real Form D XML and confirm paths before running a full 20-quarter import. Adjust `_text(root, ...)` calls if needed.

**Historical import duration:** At 0.1s per request, importing 20 quarters with ~100 filings each takes roughly 200 seconds. The web app is usable throughout — import runs in a background thread.

**form.idx column detection:** `parse_form_idx` finds column positions from the header line dynamically. This adapts to minor format changes but assumes `Form Type`, `CIK`, `Date Filed`, and `Filename` appear in that order in the header.

**Test isolation:** The `client` fixture uses `monkeypatch` to set `DATABASE_PATH` and `TESTING=1`. The `db_path` fixture is function-scoped, so each test gets a fresh empty database. Both fixtures share the same `tmp_path` instance within a single test function.
