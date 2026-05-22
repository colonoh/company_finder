# Company Finder — Design Spec

**Date:** 2026-05-21
**Status:** Approved

## Overview

A self-hosted web tool for discovering early-stage startups by pulling Form D and Form C filings from SEC EDGAR. Designed to support a job search targeting 5–20 person startups in San Francisco or remote. The tool surfaces companies from EDGAR, lets the user annotate them with interest level, and is built to accept enrichment (website, employee count, description) in a future phase.

## Goals

- Pull 5 years of historical Form D and Form C filings from EDGAR on first run
- Update quarterly with new filings going forward
- Display companies in a browsable, filterable web UI
- Allow marking each company as interesting or not interesting
- Run in a single Docker container on a Windows desktop or VPS
- Schema is enrichment-ready, but enrichment is not implemented in this phase

## Non-Goals

- Website discovery, employee count, or description (future phase)
- Email or Slack alerts
- Multi-user support
- Authentication

---

## Architecture

Single Docker container running:
- **FastAPI + Jinja2** web app (server-rendered HTML)
- **APScheduler** for scheduled import jobs
- **SQLite** for storage, persisted via Docker volume

---

## Data Model

### `companies`
Raw SEC data only. Written by the EDGAR importer. Never written by the enrichment job or user.

| Column | Type | Notes |
|---|---|---|
| `cik` | TEXT | Primary key. SEC Central Index Key, zero-padded to 10 digits. |
| `name` | TEXT | Company name as filed |
| `street1` | TEXT | |
| `city` | TEXT | |
| `state` | TEXT | Two-letter state code |
| `zip` | TEXT | |
| `form_type` | TEXT | `D`, `D/A`, or `C` |
| `filed_date` | DATE | Date of most recent relevant filing |
| `offering_amount` | REAL | Total offering amount in USD |
| `date_of_first_sale` | DATE | When the raise started, per the filing |
| `first_imported_at` | DATETIME | When this row was first created in our DB |
| `last_updated_at` | DATETIME | When this row was last updated |

On re-import, existing rows are upserted by CIK — SEC data is updated, nothing else is touched.

### `company_enrichment`
Data from external APIs and scraping. Written only by the enrichment job (future phase). Schema established now so the data model is stable.

| Column | Type | Notes |
|---|---|---|
| `cik` | TEXT | Primary key, FK → companies |
| `website` | TEXT | |
| `employee_count` | INTEGER | |
| `description` | TEXT | One or two sentence summary |
| `industry` | TEXT | |
| `enrichment_status` | TEXT | `pending`, `done`, `failed` |
| `enriched_at` | DATETIME | |
| `last_updated_at` | DATETIME | |

### `user_annotations`
User's personal data. Never overwritten by any import or enrichment job.

| Column | Type | Notes |
|---|---|---|
| `cik` | TEXT | Primary key, FK → companies |
| `interest_level` | TEXT | `NULL`, `interesting`, or `not_interesting` |
| `commute_time` | TEXT | Freeform, e.g. "45 min by BART" |
| `notes` | TEXT | Freeform |
| `last_updated_at` | DATETIME | |

### `import_runs`
Tracks which quarters have been imported. Used to skip already-completed quarters and retry failed ones.

| Column | Type | Notes |
|---|---|---|
| `quarter` | TEXT | Primary key, e.g. `2024Q1` |
| `status` | TEXT | `completed` or `failed` |
| `filings_processed` | INTEGER | |
| `imported_at` | DATETIME | |

---

## Components

### `importer.py` — EDGAR Importer
- Downloads `https://www.sec.gov/Archives/edgar/full-index/YYYY/QTRN/form.idx` for a given quarter
- Parses the fixed-width text file, filters rows where form type is `D` or `C`
- For each filing, fetches the XML from EDGAR and parses: company name, address fields, offering amount, date of first sale
- Upserts into `companies`
- Writes a row to `import_runs` with status and count on completion
- Rate-limits to 10 requests/second to comply with SEC policy
- Uses `EDGAR_USER_AGENT` env var as the `User-Agent` header on all requests (required by SEC)

### `scheduler.py` — APScheduler
Two jobs:
- **`historical_import`**: runs once on first startup. Iterates over all quarters from 5 years ago to the most recently completed quarter. Skips any quarter already marked `completed` in `import_runs`.
- **`quarterly_import`**: runs on the 5th day of January, April, July, and October (allowing a few days for EDGAR to publish the prior quarter's index). Processes the just-completed quarter.

### `db.py` — Database
- SQLite via Python's `sqlite3`
- Schema creation on startup (idempotent `CREATE TABLE IF NOT EXISTS`)
- Query helpers: `upsert_company`, `get_companies` (with filter params), `get_company`, `upsert_annotation`, `record_import_run`

### `app.py` — Web App
FastAPI with Jinja2 templates. Three routes:

| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Company list. Accepts query params: `state`, `interest_level`. Joins `companies` + `user_annotations`. |
| `POST` | `/companies/{cik}/annotate` | Save interest level. Upserts into `user_annotations`. Redirects to `/`. |
| `GET` | `/companies/{cik}` | Company detail. Joins all four tables. |

---

## Data Flow

### Import Flow
1. Scheduler triggers import for a quarter
2. Importer downloads `form.idx` for that quarter
3. Filters for `D` and `C` form types
4. For each filing: fetch XML → parse address + offering fields → upsert into `companies`
5. Write row to `import_runs` with `completed` status and filing count

### Web Flow
1. User loads `/` → app queries `companies` + `user_annotations`, applies filters, renders list
2. User clicks "interesting" / "not interesting" → `POST /companies/{cik}/annotate` → upserts `user_annotations` → redirect to list
3. User clicks a company → `GET /companies/{cik}` → full detail view

---

## Error Handling

- **Single XML fetch fails**: log and skip; do not abort the quarter's import
- **`form.idx` download fails**: mark `import_runs` as `failed`; scheduler retries on next run
- **Scheduler startup**: checks `import_runs` on startup — any quarter in range that is missing or `failed` is queued for import

---

## File Structure

```
company_finder/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── app.py
├── scheduler.py
├── importer.py
├── db.py
├── templates/
│   ├── base.html
│   ├── index.html
│   └── company.html
└── data/               # Docker volume mount
    └── companies.db
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `EDGAR_USER_AGENT` | Yes | Sent as `User-Agent` on all SEC requests. Format: `"Name email@example.com"` |

---

## Future Work (Out of Scope)

- **Enrichment job**: find company website, employee count, description via external APIs and scraping
- **HN "Who is Hiring" import**: additional data source alongside EDGAR
- **Dagster migration**: replace APScheduler with Dagster for visibility and monitoring
- **Additional annotation fields**: commute time, application status, links
