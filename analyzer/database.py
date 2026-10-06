import os

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://traffic:traffic-dev-password@localhost:5432/traffic",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class RequestLog(Base):
    """Read-only mapping for request rows written by the test web app."""

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_ip: Mapped[str] = mapped_column(String(45))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(2048))
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    user_agent: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True))


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analyzed_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    window_seconds: Mapped[int] = mapped_column(Integer)
    window_started_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    window_ended_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    detector_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), index=True)
    total_requests: Mapped[int] = mapped_column(Integer)
    unique_clients: Mapped[int] = mapped_column(Integer)
    error_requests: Mapped[int] = mapped_column(Integer)
    error_rate: Mapped[float] = mapped_column(Float)
    average_latency_ms: Mapped[float] = mapped_column(Float)
    p95_latency_ms: Mapped[float] = mapped_column(Float)
    bucket_seconds: Mapped[int] = mapped_column(Integer, default=1)
    timeline: Mapped[list] = mapped_column(JSON)
    client_summaries: Mapped[list] = mapped_column(JSON)
    findings: Mapped[list] = mapped_column(JSON)


def init_db():
    Base.metadata.create_all(bind=engine)
    # Additive migration for analyzer versions deployed before timeline charts.
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE analysis_results ADD COLUMN IF NOT EXISTS "
            "bucket_seconds INTEGER NOT NULL DEFAULT 1"
        ))
        connection.execute(text(
            "ALTER TABLE analysis_results ADD COLUMN IF NOT EXISTS "
            "timeline JSON NOT NULL DEFAULT '[]'::json"
        ))
