from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from blocker import create_or_update_network_policy
from database import AnalysisResult, SessionLocal, init_db
from detector import analyze_recent_traffic
from pathlib import Path


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


@app.get("/apply-policy")
async def apply_policy():
    """Manually apply the existing ingress-only NetworkPolicy for testing."""
    return create_or_update_network_policy()
