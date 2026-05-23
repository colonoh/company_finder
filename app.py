import logging
import os
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

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


PAGE_SIZE = 20


@app.get("/", response_class=HTMLResponse)
def index(request: Request, state: str = None, interest_level: str = None, page: int = 1):
    if page < 1:
        page = 1
    offset = (page - 1) * PAGE_SIZE
    with db.get_connection() as conn:
        companies = db.get_companies(
            conn, state=state, interest_level=interest_level, limit=PAGE_SIZE, offset=offset
        )
        total = db.count_companies(conn, state=state, interest_level=interest_level)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "companies": companies,
            "state": state,
            "interest_level": interest_level,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@app.post("/companies/{cik}/annotate")
def annotate(cik: str, interest_level: int = Form(...)):
    with db.get_connection() as conn:
        db.upsert_annotation(conn, cik, interest_level=interest_level)
    return RedirectResponse(url="/", status_code=303)


@app.get("/status", response_class=HTMLResponse)
def import_status(request: Request):
    with db.get_connection() as conn:
        runs = conn.execute(
            "SELECT quarter, status, filings_processed, imported_at FROM import_runs ORDER BY quarter DESC"
        ).fetchall()
    total_quarters = 20
    completed = sum(1 for r in runs if r["status"] == "completed")
    in_progress = completed < total_quarters
    return templates.TemplateResponse(
        request,
        "status.html",
        {"runs": runs, "completed": completed, "total": total_quarters, "in_progress": in_progress},
    )


@app.get("/companies/{cik}", response_class=HTMLResponse)
def company_detail(request: Request, cik: str):
    with db.get_connection() as conn:
        company = db.get_company(conn, cik)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return templates.TemplateResponse(
        request,
        "company.html",
        {"company": company},
    )
