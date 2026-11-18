"""Beobachtet Kubernetes Events pro Namespace und legt sie in die Queue des DB-Workers."""

import asyncio
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import suppress
from typing import Any

from kubernetes import client, config, watch
from kubernetes.client.exceptions import ApiException

from kubeevents.metrics import watch_errors, watch_restarts
from kubeevents.models import K8sEvent

logger = logging.getLogger(__name__)

HTTP_GONE = 410
MAX_BACKOFF_SECONDS = 30
CONNECT_TIMEOUT_SECONDS = 10
LIST_TIMEOUT_SECONDS = 60
# So lange wartet ein Watcher bei voller Queue, bevor er ein Event verwirft
ENQUEUE_TIMEOUT_SECONDS = 5
# So lange wartet der Watcher beim Stoppen auf das Ende des Stream-Threads
STREAM_STOP_TIMEOUT_SECONDS = 5

_k8s_config_loaded = False
_k8s_config_lock = threading.Lock()


def init_k8s() -> None:
    """Lädt die Kubernetes-Konfiguration einmal, im Cluster oder aus der lokalen kubeconfig."""
    global _k8s_config_loaded
    with _k8s_config_lock:
        if _k8s_config_loaded:
            return
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except config.ConfigException:
            config.load_kube_config()
            logger.info("Loaded local kubeconfig")
        _k8s_config_loaded = True


def safe_count(obj: Any) -> int:
    if obj.count is not None:
        return obj.count
    if obj.series and obj.series.count is not None:
        return obj.series.count
    return 1


def to_record(obj: Any) -> K8sEvent:
    """Wandelt ein CoreV1Event in eine Tabellenzeile.

    Neuere Komponenten setzen event_time, series und reporting_* statt first_timestamp, last_timestamp und
    source. Die alten Felder haben Vorrang, die neuen füllen die Lücken.
    """
    involved = obj.involved_object
    source = obj.source
    series = obj.series

    return K8sEvent(
        uid=obj.metadata.uid,
        name=obj.metadata.name,
        namespace=obj.metadata.namespace or "default",
        reason=obj.reason,
        type=obj.type,
        message=obj.message,
        involved_kind=involved.kind if involved else None,
        involved_name=involved.name if involved else None,
        component=obj.reporting_component or (source.component if source else None),
        host=(source.host if source else None) or obj.reporting_instance,
        first_timestamp=obj.first_timestamp or obj.event_time,
        last_timestamp=obj.last_timestamp or (series.last_observed_time if series else None) or obj.event_time,
        count=safe_count(obj),
    )


