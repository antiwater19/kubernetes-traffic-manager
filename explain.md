# analyzer

### 권한 확인
```bash
kubectl auth can-i create networkpolicies \
  --as=system:serviceaccount:smart-traffic:traffic-analyzer-sa \
  -n smart-traffic
```

테스트
```bash
kubectl port-forward -n smart-traffic svc/traffic-analyzer-service 9000:9000
```
다른 터미널에서:
```bash
curl http://localhost:9000/apply-policy
```

확인 방법
```bash
kubectl get networkpolicy -n smart-traffic
```
