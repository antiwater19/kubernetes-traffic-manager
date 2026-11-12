from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from blocker import create_or_update_network_policy
from database import AnalysisResult, IPPolicy, SessionLocal, init_db
from detector import analyze_recent_traffic
from pathlib import Path
from datetime import datetime, timedelta, timezone
import ipaddress


app = FastAPI(title="Smart Traffic Analyzer")
Instrumentator(
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
BASE_DIR = Path(__file__).resolve().parent
app.mount(
    "/dashboard-static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="dashboard-static",
)


class IPAddressBody(BaseModel):
    client_ip: str


class BlockIPBody(IPAddressBody):
    reason: str = Field(default="관리자 수동 차단", max_length=500)
    duration_seconds: int | None = Field(default=None, ge=1, le=2_592_000)


class RateLimitBody(IPAddressBody):
    max_requests: int = Field(ge=1, le=100_000)
    window_seconds: int = Field(ge=1, le=86_400)


def normalize_client_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="A valid IPv4 or IPv6 address is required") from exc
    if address.is_unspecified or address.is_multicast:
        raise HTTPException(status_code=422, detail="This IP address cannot be managed")
    return address.compressed


def serialize_ip_policy(policy: IPPolicy) -> dict:
    now = datetime.now(timezone.utc)
    blocked_active = bool(
        policy.is_blocked
        and (policy.blocked_until is None or policy.blocked_until > now)
    )
    return {
        "client_ip": policy.client_ip,
        "is_blocked": blocked_active,
        "block_reason": policy.block_reason,
        "blocked_at": policy.blocked_at,
        "blocked_until": policy.blocked_until,
        "rate_limit_max_requests": policy.rate_limit_max_requests,
        "rate_limit_window_seconds": policy.rate_limit_window_seconds,
        "updated_at": policy.updated_at,
    }


@app.on_event("startup")
def startup():
    init_db()


def serialize_analysis(record: AnalysisResult) -> dict:
    return {
        "id": record.id,
        "analyzed_at": record.analyzed_at,
        "window_seconds": record.window_seconds,
        "window_started_at": record.window_started_at,
        "window_ended_at": record.window_ended_at,
        "detector_name": record.detector_name,
        "status": record.status,
        "total_requests": record.total_requests,
        "unique_clients": record.unique_clients,
        "error_requests": record.error_requests,
        "error_rate": record.error_rate,
        "average_latency_ms": record.average_latency_ms,
        "p95_latency_ms": record.p95_latency_ms,
        "bucket_seconds": record.bucket_seconds,
        "timeline": record.timeline,
        "client_summaries": record.client_summaries,
        "findings": record.findings,
        "detector_metadata": record.detector_metadata,
    }


def collect_recent_traffic(window_seconds: int) -> dict:
    try:
        with SessionLocal() as session:
            return analyze_recent_traffic(session, window_seconds)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Traffic database is unavailable") from exc


@app.get("/")
async def root():
    return {"message": "Smart Traffic Analyzer is running"}


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(BASE_DIR / "templates" / "dashboard.html")


@app.get("/guide", include_in_schema=False)
async def analysis_guide():
    return FileResponse(BASE_DIR / "templates" / "guide.html")


@app.get("/traffic/summary")
async def traffic_summary(
    window_seconds: int = Query(default=60, ge=1, le=86400),
):
    """Summarize request logs from the requested recent time window."""
    return collect_recent_traffic(window_seconds)


@app.api_route("/analyze", methods=["GET", "POST"])
async def analyze(
    window_seconds: int = Query(default=60, ge=1, le=86400),
):
    """Analyze a recent window and persist the summary and findings."""
    analysis = collect_recent_traffic(window_seconds)
    try:
        with SessionLocal() as session:
            record = AnalysisResult(**analysis)
            session.add(record)
            session.commit()
            session.refresh(record)
            result = serialize_analysis(record)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Could not save analysis result") from exc
    return result


@app.get("/analyses")
async def list_analyses(limit: int = Query(default=20, ge=1, le=100)):
    """List the newest saved analysis results."""
    try:
        with SessionLocal() as session:
            records = session.scalars(
                select(AnalysisResult)
                .order_by(AnalysisResult.analyzed_at.desc(), AnalysisResult.id.desc())
                .limit(limit)
            ).all()
            return [serialize_analysis(record) for record in records]
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Traffic database is unavailable") from exc


@app.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: int):
    """Get one saved analysis result."""
    try:
        with SessionLocal() as session:
            record = session.get(AnalysisResult, analysis_id)
            if record is None:
                raise HTTPException(status_code=404, detail="Analysis result not found")
            return serialize_analysis(record)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Traffic database is unavailable") from exc


@app.get("/ip-policies")
async def list_ip_policies():
    """List persisted IP bans and rate limits for the dashboard."""
    try:
        with SessionLocal() as session:
            policies = session.scalars(
                select(IPPolicy).order_by(IPPolicy.updated_at.desc(), IPPolicy.client_ip)
            ).all()
            return [serialize_ip_policy(policy) for policy in policies]
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Traffic database is unavailable") from exc


@app.post("/ip-policies/block")
async def block_ip(body: BlockIPBody):
    client_ip = normalize_client_ip(body.client_ip)
    now = datetime.now(timezone.utc)
    try:
        with SessionLocal() as session:
            policy = session.get(IPPolicy, client_ip)
            if policy is None:
                policy = IPPolicy(client_ip=client_ip)
                session.add(policy)
            policy.is_blocked = True
            policy.block_reason = body.reason.strip() or "관리자 수동 차단"
            policy.blocked_at = now
            policy.blocked_until = now + timedelta(seconds=body.duration_seconds) if body.duration_seconds else None
            session.commit()
            session.refresh(policy)
            return serialize_ip_policy(policy)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Could not save IP block policy") from exc


@app.post("/ip-policies/unblock")
async def unblock_ip(body: IPAddressBody):
    client_ip = normalize_client_ip(body.client_ip)
    try:
        with SessionLocal() as session:
            policy = session.get(IPPolicy, client_ip)
            if policy is None:
                raise HTTPException(status_code=404, detail="IP policy not found")
            policy.is_blocked = False
            policy.blocked_until = None
            session.commit()
            session.refresh(policy)
            return serialize_ip_policy(policy)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Could not update IP block policy") from exc


@app.post("/ip-policies/rate-limit")
async def set_ip_rate_limit(body: RateLimitBody):
    client_ip = normalize_client_ip(body.client_ip)
    try:
        with SessionLocal() as session:
            policy = session.get(IPPolicy, client_ip)
            if policy is None:
                policy = IPPolicy(client_ip=client_ip)
                session.add(policy)
            policy.rate_limit_max_requests = body.max_requests
            policy.rate_limit_window_seconds = body.window_seconds
            session.commit()
            session.refresh(policy)
            return serialize_ip_policy(policy)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Could not save IP rate limit") from exc


@app.post("/ip-policies/rate-limit/clear")
async def clear_ip_rate_limit(body: IPAddressBody):
    client_ip = normalize_client_ip(body.client_ip)
    try:
        with SessionLocal() as session:
            policy = session.get(IPPolicy, client_ip)
            if policy is None:
                raise HTTPException(status_code=404, detail="IP policy not found")
            policy.rate_limit_max_requests = None
            policy.rate_limit_window_seconds = None
            session.commit()
            session.refresh(policy)
            return serialize_ip_policy(policy)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Could not clear IP rate limit") from exc


@app.get("/apply-policy")
async def apply_policy():
    """Manually apply the existing ingress-only NetworkPolicy for testing."""
    return create_or_update_network_policy()