class NamespaceWatcher:
    """LIST plus WATCH für einen Namespace.

    Der Watch-Stream blockiert und läuft deshalb in einem Thread. Jedes Event geht sofort in die Queue. Beim
    Stoppen schließt Watch.stop() den Socket, damit der Thread nicht bis zum Ende des Watch-Timeouts hängt.
    """

    def __init__(
        self,
        namespace: str,
        queue: asyncio.Queue[K8sEvent],
        stop: asyncio.Event,
        timeout_seconds: int,
        api: client.CoreV1Api | None = None,
        watch_factory: Callable[[], watch.Watch] = watch.Watch,
    ) -> None:
        self.namespace = namespace
        self._queue = queue
        self._stop = stop
        self._timeout_seconds = timeout_seconds
        self._api = api
        self._watch_factory = watch_factory
        self._loop: asyncio.AbstractEventLoop | None = None
        self._resource_version: str | None = None
        # Zuletzt gesehener count je Event-UID, damit MODIFIED ohne neuen count nichts auslöst
        self._seen_counts: dict[str, int] = {}

    async def run(self) -> None:
        logger.info("[WATCH] Starting watcher for namespace=%s", self.namespace)
        loop = self._loop = asyncio.get_running_loop()
        if self._api is None:
            await asyncio.to_thread(init_k8s)
            self._api = client.CoreV1Api()
        api = self._api

        backoff = 1
        while not self._stop.is_set():
            try:
                if self._resource_version is None:
                    await self._resync(api)
                started = loop.time()
                await self._watch(api)
                backoff = 1
                # Schließt der Server den Watch sofort wieder, nicht in einer engen Schleife neu verbinden
                if loop.time() - started < 1:
                    await self._sleep(1)
            except ApiException as e:
                if e.status == HTTP_GONE:
                    logger.info("[WATCH] 410 Gone in ns=%s, starting new LIST", self.namespace)
                    self._resource_version = None
                    continue
                watch_errors.inc()
                logger.error("[WATCH] API error in ns=%s: %s", self.namespace, e)
                await self._sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            except Exception:
                watch_errors.inc()
                watch_restarts.inc()
                logger.exception("[WATCH] Unexpected error in ns=%s", self.namespace)
                await self._sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

        logger.info("[WATCH] Watcher for ns=%s stopped", self.namespace)

    async def _resync(self, api: client.CoreV1Api) -> None:
        """Liest alle Events des Namespace, legt sie in die Queue und setzt die resourceVersion neu."""
        result = await asyncio.to_thread(
            api.list_namespaced_event,
            namespace=self.namespace,
            _request_timeout=(CONNECT_TIMEOUT_SECONDS, LIST_TIMEOUT_SECONDS),
        )
        self._seen_counts = {}
        for obj in result.items:
            record = to_record(obj)
            self._seen_counts[record.uid] = record.count
            await self._enqueue(record)

        self._resource_version = result.metadata.resource_version if result.metadata else None
        logger.info(
            "[WATCH] LIST imported %d events for ns=%s (rv=%s)",
            len(result.items),
            self.namespace,
            self._resource_version,
        )

    async def _watch(self, api: client.CoreV1Api) -> None:
        """Läuft, bis der Server den Watch beendet, ein Fehler auftritt oder stop gesetzt wird."""
        w = self._watch_factory()
        stream = asyncio.ensure_future(asyncio.to_thread(self._stream, w, api))
        stopper = asyncio.ensure_future(self._stop.wait())
        try:
            done, _ = await asyncio.wait({stream, stopper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopper.cancel()
            if not stream.done():
                w.stop()

        if stream in done:
            stream.result()
            return

        # Gestoppt: Nach w.stop() endet der Thread meist mit einem Socket-Fehler, der hier keine Rolle spielt
        with suppress(Exception):
            await asyncio.wait_for(stream, timeout=STREAM_STOP_TIMEOUT_SECONDS)

    def _stream(self, w: watch.Watch, api: client.CoreV1Api) -> None:
        """Läuft im Thread. Gibt jedes neue Event sofort an die Queue weiter."""
        items: Iterator[dict[str, Any]] = w.stream(  # type: ignore[assignment]
            api.list_namespaced_event,
            namespace=self.namespace,
            resource_version=self._resource_version,
            timeout_seconds=self._timeout_seconds,
            _request_timeout=(CONNECT_TIMEOUT_SECONDS, self._timeout_seconds + 30),
        )
        for item in items:
            obj = item["object"]
            if obj.metadata and obj.metadata.resource_version:
                self._resource_version = obj.metadata.resource_version

            record = self._accept(item["type"], obj)
            if record is not None:
                self._submit(record)

    def _accept(self, event_type: str, obj: Any) -> K8sEvent | None:
        """Gibt den Record zurück, wenn das Event gespeichert werden soll."""
        uid = obj.metadata.uid
        if event_type == "DELETED":
            self._seen_counts.pop(uid, None)
            logger.debug("[WATCH] Event deleted: %s", obj.metadata.name)
            return None

        count = safe_count(obj)
        if self._seen_counts.get(uid) == count:
            return None
        self._seen_counts[uid] = count
        return to_record(obj)

    def _submit(self, record: K8sEvent) -> None:
        """Übergibt einen Record aus dem Stream-Thread an die Queue im Event-Loop."""
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(self._enqueue(record), self._loop)
        try:
            future.result(timeout=ENQUEUE_TIMEOUT_SECONDS + 1)
        except TimeoutError:
            future.cancel()

    async def _enqueue(self, record: K8sEvent) -> None:
        try:
            await asyncio.wait_for(self._queue.put(record), timeout=ENQUEUE_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("[WATCH] Queue full, dropping event in ns=%s", self.namespace)

    async def _sleep(self, seconds: float) -> None:
        """Wartet seconds Sekunden oder bis stop gesetzt wird."""
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
