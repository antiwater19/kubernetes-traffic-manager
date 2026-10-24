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
│   │   └── values.yaml
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
docker build -t traffic-analyzer:dev ./analyzer
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
kubectl rollout status deployment/traffic-analyzer -n smart-traffic
```

### Prometheus와 Grafana 모니터링 설치

Prometheus/Grafana는 Helm `kube-prometheus-stack` 차트로 설치하고, 앱 메트릭 수집 대상은 `ServiceMonitor` 매니페스트로 관리합니다. 앱과 analyzer의 `/metrics` 경로는 Prometheus 메트릭 전용이며, test app은 이 경로의 스크레이프 요청을 트래픽 분석 DB에 기록하지 않습니다.

```powershell
# Helm 차트 저장소 (최초 1회)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update prometheus-community

# Prometheus, Grafana, Kubernetes 기본 모니터링 설치
helm upgrade --install traffic-monitoring prometheus-community/kube-prometheus-stack `
  --version 92.11.0 `
  --namespace monitoring --create-namespace `
  --values k8s/monitoring/values.yaml

# 앱/analyzer 스크레이프 대상과 NetworkPolicy 적용
kubectl apply -f k8s/monitoring/prometheus.yaml
kubectl apply -f k8s/security/monitoring-network-policy.yaml

# 모니터링 Pod 준비 확인
kubectl get pods -n monitoring
```

앱 코드를 바꾼 뒤에는 새 이미지 버전을 빌드해 Docker Hub에 올린 다음 배포를 갱신합니다. 현재 배포 버전은 test app `v8`, analyzer `v16`입니다. Isolation Forest는 과거 정상 기준선만으로 학습하고 최근 트래픽을 고정된 모델로 점수화합니다.

```powershell
docker build -t antiwater19/test-web-app:v8 ./app-testing
docker build -t antiwater19/traffic-analyzer:v16 ./analyzer
docker push antiwater19/test-web-app:v8
docker push antiwater19/traffic-analyzer:v16
kubectl apply -f k8s/app/deployment.yaml
kubectl apply -f k8s/analyzer/deployment.yaml
kubectl rollout status deployment/test-web-app -n smart-traffic
kubectl rollout status deployment/traffic-analyzer -n smart-traffic
```

Grafana와 Prometheus는 Ingress로 외부에 공개하지 않고 로컬 포트포워딩으로 접속합니다.

```powershell
# 각 명령은 별도의 터미널에서 실행
kubectl port-forward -n monitoring svc/traffic-monitoring-grafana 3000:80
kubectl port-forward -n monitoring svc/traffic-monitoring-kube-prometheus-prometheus 9090:9090

# Grafana 비밀번호 확인 (기본 사용자: admin)
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((kubectl get secret -n monitoring traffic-monitoring-grafana -o jsonpath='{.data.admin-password}')))
```

- Grafana: <http://localhost:3000>
- Prometheus: <http://localhost:9090/targets>

### 트래픽 로그 확인
```bash
# 앱 통계 API: IP별로 DB에 저장된 요청 수
curl http://test.local/stats

# 개별 트래픽 로그와 DB 연결 오류 로그
kubectl logs -n smart-traffic -l app=test-web-app --prefix=true
```

