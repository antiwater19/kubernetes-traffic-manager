import os

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, create_engine, func, text
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
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_ip: Mapped[str] = mapped_column(String(45), index=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(2048), index=True)
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    scenario: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class IPPolicy(Base):
    """Persisted manual block and per-client rate-limit settings."""

    __tablename__ = "ip_policies"

    client_ip: Mapped[str] = mapped_column(String(45), primary_key=True)
    is_blocked: Mapped[bool] = mapped_column(default=False, server_default="false")
    block_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    blocked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_limit_max_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IPRateWindow(Base):
    """Shared fixed-window counters so limits apply across all app replicas."""

    __tablename__ = "ip_rate_windows"
    __table_args__ = (
        UniqueConstraint(
            "client_ip", "window_seconds", "window_started_at",
            name="uq_ip_rate_windows_client_window",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_ip: Mapped[str] = mapped_column(String(45), index=True)
    window_seconds: Mapped[int] = mapped_column(Integer)
    window_started_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    request_count: Mapped[int] = mapped_column(Integer, default=1)


def init_db():
    Base.metadata.create_all(bind=engine)
    # Preserve existing request history while extending older installs.
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS scenario VARCHAR(64)"
        ))
