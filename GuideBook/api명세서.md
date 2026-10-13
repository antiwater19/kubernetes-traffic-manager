# API 명세서
## 1. Traffic Analyzer API
최근 60초 트래픽 요약 (초 단위로 구간 지정 가능)
```bash
curl "http://localhost:9000/traffic/summary?window_seconds=60"
```
최근 구간 분석 후 결과 저장 (기본 구간 60초, 최대 24시간)
```bash
curl -X POST "http://localhost:9000/analyze?window_seconds=60"
```
저장된 분석 결과 목록 및 ID 조회
```bash
curl "http://localhost:9000/analyses?limit=20"
curl "http://localhost:9000/analyses/1"
```
분석 응답에는 `detector_metadata`가 포함됩니다. Isolation Forest 상태(`ready` 또는
`insufficient_data`), 학습 구간 수, 기준선 기간, 사용한 특징값을 확인할 수 있습니다.
모델은 직전 7일의 IP별 60초 집계를 학습하고 최근 60초를 점수화합니다. 학습 구간이
20개 미만이면 모델 탐지는 대기하고 기존 규칙 탐지만 수행합니다.

## 2. App-testing
/api 기본 JSON 요청
```bash
curl http://test.local/api
```
/slow 지연 응답
```bash
curl http://test.local/slow
```
/error 약 50% 확률로 HTTP 500 에러 응답
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
