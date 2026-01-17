import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from sqlmodel import Session
from sqlalchemy import text
from db import init_db, engine
from k8s_watcher import watch_events_loop
from runtime import shutdown_event
from routes import router

from dotenv import load_dotenv
import aiocron

logger = logging.getLogger(__name__)

# ============================================================
# RETENTION JOB (Cron)
# ============================================================

async def retention_job() -> None:
    """Löscht Events älter als 7 Tage."""
    logger.info("Running retention job...")
    with Session(engine) as session:
        from sqlalchemy import text
        stmt = text("DELETE FROM k8sevent WHERE created_at < datetime('now', '-7 days')")
        result = session.exec(stmt)
        session.commit()
        logger.info(f"Retention job complete, deleted {result.rowcount} rows")


async def retention_worker() -> None:
    """Führt stündlich den Retention-Job aus."""
    logger.info("retention_worker started")

    cron = aiocron.crontab("0 * * * *", func=retention_job)

    try:
        await shutdown_event.wait()
    finally:
        cron.stop()
        logger.info("retention_worker stopped")


# ============================================================
# TASKGROUP RUNNER
# ============================================================

taskgroup_task: asyncio.Task | None = None


async def run_taskgroup() -> None:
    """Startet alle Hintergrund-Tasks in einer TaskGroup."""
    logger.info("Starting TaskGroup...")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(watch_events_loop(), name="watch_events_loop")
        logger.info("watcher_task started")

        tg.create_task(retention_worker(), name="retention_worker")
        logger.info("retention_worker started")

        logger.debug("Waiting for shutdown_event...")
        await shutdown_event.wait()

        logger.info("shutdown_event triggered → TaskGroup will cancel tasks")

    logger.info("TaskGroup exited cleanly")


# ============================================================
# LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup initiated")

    # Ensure DB directory exists
    db_path = os.getenv("DB_PATH", "data/events.db")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        logger.debug(f"Ensured DB directory exists: {db_dir}")

    load_dotenv(override=False)
    init_db()
    logger.info("Database initialized")

    # Start TaskGroup in background
    global taskgroup_task
    taskgroup_task = asyncio.create_task(run_taskgroup(), name="taskgroup")
    logger.info("TaskGroup started in background")

    logger.info("Startup complete")
    yield  # REST API becomes available here

    # ============================================================
    # SHUTDOWN
    # ============================================================

    logger.info("Shutdown initiated")

    shutdown_event.set()

    logger.info("Waiting for TaskGroup to finish...")

    # TaskGroup nur awaiten, wenn sie noch läuft
    if taskgroup_task and not taskgroup_task.done():
        try:
            await asyncio.wait_for(taskgroup_task, timeout=5)
        except asyncio.TimeoutError:
            logger.warning("TaskGroup timeout — forcing shutdown")
            taskgroup_task.cancel()
    else:
        logger.debug("TaskGroup already finished")

    logger.info("Shutdown complete")


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Routen aus routes.py einbinden
app.include_router(router)
