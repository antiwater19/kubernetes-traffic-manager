import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from blocker import create_or_update_network_policy
from database import AnalysisResult, AnomalyAlert, IPPolicy, SessionLocal, init_db
from detector import analyze_recent_traffic


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
ALERT_SCAN_INTERVAL_SECONDS = 15
ALERT_DEDUPE_INTERVAL_SECONDS = 300
_alert_monitor_task: asyncio.Task | None = None
HUBBLE_RELAY_ADDRESS = os.getenv("HUBBLE_RELAY_ADDRESS", "").strip()
HUBBLE_CLI_PATH = shutil.which("hubble") or "hubble"
AUTH_ADMIN_USERNAME = os.getenv("AUTH_ADMIN_USERNAME", "")
AUTH_ADMIN_PASSWORD = os.getenv("AUTH_ADMIN_PASSWORD", "")
AUTH_VIEWER_USERNAME = os.getenv("AUTH_VIEWER_USERNAME", "")
AUTH_VIEWER_PASSWORD = os.getenv("AUTH_VIEWER_PASSWORD", "")
AUTH_SESSION_SECRET = os.getenv("AUTH_SESSION_SECRET", "")
AUTH_INTERNAL_API_TOKEN = os.getenv("AUTH_INTERNAL_API_TOKEN", "")
AUTH_METRICS_TOKEN = os.getenv("AUTH_METRICS_TOKEN", "")
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
AUTH_SESSION_HOURS = max(1, min(int(os.getenv("AUTH_SESSION_HOURS", "8")), 24))
AUTH_COOKIE_NAME = "smart_traffic_session"
_login_failures: dict[str, list[float]] = {}


class IPAddressBody(BaseModel):
    client_ip: str


class BlockIPBody(IPAddressBody):
    reason: str = Field(default="관리자 수동 차단", max_length=500)
    duration_seconds: int | None = Field(default=None, ge=1, le=2_592_000)


