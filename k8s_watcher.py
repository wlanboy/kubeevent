# k8s_watcher.py
import os
from datetime import datetime
from kubernetes import client, config, watch
from sqlmodel import Session, select
from db import engine
from models import K8sEvent

def get_namespace() -> str:
    return os.getenv("POD_NAMESPACE", "demo")

def init_k8s():
    # im Cluster:
    try:
        config.load_incluster_config()
    except Exception:
        # lokal zum Testen:
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

def watch_events_loop():
    init_k8s()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    ns = get_namespace()

    with Session(engine) as session:
        for event in w.stream(v1.list_namespaced_event, namespace=ns, timeout_seconds=0):
            obj: client.V1Event = event["object"]
            upsert_event(session, obj)
