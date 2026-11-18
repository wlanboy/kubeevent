"""Antwortmodelle der HTTP-API."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite liefert naive Zeitstempel in UTC, die bekommen hier ihre Zeitzone."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


UtcDatetime = Annotated[datetime | None, AfterValidator(_as_utc)]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uid: str
    name: str
    namespace: str
    reason: str | None
    type: str | None
    message: str | None
    involved_kind: str | None
    involved_name: str | None
    component: str | None
    host: str | None
    first_timestamp: UtcDatetime
    last_timestamp: UtcDatetime
    count: int | None
    created_at: UtcDatetime


class SearchResult(BaseModel):
    items: list[EventOut]
    total: int
    page: int
    page_size: int
    pages: int


class Facets(BaseModel):
    namespaces: list[str]
    kinds: list[str]


class NamespaceCount(BaseModel):
    namespace: str
    count: int


class ReasonCount(BaseModel):
    reason: str | None
    count: int


class ObjectCount(BaseModel):
    namespace: str
    kind: str | None
    name: str | None
    count: int


class WatcherStats(BaseModel):
    restarts: int
    errors: int


class Stats(BaseModel):
    hours: int
    total: int
    by_type: dict[str, int]
    namespaces: int
    top_warning_namespaces: list[NamespaceCount]
    top_warning_reasons: list[ReasonCount]
    top_warning_objects: list[ObjectCount]
    watcher: WatcherStats


class HealthStatus(BaseModel):
    status: str
    details: str | None = None
