from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, CHAR, Date, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
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
ReviewSource = Enum("play", "appstore", "reddit", "maps", "mouthshut", name="review_source", native_enum=True, create_type=False)
ReviewBucket = Enum("complaint", "feature_request", "praise", name="review_bucket", native_enum=True, create_type=False)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String, nullable=False)
    play_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    app_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    domain: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    brand_keyword: Mapped[str] = mapped_column(String, nullable=False)
    maps_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    maps_location_hint: Mapped[str] = mapped_column(String, nullable=False, default="India")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    runs: Mapped[List["Run"]] = relationship(back_populates="company")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    company_id: Mapped[str] = mapped_column(GUID(), ForeignKey("companies.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(RunStatus, nullable=False, default="queued", index=True)
    model_used: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_counts: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    completeness: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    budget_cap: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    dedup_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    quarantine_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
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
    english_gloss: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bucket: Mapped[Optional[str]] = mapped_column(ReviewBucket, nullable=True)
    theme: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    severity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    representative_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(GUID(), ForeignKey("runs.id"), nullable=False, index=True)
    company_id: Mapped[str] = mapped_column(GUID(), ForeignKey("companies.id"), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(ReviewBucket, nullable=False)
    theme: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    normalized_frequency: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    avg_severity: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    theme_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    top_quotes: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String, nullable=False, default="gemini")
    model: Mapped[str] = mapped_column(String, nullable=False, default="gemini-3.1-flash-lite")
    max_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=3000)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    recency_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    dedup_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.86)
    per_run_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    source_weights: Mapped[Dict[str, float]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {"play": 1, "appstore": 1, "reddit": 1, "maps": 1, "mouthshut": 1},
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
