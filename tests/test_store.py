import asyncio

from prometheus_client import REGISTRY
from sqlmodel import Session, func, select

from kubeevents.db import get_engine
from kubeevents.models import K8sEvent
from kubeevents.notifier import EventNotifier
from kubeevents.store import flush, save_events
from kubeevents.watcher import to_record

from .conftest import make_event


def _row_count() -> int:
    with Session(get_engine()) as session:
        return session.exec(select(func.count()).select_from(K8sEvent)).one()


def _pod_metric(pod: str) -> float:
    labels = {"namespace": "test", "pod": pod, "type": "Warning"}
    return REGISTRY.get_sample_value("kubeevents_pod_total", labels) or 0.0


def test_save_events_skips_known_and_duplicate_keys() -> None:
    first = save_events([to_record(make_event(uid="a")), to_record(make_event(uid="a"))])
    assert [r.uid for r in first] == ["a"]
    assert first[0].id is not None

    second = save_events([to_record(make_event(uid="a")), to_record(make_event(uid="a", count=2))])
    assert [(r.uid, r.count) for r in second] == [("a", 2)]
    assert _row_count() == 2


def test_flush_counts_metrics_only_for_new_events() -> None:
    pod = "pod-metrics-test"
    notifier = EventNotifier()
    records = [to_record(make_event(uid="m1", involved_name=pod))]

    asyncio.run(flush(records, notifier))
    asyncio.run(flush([to_record(make_event(uid="m1", involved_name=pod))], notifier))

    assert _pod_metric(pod) == 1.0
    assert _row_count() == 1
