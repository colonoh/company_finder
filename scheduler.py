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
