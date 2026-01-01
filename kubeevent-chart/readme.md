## Helm install
This helm script installs the WebShell within a kubernetes cluster.

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
