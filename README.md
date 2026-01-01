# Kubernetes Event listener

## from scratch
- uv sync
- uv pip compile pyproject.toml -o requirements.txt
- uv pip install -r requirements.txt
- uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload

## run commands
```bash
kubectl apply -f kubectl/rbac-events.yaml

curl -fsSL https://raw.githubusercontent.com/metalbear-co/mirrord/main/scripts/install.sh | bash

POD=$(kubectl get pod -n kubeevent -l app=kubeevent -o jsonpath='{.items[0].metadata.name}')
mirrord exec -t pod/$POD -n kubeevent  -- uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

## get events
```bash
kubectl run test1 -n demo --image=busybox -- echo hi
kubectl delete pod test1 -n demo

kubectl run crashme -n demo --image=busybox -- sh -c "exit 1"
kubectl delete pod crashme -n demo

kubectl create deployment demoapp -n demo --image=nginx
kubectl scale deployment demoapp -n demo --replicas=2
kubectl scale deployment demoapp -n demo --replicas=0
kubectl delete deployment demoapp -n demo

```