### 최근 트래픽 집계와 분석 결과
analyzer는 PostgreSQL에서 요청 로그를 직접 조회해 기본 60초 구간을 집계합니다.
분석은 `analysis_results` 테이블에 저장되며, 구간별 지표, IP별 요약, 탐지 사유를 포함합니다.
응답의 `detector_metadata.rule_findings`, `isolation_forest_findings`, `combined_findings`는 각 방식별 탐지 클라이언트 수를 나타냅니다. `findings[]`의 `detection_sources`와 `rule_reasons`로 IP별 탐지 출처와 규칙 근거도 확인할 수 있습니다.
```bash
kubectl port-forward -n smart-traffic svc/traffic-analyzer-service 9000:9000
# 최근 60초 집계만 조회
curl "http://localhost:9000/traffic/summary?window_seconds=60"
# 최근 60초 분석 후 결과 저장
curl -X POST "http://localhost:9000/analyze?window_seconds=60"
# 최근 저장 결과 목록 또는 ID로 단건 조회
curl "http://localhost:9000/analyses?limit=20"
curl "http://localhost:9000/analyses/1"
```
분석기는 규칙 탐지와 Isolation Forest를 함께 사용합니다. 규칙은 요청 수, 오류 비율,
평균 응답 시간을 확인하고, Isolation Forest는 직전 1일 동안 명시적으로 `normal`로 표시된
IP별 60초 집계(요청 수, 오류율, 평균/p95 응답 시간, 경로 수)를 정상 기준선으로 삼습니다.
매 분석 때 최근 60초 집계와 기준선을 함께 모델에 넣어 현재 배치의 이상 점수를 계산합니다.
학습 기준이 20개 구간보다 적으면 모델 결과는 `insufficient_data`로 표시되고 규칙 탐지만 동작합니다.
응답과 저장된 분석 결과의 `detector_metadata`에 모델 준비 상태와 학습 표본 수가 포함됩니다.
첫 적용 뒤 새 기준선 표본을 모으려면 주기적으로 `/analyze`를 호출할 필요 없이 트래픽 로그를 쌓으면 됩니다.
분석 요청은 NetworkPolicy를 자동 변경하지 않습니다.

기존 정상·이상 시나리오의 Isolation Forest 초기 오탐률과 탐지율은 [평가 기록](GuideBook/탐지율_초기평가.md)을 참고하세요. 이 수치는 저장된 과거 분석 결과에서 계산한 초기 비교입니다.

### k6 트래픽 수집 및 이상 탐지 검증
k6는 프로필별로 실행해 정상 기준선과 이상 시나리오를 분리합니다.

- `normal`: `/api`에 낮은 빈도의 정상 요청을 21분간 발생시켜 모델 기준선 수집
- `normal_sample`, `normal_sample_60s`: 별도 Job에서 정상 트래픽을 30초 또는 60초 실행해 오탐 평가
- `burst_1`, `burst_2`, `burst_4`, `burst_8`: `/burst`에 초당 1·2·4·8건 요청을 보내 강도별 탐지 반응 비교
- `burst_8_10s`, `burst_8_30s`, `burst_8_60s`: 초당 8건을 유지하며 burst 지속 시간 비교
- `burst`: 초당 8건의 `/burst` 요청 (기존 프로필)
- `slow`: 2초 지연되는 `/slow` 요청
- `error`: `/error` 요청. 약 절반은 HTTP 500을 반환합니다.
- `all`: 네 가지 시나리오를 짧게 함께 실행하는 전시 시연용 프로필

각 요청의 `scenario` 값과 실제 HTTP 상태 코드가 PostgreSQL `request_logs`에 저장됩니다.
프로젝트 루트의 PowerShell에서 아래처럼 프로필을 선택합니다. Isolation Forest의 기준선은
과거 1일 중 k6가 명시적으로 `normal`로 표시한 요청의 IP별 분 단위 집계이며, 최소 20개 구간이 필요합니다.
시나리오 미지정 로그와 알려진 `burst`, `slow`, `error` 실험 데이터는 기준선에서 제외합니다. 기준선 수집을 마친 뒤
각 k6 Job은 실행 종료 직후 `/analyze`를 호출해 결과를 저장하고 모델 상태와 탐지 수를 로그에
남깁니다. 이 방식으로 트래픽이 최근 60초 구간을 벗어나기 전에 분석 결과를 만들 수 있습니다.
정상 기준선 수집을 마친 뒤 `burst`, `slow`, `error`를 각각 실행해 로그를 비교합니다.
시나리오별 결과를 겹치지 않게 보려면 각 Job이 끝난 뒤 60초 이상 기다렸다가 다음 프로필을 실행합니다.
```powershell
kubectl create configmap k6-script --from-file=test.js=k6/test.js -n smart-traffic --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap k6-run-profile --from-literal=RUN_PROFILE=normal -n smart-traffic --dry-run=client -o yaml | kubectl apply -f -
kubectl delete job k6-test -n smart-traffic --ignore-not-found
kubectl apply -f k8s/k6/k6.yaml
kubectl wait --for=condition=complete job/k6-test -n smart-traffic --timeout=25m
kubectl logs -n smart-traffic job/k6-test
```

