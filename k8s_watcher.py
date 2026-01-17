import os
import asyncio
import logging
from typing import List, Set, Tuple

from kubernetes import client, config, watch
from sqlmodel import Session, select
from sqlalchemy import tuple_

from db import engine
from models import K8sEvent
from metrics import (
    events_total, events_by_type, events_by_namespace,
    events_by_namespace_type, watch_errors, watch_restarts,
    events_by_involved, events_by_pod, events_by_deployment,
    events_by_component, events_by_node
)
import runtime

logger = logging.getLogger(__name__)

# Queue mit maxsize um Speicherüberlauf zu verhindern
event_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)

# ============================================================
# HELFER
# ============================================================

def get_namespaces() -> List[str]:
    raw = os.getenv("POD_NAMESPACE", "demo")
    namespaces = [ns.strip() for ns in raw.split(",") if ns.strip()]
    logger.info(f"Using namespaces: {namespaces}")
    return namespaces


def init_k8s() -> None:
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig")


# ============================================================
# METRICS + DB SAVE
# ============================================================

def process_metrics(ev) -> None:
    """Aktualisiert Prometheus-Metriken für ein Event."""
    namespace = ev.metadata.namespace or "default"
    event_type = ev.type or "unknown"
    kind = getattr(ev.involved_object, "kind", None) or "unknown"
    involved_name = getattr(ev.involved_object, "name", None) or "unknown"
    reason = ev.reason or "unknown"
    component = getattr(ev, "reporting_component", None) or "unknown"
    host = getattr(ev.source, "host", None) or "unknown" if ev.source else "unknown"

    # 1) Gesamt
    events_total.inc()

    # 2) Nach Typ
    events_by_type.labels(type=event_type).inc()

    # 3) Nach Namespace
    events_by_namespace.labels(namespace=namespace).inc()

    # 4) Nach Namespace + Typ
    events_by_namespace_type.labels(namespace=namespace, type=event_type).inc()

    # 5) Nach betroffenem Objekt (detailliert)
    events_by_involved.labels(
        namespace=namespace,
        type=event_type,
        kind=kind,
        involved_name=involved_name,
        reason=reason,
        component=component
    ).inc()

    # 6) Nach Komponente
    if component != "unknown":
        events_by_component.labels(component=component).inc()

    # 7) Nach Node/Host
    if host != "unknown":
        events_by_node.labels(host=host).inc()

    # 8) Nach Pod
    if kind == "Pod":
        events_by_pod.labels(namespace=namespace, pod=involved_name, type=event_type).inc()

    # 9) Nach Deployment
    if kind == "Deployment":
        events_by_deployment.labels(namespace=namespace, deployment=involved_name, type=event_type).inc()


def sync_db_save(events: list) -> None:
    """Speichert Events in die Datenbank (wird im ThreadPool ausgeführt)."""
    if not events:
        return

    logger.debug(f"Saving batch of {len(events)} events")

    # 1) Alle Keys extrahieren
    keys: Set[Tuple[str, int]] = {(ev.metadata.uid, ev.count or 1) for ev in events}

    with Session(engine) as session:
        # 2) Einmalig alle existierenden Events laden
        stmt = select(K8sEvent.uid, K8sEvent.count).where(
            tuple_(K8sEvent.uid, K8sEvent.count).in_(keys)
        )
        existing_rows: Set[Tuple[str, int]] = set(session.exec(stmt).all())

        # 3) Neue Events filtern und Metriken verarbeiten
        new_events: List[K8sEvent] = []
        for ev in events:
            process_metrics(ev)

            key = (ev.metadata.uid, ev.count or 1)
            if key in existing_rows:
                continue

            # Component und Host extrahieren
            component = getattr(ev, "reporting_component", None)
            host = getattr(ev.source, "host", None) if ev.source else None

            new_events.append(
                K8sEvent(
                    uid=ev.metadata.uid,
                    name=ev.metadata.name,
                    namespace=ev.metadata.namespace or "default",
                    reason=ev.reason,
                    type=ev.type,
                    message=ev.message,
                    involved_kind=getattr(ev.involved_object, "kind", None),
                    involved_name=getattr(ev.involved_object, "name", None),
                    component=component,
                    host=host,
                    first_timestamp=ev.first_timestamp,
                    last_timestamp=ev.last_timestamp,
                    count=ev.count or 1
                )
            )

        if not new_events:
            logger.debug("No new events to insert")
            return

        # 4) Bulk insert
        session.add_all(new_events)

        try:
            session.commit()
            logger.info(f"Batch committed ({len(new_events)} new events)")
        except Exception as e:
            logger.error(f"Error during commit: {e}", exc_info=True)
            session.rollback()


# ============================================================
# ADAPTIVER, NICHT-BLOCKIERENDER DB WORKER
# ============================================================

