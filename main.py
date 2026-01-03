import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Response, Query
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select, func
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from db import init_db, get_session, engine
from models import K8sEvent
from k8s_watcher import watch_events_loop, stop_watcher 
from dotenv import load_dotenv

@asynccontextmanager
async def lifespan(app: FastAPI):
    import k8s_watcher 
    
    load_dotenv(override=False)
    init_db()

    watcher_task = asyncio.create_task(watch_events_loop())
    retention_task = asyncio.create_task(retention_worker())

    yield

    # Shutdown-Logik
    k8s_watcher.stop_watcher = True
    print("Stopping watcher tasks...")
    watcher_task.cancel()
    retention_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        print("Watcher task cancelled successfully.")

async def retention_worker():
    """Löscht alle Events, die älter als 7 Tage sind."""
    while not stop_watcher:
        try:
            with Session(engine) as session:
                from sqlalchemy import text
                # Beispiel: Alles älter als 7 Tage löschen
                stmt = text("DELETE FROM k8sevent WHERE created_at < datetime('now', '-7 days')")
                session.execute(stmt)
                session.commit()
            await asyncio.sleep(3600) # Einmal pro Stunde prüfen
        except Exception as e:
            print(f"Retention Error: {e}")
            await asyncio.sleep(60)

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
            session.exec(select(1)) # SQLModel-konformer Check
    except Exception:
        return {"status": "error", "details": "db not ready"}
    return {"status": "ready"}

@app.get("/metrics")
def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    svg = '''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <text y=".9em" font-size="90">☸️</text>
    </svg>
    '''
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/events/latest")
def latest_events(session: Session = Depends(get_session)):
    stmt = select(K8sEvent).order_by(K8sEvent.created_at.desc()).limit(100)
    return list(session.exec(stmt).all())

@app.get("/events/search")
def search_events(
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session)
):
    stmt = select(K8sEvent)

    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (K8sEvent.message.ilike(like)) |
            (K8sEvent.name.ilike(like)) |
            (K8sEvent.involved_name.ilike(like)) |
            (K8sEvent.involved_kind.ilike(like)) |
            (K8sEvent.namespace.ilike(like)) |
            (K8sEvent.reason.ilike(like)) |
            (K8sEvent.type.ilike(like))
        )

    # --- Count total ---
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()

    # --- Pagination ---
    offset = (page - 1) * page_size
    stmt = stmt.order_by(K8sEvent.created_at.desc()).offset(offset).limit(page_size)
    items = list(session.exec(stmt).all())

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size
    }

@app.get("/events/stream")
async def stream_events(limit: int = 100, session: Session = Depends(get_session)):
    async def event_generator():
        while True:
            stmt = select(K8sEvent).order_by(K8sEvent.created_at.desc()).limit(limit)
            events = list(session.exec(stmt).all())

            json_data = json.dumps(jsonable_encoder(events))
            yield f"data: {json_data}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")