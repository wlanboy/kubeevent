"""Weboberfläche, Event-API, SSE-Stream und Prometheus-Endpunkt."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from sqlalchemy import ColumnElement, column, or_, table, text
from sqlmodel import Session, col, func, select

from kubeevents.db import FTS_TABLE, get_engine, get_session
from kubeevents.models import K8sEvent
from kubeevents.runtime import Runtime
from kubeevents.schemas import (
    EventOut,
    Facets,
    NamespaceCount,
    ObjectCount,
    ReasonCount,
    SearchResult,
    Stats,
    WatcherStats,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

router = APIRouter()
templates = Jinja2Templates(directory=BASE_DIR / "templates")

LATEST_LIMIT = 100
STREAM_KEEPALIVE_SECONDS = 15
# Wartezeit des Browsers bis zum Neuverbinden nach einem Abbruch
STREAM_RETRY_MS = 3000
# Der Trigramm-Index findet erst Suchbegriffe ab drei Zeichen, kürzere laufen über LIKE
MIN_FULLTEXT_LENGTH = 3

FAVICON_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
    <text y=".9em" font-size="90">☸️</text>
</svg>
"""

_fts = table(FTS_TABLE, column("rowid"))


def to_db_time(value: datetime) -> datetime:
    """Wandelt einen Zeitpunkt in naive UTC um, so wie SQLite ihn speichert."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _text_filter(q: str) -> ColumnElement[bool]:
    if len(q) >= MIN_FULLTEXT_LENGTH:
        phrase = '"' + q.replace('"', '""') + '"'
        matches = select(_fts.c.rowid).where(text(f"{FTS_TABLE} MATCH :fts_query").bindparams(fts_query=phrase))
        return col(K8sEvent.id).in_(matches)

    like = f"%{q}%"
    return or_(
        col(K8sEvent.message).ilike(like),
        col(K8sEvent.name).ilike(like),
        col(K8sEvent.involved_name).ilike(like),
        col(K8sEvent.involved_kind).ilike(like),
        col(K8sEvent.namespace).ilike(like),
        col(K8sEvent.reason).ilike(like),
        col(K8sEvent.type).ilike(like),
        col(K8sEvent.component).ilike(like),
        col(K8sEvent.host).ilike(like),
    )


@router.get("/", include_in_schema=False)
def index(request: Request) -> Response:
    return templates.TemplateResponse(request, "index.html")


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(content=FAVICON_SVG, media_type="image/svg+xml")


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/events/latest")
def latest_events() -> list[EventOut]:
    events, _ = _fetch_latest(LATEST_LIMIT)
    return events


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
    session: Session = Depends(get_session),
) -> SearchResult:
    stmt = select(K8sEvent)

    if q and q.strip():
        stmt = stmt.where(_text_filter(q.strip()))
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

    stmt = (
        stmt.order_by(col(K8sEvent.created_at).desc(), col(K8sEvent.id).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    return SearchResult(
        items=[EventOut.model_validate(ev) for ev in session.exec(stmt).all()],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/events/facets")
def event_facets(session: Session = Depends(get_session)) -> Facets:
    """Werte für die Filter-Dropdowns der Suche."""
    namespaces = session.exec(select(K8sEvent.namespace).distinct().order_by(col(K8sEvent.namespace))).all()
    kinds = session.exec(
        select(col(K8sEvent.involved_kind))
        .where(col(K8sEvent.involved_kind).is_not(None))
        .distinct()
        .order_by(col(K8sEvent.involved_kind))
    ).all()
    return Facets(namespaces=list(namespaces), kinds=[k for k in kinds if k is not None])


@router.get("/events/stats")
def event_stats(
    hours: int = Query(24, ge=1, le=24 * 7),
    top: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> Stats:
    """Kennzahlen aus der Datenbank für das gewählte Zeitfenster."""
    since = utc_now_naive() - timedelta(hours=hours)
    in_window = col(K8sEvent.created_at) >= since
    is_warning = col(K8sEvent.type) == "Warning"
    count = func.count().label("count")

    by_type = session.exec(select(K8sEvent.type, count).where(in_window).group_by(col(K8sEvent.type))).all()

    namespaces = session.exec(select(func.count(func.distinct(col(K8sEvent.namespace)))).where(in_window)).one()

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

    return Stats(
        hours=hours,
        total=sum(type_counts.values()),
        by_type=type_counts,
        namespaces=namespaces,
        top_warning_namespaces=[NamespaceCount(namespace=ns, count=c) for ns, c in top_namespaces],
        top_warning_reasons=[ReasonCount(reason=r, count=c) for r, c in top_reasons],
        top_warning_objects=[ObjectCount(namespace=ns, kind=k, name=n, count=c) for ns, k, n, c in top_objects],
        watcher=WatcherStats(
            restarts=int(REGISTRY.get_sample_value("kubeevents_watch_restarts_total") or 0),
            errors=int(REGISTRY.get_sample_value("kubeevents_watch_errors_total") or 0),
        ),
    )


def _fetch_latest(limit: int) -> tuple[list[EventOut], int]:
    """Letzte Events nach Eingang plus höchste ID als Startpunkt für Deltas."""
    with Session(get_engine()) as session:
        stmt = select(K8sEvent).order_by(col(K8sEvent.created_at).desc(), col(K8sEvent.id).desc()).limit(limit)
        events = [EventOut.model_validate(ev) for ev in session.exec(stmt).all()]
        max_id = session.exec(select(func.max(K8sEvent.id))).one() or 0
        return events, max_id


def _fetch_newer(last_id: int, limit: int) -> list[EventOut]:
    with Session(get_engine()) as session:
        stmt = select(K8sEvent).where(col(K8sEvent.id) > last_id).order_by(col(K8sEvent.id).desc()).limit(limit)
        return [EventOut.model_validate(ev) for ev in session.exec(stmt).all()]


def _sse(event: str, events: list[EventOut]) -> str:
    payload: list[dict[str, Any]] = [ev.model_dump(mode="json") for ev in events]
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.get("/events/stream")
async def stream_events(request: Request, limit: int = Query(100, ge=1, le=500)) -> StreamingResponse:
    """Sendet beim Verbinden einen Snapshot, danach nur neu gespeicherte Events.

    Der Stream wartet auf Meldungen des DB-Workers. Kommt bis zum Keep-alive keine Meldung, fragt er die
    Datenbank trotzdem einmal ab. Er endet, sobald der Notifier geschlossen wird, damit uvicorn beim Shutdown
    nicht auf offene Verbindungen wartet.
    """
    runtime: Runtime = request.app.state.runtime

    async def event_generator() -> AsyncIterator[str]:
        try:
            yield f"retry: {STREAM_RETRY_MS}\n\n"

            events, last_id = await asyncio.to_thread(_fetch_latest, limit)
            yield _sse("snapshot", events)

            while not runtime.notifier.closed:
                notified = await runtime.notifier.wait_newer(last_id, STREAM_KEEPALIVE_SECONDS)
                if runtime.notifier.closed:
                    break

                newer = await asyncio.to_thread(_fetch_newer, last_id, limit)
                if newer:
                    last_id = max(ev.id for ev in newer)
                    yield _sse("append", newer)
                elif not notified:
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
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)
