# Grafana Dashboards

Dieser Ordner enthält vorgefertigte Grafana-Dashboards (als JSON-Export) zur Überwachung von Kubernetes-Events, die von kubeevent eingesammelt werden. Die Dashboards reichen von einer globalen Übersicht über alle Events bis zu Detailansichten für einzelne Ressourcentypen (Pod, Deployment, StatefulSet, DaemonSet, PVC, Node) sowie einer verdichteten Workload-Analyse über mehrere Objekttypen hinweg. Alle Dashboards nutzen Template-Variablen (u. a. `datasource`, `namespace`) zur Filterung und sind so aufgebaut, dass sie sich per Import direkt in Grafana nutzen lassen.

## Kubernetes_Event_Monitoring.json
Zentrales Übersichts-Dashboard "Kubernetes Event Monitoring" über alle Events hinweg. Zeigt Gesamt-Events, Event-Rate mit Spike-Detection, Events nach Typ, eine Namespace×Typ-Matrix als Zeitreihe sowie die Warning-Rate pro Namespace. Enthält zusätzlich Panels zu Watcher-Fehlern und Watcher-Neustarts, um den Zustand des kubeevent-Watchers selbst zu überwachen. Variablen: `datasource`, `namespace`, `type`.

## Namespace Detail.json
Detailansicht "Namespace Detail" für einen einzelnen Namespace. Zeigt Gesamt-Events im Namespace, Events pro Sekunde, Aufschlüsselung nach Event-Typ sowie Spike-Detection. Variablen: `datasource`, `namespace`.

## Workload_Analysis.json
Übergreifende Analyse "Kubernetes Workload Analysis" über Pods, Deployments, StatefulSets und DaemonSets hinweg. Vergleicht jeweils Events und Warnings pro Workload-Typ (5-Minuten-Zuwachs) und stellt Normal- vs. Warning-Events gegenüber. Variablen: `datasource`, `namespace`, `type`.

## Pod_Detail.json
Detailansicht "Pod Detail" für einen einzelnen Pod. Zeigt Gesamt-Events, Events pro Sekunde sowie Aufschlüsselung nach Reason und Component für den gewählten Pod. Variablen: `datasource`, `namespace`, `pod`.

## Deployment_Detail.json
Detailansicht "Deployment Detail" für ein einzelnes Deployment. Zeigt Gesamt-Events, Events pro Sekunde sowie ReplicaSet- und Scaling-Events. Variablen: `datasource`, `namespace`, `deployment`.

## StatefulSet_Detail.json
Detailansicht "StatefulSet Detail" für ein einzelnes StatefulSet. Zeigt Gesamt-Events, Warning-Events, Events pro Sekunde sowie Aufschlüsselung nach Reason und Component. Variablen: `datasource`, `namespace`, `statefulset`.

## DaemonSet_Detail.json
Detailansicht "DaemonSet Detail" für ein einzelnes DaemonSet. Zeigt Gesamt-Events, Warning-Events, Events pro Sekunde sowie Aufschlüsselung nach Reason und Component. Variablen: `datasource`, `namespace`, `daemonset`.

## PVC_Events.json
Detailansicht "PVC Events" für einzelne PersistentVolumeClaims. Zeigt Gesamt-Events, Warning-Events, Events pro Sekunde, Aufschlüsselung nach Reason und Component sowie eine Übersicht aller PVCs im Namespace (5-Minuten-Zuwachs). Variablen: `datasource`, `namespace`, `pvc`.

## Node_Events.json
Detailansicht "Node Events" für einzelne Nodes. Zeigt Gesamt- und Warning-Events, Events pro Sekunde pro Node, Aufschlüsselung nach Reason, Warning-Spike-Detection sowie die Top-Reasons im 5-Minuten-Zuwachs. Variablen: `datasource`, `node`.
