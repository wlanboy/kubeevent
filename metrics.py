from prometheus_client import Counter

events_total = Counter("kubeevents_total", "Total number of Kubernetes events received")
events_by_type = Counter("kubeevents_type_total", "Events by type", ["type"])
events_by_namespace = Counter("kubeevents_namespace_total", "Events by namespace", ["namespace"])
events_by_namespace_type = Counter(
    "kubeevents_namespace_type_total",
    "Events by namespace and type",
    ["namespace", "type"]
)
watch_errors = Counter("kubeevents_watch_errors_total", "Number of watch errors")
watch_restarts = Counter("kubeevents_watch_restarts_total", "Number of watcher restarts")
