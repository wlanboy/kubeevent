# kubeevent-chart

Helm-Chart zum Deployment von kubeevent in einem Kubernetes-Cluster. Das Chart erzeugt Deployment, Service und ein PVC für die SQLite-Datenbank, richtet über cert-manager ein TLS-Zertifikat ein und macht den Service via Istio Gateway/VirtualService nach außen erreichbar. Zusätzlich legt es ServiceAccount und RBAC-Rollen an, damit kubeevent Events aus den konfigurierten Namespaces lesen darf, sowie eine ConfigMap mit den Environment-Variablen der Anwendung. Alle Werte werden zentral über `values.yaml` gesteuert.

## Chart.yaml
Chart-Metadaten (Name `kubeevent`, Typ `application`, Version). Beschreibt das Chart als "Kube Event Listener deployment with Istio Gateway and cert-manager".

## values.yaml
Zentrale Konfigurationsdatei des Charts. Steuert u. a. Image/Tag, Replica-Anzahl, Service (Name/Port), Persistenz der Datenbank (`persistence`), Security-Context (`podSecurityContext`, `securityContext`), Istio-Hosts und TLS-Secret, cert-manager-Issuer, ServiceAccount-Name und die zu überwachenden Namespaces (`watchNamespaces`).

## templates/deployment.yaml
Deployment der kubeevent-Anwendung. Startet den Container als UID 1000 mit read-only Root-Dateisystem. Das PVC hängt unter `/app/data`, `/tmp` ist ein `emptyDir`. Die Environment-Variablen kommen per `envFrom` aus der ConfigMap. Mit PVC nutzt das Deployment `strategy: Recreate`, damit nie zwei Pods dieselbe SQLite-Datei öffnen. Mehr als eine Replica auf einem ReadWriteOnce-PVC lehnt das Template ab.

## templates/service.yaml
ClusterIP-Service, der den kubeevent-Pod unter dem konfigurierten Port erreichbar macht und als Ziel für VirtualService/Gateway dient.

## templates/pvc.yaml
PersistentVolumeClaim für die SQLite-Datenbank unter `persistence.mountPath`, abschaltbar per `persistence.enabled` (dann `emptyDir`, Daten gehen beim Neustart verloren). Durch `helm.sh/resource-policy: keep` bleibt das PVC bei `helm uninstall` erhalten.

## templates/configmap-env.yaml
ConfigMap mit `DB_PATH` (aus `persistence.mountPath`) und `POD_NAMESPACE` (aus `watchNamespaces`). Eine Änderung startet den Pod über die Checksum-Annotation neu.

## templates/serviceaccount.yaml
Optional erzeugter ServiceAccount (per `serviceAccount.create`), unter dem der kubeevent-Pod läuft und der für die RBAC-Bindings verwendet wird.

## templates/rbac.yaml
Erzeugt pro Eintrag in `watchNamespaces` jeweils eine Role und RoleBinding, die dem ServiceAccount Lesezugriff (`get`, `list`, `watch`) auf Kubernetes-Events in diesem Namespace gewähren.

## templates/certificate.yaml
Optionales (per `certManager.enabled` steuerbares) cert-manager-`Certificate`-Objekt, das über den konfigurierten `ClusterIssuer` ein TLS-Zertifikat für die Istio-Hosts ausstellt und im TLS-Secret ablegt.

## templates/gateway.yaml
Istio-`Gateway`, das HTTPS (mit dem cert-manager-Secret) und HTTP für die konfigurierten Hosts terminiert und den Ingress-Einstiegspunkt definiert.

## templates/virtualservice.yaml
Istio-`VirtualService`, das eingehenden Traffic für die konfigurierten Hosts über das Gateway (und das Mesh) auf den kubeevent-Service routet.

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
