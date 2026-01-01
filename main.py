import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from db import init_db, get_session
from models import K8sEvent
from k8s_watcher import watch_events_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, watch_events_loop)

    yield

    # Shutdown (optional)
    # Hier könntest du später den Watch sauber stoppen.

app = FastAPI(lifespan=lifespan)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


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
async def stream_events(session: Session = Depends(get_session)):
    async def event_generator():
        while True:
            stmt = select(K8sEvent).order_by(K8sEvent.created_at.desc()).limit(100)
            events = list(session.exec(stmt))

            json_data = json.dumps(jsonable_encoder(events))
            yield f"data: {json_data}\n\n"

            await asyncio.sleep(3)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
