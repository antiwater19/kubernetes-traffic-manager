from fastapi import FastAPI
import requests

from detector import detect_abnormal_traffic

app = FastAPI()

# Kubernetes 내부 Service 주소
TEST_APP_STATS_URL = "http://test-web-app-service.smart-traffic.svc.cluster.local/stats"


@app.get("/")
async def root():
    return {
        "message": "Smart Traffic Analyzer is running"
    }


@app.get("/analyze")
async def analyze():
    # test-web-app의 /stats API 호출
    response = requests.get(TEST_APP_STATS_URL)
    stats_data = response.json()

    # 이상 트래픽 탐지
    abnormal_result = detect_abnormal_traffic(stats_data)

    return {
        "stats": stats_data,
        "abnormal_traffic": abnormal_result
    }