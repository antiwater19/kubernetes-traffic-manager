from fastapi import FastAPI, Request
from datetime import datetime
import logging
import time
import random

app = FastAPI()

# 로그 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

# 요청 카운트 (간단 테스트용)
request_count = {}

# 🔹 기본 엔드포인트
@app.get("/")
async def root(request: Request):
    client_ip = request.client.host
    now = datetime.now().strftime("%H:%M:%S")

    # 요청 수 증가
    request_count[client_ip] = request_count.get(client_ip, 0) + 1

    logging.info(f"[NORMAL] IP={client_ip} COUNT={request_count[client_ip]}")

    return {
        "message": "Hello from test server",
        "ip": client_ip,
        "count": request_count[client_ip],
        "time": now
    }

# 🔹 의도적으로 느린 API (부하 테스트용)
@app.get("/slow")
async def slow(request: Request):
    client_ip = request.client.host

    time.sleep(2)  # 일부러 지연

    logging.info(f"[SLOW] IP={client_ip}")

    return {"message": "slow response"}

# 🔹 랜덤 에러 발생 API (이상 상황 테스트)
@app.get("/error")
async def error(request: Request):
    client_ip = request.client.host

    if random.random() < 0.5:
        logging.warning(f"[ERROR] IP={client_ip}")
        return {"error": "something went wrong"}

    return {"message": "ok"}

# 🔹 트래픽 폭탄 테스트용 엔드포인트
@app.get("/burst")
async def burst(request: Request):
    client_ip = request.client.host

    for _ in range(1000):
        pass  # CPU 살짝 사용

    logging.info(f"[BURST] IP={client_ip}")

    return {"message": "burst traffic simulated"}

# 🔹 통계 확인용
@app.get("/stats")
async def stats():
    return {
        "total_clients": len(request_count),
        "requests": request_count
    }