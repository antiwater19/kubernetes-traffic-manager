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
cd app
docker build -t test-web-app:latest .
```

## k8s에 배포하기

### 차례로 배포하기
```bash
# 위에서 부터 차례로 명령어 치면 됩니다.
kubectl apply -f k8s/namespace.yaml
# service 배포
kubectl apply -f k8s/app/service.yaml
# deployment 배포 (배포시 이미지에 문제 생기면 도커허브 로그인 후 다시 배포)
kubectl apply -f k8s/app/deployment.yaml
# ingress 배포
kubectl apply -f k8s/ingress/ingress.yaml
```

### deployment 재배포 
```bash
kubectl rollout restart deployment <deployment-name> -n <namespace>
```

### nginx ingress controller 설치
```bash
# 이거는 사실 올려져 있는걸 그대로 다운로드 해서 파일을 만들어둔거라 그냥 배포하기만 하면 됩니다.
kubectl apply -f k8s/ingress-controller/nginx-ingress-controller.yaml

# nginx ingress controller 설치 (공식 매니페스트)(요거랑 위에거 둘중 하나만 하면 됩니다.)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml
```
nginx ingress controller 설치 되어야 ingress가 제대로 동작합니다.

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
### 이후에 계속 추가 예정
