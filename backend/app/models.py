from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, CHAR, Date, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def uuid_str() -> str:
    return str(uuid.uuid4())


class GUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PostgresUUID(as_uuid=False))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return str(value)


class Base(DeclarativeBase):
    pass


RunStatus = Enum(
    "queued",
    "scraping",
    "classifying",
    "done",
    "partial",
    "failed",
    name="run_status",
    native_enum=True,
    create_type=False,
)
ReviewSource = Enum(
    "play",
    "appstore",
    "reddit",
    "maps",
    "mouthshut",
    "instagram",
    "twitter",
    name="review_source",
    native_enum=True,
    create_type=False,
)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    owner_user_id: Mapped[Optional[str]] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True, index=True)
    guest_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    play_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    app_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    domain: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    brand_keyword: Mapped[str] = mapped_column(String, nullable=False)
    maps_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    maps_location_hint: Mapped[str] = mapped_column(String, nullable=False, default="India")
    reddit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    business_type: Mapped[str] = mapped_column(String, nullable=False, default="other")
    selected_sources: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=lambda: ["play", "appstore"])
    analysis_goals: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    analysis_focus: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    maps_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    instagram_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    twitter_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    mouthshut_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    runs: Mapped[List["Run"]] = relationship(back_populates="company")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    company_id: Mapped[str] = mapped_column(GUID(), ForeignKey("companies.id"), nullable=False, index=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True, index=True)
    guest_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(RunStatus, nullable=False, default="queued", index=True)
    model_used: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_counts: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    completeness: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    budget_cap: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    dedup_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    quarantine_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    insight_summary: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Immutable presentation data produced once during synthesis. Serving this
    # snapshot keeps report refreshes from materializing every review again.
    report_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # An opaque, unguessable token for an explicitly shared read-only report.
    # It is deliberately separate from the run ID so normal workspace routes
    # remain private to their owner.
    public_share_token: Mapped[Optional[str]] = mapped_column(String(96), nullable=True, unique=True, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="runs")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("run_id", "review_hash", name="reviews_run_hash_unique"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(GUID(), ForeignKey("runs.id"), nullable=False, index=True)
    company_id: Mapped[str] = mapped_column(GUID(), ForeignKey("companies.id"), nullable=False, index=True)
    review_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source: Mapped[str] = mapped_column(ReviewSource, nullable=False, index=True)
    date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False, default="other")
    theme: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    l2_theme: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    representative_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(GUID(), ForeignKey("runs.id"), nullable=False, index=True)
    company_id: Mapped[str] = mapped_column(GUID(), ForeignKey("companies.id"), nullable=False, index=True)
    theme: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    normalized_frequency: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    avg_severity: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    theme_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    top_quotes: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    l2_subthemes: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def share(self) -> float:
        return float(self.normalized_frequency or 0)


class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(GUID(), ForeignKey("runs.id"), nullable=False, index=True)
    company_id: Mapped[str] = mapped_column(GUID(), ForeignKey("companies.id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="info", index=True)
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    attempt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ApiUsageDaily(Base):
    __tablename__ = "api_usage_daily"
    __table_args__ = (UniqueConstraint("usage_date", "endpoint", "status_code", name="api_usage_daily_endpoint_status_unique"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_body_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EgressWarning(Base):
    __tablename__ = "egress_warnings"
    __table_args__ = (UniqueConstraint("cycle_start", "threshold_bytes", name="egress_warning_cycle_threshold_unique"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    cycle_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    threshold_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String, nullable=False, default="gemini")
    model: Mapped[str] = mapped_column(String, nullable=False, default="gemini-3.1-flash-lite")
    max_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    recency_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    dedup_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.86)
    per_run_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    source_weights: Mapped[Dict[str, float]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {"play": 1, "appstore": 1, "reddit": 1, "maps": 1, "mouthshut": 1, "instagram": 1, "twitter": 1},
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LegacyRunAccess(Base):
    __tablename__ = "legacy_run_access"
    __table_args__ = (UniqueConstraint("run_id", "user_id", name="legacy_run_access_unique"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(GUID(), ForeignKey("runs.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
