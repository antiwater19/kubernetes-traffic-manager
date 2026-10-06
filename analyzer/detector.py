from datetime import datetime, timedelta, timezone
import math

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from database import RequestLog


DETECTOR_NAME = "windowed-rules-v1"
REQUEST_COUNT_THRESHOLD = 20
ERROR_RATE_THRESHOLD = 0.5
MIN_ERRORS_FOR_RATE_ALERT = 3
SLOW_AVERAGE_MS_THRESHOLD = 1000.0
MIN_REQUESTS_FOR_LATENCY_ALERT = 3


def analyze_recent_traffic(session: Session, window_seconds: int) -> dict:
    """Summarize a recent time window and return rule-based findings."""
    window_ended_at = datetime.now(timezone.utc)
    window_started_at = window_ended_at - timedelta(seconds=window_seconds)
    in_window = (
        RequestLog.created_at >= window_started_at,
        RequestLog.created_at <= window_ended_at,
    )

    totals = session.execute(
        select(
            func.count(RequestLog.id),
            func.count(func.distinct(RequestLog.client_ip)),
            func.coalesce(
                func.sum(case((RequestLog.status_code >= 400, 1), else_=0)), 0
            ),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0),
            func.coalesce(
                func.percentile_cont(0.95).within_group(RequestLog.latency_ms), 0.0
            ),
        ).where(*in_window)
    ).one()

    client_rows = session.execute(
        select(
            RequestLog.client_ip,
            func.count(RequestLog.id).label("request_count"),
            func.coalesce(
                func.sum(case((RequestLog.status_code >= 400, 1), else_=0)), 0
            ).label("error_count"),
            func.count(func.distinct(RequestLog.path)).label("unique_paths"),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0).label("average_latency_ms"),
            func.coalesce(
                func.percentile_cont(0.95).within_group(RequestLog.latency_ms), 0.0
            ).label("p95_latency_ms"),
        )
        .where(*in_window)
        .group_by(RequestLog.client_ip)
        .order_by(func.count(RequestLog.id).desc())
    ).all()

    bucket_seconds = max(1, math.ceil(window_seconds / 60))
    bucket_number = func.floor(
        func.extract("epoch", RequestLog.created_at) / bucket_seconds
    ).label("bucket_number")
    bucket_rows = session.execute(
        select(
            bucket_number,
            func.count(RequestLog.id),
            func.coalesce(
                func.sum(case((RequestLog.status_code >= 400, 1), else_=0)), 0
            ),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0),
        )
        .where(*in_window)
        .group_by(bucket_number)
        .order_by(bucket_number)
    ).all()

    buckets = {
        int(row[0]): {
            "request_count": int(row[1]),
            "error_count": int(row[2]),
            "average_latency_ms": round(float(row[3]), 2),
        }
        for row in bucket_rows
    }
    first_bucket = math.floor(window_started_at.timestamp() / bucket_seconds)
    last_bucket = math.floor(window_ended_at.timestamp() / bucket_seconds)
    timeline = []
    for number in range(first_bucket, last_bucket + 1):
        bucket = buckets.get(number, {
            "request_count": 0,
            "error_count": 0,
            "average_latency_ms": 0.0,
        })
        timeline.append({
            "timestamp": datetime.fromtimestamp(
                number * bucket_seconds, tz=timezone.utc
            ),
            **bucket,
        })

    clients = []
    findings = []
    for row in client_rows:
        request_count = int(row.request_count)
        error_count = int(row.error_count)
        error_rate = error_count / request_count if request_count else 0.0
        average_latency_ms = float(row.average_latency_ms)
        client = {
            "client_ip": row.client_ip,
            "request_count": request_count,
            "error_count": error_count,
            "error_rate": round(error_rate, 4),
            "unique_paths": int(row.unique_paths),
            "average_latency_ms": round(average_latency_ms, 2),
            "p95_latency_ms": round(float(row.p95_latency_ms), 2),
        }
        clients.append(client)

        reasons = []
        if request_count > REQUEST_COUNT_THRESHOLD:
            reasons.append(
                f"최근 {window_seconds}초 요청 {request_count}건이 "
                f"기준 {REQUEST_COUNT_THRESHOLD}건을 초과했습니다."
            )
        if error_count >= MIN_ERRORS_FOR_RATE_ALERT and error_rate >= ERROR_RATE_THRESHOLD:
            reasons.append(
                f"오류 응답 비율이 {error_rate:.0%} "
                f"({error_count}/{request_count})입니다."
            )
        if (
            request_count >= MIN_REQUESTS_FOR_LATENCY_ALERT
            and average_latency_ms >= SLOW_AVERAGE_MS_THRESHOLD
        ):
            reasons.append(
                f"평균 응답 시간이 {average_latency_ms:.0f}ms로 "
                f"기준 {SLOW_AVERAGE_MS_THRESHOLD:.0f}ms 이상입니다."
            )

        if reasons:
            findings.append({
                **client,
                "severity": "high" if request_count >= 60 or error_rate >= 0.8 else "medium",
                "reasons": reasons,
            })

    total_requests = int(totals[0])
    unique_clients = int(totals[1])
    error_requests = int(totals[2])
    return {
        "window_seconds": window_seconds,
        "window_started_at": window_started_at,
        "window_ended_at": window_ended_at,
        "detector_name": DETECTOR_NAME,
        "status": "abnormal" if findings else "normal",
        "total_requests": total_requests,
        "unique_clients": unique_clients,
        "error_requests": error_requests,
        "error_rate": round(error_requests / total_requests, 4) if total_requests else 0.0,
        "average_latency_ms": round(float(totals[3]), 2),
        "p95_latency_ms": round(float(totals[4]), 2),
        "client_summaries": clients,
        "findings": findings,
        "bucket_seconds": bucket_seconds,
        "timeline": timeline,
    }
