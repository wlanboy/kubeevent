# Kubernetes Event listener

## run commands
```bash
kubectl apply -f kubectl/rbac-events.yaml

mirrord exec -t pod/demo-app-85fdbd69d7-9nfqm -n demo  -- uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload

uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload
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