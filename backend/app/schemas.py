from __future__ import annotations

from datetime import date as dt_date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=3)
    guest_id: str = ""


class UserOut(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthLoginResponse(BaseModel):
    user: UserOut
    token: str
    claimed_runs: int = 0


class SubmitRunRequest(BaseModel):
    name: str = Field(min_length=1)
    play_link: str = ""
    app_store_link: str = ""
    website: str = ""
    maps_enabled: bool = False
    maps_location_hint: str = "India"
    reddit_enabled: bool = False


class CompanyOut(BaseModel):
    id: str
    name: str
    play_id: Optional[str] = None
    app_id: Optional[str] = None
    domain: Optional[str] = None
    brand_keyword: str
    maps_enabled: bool = False
    maps_location_hint: str = "India"
    reddit_enabled: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    id: str
    company_id: str
    status: str
    model_used: Optional[str] = None
    source_counts: Dict[str, Any]
    completeness: Dict[str, Any]
    cost_estimate: float
    budget_cap: float
    dedup_ratio: float
    quarantine_rate: float
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    created_at: datetime
    company: Optional[CompanyOut] = None
    current_stage: str = "Queued"
    stage_detail: str = ""
    progress: float = 0

    model_config = {"from_attributes": True}


class SubmitRunResponse(BaseModel):
    run: RunOut
    deduped_existing: bool


class ReviewOut(BaseModel):
    id: str
    review_hash: str
    source: str
    date: Optional[dt_date] = None
    rating: Optional[int] = None
    text: str
    theme: Optional[str] = None
    l2_theme: Optional[str] = None
    representative_flag: bool

    model_config = {"from_attributes": True}


class ReviewPageOut(BaseModel):
    items: List[ReviewOut]
    total: int
    page: int
    page_size: int
    pages: int


class ThemeOut(BaseModel):
    id: str
    theme: str
    count: int
    normalized_frequency: float
    share: float = 0
    theme_score: float
    rank: int
    top_quotes: List[Dict[str, Any]]
    l2_subthemes: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RunLogOut(BaseModel):
    id: str
    run_id: str
    company_id: str
    stage: str
    event: str
    status: str
    source: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    attempt: Optional[int] = None
    cost_usd: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    details: Dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class SettingsOut(BaseModel):
    provider: str
    model: str
    max_reviews: int
    batch_size: int
    recency_window_days: int
    dedup_threshold: float
    per_run_budget_usd: float
    source_weights: Dict[str, float]

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    max_reviews: Optional[int] = Field(default=None, ge=1, le=10000)
    batch_size: Optional[int] = Field(default=None, ge=1, le=100)
    recency_window_days: Optional[int] = Field(default=None, ge=1, le=365)
    dedup_threshold: Optional[float] = Field(default=None, ge=0.5, le=0.99)
    per_run_budget_usd: Optional[float] = Field(default=None, ge=0.01, le=100)
    source_weights: Optional[Dict[str, float]] = None


class ResultsOut(BaseModel):
    company: CompanyOut
    run: RunOut
    reviews: List[ReviewOut]
    themes: List[ThemeOut]
    logs: List[RunLogOut] = []
    summary: Dict[str, Any]
    deck_spec: str
