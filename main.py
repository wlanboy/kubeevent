import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from db import init_db, get_session, engine
from models import K8sEvent
from k8s_watcher import watch_events_loop, stop_watcher
from dotenv import load_dotenv

@asynccontextmanager
async def lifespan(app: FastAPI):
    global stop_watcher

    load_dotenv(override=False)

    init_db()

    # Async Watcher starten
    watcher_task = asyncio.create_task(watch_events_loop())

    yield

    # Shutdown
    stop_watcher = True
    watcher_task.cancel()
    try:
        await watcher_task
    except:
        pass


app = FastAPI(lifespan=lifespan)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/readyz")
async def readyz():
    try:
        with Session(engine) as session:
            session.exec("SELECT 1")
    except Exception:
        return {"status": "error", "details": "db not ready"}
    return {"status": "ready"}

@app.get("/metrics")
def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/events/latest")
def latest_events(session: Session = Depends(get_session)):
    stmt = select(K8sEvent).order_by(K8sEvent.created_at.desc()).limit(20)
    return list(session.exec(stmt))


@app.get("/events/search")
def search_events(q: str | None = None, session: Session = Depends(get_session)):
    stmt = select(K8sEvent)

    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (K8sEvent.message.ilike(like)) |
            (K8sEvent.name.ilike(like)) |
            (K8sEvent.involved_name.ilike(like))
        )

    stmt = stmt.order_by(K8sEvent.created_at.desc()).limit(200)
    return list(session.exec(stmt))

@app.get("/events/stream")
async def stream_events(
    limit: int = 100,
    session: Session = Depends(get_session)
):
    async def event_generator():
        while True:
            stmt = (
                select(K8sEvent)
                .order_by(K8sEvent.created_at.desc())
                .limit(limit)
            )
            events = list(session.exec(stmt))

            json_data = json.dumps(jsonable_encoder(events))
            yield f"data: {json_data}\n\n"

            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

