"""Prometheus-Metriken für Kubernetes Events.

Labels wie Pod- oder Objektnamen erzeugen mit der Zeit viele Zeitreihen. Jede Zeitreihe merkt sich deshalb,
wann sie zuletzt erhöht wurde, und `prune_stale_series` entfernt die, die länger nicht mehr vorkamen.
"""

import time
from contextlib import suppress

from prometheus_client import Counter

from kubeevents.models import K8sEvent

UNKNOWN = "unknown"

events_total = Counter("kubeevents_total", "Total number of Kubernetes events received")

events_by_type = Counter("kubeevents_type_total", "Events by type", ["type"])

events_by_namespace = Counter("kubeevents_namespace_total", "Events by namespace", ["namespace"])

events_by_namespace_type = Counter(
    "kubeevents_namespace_type_total", "Events by namespace and type", ["namespace", "type"]
)

# Die Grafana-Dashboards filtern auf kind und involved_name und zeigen component in der Legende
events_by_involved = Counter(
    "kubeevents_involved_total",
    "Events by involved object",
    ["namespace", "type", "kind", "involved_name", "reason", "component", "host"],
)

events_by_component = Counter("kubeevents_component_total", "Events by reporting component", ["component"])

events_by_node = Counter("kubeevents_node_total", "Events by node/host", ["host"])

events_by_deployment = Counter(
    "kubeevents_deployment_total", "Events by deployment", ["namespace", "deployment", "type"]
)

events_by_pod = Counter("kubeevents_pod_total", "Events by pod", ["namespace", "pod", "type"])

events_by_reason = Counter("kubeevents_reason_total", "Events by reason", ["namespace", "reason", "type"])

events_by_replicaset = Counter(
    "kubeevents_replicaset_total", "Events by replicaset", ["namespace", "replicaset", "type"]
)

events_by_statefulset = Counter(
    "kubeevents_statefulset_total", "Events by statefulset", ["namespace", "statefulset", "type"]
)

events_by_daemonset = Counter("kubeevents_daemonset_total", "Events by daemonset", ["namespace", "daemonset", "type"])

events_by_pvc = Counter("kubeevents_pvc_total", "Events by persistentvolumeclaim", ["namespace", "pvc", "type"])

events_by_node_events = Counter("kubeevents_node_events_total", "Events by node", ["node", "type", "reason"])

watch_errors = Counter("kubeevents_watch_errors_total", "Number of watch errors")

watch_restarts = Counter("kubeevents_watch_restarts_total", "Number of watcher restarts")

# Bei welcher Zeit (time.monotonic) welche Zeitreihe zuletzt erhöht wurde
_series_last_seen: dict[tuple[Counter, tuple[str, ...]], float] = {}

# Wird ein Kind hier nicht gefunden, bekommt es nur die allgemeinen Metriken
_KIND_COUNTERS = {
    "ReplicaSet": events_by_replicaset,
    "StatefulSet": events_by_statefulset,
    "DaemonSet": events_by_daemonset,
    "PersistentVolumeClaim": events_by_pvc,
}


def _inc(counter: Counter, *label_values: str) -> None:
    """Erhöht eine Zeitreihe. Die Werte stehen in der Reihenfolge, in der der Counter seine Labels deklariert."""
    counter.labels(*label_values).inc()
    _series_last_seen[(counter, label_values)] = time.monotonic()


def extract_deployment(kind: str, name: str) -> str | None:
    """Leitet den Deployment-Namen aus dem Namen eines ReplicaSets ab (<deployment>-<hash>)."""
    if kind == "ReplicaSet" and "-" in name:
        return name.rsplit("-", 1)[0]
    return None


def record_event(ev: K8sEvent) -> None:
    """Zählt ein neu gespeichertes Event in allen Metriken."""
    namespace = ev.namespace
    event_type = ev.type or UNKNOWN
    kind = ev.involved_kind or UNKNOWN
    involved_name = ev.involved_name or UNKNOWN
    reason = ev.reason or UNKNOWN
    component = ev.component or UNKNOWN
    host = ev.host or UNKNOWN

    events_total.inc()
    _inc(events_by_type, event_type)
    _inc(events_by_namespace, namespace)
    _inc(events_by_namespace_type, namespace, event_type)
    _inc(events_by_involved, namespace, event_type, kind, involved_name, reason, component, host)
    _inc(events_by_reason, namespace, reason, event_type)

    if component != UNKNOWN:
        _inc(events_by_component, component)
    if host != UNKNOWN:
        _inc(events_by_node, host)

    if kind == "Pod":
        _inc(events_by_pod, namespace, involved_name, event_type)
    elif kind == "Node":
        _inc(events_by_node_events, involved_name, event_type, reason)
    elif counter := _KIND_COUNTERS.get(kind):
        _inc(counter, namespace, involved_name, event_type)

    if deployment := extract_deployment(kind, involved_name):
        _inc(events_by_deployment, namespace, deployment, event_type)


def prune_stale_series(max_age_seconds: float) -> int:
    """Entfernt Zeitreihen, die länger als max_age_seconds nicht erhöht wurden. Gibt deren Anzahl zurück."""
    cutoff = time.monotonic() - max_age_seconds
    stale = [key for key, last_seen in _series_last_seen.items() if last_seen < cutoff]
    for counter, label_values in stale:
        with suppress(KeyError):
            counter.remove(*label_values)
        del _series_last_seen[(counter, label_values)]
    return len(stale)
