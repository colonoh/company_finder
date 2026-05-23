# Company Finder

A self-hosted web tool for discovering early-stage startups by pulling Form D and Form C filings from the SEC EDGAR database. Built to support a job search targeting 5–20 person startups in San Francisco or remote.

## What it does

- Imports 5 years of historical Form D (private placement) and Form C (equity crowdfunding) filings from SEC EDGAR on first run
- Updates quarterly with new filings going forward
- Displays companies in a browsable, filterable web UI
- Lets you mark each company as interesting (0–3 scale) for later follow-up

## Running with Docker

**1. Clone the repo and create your `.env` file:**

```bash
cp .env.example .env
```

Edit `.env`:
```
EDGAR_USER_AGENT=Your Name your@email.com
DATABASE_PATH=/app/data/companies.db
```

The `EDGAR_USER_AGENT` is required by the SEC. Use your real name and email.

**2. Build and start:**

```bash
docker compose up --build
```

The web UI is at `http://localhost:8000`.

On first startup, the scheduler begins a background import of the last 20 quarters (~5 years). This takes a while — check progress at `http://localhost:8000/status`.

## Using the UI

- **`/`** — Browse and filter companies by state and interest level. Set a 0–3 rating directly from the list.
- **`/companies/{cik}`** — Detail view for a single company with full filing data and a rating form.
- **`/status`** — Import job history showing which quarters have been processed.

**Interest levels:**
- `0` — No interest
- `1` — Mild interest
- `2` — Interesting
- `3` — Very interesting

Unrated companies have no badge and appear when filtering by "Unreviewed."

## Scheduled imports

- **Historical import** — Runs once on first startup. Imports up to 20 quarters, skipping any already completed.
- **Quarterly import** — Runs on the 5th of January, April, July, and October, picking up the just-completed quarter.

If the container restarts mid-import, it resumes from where it left off (completed quarters are skipped).

## Development

Install dependencies:

```bash
pip install -r requirements.txt
```

Run tests:

```bash
pytest
```

Run locally (without Docker):

```bash
cp .env.example .env
# edit .env with your details and set DATABASE_PATH=data/companies.db
export $(cat .env | xargs)
uvicorn app:app --reload
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `EDGAR_USER_AGENT` | Yes | Sent as `User-Agent` on all SEC requests. Format: `"Name email@example.com"` |
| `DATABASE_PATH` | No | Path to SQLite database file. Defaults to `data/companies.db` |

## Data sources

Filings are pulled from EDGAR's quarterly full-index files:
```
https://www.sec.gov/Archives/edgar/full-index/YYYY/QTRN/form.idx
```

Form D = private placement fundraise disclosure (Regulation D)
Form C = equity crowdfunding disclosure (Regulation CF)
