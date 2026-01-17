# routes.py
import asyncio
import json
import logging
from fastapi import APIRouter, Request, Depends, Response, Query
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, select, func
from fastapi.templating import Jinja2Templates

from db import get_session, engine
from models import K8sEvent
from runtime import shutdown_event

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@router.get('/favicon.ico', include_in_schema=False)
async def favicon():
    svg = '''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <text y=".9em" font-size="90">☸️</text>
    </svg>
    '''
    return Response(content=svg, media_type="image/svg+xml")

@router.get("/healthz")
async def healthz():
    return {"status": "ok"}

@router.get("/readyz")
async def readyz():
    try:
        with Session(engine) as session:
            session.exec(select(1))
    except Exception:
        return {"status": "error", "details": "db not ready"}
    return {"status": "ready"}


@router.get("/metrics")
def metrics():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@router.get("/events/latest")
def latest_events(session: Session = Depends(get_session)):
    stmt = select(K8sEvent).order_by(K8sEvent.created_at.desc()).limit(100)
    return list(session.exec(stmt).all())


@router.get("/events/search")
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

    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()

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

@router.get("/events/stream")
async def stream_events(limit: int = Query(100, ge=1, le=500)):
    async def event_generator():
        try:
            while not shutdown_event.is_set():
                # Session innerhalb der Loop erstellen um Lifecycle-Probleme zu vermeiden
                with Session(engine) as session:
                    stmt = select(K8sEvent).order_by(K8sEvent.created_at.desc()).limit(limit)
                    events = list(session.exec(stmt).all())
                    json_data = json.dumps(jsonable_encoder(events))

                # SSE event
                yield f"data: {json_data}\n\n"

                # keep-alive comment
                yield ": keep-alive\n\n"

                await asyncio.sleep(2)

        except asyncio.CancelledError:
            logger.debug("SSE client disconnected or shutdown")
        except Exception as e:
            logger.error(f"SSE stream error: {e}", exc_info=True)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers
    )

