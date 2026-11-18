# kubeevent-chart

Helm-Chart zum Deployment von kubeevent in einem Kubernetes-Cluster. Das Chart erzeugt Deployment, Service und ein PVC für die SQLite-Datenbank, richtet über cert-manager ein TLS-Zertifikat ein und macht den Service via Istio Gateway/VirtualService nach außen erreichbar. Zusätzlich legt es ServiceAccount und RBAC-Rollen an, damit kubeevent Events aus den konfigurierten Namespaces lesen darf, sowie eine ConfigMap mit den Environment-Variablen der Anwendung. Alle Werte werden zentral über `values.yaml` gesteuert.

## Chart.yaml
Chart-Metadaten (Name `kubeevent`, Typ `application`, Version). Beschreibt das Chart als "Kube Event Listener deployment with Istio Gateway and cert-manager".

## values.yaml
Zentrale Konfigurationsdatei des Charts. Steuert u. a. Image/Tag, Replica-Anzahl, Service (Name/Port), Persistenz der Datenbank (`persistence`), Ressourcen (`resources`), Shutdown-Zeiten (`shutdown`), Probes (`probes`), Security-Context (`podSecurityContext`, `securityContext`), Istio (Hosts, Gateway-Selector, TLS), cert-manager-Issuer, ServiceAccount, RBAC (`rbac.create`) die zu überwachenden Namespaces (`watchNamespaces`) und die Einstellungen der App (`config`: Retention, Metrik-Aufräumen, Queue, Batches, Watch-Timeout, Log-Level). `istio.hosts` gilt für Gateway, VirtualService und Zertifikat.

## templates/deployment.yaml
Deployment der kubeevent-Anwendung. Startet den Container als UID 1000 mit read-only Root-Dateisystem. Das PVC hängt unter `/app/data`, `/tmp` ist ein `emptyDir`. Die Environment-Variablen kommen per `envFrom` aus der ConfigMap. Mit PVC nutzt das Deployment `strategy: Recreate`, damit nie zwei Pods dieselbe SQLite-Datei öffnen. Mehr als eine Replica auf einem ReadWriteOnce-PVC lehnt das Template ab.

Startup- und Liveness-Probe prüfen `/healthz`, die Readiness-Probe `/readyz`. Beim Beenden wartet ein `preStop`-Hook `shutdown.preStopSleepSeconds` lang, bis Service und Istio den Pod nicht mehr ansprechen. `terminationGracePeriodSeconds` ergibt sich aus `preStopSleepSeconds + appShutdownSeconds + 5`.

## templates/service.yaml
ClusterIP-Service, der den kubeevent-Pod unter dem konfigurierten Port erreichbar macht und als Ziel für VirtualService/Gateway dient.

## templates/pvc.yaml
PersistentVolumeClaim für die SQLite-Datenbank unter `persistence.mountPath`, abschaltbar per `persistence.enabled` (dann `emptyDir`, Daten gehen beim Neustart verloren). Durch `helm.sh/resource-policy: keep` bleibt das PVC bei `helm uninstall` erhalten.

## templates/configmap-env.yaml
ConfigMap mit `DB_PATH` (aus `persistence.mountPath`), `WATCH_NAMESPACES` (aus `watchNamespaces`) und den Werten aus `config`. Eine Änderung startet den Pod über die Checksum-Annotation neu.

## templates/_helpers.tpl
Standard-Labels `app.kubernetes.io/*` für alle Ressourcen. Deployment und Service selektieren weiter über `app`, weil sich der Selector eines bestehenden Deployments nicht ändern lässt.

## templates/serviceaccount.yaml
Optional erzeugter ServiceAccount (per `serviceAccount.create`), unter dem der kubeevent-Pod läuft und der für die RBAC-Bindings verwendet wird.

## templates/rbac.yaml
Erzeugt pro Eintrag in `watchNamespaces` eine Role und ein RoleBinding `<release>-event-reader`, die dem ServiceAccount Lesezugriff (`get`, `list`, `watch`) auf Events in diesem Namespace geben. Abschaltbar per `rbac.create`, unabhängig von `serviceAccount.create`.

## templates/certificate.yaml
cert-manager-`Certificate` für `istio.hosts`, nur wenn `istio.tls.enabled` und `certManager.enabled` gesetzt sind. Das Secret landet im Namespace des Ingress-Gateways (`istio.gatewayNamespace`).

## templates/gateway.yaml
Istio-`Gateway` (`networking.istio.io/v1`) für die Pods aus `istio.gatewaySelector`. HTTP auf Port 80 immer, HTTPS auf Port 443 mit `istio.tls.enabled`.

## templates/virtualservice.yaml
Istio-`VirtualService` (`networking.istio.io/v1`), der Traffic für `istio.hosts` vom Gateway und aus dem Mesh auf den Service leitet. Sichtbar im eigenen Namespace und in `istio.gatewayNamespace`.

## Helm install
Installation, Upgrade und Deinstallation des Charts:

```bash
helm install kubeevent . -n kubeevent --create-namespace
```

```bash
kubectl get secret kubeevent-tls -n istio-ingress
kubectl get gateway,virtualservice -n kubeevent
```

```bash
helm upgrade kubeevent . -n kubeevent 
```

```bash
helm uninstall kubeevent -n kubeevent
```
