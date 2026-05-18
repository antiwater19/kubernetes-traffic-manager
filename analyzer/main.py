from fastapi import FastAPI
import requests
import logging

from detector import detect_abnormal_traffic
from blocker import create_or_update_network_policy


app = FastAPI()

# Kubernetes 내부 Service 주소
TEST_APP_STATS_URL = "http://test-web-app-service.smart-traffic.svc.cluster.local/stats"


@app.get("/")
async def root():
    return {
        "message": "Smart Traffic Analyzer is running"
    }


# @app.get("/analyze")
# async def analyze():
#     # test-web-app의 /stats API 호출
#     response = requests.get(TEST_APP_STATS_URL)
#     stats_data = response.json()

#     # 이상 트래픽 탐지
#     abnormal_result = detect_abnormal_traffic(stats_data)

#     return {
#         "stats": stats_data,
#         "abnormal_traffic": abnormal_result
#     }

@app.get("/analyze")
async def analyze():
    response = requests.get(TEST_APP_STATS_URL)
    stats_data = response.json()

    abnormal_result = detect_abnormal_traffic(stats_data)

    block_result = None

    if abnormal_result:
        logging.warning(f"[ANALYZER] Abnormal traffic detected: {abnormal_result}")

        block_result = create_or_update_network_policy()

        logging.warning(f"[ANALYZER] NetworkPolicy applied: {block_result}")

    return {
        "stats": stats_data,
        "abnormal_traffic": abnormal_result,
        "block_result": block_result
    }

@app.get("/apply-policy")
async def apply_policy():
    # 테스트용: 이상 탐지와 상관없이 NetworkPolicy 적용
    result = create_or_update_network_policy()
    return result