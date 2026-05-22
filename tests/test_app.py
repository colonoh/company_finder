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
