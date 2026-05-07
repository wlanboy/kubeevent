"""Prometheus-Metriken für Kubernetes Events."""

from prometheus_client import Counter

# Gesamt-Counter
events_total = Counter(
    "kubeevents_total",
    "Total number of Kubernetes events received"
)

# Events nach Typ (Normal/Warning)
events_by_type = Counter(
    "kubeevents_type_total",
    "Events by type",
    ["type"]
)

# Events nach Namespace
events_by_namespace = Counter(
    "kubeevents_namespace_total",
    "Events by namespace",
    ["namespace"]
)

# Events nach Namespace und Typ
events_by_namespace_type = Counter(
    "kubeevents_namespace_type_total",
    "Events by namespace and type",
    ["namespace", "type"]
)

# Events nach betroffenem Objekt (detailliert)
events_by_involved = Counter(
    "kubeevents_involved_total",
    "Events by involved object",
    ["namespace", "type", "kind", "involved_name", "reason", "component", "host"]
)

# Events nach Komponente (kubelet, scheduler, etc.)
events_by_component = Counter(
    "kubeevents_component_total",
    "Events by reporting component",
    ["component"]
)

# Events nach Node/Host
events_by_node = Counter(
    "kubeevents_node_total",
    "Events by node/host",
    ["host"]
)

# Events nach Deployment
events_by_deployment = Counter(
    "kubeevents_deployment_total",
    "Events by deployment",
    ["namespace", "deployment", "type"]
)

# Events nach Pod
events_by_pod = Counter(
    "kubeevents_pod_total",
    "Events by pod",
    ["namespace", "pod", "type"]
)

# Events nach Reason
events_by_reason = Counter(
    "kubeevents_reason_total",
    "Events by reason",
    ["namespace", "reason", "type"]
)

# Events nach ReplicaSet
events_by_replicaset = Counter(
    "kubeevents_replicaset_total",
    "Events by replicaset",
    ["namespace", "replicaset", "type"]
)

# Events nach StatefulSet
events_by_statefulset = Counter(
    "kubeevents_statefulset_total",
    "Events by statefulset",
    ["namespace", "statefulset", "type"]
)

# Events nach DaemonSet
events_by_daemonset = Counter(
    "kubeevents_daemonset_total",
    "Events by daemonset",
    ["namespace", "daemonset", "type"]
)

# Events nach PersistentVolumeClaim
events_by_pvc = Counter(
    "kubeevents_pvc_total",
    "Events by persistentvolumeclaim",
    ["namespace", "pvc", "type"]
)

# Events nach Node (kind=Node)
events_by_node_events = Counter(
    "kubeevents_node_events_total",
    "Events by node",
    ["node", "type", "reason"]
)

# Watch-Fehler
watch_errors = Counter(
    "kubeevents_watch_errors_total",
    "Number of watch errors"
)

# Watch-Neustarts
watch_restarts = Counter(
    "kubeevents_watch_restarts_total",
    "Number of watcher restarts"
)
