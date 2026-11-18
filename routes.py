# routes.py
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from prometheus_client import REGISTRY
from sqlmodel import Session, col, func, select

from db import engine, get_session
from models import K8sEvent
from runtime import shutdown_event

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

STREAM_POLL_SECONDS = 2
STREAM_KEEPALIVE_SECONDS = 15
DATETIME_FIELDS = ("created_at", "first_timestamp", "last_timestamp")


def event_to_dict(ev: K8sEvent) -> dict[str, Any]:
    """Serialisiert ein Event. SQLite liefert naive Zeitstempel in UTC, die bekommen hier ihre Zeitzone."""
    data = ev.model_dump()
    for field in DATETIME_FIELDS:
        value = data.get(field)
        if isinstance(value, datetime) and value.tzinfo is None:
            data[field] = value.replace(tzinfo=UTC)
    return jsonable_encoder(data)


def to_db_time(value: datetime) -> datetime:
    """Wandelt einen Zeitpunkt in naive UTC um, so wie SQLite ihn speichert."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

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
    except Exception:  # noqa: BLE001 - readiness probe must not crash on any db failure
        return {"status": "error", "details": "db not ready"}
    return {"status": "ready"}


@router.get("/metrics")
def metrics():
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@router.get("/events/latest")
def latest_events(session: Session = Depends(get_session)):
    stmt = select(K8sEvent).order_by(col(K8sEvent.created_at).desc()).limit(100)
    return [event_to_dict(ev) for ev in session.exec(stmt).all()]


@router.get("/events/search")
def search_events(
    q: str | None = None,
    event_type: str | None = Query(None, alias="type"),
    namespace: str | None = None,
    kind: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session)
):
    stmt = select(K8sEvent)

    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            col(K8sEvent.message).ilike(like) |
            col(K8sEvent.name).ilike(like) |
            col(K8sEvent.involved_name).ilike(like) |
            col(K8sEvent.involved_kind).ilike(like) |
            col(K8sEvent.namespace).ilike(like) |
            col(K8sEvent.reason).ilike(like) |
            col(K8sEvent.type).ilike(like) |
            col(K8sEvent.component).ilike(like) |
            col(K8sEvent.host).ilike(like)
        )
    if event_type:
        stmt = stmt.where(col(K8sEvent.type) == event_type)
    if namespace:
        stmt = stmt.where(col(K8sEvent.namespace) == namespace)
    if kind:
        stmt = stmt.where(col(K8sEvent.involved_kind) == kind)
    if since:
        stmt = stmt.where(col(K8sEvent.created_at) >= to_db_time(since))
    if until:
        stmt = stmt.where(col(K8sEvent.created_at) <= to_db_time(until))

    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()

    offset = (page - 1) * page_size
    stmt = (
        stmt.order_by(col(K8sEvent.created_at).desc(), col(K8sEvent.id).desc())
        .offset(offset)
        .limit(page_size)
    )
    items = [event_to_dict(ev) for ev in session.exec(stmt).all()]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size
    }


@router.get("/events/facets")
def event_facets(session: Session = Depends(get_session)):
    """Werte für die Filter-Dropdowns der Suche."""
    namespaces = session.exec(
        select(K8sEvent.namespace).distinct().order_by(col(K8sEvent.namespace))
    ).all()
    kinds = session.exec(
        select(K8sEvent.involved_kind)
        .where(col(K8sEvent.involved_kind).is_not(None))
        .distinct()
        .order_by(col(K8sEvent.involved_kind))
    ).all()
    return {"namespaces": list(namespaces), "kinds": list(kinds)}


@router.get("/events/stats")
def event_stats(
    hours: int = Query(24, ge=1, le=24 * 7),
    top: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
):
    """Kennzahlen aus der Datenbank für das gewählte Zeitfenster."""
    since = utc_now_naive() - timedelta(hours=hours)
    in_window = col(K8sEvent.created_at) >= since
    is_warning = col(K8sEvent.type) == "Warning"
    count = func.count().label("count")

    by_type = session.exec(
        select(K8sEvent.type, count).where(in_window).group_by(col(K8sEvent.type))
    ).all()

    namespaces = session.exec(
        select(func.count(func.distinct(col(K8sEvent.namespace)))).where(in_window)
    ).one()

    top_namespaces = session.exec(
        select(K8sEvent.namespace, count)
        .where(in_window, is_warning)
        .group_by(col(K8sEvent.namespace))
        .order_by(count.desc())
        .limit(top)
    ).all()

    top_reasons = session.exec(
        select(K8sEvent.reason, count)
        .where(in_window, is_warning)
        .group_by(col(K8sEvent.reason))
        .order_by(count.desc())
        .limit(top)
    ).all()

    top_objects = session.exec(
        select(K8sEvent.namespace, K8sEvent.involved_kind, K8sEvent.involved_name, count)
        .where(in_window, is_warning)
        .group_by(col(K8sEvent.namespace), col(K8sEvent.involved_kind), col(K8sEvent.involved_name))
        .order_by(count.desc())
        .limit(top)
    ).all()

    type_counts = {t or "Unknown": c for t, c in by_type}

    return {
        "hours": hours,
        "total": sum(type_counts.values()),
        "by_type": type_counts,
        "namespaces": namespaces,
        "top_warning_namespaces": [{"namespace": ns, "count": c} for ns, c in top_namespaces],
        "top_warning_reasons": [{"reason": r, "count": c} for r, c in top_reasons],
        "top_warning_objects": [
            {"namespace": ns, "kind": k, "name": n, "count": c} for ns, k, n, c in top_objects
        ],
        "watcher": {
            "restarts": int(REGISTRY.get_sample_value("kubeevents_watch_restarts_total") or 0),
            "errors": int(REGISTRY.get_sample_value("kubeevents_watch_errors_total") or 0),
        },
    }


def _fetch_latest(limit: int) -> tuple[list[dict[str, Any]], int]:
    """Letzte Events nach Eingang plus höchste ID als Startpunkt für Deltas."""
    with Session(engine) as session:
        stmt = (
            select(K8sEvent)
            .order_by(col(K8sEvent.created_at).desc(), col(K8sEvent.id).desc())
            .limit(limit)
        )
        events = [event_to_dict(ev) for ev in session.exec(stmt).all()]
        max_id = session.exec(select(func.max(K8sEvent.id))).one() or 0
        return events, max_id


def _fetch_newer(last_id: int, limit: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        stmt = (
            select(K8sEvent)
            .where(col(K8sEvent.id) > last_id)
            .order_by(col(K8sEvent.id).desc())
            .limit(limit)
        )
        return [event_to_dict(ev) for ev in session.exec(stmt).all()]


def _sse(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.get("/events/stream")
async def stream_events(limit: int = Query(100, ge=1, le=500)):
    """Sendet beim Verbinden einen Snapshot, danach nur neu gespeicherte Events."""
    async def event_generator():
        try:
            yield f"retry: {STREAM_POLL_SECONDS * 1500}\n\n"

            events, last_id = await asyncio.to_thread(_fetch_latest, limit)
            yield _sse("snapshot", events)

            idle = 0
            while not shutdown_event.is_set():
                await asyncio.sleep(STREAM_POLL_SECONDS)

                newer = await asyncio.to_thread(_fetch_newer, last_id, limit)
                if newer:
                    last_id = max(ev["id"] for ev in newer)
                    idle = 0
                    yield _sse("append", newer)
                    continue

                idle += STREAM_POLL_SECONDS
                if idle >= STREAM_KEEPALIVE_SECONDS:
                    idle = 0
                    yield ": keep-alive\n\n"

        except asyncio.CancelledError:
            logger.debug("SSE client disconnected or shutdown")
        except Exception:
            logger.exception("SSE stream error")

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
