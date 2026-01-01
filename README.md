# Kubernetes Event listener

## run commands
```bash
kubectl apply -f kubectl/rbac-events.yaml

mirrord exec -t pod/demo-app-85fdbd69d7-9nfqm -n demo  -- uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload

uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```