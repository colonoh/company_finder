import logging
import os
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

import db
import importer

BACKUP_RETENTION_DAYS = 7

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


def _run_backup() -> None:
    src_path = _db_path()
    backup_dir = Path(src_path).parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"companies.{date.today().isoformat()}.db"
    tmp = dest.with_suffix(".db.tmp")
    try:
        src = sqlite3.connect(src_path, timeout=30)
        try:
            dst = sqlite3.connect(str(tmp))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        os.replace(tmp, dest)
        logger.info("Backup written to %s", dest)
        _prune_backups(backup_dir)
    except Exception as e:
        logger.error("Backup failed: %s", e)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _prune_backups(backup_dir: Path) -> None:
    cutoff = time.time() - BACKUP_RETENTION_DAYS * 86400
    for f in backup_dir.glob("companies.*.db"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            logger.info("Pruned old backup %s", f)


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
    _scheduler.add_job(_run_backup, "cron", hour=3, minute=0)
    _scheduler.start()
    logger.info("Scheduler started")


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
