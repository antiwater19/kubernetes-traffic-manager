from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from datetime import datetime
import logging
import time
import random
from database import RequestLog, SessionLocal, init_db

# FastAPI 애플리케이션 생성
app = FastAPI()


@app.on_event("startup")
def startup():
    init_db()


@app.middleware("http")
async def record_traffic(request: Request, call_next):
    started_at = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        client_ip = forwarded_for.split(",", 1)[0].strip() or (
            request.client.host if request.client else "unknown"
        )
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        try:
            with SessionLocal() as session:
                session.add(RequestLog(
                    client_ip=client_ip,
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    user_agent=request.headers.get("user-agent", "")[:512],
                ))
                session.commit()
            logging.info(
                "[TRAFFIC] IP=%s METHOD=%s PATH=%s STATUS=%s LATENCY_MS=%s",
                client_ip, request.method, request.url.path, status_code, latency_ms,
            )
        except SQLAlchemyError:
            logging.exception("[TRAFFIC] Failed to persist request log")


# -----------------------------------
# 로그 설정
# -----------------------------------
# 이후 analyzer 서비스가 이 로그를 읽어서
# 비정상 트래픽 탐지에 활용 가능
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)


# -----------------------------------
# 요청 횟수 저장용 딕셔너리
# key   : client ip
# value : 요청 횟수
# -----------------------------------
request_count = {}


# -----------------------------------
# 정적 파일(css/js) 경로 설정
# /static/style.css 형태로 접근 가능
# -----------------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")


# -----------------------------------
# HTML template 경로 설정
# templates/index.html 사용
# -----------------------------------
templates = Jinja2Templates(directory="templates")


# ==========================================================
# 메인 페이지
# ==========================================================
# 브라우저에서 접속하면 HTML 화면 출력
# 현재 접속 IP / 요청 횟수 / 시간 표시
# ==========================================================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    client_ip = request.client.host
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 요청 횟수 증가
    request_count[client_ip] = request_count.get(client_ip, 0) + 1

    # 정상 요청 로그 저장
    logging.info(
        f"[NORMAL] IP={client_ip} COUNT={request_count[client_ip]}"
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "client_ip": client_ip,
            "request_count": request_count[client_ip],
            "server_time": now
        }
    )


# ==========================================================
# 기본 JSON API
# ==========================================================
# API 테스트용 기본 엔드포인트
# 정상적인 트래픽 시뮬레이션
# ==========================================================
@app.get("/api")
async def api_root(request: Request):
    client_ip = request.client.host
    now = datetime.now().strftime("%H:%M:%S")

    request_count[client_ip] = request_count.get(client_ip, 0) + 1

    logging.info(
        f"[NORMAL_API] IP={client_ip} COUNT={request_count[client_ip]}"
    )

    return {
        "message": "Hello from test server",
        "ip": client_ip,
        "count": request_count[client_ip],
        "time": now
    }


# ==========================================================
# 느린 응답 API
# ==========================================================
# 일부러 응답 지연 발생
# 트래픽 병목 테스트용
# ==========================================================
@app.get("/slow")
async def slow(request: Request):
    client_ip = request.client.host

    # 2초 지연
    time.sleep(2)

    logging.info(f"[SLOW] IP={client_ip}")

    return {
        "message": "slow response",
        "ip": client_ip
    }


# ==========================================================
# 랜덤 에러 API
# ==========================================================
# 비정상적인 응답 상황 테스트
# analyzer가 에러 패턴 분석 가능
# ==========================================================
@app.get("/error")
async def error(request: Request):
    client_ip = request.client.host

    # 50% 확률로 에러 발생
    if random.random() < 0.5:
        logging.warning(f"[ERROR] IP={client_ip}")

        return {
            "error": "something went wrong",
            "ip": client_ip
        }

    logging.info(f"[ERROR_TEST_OK] IP={client_ip}")

    return {
        "message": "ok",
        "ip": client_ip
    }


# ==========================================================
# Burst API
# ==========================================================
# 짧은 시간 내 많은 요청 발생 상황 시뮬레이션
# DDoS/비정상 트래픽 테스트용
# ==========================================================
@app.get("/burst")
async def burst(request: Request):
    client_ip = request.client.host

    # CPU 연산 유도
    for _ in range(1000):
        pass

    logging.info(f"[BURST] IP={client_ip}")

    return {
        "message": "burst traffic simulated",
        "ip": client_ip
    }


# ==========================================================
# 통계 확인 API
# ==========================================================
# 현재 몇 명이 접속했는지
# IP별 요청 수 확인 가능
# ==========================================================
@app.get("/stats")
async def stats():
    with SessionLocal() as session:
        total_clients = session.scalar(
            select(func.count(func.distinct(RequestLog.client_ip)))
        ) or 0
        rows = session.execute(
            select(RequestLog.client_ip, func.count(RequestLog.id))
            .group_by(RequestLog.client_ip)
        ).all()
    return {"total_clients": total_clients, "requests": dict(rows)}
