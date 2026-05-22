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
