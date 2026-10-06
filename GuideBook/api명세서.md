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

## 2. App-testing
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
