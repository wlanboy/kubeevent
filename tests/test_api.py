from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from kubeevents import health
from kubeevents.db import get_engine
from kubeevents.store import save_events
from kubeevents.watcher import to_record

from .conftest import make_event


@pytest.fixture
def events() -> None:
    save_events(
        [
            to_record(make_event(uid="e1", namespace="alpha", message="Back-off restarting failed container")),
            to_record(make_event(uid="e2", namespace="alpha", event_type="Normal", reason="Pulled", message="ok")),
            to_record(make_event(uid="e3", namespace="beta", kind="Node", involved_name="node-1", message="NodeReady")),
        ]
    )


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_ok(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readyz_db_failure(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlmodel import create_engine

    broken = create_engine(f"sqlite:///{tmp_path}/missing/dir/x.db")
    monkeypatch.setattr(health, "get_engine", lambda: broken)

    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["details"] == "db not ready"


def test_readyz_background_stopped(client: TestClient) -> None:
    class FinishedTask:
        def done(self) -> bool:
            return True

    client.app.state.runtime.background = FinishedTask()  # type: ignore[attr-defined]

    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["details"] == "background tasks stopped"


@pytest.mark.usefixtures("events")
def test_search_filters_and_pagination(client: TestClient) -> None:
    data = client.get("/events/search", params={"namespace": "alpha", "page_size": 1}).json()
    assert data["total"] == 2
    assert data["pages"] == 2
    assert len(data["items"]) == 1

    data = client.get("/events/search", params={"type": "Warning", "kind": "Node"}).json()
    assert [item["uid"] for item in data["items"]] == ["e3"]


@pytest.mark.usefixtures("events")
def test_search_fulltext_and_short_query(client: TestClient) -> None:
    data = client.get("/events/search", params={"q": "restarting FAILED"}).json()
    assert [item["uid"] for item in data["items"]] == ["e1"]

    # Zwei Zeichen laufen über LIKE statt über den Trigramm-Index
    data = client.get("/events/search", params={"q": "ok"}).json()
    assert [item["uid"] for item in data["items"]] == ["e2"]


@pytest.mark.usefixtures("events")
def test_search_time_window(client: TestClient) -> None:
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    data = client.get("/events/search", params={"since": future}).json()
    assert data["total"] == 0


@pytest.mark.usefixtures("events")
def test_event_timestamps_have_timezone(client: TestClient) -> None:
    item = client.get("/events/latest").json()[0]
    assert item["created_at"].endswith("Z")
    assert item["first_timestamp"].endswith("Z")


@pytest.mark.usefixtures("events")
def test_facets(client: TestClient) -> None:
    assert client.get("/events/facets").json() == {"namespaces": ["alpha", "beta"], "kinds": ["Node", "Pod"]}


@pytest.mark.usefixtures("events")
def test_stats(client: TestClient) -> None:
    data = client.get("/events/stats", params={"hours": 1}).json()
    assert data["total"] == 3
    assert data["by_type"] == {"Warning": 2, "Normal": 1}
    assert data["namespaces"] == 2
    assert {"namespace": "alpha", "count": 1} in data["top_warning_namespaces"]
    assert set(data["watcher"]) == {"restarts", "errors"}


@pytest.mark.usefixtures("events")
def test_fulltext_index_follows_deletes(client: TestClient) -> None:
    with Session(get_engine()) as session:
        session.execute(text("DELETE FROM k8sevent WHERE uid = 'e1'"))
        session.commit()

    data = client.get("/events/search", params={"q": "restarting"}).json()
    assert data["total"] == 0
