# analyzer

### 권한 확인
```bash
kubectl auth can-i create networkpolicies \
  --as=system:serviceaccount:smart-traffic:traffic-analyzer-sa \
  -n smart-traffic
```

### 테스트
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
allow-only-from-nginx-ingress가 나오면 성공이다.

### 간단한 pod 띄워서 확인해보기(Testing NetworkPolicy)
(이 pod는 터미널에서 나가게 되면 자동으로 삭제된다.)
```bash
kubectl run test-client -n smart-traffic --image=curlimages/curl -it --rm -- sh
```
그리고 이 pod에서 nginx-ingress-controller의 IP로 curl을 해보자.
```bash
curl http://test.local
```
응답이 없으면 NetworkPolicy가 잘 적용된 것이다. 이제 nginx-ingress-controller의 IP로 curl을 해보자.
```bash
curl http://<nginx-ingress-controller-ip>
```