async def db_worker() -> None:
    """Verarbeitet Events aus der Queue und speichert sie in Batches."""
    logger.info("DB worker started")

    MAX_DELAY = 0.2  # max 200ms
    MAX_BATCH = 500  # adaptive upper bound

    loop = asyncio.get_running_loop()

    while not runtime.shutdown_event.is_set():
        try:
            # Warte auf erstes Event
            try:
                ev = await asyncio.wait_for(event_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            batch = [ev]

            # Adaptives Sammeln mit korrekter Zeit-API
            start = loop.time()

            while len(batch) < MAX_BATCH:
                remaining = MAX_DELAY - (loop.time() - start)
                if remaining <= 0:
                    break

                try:
                    ev = await asyncio.wait_for(event_queue.get(), timeout=remaining)
                    batch.append(ev)
                except asyncio.TimeoutError:
                    break

            await loop.run_in_executor(None, sync_db_save, batch)

            for _ in batch:
                event_queue.task_done()

        except asyncio.CancelledError:
            logger.info("DB worker cancelled")
            break
        except Exception as e:
            logger.error(f"DB worker error: {e}", exc_info=True)

    logger.info("DB worker stopped")


# ============================================================
# SMARTER WATCHER MIT BACKOFF + HEARTBEAT
# ============================================================

def _list_events(v1: client.CoreV1Api, namespace: str):
    """Synchrone Hilfsfunktion für LIST-Aufruf."""
    return v1.list_namespaced_event(namespace=namespace)


def _watch_events(v1: client.CoreV1Api, namespace: str, resource_version: str | None):
    """Synchrone Hilfsfunktion für Watch-Stream."""
    w = watch.Watch()
    return list(w.stream(
        v1.list_namespaced_event,
        namespace=namespace,
        resource_version=resource_version,
        timeout_seconds=30
    ))


async def watch_namespace(namespace: str) -> None:
    """Überwacht Events in einem Namespace mit Backoff und 410-Handling."""
    logger.info(f"Starting watcher for namespace={namespace}")

    v1 = client.CoreV1Api()
    loop = asyncio.get_running_loop()
    backoff = 1
    resource_version: str | None = None

    # ============================================================
    # 1) Initialer LIST → resourceVersion bestimmen
    # ============================================================
    try:
        initial = await loop.run_in_executor(None, _list_events, v1, namespace)
        resource_version = initial.metadata.resource_version
        logger.info(f"Initial LIST for ns={namespace}, rv={resource_version}")
    except Exception as e:
        logger.warning(f"Initial LIST failed for ns={namespace}: {e}")

    # ============================================================
    # 2) Hauptschleife
    # ============================================================
    while not runtime.shutdown_event.is_set():
        try:
            events = await loop.run_in_executor(
                None, _watch_events, v1, namespace, resource_version
            )

            if not events:
                logger.debug(f"Empty stream for ns={namespace}, reconnecting...")
                await asyncio.sleep(1)
                continue

            logger.debug(f"Received {len(events)} events from ns={namespace}")

            # Backoff resetten
            backoff = 1

            # Events verarbeiten
            for ev in events:
                obj = ev["object"]
                resource_version = obj.metadata.resource_version

                try:
                    event_queue.put_nowait(obj)
                except asyncio.QueueFull:
                    logger.warning(f"Queue full, dropping event in ns={namespace}")

        # ============================================================
        # 410 Gone → ResourceVersion zu alt → neuen LIST-Sync machen
        # ============================================================
        except client.exceptions.ApiException as e:
            if e.status == 410:
                logger.info(f"410 Gone in ns={namespace} → resetting resourceVersion")

                try:
                    initial = await loop.run_in_executor(None, _list_events, v1, namespace)
                    resource_version = initial.metadata.resource_version
                    logger.info(f"New LIST rv={resource_version} for ns={namespace}")
                except Exception as e2:
                    logger.error(f"LIST retry failed for ns={namespace}: {e2}")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

                continue

            watch_errors.inc()
            logger.error(f"API error in ns={namespace}: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

        # ============================================================
        # Cancel
        # ============================================================
        except asyncio.CancelledError:
            logger.info(f"Watcher for ns={namespace} cancelled")
            break

        # ============================================================
        # Andere Fehler → Backoff
        # ============================================================
        except Exception as e:
            watch_errors.inc()
            watch_restarts.inc()
            logger.error(f"Unexpected error in ns={namespace}: {e}", exc_info=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    logger.info(f"Watcher for ns={namespace} stopped")

# ============================================================
# HAUPTSCHLEIFE
# ============================================================

async def watch_events_loop() -> None:
    """Hauptschleife: Startet DB-Worker und Namespace-Watcher."""
    logger.info("watch_events_loop starting...")
    init_k8s()
    namespaces = get_namespaces()

    while not runtime.shutdown_event.is_set():
        logger.info("Starting watcher + db_worker cycle")

        worker_task = asyncio.create_task(db_worker(), name="db_worker")
        watcher_tasks = [
            asyncio.create_task(watch_namespace(ns), name=f"watcher_{ns}")
            for ns in namespaces
        ]

        all_tasks = [worker_task, *watcher_tasks]

        try:
            # return_exceptions=True verhindert, dass eine Exception alles beendet
            results = await asyncio.gather(*all_tasks, return_exceptions=True)

            # Logging, falls etwas unerwartet beendet wurde
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    task_name = all_tasks[i].get_name()
                    logger.error(f"Task {task_name} ended with exception: {r}")

        except asyncio.CancelledError:
            logger.info("watch_events_loop cancelled, cleaning up...")
            for task in all_tasks:
                task.cancel()
            await asyncio.gather(*all_tasks, return_exceptions=True)
            break

        # Wenn wir hier landen, sind alle Tasks durch – evtl. unerwartet
        if not runtime.shutdown_event.is_set():
            logger.warning("Tasks ended unexpectedly, restarting...")
            await asyncio.sleep(2)

    logger.info("watch_events_loop exiting")
