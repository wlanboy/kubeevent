import asyncio
import os
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from sqlmodel import Session
from db import init_db, engine
from k8s_watcher import watch_events_loop
from runtime import shutdown_event
import runtime  # für stop_watcher
from routes import router

from dotenv import load_dotenv
import aiocron


# ============================================================
# SIGNAL HANDLING
# ============================================================

def handle_sigterm(*_):
    print("[SIGNAL] SIGTERM/SIGINT received → triggering shutdown...")
    shutdown_event.set()

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)


# ============================================================
# RETENTION JOB (Cron)
# ============================================================

async def retention_job():
    print("[CRON] Running retention job...")
    with Session(engine) as session:
        from sqlalchemy import text
        stmt = text("DELETE FROM k8sevent WHERE created_at < datetime('now', '-7 days')")
        session.execute(stmt)
        session.commit()
    print("[CRON] Retention job complete")


async def retention_worker():
    print("[TASK] retention_worker started")

    cron = aiocron.crontab("0 * * * *", func=retention_job)

    try:
        await shutdown_event.wait()
    finally:
        cron.stop()
        print("[TASK] retention_worker stopped")


# ============================================================
# TASKGROUP RUNNER
# ============================================================

taskgroup_task: asyncio.Task | None = None

async def run_taskgroup():
    print("[TASKGROUP] Starting TaskGroup...")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(watch_events_loop())
        print("[TASKGROUP] watcher_task started")

        tg.create_task(retention_worker())
        print("[TASKGROUP] retention_worker started")

        print("[TASKGROUP] Waiting for shutdown_event...")
        await shutdown_event.wait()

        print("[TASKGROUP] shutdown_event triggered → TaskGroup will cancel tasks")

    print("[TASKGROUP] TaskGroup exited cleanly")


# ============================================================
# LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFESPAN] Startup initiated")

    # Ensure DB directory exists
    DB_PATH = os.getenv("DB_PATH", "data/events.db")
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        print(f"[LIFESPAN] Ensured DB directory exists: {db_dir}")

    load_dotenv(override=False)
    init_db()
    print("[LIFESPAN] Database initialized")

    # Start TaskGroup in background
    global taskgroup_task
    taskgroup_task = asyncio.create_task(run_taskgroup())
    print("[LIFESPAN] TaskGroup started in background")

    print("[LIFESPAN] Startup complete")
    yield  # REST API becomes available here

    # ============================================================
    # SHUTDOWN
    # ============================================================

    print("[LIFESPAN] Shutdown initiated")

    # global stop_watcher setzen
    runtime.stop_watcher = True
    shutdown_event.set()

    print("[LIFESPAN] Waiting for TaskGroup to finish...")

    # FIX: TaskGroup nur awaiten, wenn sie noch läuft
    if taskgroup_task and not taskgroup_task.done():
        try:
            await asyncio.wait_for(taskgroup_task, timeout=5)
        except asyncio.TimeoutError:
            print("[LIFESPAN] TaskGroup timeout — forcing shutdown")
    else:
        print("[LIFESPAN] TaskGroup already finished")

    print("[LIFESPAN] Shutdown complete")


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(lifespan=lifespan)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routen aus routes.py einbinden
app.include_router(router)


# ============================================================
# ROOT + FAVICON
# ============================================================

@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    svg = '''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <text y=".9em" font-size="90">☸️</text>
    </svg>
    '''
    return Response(content=svg, media_type="image/svg+xml")
