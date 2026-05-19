# API 명세서
## 1. Traffic Analyzer API
/analyze 요청 카운트 세는거
```bash
curl http://localhost:9000/analyze
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