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
                interest_level INTEGER,
                commute_time INTEGER,
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


def get_companies(
    conn: sqlite3.Connection,
    state: str = None,
    interest_level: str = None,
    limit: int = None,
    offset: int = 0,
) -> list:
    query, params = _companies_filter("c.*, ua.interest_level, ua.notes", state, interest_level)
    query += " ORDER BY c.filed_date DESC"
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return conn.execute(query, params).fetchall()


def count_companies(conn: sqlite3.Connection, state: str = None, interest_level: str = None) -> int:
    query, params = _companies_filter("COUNT(*)", state, interest_level)
    return conn.execute(query, params).fetchone()[0]


def _companies_filter(select: str, state: str, interest_level: str):
    query = f"""
        SELECT {select}
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
    return query, params


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