`RUN_PROFILE` 값을 `normal`, `normal_eval`, `normal_sample`, `normal_sample_60s`, `burst_1`, `burst_2`, `burst_4`, `burst_8`, `burst_8_10s`, `burst_8_30s`, `burst_8_60s`, `burst`, `slow`, `error`, `all` 중 하나로 바꿔 실행합니다. `normal`은 21분 기준선 수집용이고, `normal_eval`은 기준선 준비 후 정상 요청을 5분 보내면서 매 60초 분석 결과를 저장합니다. 별도 오탐 검증에서는 `normal_sample_60s`처럼 분석 창과 같은 60초 길이를 사용하세요. 지속 시간 또는 강도별 실험은 각 Job이 끝난 뒤 최소 70초 기다려 분석 시간창이 겹치지 않게 합니다.
프로필이 끝난 뒤에는 시나리오별 요청·오류 수를 확인할 수 있습니다.
```sql
SELECT scenario, status_code, COUNT(*) AS requests
FROM request_logs
GROUP BY scenario, status_code
ORDER BY scenario, status_code;
```

테스트 Job은 완료 1시간 후 자동으로 정리됩니다.

### deployment 재배포 
```bash
kubectl rollout restart deployment <deployment-name> -n <namespace>
```

---

### 관리자 대시보드 열기
먼저 Docker Desktop의 Kubernetes가 실행 중이고 `smart-traffic` 네임스페이스에 analyzer가 배포되어 있어야 합니다.
PowerShell을 열고 프로젝트 폴더에서 아래 명령을 실행하세요. 이 터미널 창은 대시보드를 보는 동안 계속 켜두어야 합니다.

```powershell
kubectl port-forward -n smart-traffic svc/traffic-analyzer-service 9000:9000
```

명령이 `Forwarding from 127.0.0.1:9000 -> 9000`이라고 표시되면 브라우저에서 [http://localhost:9000/dashboard](http://localhost:9000/dashboard)를 여세요.
대시보드 요약은 5초마다 갱신됩니다. 분석 구간을 고르고 **지금 분석하기**를 누르면 해당 구간의 분석 결과가 DB에 저장됩니다.
대시보드의 **분석 가이드** 버튼 또는 [http://localhost:9000/guide](http://localhost:9000/guide)에서 데이터 흐름, 탐지 방식, Isolation Forest 기준선 수집, k6 프로필과 API 사용법을 확인할 수 있습니다.
대시보드와 가이드 상단의 테마 버튼으로 다크 모드와 라이트 모드를 전환할 수 있으며, 선택은 브라우저에 저장됩니다.
대시보드를 닫을 때는 포트포워딩 중인 터미널에서 `Ctrl+C`를 누르세요.

접속되지 않으면 다른 프로그램이 9000 포트를 사용 중인지 확인한 뒤, 예를 들어 로컬 포트만 9001로 바꿔 실행하고 `http://localhost:9001/dashboard`로 접속할 수 있습니다.
```powershell
kubectl port-forward -n smart-traffic svc/traffic-analyzer-service 9001:9000
```

### 테스트 앱 포트포워딩
```powershell
kubectl port-forward svc/test-web-app-service 8080:80 -n smart-traffic
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
