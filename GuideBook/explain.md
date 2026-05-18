# analyzer

### 권한 확인
```bash
kubectl auth can-i create networkpolicies \
  --as=system:serviceaccount:smart-traffic:traffic-analyzer-sa \
  -n smart-traffic
```
yes가 나오면 권한이 잘 설정된 것이다. 만약 no가 나온다면 RBAC 설정을 다시 확인해야 한다.
---

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
```bash
kubectl describe networkpolicy allow-only-from-nginx-ingress -n smart-traffic
```
(추가확인작업) NetworkPolicy의 상세 정보를 보여준다. 여기서 ingress 규칙이 nginx-ingress-controller의 IP에서 오는 트래픽만 허용하도록 설정되어 있는지 확인할 수 있다.
---

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

## 기능 테스트
```bash
curl http://localhost:9000/apply-policy
```

### 임의로 트래픽을 감지하는 app에 api여러번 요청
```bash
for i in {1..30}; do curl http://test.local/api; done
```
이후 결과 확인
```bash
kubectl logs -n smart-traffic -l app=traffic-analyzer
```
또는 9000포트로 포트포워딩해서 웹 UI로도 확인 가능
```bash
kubectl port-forward -n smart-traffic svc/traffic-analyzer-service 9000:9000
```

```bash
curl http://localhost:9000/analyze
```
결과 예시
```json
{
  "stats": {
    "total_clients": 1,
    "requests": {
      "10.1.0.136": 126
    }
  },
  "abnormal_traffic": [
    {
      "ip": "10.1.0.136",
      "count": 126,
      "status": "abnormal"
    }
  ],
  "block_result": {
    "status": "updated",
    "policy": "allow-only-from-nginx-ingress"
  }
}
```

---