import os

from sqlalchemy import DateTime, Float, Integer, String, create_engine, func, text
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


def init_db():
    Base.metadata.create_all(bind=engine)
    # Preserve existing request history while extending older installs.
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS scenario VARCHAR(64)"
        ))
