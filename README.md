# K8s기반 스마트 트래픽 시스템

K8s 기반의 트래픽 관리 시스템입니다.


## 파일 구조 계획
```bash
smart-traffic-system/
│
├── k8s/                      # Kubernetes 설정 파일 모음
│   ├── namespace.yaml
│   │
│   ├── ingress/
│   │   └── ingress.yaml
│   │
│   ├── app/                  # 테스트용 서비스 (트래픽 발생용)
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   │
│   ├── analyzer/             # 트래픽 분석 서버 (FastAPI)
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   │
│   ├── monitoring/           # 모니터링 스택
│   │   ├── prometheus.yaml
│   │   └── grafana.yaml
│   │
│   ├── security/             # 차단 정책
│   │   └── network-policy.yaml
│   │
│   └── configmap/            # 설정값
│       └── app-config.yaml
│
├── analyzer/                 # Python 분석 서버 코드
│   ├── main.py
│   ├── detector.py           # 이상 탐지 로직
│   ├── blocker.py            # k8s 차단 API 호출
│   ├── requirements.txt
│   └── Dockerfile
│
├── app/                      # 테스트용 웹 서버
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── scripts/                  # 테스트 및 자동화
│   ├── load_test.js          # k6 스크립트
│   └── deploy.sh
│
├── docs/                     # 발표용 자료
│   ├── architecture.png
│   └── flowchart.md
│
└── README.md
```

## app-testing의 docker image 만들기 
```bash
docker build -t test-web-app:dev ./app-testing
```

테스트 웹앱은 모든 요청의 시각, 클라이언트 IP, HTTP 메서드, 경로, 응답 코드,
처리 시간, User-Agent를 PostgreSQL의 `request_logs` 테이블에 저장합니다.
DB 데이터는 `traffic-db-data` PVC에 보관되어 DB Pod가 재시작되어도 유지됩니다.
현재 개발용 DB 비밀번호는 Kubernetes 매니페스트에 들어 있으므로 실제 서비스에는 사용하지 마세요.

## k8s에 배포하기
### 배포전 도커허브 로그인
```bash
# 도커허브 로그인 (이미 로그인 되어 있으면 패스)
docker login
```
dockerhub에 로그인이 되어있지 않으면 배포시 이미지 풀링이 안되서 배포가 실패할 수 있습니다. 로그인 후 다시 배포해보세요.

### 배포전 nginx ingress controller 설치
```bash
# 이거는 사실 올려져 있는걸 그대로 다운로드 해서 파일을 만들어둔거라 그냥 배포하기만 하면 됩니다.
kubectl apply -f k8s/ingress-controller/nginx-ingress-controller.yaml

# nginx ingress controller 설치 (공식 매니페스트)(요거랑 위에거 둘중 하나만 하면 됩니다.)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml
```
nginx ingress controller 설치 되어야 ingress가 제대로 동작합니다.
---

### 본격적으로 차례로 배포하기
```bash
# 위에서 부터 차례로 명령어 치면 됩니다.
kubectl apply -f k8s/namespace.yaml
# 트래픽 기록 저장용 PostgreSQL과 영구 볼륨
kubectl apply -f k8s/app/database.yaml
# DB가 준비될 때까지 확인
kubectl rollout status deployment/traffic-db -n smart-traffic
# service 배포
kubectl apply -f k8s/app/service.yaml
# deployment 배포 (배포시 이미지에 문제 생기면 도커허브 로그인 후 다시 배포)
kubectl apply -f k8s/app/deployment.yaml
kubectl rollout status deployment/test-web-app -n smart-traffic

# ingress 배포
kubectl apply -f k8s/ingress/ingress.yaml

# security 배포
kubectl apply -f k8s/security/network-policy.yaml

# analyzer 서비스 배포
kubectl apply -f k8s/analyzer/rbac.yaml
kubectl apply -f k8s/analyzer/deployment.yaml
kubectl apply -f k8s/analyzer/service.yaml
```

### 트래픽 로그 확인
```bash
# 앱 통계 API: IP별로 DB에 저장된 요청 수
curl http://test.local/stats

# 개별 트래픽 로그와 DB 연결 오류 로그
kubectl logs -n smart-traffic -l app=test-web-app --prefix=true
```

### k6 부하 테스트
Kubernetes 안에서 5명의 가상 사용자가 30초 동안 Ingress를 거쳐 요청합니다.
`/api`, `/slow`, `/burst`, `/error` 경로를 섞어서 호출하며 결과는 PostgreSQL에 저장됩니다.
테스트 Job은 완료 1시간 후 자동으로 정리됩니다.
```bash
kubectl apply -f k8s/k6/k6.yaml
kubectl wait --for=condition=complete job/k6-test -n smart-traffic --timeout=120s
kubectl logs -n smart-traffic job/k6-test
```

완료되기 전에 다시 실행하려면 이전 Job을 지운 뒤 다시 적용합니다.
```bash
kubectl delete job k6-test -n smart-traffic
kubectl apply -f k8s/k6/k6.yaml
```

### deployment 재배포 
```bash
kubectl rollout restart deployment <deployment-name> -n <namespace>
```

---

### 테스팅용 포트포워딩
```bash
# app 서비스 포트포워딩
kubectl port-forward svc/app-service 8080:80 -n <namespace>

# analyzer 서비스 포트포워딩
kubectl port-forward -n smart-traffic svc/traffic-analyzer-service 9000:9000
```

## API 명세서
### App
/api 기본 JSON 요청
```bash
curl http://test.local/api
```
/slow 지연 응답
```bash
curl http://test.local/slow
```
/error 에러 응답
```bash
curl http://test.local/error
```
/burst 부하 테스트용 응답
```bash
curl http://test.local/burst
```
/stats 통계 정보
```bash
curl http://test.local/stats
```

### analyzer
요청 카운트 세는거
```bash
curl http://localhost:9000/analyze
```

---

## 기타 
탐지 결과 확인용 로그 보기
```bash
kubectl logs -n smart-traffic -l app=traffic-analyzer -f
```

### 새로 개조해서 Docker 이미지 만들기

```bash
cd analyzer
# Docker 이미지 빌드
docker build -t traffic-analyzer:latest .
# Docker Hub에 태그 달기
docker tag traffic-analyzer:latest <dockerhub-username>/traffic-analyzer:latest
# Docker Hub에 푸시
docker push <dockerhub-username>/traffic-analyzer:latest
```
```bash
cd app
docker build -t test-web-app:latest .

docker tag test-web-app:latest <dockerhub-username>/test-web-app:latest

docker push <dockerhub-username>/test-web-app:latest
```

### 이후에 계속 추가 예정