class RateLimitBody(IPAddressBody):
    max_requests: int = Field(ge=1, le=100_000)
    window_seconds: int = Field(ge=1, le=86_400)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)
    next: str = Field(default="/dashboard", max_length=2048)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _create_session_token(username: str, role: str) -> str:
    payload = _b64url_encode(json.dumps({
        "username": username,
        "role": role,
        "expires": int(time.time()) + AUTH_SESSION_HOURS * 3600,
    }, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(AUTH_SESSION_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return f"{payload}.{_b64url_encode(signature)}"


def _read_session_token(token: str | None) -> dict | None:
    if not token or not AUTH_SESSION_SECRET:
        return None
    try:
        payload, supplied_signature = token.split(".", 1)
        expected_signature = _b64url_encode(
            hmac.new(AUTH_SESSION_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        padding = "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload + padding))
        if data.get("expires", 0) <= time.time() or data.get("role") not in {"admin", "viewer"}:
            return None
        return {"username": data["username"], "role": data["role"]}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _configured_users() -> list[tuple[str, str, str]]:
    return [
        (AUTH_ADMIN_USERNAME, AUTH_ADMIN_PASSWORD, "admin"),
        (AUTH_VIEWER_USERNAME, AUTH_VIEWER_PASSWORD, "viewer"),
    ]


def _is_admin_only_request(request: Request) -> bool:
    path = request.url.path
    if path in {"/analyze", "/apply-policy", "/alerts/acknowledge-all"}:
        return True
    if path.startswith("/ip-policies/"):
        return request.method not in {"GET", "HEAD", "OPTIONS"}
    if path.startswith("/alerts/") and path.endswith("/acknowledge"):
        return request.method not in {"GET", "HEAD", "OPTIONS"}
    return False


@app.middleware("http")
async def authenticate_requests(request: Request, call_next):
    path = request.url.path
    public_paths = {"/login", "/auth/login", "/auth/logout", "/healthz"}
    is_public = path in public_paths or path.startswith("/dashboard-static/")
    user = None

    if not is_public:
        if path == "/metrics" and AUTH_METRICS_TOKEN:
            supplied = request.headers.get("authorization", "")
            if hmac.compare_digest(supplied, f"Bearer {AUTH_METRICS_TOKEN}"):
                user = {"username": "prometheus", "role": "service"}
        if user is None and path == "/analyze" and request.method == "POST" and AUTH_INTERNAL_API_TOKEN:
            supplied = request.headers.get("authorization", "")
            if hmac.compare_digest(supplied, f"Bearer {AUTH_INTERNAL_API_TOKEN}"):
                user = {"username": "k6", "role": "service"}
        if user is None:
            user = _read_session_token(request.cookies.get(AUTH_COOKIE_NAME))
        if user is None:
            if path in {"/", "/dashboard", "/guide"}:
                next_path = quote(request.url.path + (f"?{request.url.query}" if request.url.query else ""), safe="/?=&")
                return RedirectResponse(f"/login?next={next_path}", status_code=303)
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        if _is_admin_only_request(request) and user["role"] not in {"admin", "service"}:
            return JSONResponse({"detail": "Administrator role required"}, status_code=403)

    request.state.auth_user = user
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if path in {"/login", "/auth/me"} or path.startswith("/dashboard") or path == "/guide":
        response.headers["Cache-Control"] = "no-store"
    return response


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


def serialize_alert(alert: AnomalyAlert) -> dict:
    return {
        "id": alert.id,
        "client_ip": alert.client_ip,
        "severity": alert.severity,
        "title": alert.title,
        "reasons": alert.reasons or [],
        "detection_sources": alert.detection_sources or [],
        "details": alert.details or {},
        "first_seen_at": alert.first_seen_at,
        "last_seen_at": alert.last_seen_at,
        "occurrence_count": alert.occurrence_count,
        "is_acknowledged": alert.is_acknowledged,
        "acknowledged_at": alert.acknowledged_at,
    }


def persist_anomaly_alerts(summary: dict) -> int:
    findings = summary.get("findings") or []
    if not findings:
        return 0

    now = datetime.now(timezone.utc)
    interval = int(now.timestamp()) // ALERT_DEDUPE_INTERVAL_SECONDS
    try:
        with SessionLocal() as session:
            for finding in findings:
                client_ip = str(finding.get("client_ip", "unknown"))
                sources = sorted(finding.get("detection_sources") or [])
                dedupe_key = hashlib.sha256(
                    f"{client_ip}|{interval}|{','.join(sources)}".encode("utf-8")
                ).hexdigest()
                reasons = finding.get("reasons") or []
                values = {
                    "dedupe_key": dedupe_key,
                    "client_ip": client_ip,
                    "severity": finding.get("severity", "medium"),
                    "title": f"이상 트래픽 감지 · {client_ip}",
                    "reasons": reasons,
                    "detection_sources": sources,
                    "details": {
                        "request_count": finding.get("request_count", 0),
                        "error_rate": finding.get("error_rate", 0),
                        "average_latency_ms": finding.get("average_latency_ms", 0),
                        "window_seconds": summary.get("window_seconds", 60),
                    },
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "occurrence_count": 1,
                    "is_acknowledged": False,
                }
                statement = pg_insert(AnomalyAlert).values(**values).on_conflict_do_update(
                    index_elements=[AnomalyAlert.dedupe_key],
                    set_={
                        "severity": values["severity"],
                        "reasons": values["reasons"],
                        "detection_sources": values["detection_sources"],
                        "details": values["details"],
                        "last_seen_at": now,
                        "occurrence_count": AnomalyAlert.occurrence_count + 1,
                    },
                )
                session.execute(statement)
            session.commit()
        return len(findings)
    except SQLAlchemyError:
        logging.exception("Could not persist anomaly alerts")
        return 0


def automatic_alert_scan() -> None:
    summary = collect_recent_traffic(60)
    persist_anomaly_alerts(summary)


async def alert_monitor_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(automatic_alert_scan)
        except Exception:
            logging.exception("Automatic anomaly scan failed")
        await asyncio.sleep(ALERT_SCAN_INTERVAL_SECONDS)


@app.on_event("startup")
def startup():
    init_db()


@app.on_event("startup")
async def start_alert_monitor():
    global _alert_monitor_task
    _alert_monitor_task = asyncio.create_task(alert_monitor_loop())


@app.on_event("shutdown")
async def stop_alert_monitor():
    if _alert_monitor_task:
        _alert_monitor_task.cancel()
        try:
            await _alert_monitor_task
        except asyncio.CancelledError:
            pass


@app.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse(BASE_DIR / "templates" / "login.html")


@app.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    if not AUTH_SESSION_SECRET or not all((AUTH_ADMIN_USERNAME, AUTH_ADMIN_PASSWORD, AUTH_VIEWER_USERNAME, AUTH_VIEWER_PASSWORD)):
        raise HTTPException(status_code=503, detail="Authentication credentials are not configured")

    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    failures = [stamp for stamp in _login_failures.get(client_ip, []) if now - stamp < 300]
    _login_failures[client_ip] = failures
    if len(failures) >= 5:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in five minutes.")

    matched_user = None
    for username, password, role in _configured_users():
        username_matches = hmac.compare_digest(body.username.encode("utf-8"), username.encode("utf-8"))
        password_matches = hmac.compare_digest(body.password.encode("utf-8"), password.encode("utf-8"))
        if username_matches and password_matches:
            matched_user = {"username": username, "role": role}

    if matched_user is None:
        failures.append(now)
        _login_failures[client_ip] = failures
        raise HTTPException(status_code=401, detail="사용자 이름 또는 비밀번호가 올바르지 않습니다.")

    _login_failures.pop(client_ip, None)
    token = _create_session_token(matched_user["username"], matched_user["role"])
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=AUTH_SESSION_HOURS * 3600,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    requested_next = body.next
    next_path = (
        requested_next
        if requested_next.startswith("/") and not requested_next.startswith("//") and "\\" not in requested_next
        else "/dashboard"
    )
    return {**matched_user, "next": next_path, "session_hours": AUTH_SESSION_HOURS}


@app.get("/auth/me")
async def current_user(request: Request):
    return request.state.auth_user


@app.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", httponly=True, secure=AUTH_COOKIE_SECURE, samesite="lax")
    return {"logged_out": True}


@app.get("/healthz", include_in_schema=False)
async def health_check():
    return {"status": "ok"}


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
    persist_anomaly_alerts(analysis)
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


@app.get("/alerts")
async def list_alerts(
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = Query(default=False),
):
    try:
        with SessionLocal() as session:
            statement = select(AnomalyAlert)
            if unread_only:
                statement = statement.where(AnomalyAlert.is_acknowledged.is_(False))
            alerts = session.scalars(
                statement.order_by(AnomalyAlert.last_seen_at.desc(), AnomalyAlert.id.desc()).limit(limit)
            ).all()
            return [serialize_alert(alert) for alert in alerts]
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Alert database is unavailable") from exc


@app.get("/alerts/unread-count")
async def unread_alert_count():
    try:
        with SessionLocal() as session:
            count = session.scalar(
                select(func.count(AnomalyAlert.id)).where(AnomalyAlert.is_acknowledged.is_(False))
            ) or 0
            return {"unread_count": count}
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Alert database is unavailable") from exc


@app.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    try:
        with SessionLocal() as session:
            alert = session.get(AnomalyAlert, alert_id)
            if alert is None:
                raise HTTPException(status_code=404, detail="Alert not found")
            alert.is_acknowledged = True
            alert.acknowledged_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(alert)
            return serialize_alert(alert)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Could not acknowledge alert") from exc


@app.post("/alerts/acknowledge-all")
async def acknowledge_all_alerts():
    try:
        with SessionLocal() as session:
            result = session.execute(
                update(AnomalyAlert)
                .where(AnomalyAlert.is_acknowledged.is_(False))
                .values(is_acknowledged=True, acknowledged_at=datetime.now(timezone.utc))
            )
            session.commit()
            return {"acknowledged_count": result.rowcount or 0}
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Could not acknowledge alerts") from exc


def _flow_field(mapping: dict, snake_name: str, camel_name: str | None = None):
    return mapping.get(snake_name, mapping.get(camel_name) if camel_name else None)


def _endpoint_summary(endpoint: dict, fallback_ip: str | None) -> dict:
    return {
        "namespace": endpoint.get("namespace", ""),
        "pod": endpoint.get("pod_name", endpoint.get("podName", "")),
        "workload": endpoint.get("workload_name", endpoint.get("workloadName", "")),
        "ip": endpoint.get("ip", fallback_ip or ""),
    }


def normalize_hubble_flow(record: dict) -> dict:
    flow = record.get("flow", record)
    ip_data = flow.get("IP", flow.get("ip", {})) or {}
    source = _endpoint_summary(flow.get("source", {}) or {}, ip_data.get("source", ""))
    destination = _endpoint_summary(flow.get("destination", {}) or {}, ip_data.get("destination", ""))
    verdict = str(flow.get("verdict", "UNKNOWN")).upper()
    verdict_labels = {
        "FORWARDED": "허용·전달",
        "DROPPED": "차단·드롭",
        "AUDIT": "감사 모드",
        "ERROR": "처리 오류",
        "REDIRECTED": "프록시 전달",
        "TRACED": "관측",
        "TRANSLATED": "주소 변환",
    }
    l4 = flow.get("l4", {}) or {}
    protocol = ""
    source_port = ""
    destination_port = ""
    for protocol_name, protocol_data in l4.items():
        if isinstance(protocol_data, dict):
            protocol = protocol_name.upper()
            source_port = protocol_data.get("source_port", protocol_data.get("sourcePort", ""))
            destination_port = protocol_data.get("destination_port", protocol_data.get("destinationPort", ""))
            break

    policy_names = []
    policy_fields = (
        ("ingress_allowed_by", "ingressAllowedBy", "ingress 허용"),
        ("egress_allowed_by", "egressAllowedBy", "egress 허용"),
        ("ingress_denied_by", "ingressDeniedBy", "ingress 차단"),
        ("egress_denied_by", "egressDeniedBy", "egress 차단"),
    )
    for snake_name, camel_name, label in policy_fields:
        matched = _flow_field(flow, snake_name, camel_name) or []
        for entry in matched:
            if isinstance(entry, dict):
                name = entry.get("name", "")
                namespace = entry.get("namespace", "")
                rule = entry.get("rule")
                identifier = f"{namespace}/{name}" if namespace and name else name or namespace or "정책"
                if rule not in (None, ""):
                    identifier += f" 규칙 {rule}"
                policy_names.append(f"{label}: {identifier}")
            else:
                policy_names.append(f"{label}: {entry}")

    reason = flow.get("drop_reason_desc", flow.get("dropReasonDesc", ""))
    if not policy_names and reason:
        policy_names.append(str(reason))
    event = flow.get("event_type", flow.get("eventType", {})) or {}
    l7 = flow.get("l7", {}) or {}
    l7_summary = ""
    if isinstance(l7, dict):
        http = l7.get("http", l7.get("HTTP", {})) or {}
        dns = l7.get("dns", l7.get("DNS", {})) or {}
        if http:
            l7_summary = " ".join(str(http.get(key, "")) for key in ("method", "url", "code")).strip()
        elif dns:
            l7_summary = "DNS " + str(dns.get("query", dns.get("Query", "")))

    return {
        "time": flow.get("time", ""),
        "source": source,
        "destination": destination,
        "protocol": protocol,
        "source_port": source_port,
        "destination_port": destination_port,
        "verdict": verdict,
        "verdict_label": verdict_labels.get(verdict, verdict),
        "drop_reason": reason,
        "policy_names": policy_names,
        "direction": str(flow.get("traffic_direction", flow.get("trafficDirection", ""))).replace("TRAFFIC_DIRECTION_", ""),
        "event_type": event.get("type", "") if isinstance(event, dict) else "",
        "summary": l7_summary or flow.get("summary", ""),
    }


@app.get("/hubble/flows")
async def hubble_flows(
    limit: int = Query(default=100, ge=1, le=200),
    namespace: str | None = Query(default=None, min_length=1, max_length=63),
):
    """Read recent Cilium network flows through the configured Hubble Relay."""
    if not HUBBLE_RELAY_ADDRESS:
        return {
            "configured": False,
            "available": False,
            "relay_address": None,
            "message": "Hubble Relay가 이 Analyzer에 설정되지 않았습니다.",
            "flows": [],
        }

    command = [
        HUBBLE_CLI_PATH,
        "observe",
        "--server",
        HUBBLE_RELAY_ADDRESS,
        "--last",
        str(limit),
        "--output",
        "json",
    ]
    if namespace:
        command.extend(["--namespace", namespace])
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "configured": True,
            "available": False,
            "relay_address": HUBBLE_RELAY_ADDRESS,
            "message": f"Hubble Relay에 연결하지 못했습니다: {exc}",
            "flows": [],
        }

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Hubble 조회 오류").strip()[-500:]
        return {
            "configured": True,
            "available": False,
            "relay_address": HUBBLE_RELAY_ADDRESS,
            "message": message,
            "flows": [],
        }

    flows = []
    decoder = json.JSONDecoder()
    output = result.stdout.lstrip()
    while output:
        try:
            record, end = decoder.raw_decode(output)
        except json.JSONDecodeError:
            break
        records = record if isinstance(record, list) else [record]
        flows.extend(normalize_hubble_flow(item) for item in records if isinstance(item, dict))
        output = output[end:].lstrip()
    return {
        "configured": True,
        "available": True,
        "relay_address": HUBBLE_RELAY_ADDRESS,
        "message": "Hubble Relay 연결됨",
        "flow_count": len(flows),
        "flows": flows,
    }


@app.get("/apply-policy")
async def apply_policy():
    """Manually apply the existing ingress-only NetworkPolicy for testing."""
    return create_or_update_network_policy()
