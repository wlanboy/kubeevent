from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from kubernetes.client import (
    CoreV1Event,
    CoreV1EventSeries,
    V1EventSource,
    V1ObjectMeta,
    V1ObjectReference,
)

from kubeevents.config import get_settings
from kubeevents.db import get_engine, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Jeder Test bekommt eine eigene SQLite-Datei und frische Einstellungen."""
    db_path = tmp_path / "events.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WATCH_NAMESPACES", "test")
    get_settings.cache_clear()
    get_engine.cache_clear()
    init_db()
    yield db_path
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from kubeevents.app import create_app

    with TestClient(create_app(get_settings(), background=False)) as test_client:
        yield test_client


def make_event(
    uid: str = "uid-1",
    name: str = "pod-a.123",
    namespace: str = "test",
    reason: str = "BackOff",
    event_type: str = "Warning",
    message: str = "Back-off restarting failed container",
    kind: str = "Pod",
    involved_name: str = "pod-a",
    count: int | None = 1,
    resource_version: str = "100",
    legacy_fields: bool = True,
) -> CoreV1Event:
    """Baut ein CoreV1Event. legacy_fields=False belegt nur die Felder, die neuere Komponenten setzen."""
    ts = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
    metadata = V1ObjectMeta(uid=uid, name=name, namespace=namespace, resource_version=resource_version)
    involved = V1ObjectReference(kind=kind, name=involved_name, namespace=namespace)
    if legacy_fields:
        return CoreV1Event(
            metadata=metadata,
            involved_object=involved,
            reason=reason,
            type=event_type,
            message=message,
            count=count,
            first_timestamp=ts,
            last_timestamp=ts,
            source=V1EventSource(component="kubelet", host="node-1"),
        )
    return CoreV1Event(
        metadata=metadata,
        involved_object=involved,
        reason=reason,
        type=event_type,
        message=message,
        event_time=ts,
        series=CoreV1EventSeries(count=count, last_observed_time=ts.replace(hour=11)),
        reporting_component="kubelet",
        reporting_instance="node-2",
    )
