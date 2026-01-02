import os
import asyncio
import time
from datetime import datetime
from kubernetes import client, config, watch
from sqlmodel import Session, select
from metrics import events_total, events_by_type, events_by_namespace, events_by_namespace_type, watch_errors, events_by_involved, events_by_pod, events_by_deployment
from db import engine
from models import K8sEvent

stop_watcher = False


def get_namespaces() -> list[str]:
    """Mehrere Namespaces, kommasepariert: POD_NAMESPACE=demo,prod"""
    raw = os.getenv("POD_NAMESPACE", "demo")
    return [ns.strip() for ns in raw.split(",")]


def init_k8s():
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()


def upsert_event(session: Session, ev):
    uid = ev.metadata.uid
    stmt = select(K8sEvent).where(K8sEvent.uid == uid)
    existing = session.exec(stmt).first()

    def to_dt(ts):
        return ts if isinstance(ts, datetime) else None

    # Extract labels from Kubernetes event object
    namespace = ev.metadata.namespace or "default"
    event_type = ev.type or "Unknown"
    kind = getattr(ev.involved_object, "kind", "Unknown")
    involved_name = getattr(ev.involved_object, "name", "Unknown")
    reason = ev.reason or "Unknown"
    component = getattr(ev, "reporting_component", "Unknown")

    # Increment metrics ALWAYS (new + updated events)
    events_total.inc()
    events_by_type.labels(event_type).inc()
    events_by_namespace.labels(namespace).inc()
    events_by_namespace_type.labels(namespace, event_type).inc()

    events_by_involved.labels(
        namespace=namespace,
        type=event_type,
        kind=kind,
        involved_name=involved_name,
        reason=reason,
        component=component
    ).inc()

    if kind == "Pod":
        events_by_pod.labels(
            namespace=namespace,
            pod=involved_name,
            type=event_type
        ).inc()

    if kind == "Deployment":
        events_by_deployment.labels(
            namespace=namespace,
            deployment=involved_name,
            type=event_type
        ).inc()

    if existing:
        existing.last_timestamp = to_dt(ev.last_timestamp) or existing.last_timestamp
        existing.count = ev.count or existing.count
    else:
        obj = K8sEvent(
            uid=uid,
            name=ev.metadata.name,
            namespace=namespace,
            reason=reason,
            type=event_type,
            message=ev.message,
            involved_kind=kind,
            involved_name=involved_name,
            first_timestamp=to_dt(ev.first_timestamp),
            last_timestamp=to_dt(ev.last_timestamp),
        )
        session.add(obj)

    session.commit()

def handle_event(event):
    ev = event["object"]
    with Session(engine) as session:
        upsert_event(session, ev)

async def watch_namespace(namespace: str):
    global stop_watcher

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    def sync_watch():
        w = watch.Watch()
        v1 = client.CoreV1Api()

        while not stop_watcher:
            try:
                for event in w.stream(
                    v1.list_namespaced_event,
                    namespace=namespace,
                    timeout_seconds=5
                ):
                    if stop_watcher:
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as e:
                print("WATCH ERROR:", e)
                watch_errors.inc()
                time.sleep(1)
            finally:
                w.stop()

    thread = loop.run_in_executor(None, sync_watch)

    while not stop_watcher:
        event = await queue.get()
        handle_event(event)

async def watch_events_loop():
    """Startet mehrere Namespace‑Watcher parallel."""
    init_k8s()

    namespaces = get_namespaces()
    print(f"Watching namespaces: {namespaces}")

    tasks = [
        asyncio.create_task(watch_namespace(ns))
        for ns in namespaces
    ]

    # Warten bis Stop-Signal kommt
    await asyncio.gather(*tasks)
