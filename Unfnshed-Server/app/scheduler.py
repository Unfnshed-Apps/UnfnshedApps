"""Background scheduler for automated forecast, replenishment, and Shopify sync jobs."""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("nesting-api")

_scheduler: BackgroundScheduler | None = None

SHOPIFY_SYNC_JOB_ID = "shopify_sync"


def _safe_run(func, name):
    """Wrapper to catch exceptions so the scheduler doesn't die."""
    def wrapper():
        try:
            func()
        except Exception:
            logger.exception(f"Scheduled job '{name}' failed")
    return wrapper


def _run_shopify_sync_job():
    """Execute a Shopify sync using a fresh DB connection."""
    from .database import get_db
    from .shopify_sync import run_shopify_sync

    with get_db() as conn:
        synced, errors = run_shopify_sync(conn)
        logger.info(f"Scheduled Shopify sync: {synced} synced, {errors} errors")


def configure_shopify_sync(enabled: bool, interval_minutes: int):
    """
    Add, update, or remove the Shopify sync job on the running scheduler.

    Called by the admin router when sync settings change.
    """
    if _scheduler is None:
        return

    # Remove existing job if any
    try:
        _scheduler.remove_job(SHOPIFY_SYNC_JOB_ID)
    except Exception:
        pass

    if enabled and interval_minutes > 0:
        _scheduler.add_job(
            _safe_run(_run_shopify_sync_job, "shopify_sync"),
            trigger=IntervalTrigger(minutes=interval_minutes),
            id=SHOPIFY_SYNC_JOB_ID,
            name="Shopify Order Sync",
            replace_existing=True,
        )
        logger.info(f"Shopify sync job configured: every {interval_minutes} minutes")
    else:
        logger.info("Shopify sync job disabled")


def _load_shopify_sync_settings():
    """Read shopify_settings from DB and configure the sync job on startup."""
    from .database import get_db

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT auto_sync, sync_interval_minutes
                    FROM shopify_settings WHERE id = 1
                """)
                row = cur.fetchone()

        if row and row["auto_sync"]:
            interval = row["sync_interval_minutes"] or 60
            configure_shopify_sync(True, interval)
        else:
            logger.info("Shopify auto-sync not enabled")
    except Exception:
        logger.debug("shopify_settings table not found or empty — skipping sync job")


def start_scheduler():
    """Create and start the background scheduler."""
    global _scheduler

    from .routers.replenishment import run_full_recalculation

    _scheduler = BackgroundScheduler(timezone="America/New_York")

    # Daily at 4 AM: full recalculation (demand + SES + targets + snapshot)
    _scheduler.add_job(
        _safe_run(run_full_recalculation, "full_recalculation"),
        CronTrigger(hour=4, minute=0),
        id="full_recalculation",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Background scheduler started (full recalculation daily 4AM)")

    # Load Shopify sync settings and add job if enabled
    _load_shopify_sync_settings()


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Background scheduler stopped")


def _run_migrations():
    """Apply schema.sql then any unapplied numbered migrations on startup.

    Tracks applied migrations in a schema_migrations table so each file runs
    exactly once. Each migration runs in its own connection/transaction, so a
    failure in one doesn't poison the rest.
    """
    import pathlib
    from .database import get_connection

    server_dir = pathlib.Path(__file__).resolve().parent.parent

    # 1. Run schema.sql + create migrations tracking table in one transaction.
    #    schema.sql is fully idempotent so it's safe to re-run on every startup.
    #    Strip GRANT lines (require owner role, only needed at initial setup).
    schema_file = server_dir / "schema.sql"
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            if schema_file.exists():
                sql = "\n".join(
                    line for line in schema_file.read_text().splitlines()
                    if not line.strip().upper().startswith("GRANT")
                )
                cur.execute(sql)
                logger.info("schema.sql applied")
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Failed to apply schema.sql")
        raise
    finally:
        conn.close()

    # 2. Run unapplied numbered migrations in order. Each in its own connection
    #    so a failing migration aborts only itself.
    migrations_dir = server_dir / "migrations"
    if not migrations_dir.is_dir():
        return

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row["filename"] for row in cur.fetchall()}
    finally:
        conn.close()

    for mig in sorted(migrations_dir.glob("*.sql")):
        if mig.name in applied:
            continue
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(mig.read_text())
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (mig.name,),
                )
            conn.commit()
            logger.info(f"Migration '{mig.name}' applied")
        except Exception:
            conn.rollback()
            logger.exception(f"Migration '{mig.name}' FAILED")
            raise
        finally:
            conn.close()


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan context manager for scheduler lifecycle."""
    _run_migrations()
    start_scheduler()
    yield
    stop_scheduler()
