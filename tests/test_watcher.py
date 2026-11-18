import asyncio
from collections.abc import Iterator
from typing import Any

from kubernetes.client import CoreV1Event, CoreV1EventList, V1ListMeta
from kubernetes.client.exceptions import ApiException

from kubeevents.models import K8sEvent
from kubeevents.watcher import NamespaceWatcher

from .conftest import make_event


class FakeApi:
    def __init__(self, lists: list[list[CoreV1Event]]) -> None:
        self._lists = lists
        self.list_calls = 0

    def list_namespaced_event(self, namespace: str, **_: Any) -> CoreV1EventList:
        items = self._lists[min(self.list_calls, len(self._lists) - 1)]
        self.list_calls += 1
        return CoreV1EventList(items=items, metadata=V1ListMeta(resource_version=f"rv-{self.list_calls}"))


class FakeWatch:
    """Spielt pro Instanz ein Skript ab: eine Exception oder eine Liste von (Typ, Event)."""

    def __init__(self, script: list[Exception | list[tuple[str, CoreV1Event]]], on_exhausted: Any) -> None:
        self._script = script
        self._on_exhausted = on_exhausted
        self.resource_versions: list[str | None] = []

    def __call__(self) -> FakeWatch:
        return self

    def stream(self, func: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        self.resource_versions.append(kwargs.get("resource_version"))
        if not self._script:
            self._on_exhausted()
            return
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        for event_type, obj in step:
            yield {"type": event_type, "object": obj}

    def stop(self) -> None:
        pass


async def _run_watcher(api: FakeApi, fake_watch_script: list[Any]) -> tuple[list[K8sEvent], FakeWatch]:
    queue: asyncio.Queue[K8sEvent] = asyncio.Queue()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    fake_watch = FakeWatch(fake_watch_script, on_exhausted=lambda: loop.call_soon_threadsafe(stop.set))
    watcher = NamespaceWatcher("test", queue, stop, timeout_seconds=60, api=api, watch_factory=fake_watch)  # type: ignore[arg-type]

    await asyncio.wait_for(watcher.run(), timeout=10)

    records = []
    while not queue.empty():
        records.append(queue.get_nowait())
    return records, fake_watch


def test_watcher_resyncs_and_imports_after_410() -> None:
    api = FakeApi([[make_event(uid="a")], [make_event(uid="a"), make_event(uid="b")]])
    script: list[Any] = [
        ApiException(status=410),
        [("ADDED", make_event(uid="c", resource_version="200"))],
    ]

    records, fake_watch = asyncio.run(_run_watcher(api, script))

    assert api.list_calls == 2
    # Der zweite LIST importiert seine Events wieder, die DB filtert bekannte heraus
    assert [r.uid for r in records] == ["a", "a", "b", "c"]
    assert fake_watch.resource_versions[:2] == ["rv-1", "rv-2"]
    # Nach dem Watch-Event setzt der Watcher bei dessen resourceVersion fort
    assert fake_watch.resource_versions[2] == "200"


def test_watcher_skips_unchanged_modified_and_handles_deleted() -> None:
    api = FakeApi([[make_event(uid="a", count=1)]])
    script: list[Any] = [
        [
            ("MODIFIED", make_event(uid="a", count=1)),
            ("MODIFIED", make_event(uid="a", count=2)),
            ("DELETED", make_event(uid="a", count=2)),
            ("ADDED", make_event(uid="a", count=2)),
        ]
    ]

    records, _ = asyncio.run(_run_watcher(api, script))

    assert [(r.uid, r.count) for r in records] == [("a", 1), ("a", 2), ("a", 2)]
