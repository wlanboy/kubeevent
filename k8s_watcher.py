import os
import asyncio
import time
from typing import List
from kubernetes import client, config, watch
from sqlmodel import Session
from sqlalchemy.dialects.sqlite import insert

from db import engine
from models import K8sEvent
from metrics import (
    events_total, events_by_type, events_by_namespace, 
    events_by_namespace_type, watch_errors, watch_restarts, 
    events_by_involved, events_by_pod, events_by_deployment
)

stop_watcher = False
event_queue = asyncio.Queue()

def get_namespaces() -> List[str]:
    raw = os.getenv("POD_NAMESPACE", "demo")
    return [ns.strip() for ns in raw.split(",")]

def init_k8s():
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()

def process_metrics(ev):
    """Aktualisiert alle Metriken exakt nach deiner metrics.py Definition."""
    namespace = ev.metadata.namespace or "default"
    event_type = ev.type or "Unknown"
    kind = getattr(ev.involved_object, "kind", "Unknown")
    involved_name = getattr(ev.involved_object, "name", "Unknown")
    reason = ev.reason or "Unknown"
    # 'reporting_component' ist das Feld für 'component' in K8s Events
    component = getattr(ev, "reporting_component", "Unknown") or "Unknown"

    # 1. Einfache Counter
    events_total.inc()
    events_by_type.labels(type=event_type).inc()
    events_by_namespace.labels(namespace=namespace).inc()
    events_by_namespace_type.labels(namespace=namespace, type=event_type).inc()

    # 2. Involved Object Counter (Alle 6 Labels müssen hier rein!)
    events_by_involved.labels(
        namespace=namespace,
        type=event_type,
        kind=kind,
        involved_name=involved_name,
        reason=reason,
        component=component
    ).inc()

    # 3. Spezifische Counter für Pods
    if kind == "Pod":
        events_by_pod.labels(
            namespace=namespace,
            pod=involved_name,
            type=event_type
        ).inc()

    # 4. Spezifische Counter für Deployments (Achtung: involved_name ist hier der Name)
    if kind == "Deployment":
        events_by_deployment.labels(
            namespace=namespace,
            deployment=involved_name,
            type=event_type
        ).inc()

def sync_db_save(events: List[any]):
    with Session(engine) as session:
        for ev in events:
            process_metrics(ev)
            
            # Wir erstellen IMMER ein neues Objekt
            obj = K8sEvent(
                uid=ev.metadata.uid,
                name=ev.metadata.name,
                namespace=ev.metadata.namespace or "default",
                reason=ev.reason,
                type=ev.type,
                message=ev.message,
                involved_kind=getattr(ev.involved_object, "kind", None),
                involved_name=getattr(ev.involved_object, "name", None),
                first_timestamp=ev.first_timestamp,
                last_timestamp=ev.last_timestamp,
                count=ev.count or 1
            )
            session.add(obj)
        session.commit()

async def db_worker():
    while not stop_watcher:
        try:
            ev = await event_queue.get()
            batch = [ev]
            # Kurzes Window zum Sammeln
            await asyncio.sleep(0.1) 
            while not event_queue.empty() and len(batch) < 100:
                batch.append(event_queue.get_nowait())
            
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, sync_db_save, batch)
            
            for _ in range(len(batch)):
                event_queue.task_done()
        except Exception as e:
            print(f"Worker Error: {e}")
            await asyncio.sleep(1)

def sync_watch_namespace(namespace: str, loop: asyncio.AbstractEventLoop):
    v1 = client.CoreV1Api()
    w = watch.Watch()
    resource_version = None
    while not stop_watcher:
        try:
            stream = w.stream(v1.list_namespaced_event, namespace=namespace, 
                              resource_version=resource_version, timeout_seconds=300)
            for event in stream:
                if stop_watcher: break
                obj = event["object"]
                resource_version = obj.metadata.resource_version
                loop.call_soon_threadsafe(event_queue.put_nowait, obj)
        except Exception:
            watch_errors.inc()
            time.sleep(5)
            watch_restarts.inc()

async def watch_events_loop():
    init_k8s()
    namespaces = get_namespaces()
    loop = asyncio.get_running_loop()
    
    # DB Worker starten
    worker_task = asyncio.create_task(db_worker())
    
    # Watcher starten
    watcher_tasks = []
    for ns in namespaces:
        t = loop.run_in_executor(None, sync_watch_namespace, ns, loop)
        watcher_tasks.append(t)
    
    await asyncio.gather(*watcher_tasks, worker_task)