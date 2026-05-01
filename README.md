# 이민수의 졸업작품입니다.

K8s 기반의 트래픽 관리 시스템입니다.


# 파일 구조 계획
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
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/app/deployment.yaml
kubectl apply -f k8s/app/service.yaml
```
### 이후에 계속 추가 예정
