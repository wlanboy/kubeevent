from datetime import UTC, datetime, timedelta

from prometheus_client import REGISTRY
from sqlalchemy import text
from sqlmodel import Session

from kubeevents import metrics
from kubeevents.db import get_engine
from kubeevents.retention import delete_old_events
from kubeevents.store import save_events
from kubeevents.watcher import to_record

from .conftest import make_event


def test_delete_old_events() -> None:
    save_events([to_record(make_event(uid="old")), to_record(make_event(uid="new"))])
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10)
    with Session(get_engine()) as session:
        session.execute(
            text("UPDATE k8sevent SET created_at = :ts WHERE uid = 'old'"), {"ts": old.strftime("%Y-%m-%d %H:%M:%S")}
        )
        session.commit()

    assert delete_old_events(retention_days=7) == 1

    with Session(get_engine()) as session:
        assert session.execute(text("SELECT uid FROM k8sevent")).scalars().all() == ["new"]


def test_prune_stale_series() -> None:
    record = to_record(make_event(uid="p", involved_name="pod-prune-test"))
    labels = {"namespace": "test", "pod": "pod-prune-test", "type": "Warning"}

    metrics.record_event(record)
    assert REGISTRY.get_sample_value("kubeevents_pod_total", labels) == 1.0

    assert metrics.prune_stale_series(max_age_seconds=3600) == 0
    assert metrics.prune_stale_series(max_age_seconds=-1) > 0
    assert REGISTRY.get_sample_value("kubeevents_pod_total", labels) is None
