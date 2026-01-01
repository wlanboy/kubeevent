import os
import asyncio
import time
from datetime import datetime
from kubernetes import client, config, watch
from sqlmodel import Session, select
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

    if existing:
        existing.last_timestamp = to_dt(ev.last_timestamp) or existing.last_timestamp
        existing.count = ev.count or existing.count
    else:
        obj = K8sEvent(
            uid=uid,
            name=ev.metadata.name,
            namespace=ev.metadata.namespace,
            reason=ev.reason,
            type=ev.type,
            message=ev.message,
            involved_kind=getattr(ev.involved_object, "kind", None),
            involved_name=getattr(ev.involved_object, "name", None),
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
    """Async Wrapper für einen Namespace."""
    global stop_watcher

    loop = asyncio.get_running_loop()
    w = watch.Watch()
    v1 = client.CoreV1Api()

    while not stop_watcher:
        try:
            # Stream im Threadpool ausführen
            async for event in loop.run_in_executor(
                None,
                lambda: w.stream(
                    v1.list_namespaced_event,
                    namespace=namespace,
                    timeout_seconds=5
                )
            ):
                if stop_watcher:
                    break

                handle_event(event)

        except Exception as e:
            print("WATCH ERROR:", e)
            await asyncio.sleep(1)

        finally:
            w.stop()


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
