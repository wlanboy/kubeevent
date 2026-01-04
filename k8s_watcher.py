import os
import asyncio
from typing import List

from kubernetes import client, config, watch
from sqlmodel import Session, select

from db import engine
from models import K8sEvent
from metrics import (
    events_total, events_by_type, events_by_namespace,
    events_by_namespace_type, watch_errors, watch_restarts,
    events_by_involved, events_by_pod, events_by_deployment
)
import runtime

runtime.stop_watcher = False
event_queue: asyncio.Queue = asyncio.Queue()

# ============================================================
# HELFER
# ============================================================

def get_namespaces() -> List[str]:
    raw = os.getenv("POD_NAMESPACE", "demo")
    namespaces = [ns.strip() for ns in raw.split(",") if ns.strip()]
    print(f"[WATCH] Using namespaces: {namespaces}")
    return namespaces

def init_k8s():
    try:
        config.load_incluster_config()
        print("[WATCH] Loaded in-cluster Kubernetes config")
    except Exception:
        config.load_kube_config()
        print("[WATCH] Loaded local kubeconfig")


# ============================================================
# METRICS + DB SAVE
# ============================================================

def process_metrics(ev):
    namespace = ev.metadata.namespace or "default"
    event_type = ev.type or "Unknown"
    kind = getattr(ev.involved_object, "kind", "Unknown")
    involved_name = getattr(ev.involved_object, "name", "Unknown")
    reason = ev.reason or "Unknown"
    component = getattr(ev, "reporting_component", "Unknown") or "Unknown"

    events_total.inc()
    events_by_type.labels(type=event_type).inc()
    events_by_namespace.labels(namespace=namespace).inc()
    events_by_namespace_type.labels(namespace=namespace, type=event_type).inc()

    events_by_involved.labels(
        namespace=namespace,
        type=event_type,
        kind=kind,
        involved_name=involved_name,
        reason=reason,
        component=component
    ).inc()

    if kind == "Pod":
        events_by_pod.labels(namespace=namespace, pod=involved_name, type=event_type).inc()

    if kind == "Deployment":
        events_by_deployment.labels(namespace=namespace, deployment=involved_name, type=event_type).inc()


def sync_db_save(events: list):
    if not events:
        return

    print(f"[DB] Saving batch of {len(events)} events")
    with Session(engine) as session:
        for ev in events:
            process_metrics(ev)

            uid = ev.metadata.uid
            current_count = ev.count or 1

            stmt = select(K8sEvent).where(
                K8sEvent.uid == uid,
                K8sEvent.count == current_count
            )
            existing = session.exec(stmt).first()

            if not existing:
                obj = K8sEvent(
                    uid=uid,
                    name=ev.metadata.name,
                    namespace=ev.metadata.namespace or "default",
                    reason=ev.reason,
                    type=ev.type,
                    message=ev.message,
                    involved_kind=getattr(ev.involved_object, "kind", None),
                    involved_name=getattr(ev.involved_object, "name", None),
                    first_timestamp=ev.first_timestamp,
                    last_timestamp=ev.last_timestamp,
                    count=current_count
                )
                session.add(obj)

        try:
            session.commit()
            print("[DB] Batch committed")
        except Exception as e:
            print(f"[DB] Error during commit: {e}")
            session.rollback()


# ============================================================
# ADAPTIVER, NICHT-BLOCKIERENDER DB WORKER
# ============================================================

async def db_worker():
    print("[DB] worker started")

    MAX_DELAY = 0.2  # max 200ms
    MAX_BATCH = 500  # adaptive upper bound

    while not runtime.stop_watcher:
        try:
            # Warte auf erstes Event
            try:
                ev = await asyncio.wait_for(event_queue.get(), timeout=1)
            except asyncio.TimeoutError:
                continue

            batch = [ev]

            # adaptives Sammeln
            start = asyncio.get_event_loop().time()

            while len(batch) < MAX_BATCH:
                remaining = MAX_DELAY - (asyncio.get_event_loop().time() - start)
                if remaining <= 0:
                    break

                try:
                    ev = await asyncio.wait_for(event_queue.get(), timeout=remaining)
                    batch.append(ev)
                except asyncio.TimeoutError:
                    break

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, sync_db_save, batch)

            for _ in batch:
                event_queue.task_done()

        except asyncio.CancelledError:
            print("[DB] worker cancelled")
            break
        except Exception as e:
            print(f"[DB] worker error: {e}")

    print("[DB] worker stopped")


# ============================================================
# SMARTER WATCHER MIT BACKOFF + HEARTBEAT
# ============================================================

async def watch_namespace(namespace: str):
    print(f"[WATCH] starting watcher for namespace={namespace}")

    v1 = client.CoreV1Api()
    w = watch.Watch()
    resource_version = None

    loop = asyncio.get_running_loop()
    backoff = 1  # Start bei 1s

    while not runtime.stop_watcher:
        try:
            def _stream_once():
                return list(w.stream(
                    v1.list_namespaced_event,
                    namespace=namespace,
                    resource_version=resource_version,
                    timeout_seconds=5
                ))

            events = await loop.run_in_executor(None, _stream_once)

            # Erfolgreich → Backoff resetten
            backoff = 1

            for event in events:
                if runtime.stop_watcher:
                    break

                obj = event["object"]
                resource_version = obj.metadata.resource_version

                try:
                    event_queue.put_nowait(obj)
                except asyncio.QueueFull:
                    print("[WATCH] queue full, dropping event")

        except asyncio.CancelledError:
            print(f"[WATCH] watcher for ns={namespace} cancelled")
            break

        except Exception as e:
            watch_errors.inc()
            watch_restarts.inc()
            print(f"[WATCH] error in ns={namespace}: {e}")

            # Exponentielles Backoff
            print(f"[WATCH] reconnecting in {backoff}s...")
            try:
                await asyncio.wait_for(asyncio.sleep(backoff), timeout=backoff)
            except asyncio.CancelledError:
                break

            backoff = min(backoff * 2, 30)

    print(f"[WATCH] watcher for ns={namespace} stopped")


# ============================================================
# HAUPTSCHLEIFE
# ============================================================

async def watch_events_loop():
    print("[WATCH] watch_events_loop starting...")
    init_k8s()
    namespaces = get_namespaces()

    worker_task = asyncio.create_task(db_worker())
    watcher_tasks = [
        asyncio.create_task(watch_namespace(ns))
        for ns in namespaces
    ]

    try:
        await asyncio.gather(worker_task, *watcher_tasks)
    except asyncio.CancelledError:
        print("[WATCH] watch_events_loop cancelled")
    finally:
        print("[WATCH] watch_events_loop exiting")
