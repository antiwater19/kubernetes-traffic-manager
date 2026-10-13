from datetime import datetime, timedelta, timezone
import math
import time

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from database import RequestLog


DETECTOR_NAME = "windowed-rules+isolation-forest-v2"
REQUEST_COUNT_THRESHOLD = 20
ERROR_RATE_THRESHOLD = 0.5
MIN_ERRORS_FOR_RATE_ALERT = 3
SLOW_AVERAGE_MS_THRESHOLD = 1000.0
MIN_REQUESTS_FOR_LATENCY_ALERT = 3
BASELINE_DAYS = 1
MIN_TRAINING_SAMPLES = 20
CONTAMINATION = 0.05
FEATURE_NAMES = [
    "request_count",
    "error_rate",
    "average_latency_ms",
    "p95_latency_ms",
    "unique_paths",
]
_MODEL_CACHE = {"checked_at": 0.0, "training_features": None, "training_samples": 0}


def _feature_row(row) -> list[float]:
    count = int(row.request_count)
    errors = int(row.error_count)
    return [
        float(count),
        errors / count if count else 0.0,
        float(row.average_latency_ms),
        float(row.p95_latency_ms),
        float(row.unique_paths),
    ]


def _run_isolation_forest(session: Session, window_started_at: datetime, window_ended_at: datetime):
    """Train on prior per-client minute buckets and score the latest minute."""
    minute_bucket = func.floor(func.extract("epoch", RequestLog.created_at) / 60)
    error_count = func.coalesce(
        func.sum(case((RequestLog.status_code >= 400, 1), else_=0)), 0
    )

    cache_ttl = 300 if _MODEL_CACHE["training_features"] is not None else 60
    if time.monotonic() - _MODEL_CACHE["checked_at"] >= cache_ttl:
        baseline_rows = session.execute(
            select(
                RequestLog.client_ip.label("client_ip"),
                minute_bucket.label("minute_bucket"),
                func.count(RequestLog.id).label("request_count"),
                error_count.label("error_count"),
                func.coalesce(func.avg(RequestLog.latency_ms), 0.0).label("average_latency_ms"),
                func.coalesce(
                    func.percentile_cont(0.95).within_group(RequestLog.latency_ms), 0.0
                ).label("p95_latency_ms"),
                func.count(func.distinct(RequestLog.path)).label("unique_paths"),
            )
            .where(
                RequestLog.created_at >= window_started_at - timedelta(days=BASELINE_DAYS),
                RequestLog.created_at < window_started_at,
                RequestLog.scenario == "normal",
            )
            .group_by(RequestLog.client_ip, minute_bucket)
            .order_by(minute_bucket.desc())
            .limit(2000)
        ).all()
        _MODEL_CACHE["training_samples"] = len(baseline_rows)
        if len(baseline_rows) >= MIN_TRAINING_SAMPLES:
            _MODEL_CACHE["training_features"] = np.asarray(
                [_feature_row(row) for row in baseline_rows], dtype=float
            )
        else:
            _MODEL_CACHE["training_features"] = None
        _MODEL_CACHE["checked_at"] = time.monotonic()

    score_started_at = max(window_started_at, window_ended_at - timedelta(seconds=60))
    current_rows = session.execute(
        select(
            RequestLog.client_ip.label("client_ip"),
            func.count(RequestLog.id).label("request_count"),
            error_count.label("error_count"),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0).label("average_latency_ms"),
            func.coalesce(
                func.percentile_cont(0.95).within_group(RequestLog.latency_ms), 0.0
            ).label("p95_latency_ms"),
            func.count(func.distinct(RequestLog.path)).label("unique_paths"),
        )
        .where(
            RequestLog.created_at >= score_started_at,
            RequestLog.created_at <= window_ended_at,
        )
        .group_by(RequestLog.client_ip)
    ).all()

    metadata = {
        "name": "Isolation Forest",
        "status": "insufficient_data",
        "training_samples": _MODEL_CACHE["training_samples"],
        "minimum_training_samples": MIN_TRAINING_SAMPLES,
        "scored_clients": len(current_rows),
        "baseline_days": BASELINE_DAYS,
        "baseline_scenarios": ["normal"],
        "scored_window_seconds": 60,
        "contamination": CONTAMINATION,
        "features": FEATURE_NAMES,
    }
    scored = {}
    training = _MODEL_CACHE["training_features"]
    if training is None:
        return scored, metadata

    metadata["status"] = "ready"
    metadata["anomalies"] = 0
    if not current_rows:
        return scored, metadata

    current = np.asarray([_feature_row(row) for row in current_rows], dtype=float)
    model = IsolationForest(
        n_estimators=150,
        contamination=CONTAMINATION,
        random_state=42,
        n_jobs=1,
    )
    # Include the current scoring batch so values outside the historical range
    # can be isolated as outliers by the forest's random splits.
    model.fit(np.vstack([training, current]))
    metadata["decision_threshold"] = round(float(model.offset_), 6)
    predictions = model.predict(current)
    decision_scores = model.decision_function(current)
    metadata["anomalies"] = int(np.count_nonzero(predictions == -1))
    for row, prediction, score in zip(current_rows, predictions, decision_scores):
        scored[row.client_ip] = {
            "is_anomaly": bool(prediction == -1),
            "decision_score": round(float(score), 6),
        }
    return scored, metadata


def analyze_recent_traffic(session: Session, window_seconds: int) -> dict:
    """Summarize a recent time window and return rule and model findings."""
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
            ).isoformat(),
            **bucket,
        })

    model_scores, detector_metadata = _run_isolation_forest(
        session, window_started_at, window_ended_at
    )
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
        score = model_scores.get(row.client_ip)
        if score:
            client["isolation_forest"] = score
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
        if score and score["is_anomaly"]:
            reasons.append(
                "Isolation Forest가 최근 60초의 요청량, 오류율, 응답 시간, "
                f"경로 수 조합을 과거 기준선과 다른 이상 패턴으로 판단했습니다. "
                f"(점수 {score['decision_score']:.4f})"
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
        "detector_metadata": detector_metadata,
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
