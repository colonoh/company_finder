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
        request,
        "index.html",
        {"companies": companies, "state": state, "interest_level": interest_level},
    )


@app.post("/companies/{cik}/annotate")
def annotate(cik: str, interest_level: int = Form(...)):
    with db.get_connection() as conn:
        db.upsert_annotation(conn, cik, interest_level=interest_level)
    return RedirectResponse(url="/", status_code=303)


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
