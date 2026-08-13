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
    business_type: str = "other"
    selected_sources: List[str] = Field(default_factory=list)
    analysis_goals: List[str] = Field(default_factory=list)
    analysis_focus: str = Field(default="", max_length=600)
    maps_enabled: bool = False
    maps_location_hint: str = "India"
    reddit_enabled: bool = False
    maps_url: str = ""
    instagram_url: str = ""
    twitter_url: str = ""
    mouthshut_url: str = ""


class CompanyDiscoveryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    website: str = ""
    business_type: str = "other"


class CompanyDiscoveryOut(BaseModel):
    name: str
    domain: str = ""
    brand_keyword: str
    play_id: str = ""
    app_id: str = ""
    icon_text: str
    business_type: str
    recommended_sources: List[str]
    source_catalog: List[Dict[str, Any]]


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
    business_type: str = "other"
    selected_sources: List[str] = Field(default_factory=list)
    analysis_goals: List[str] = Field(default_factory=list)
    analysis_focus: Optional[str] = None
    maps_url: Optional[str] = None
    instagram_url: Optional[str] = None
    twitter_url: Optional[str] = None
    mouthshut_url: Optional[str] = None
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
    insight_summary: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    created_at: datetime
    company: Optional[CompanyOut] = None
    current_stage: str = "Queued"
    stage_detail: str = ""
    progress: float = 0

    model_config = {"from_attributes": True}


class RunListCompanyOut(BaseModel):
    """The small company shape needed to render a workspace row."""

    id: str
    name: str
    domain: Optional[str] = None
    selected_sources: List[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RunListItemOut(BaseModel):
    id: str
    company_id: str
    status: str
    model_used: Optional[str] = None
    cost_estimate: float = 0
    budget_cap: float = 0
    quarantine_rate: float = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    company: Optional[RunListCompanyOut] = None
    current_stage: str = "Queued"
    stage_detail: str = ""
    progress: float = 0


class RunPageOut(BaseModel):
    items: List[RunListItemOut]
    total: int
    page: int
    page_size: int
    pages: int


class RunStatusOut(BaseModel):
    id: str
    status: str
    current_stage: str = "Queued"
    stage_detail: str = ""
    progress: float = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    cost_estimate: float = 0
    quarantine_rate: float = 0
    source_states: Dict[str, str] = Field(default_factory=dict)


class RunStatusPageOut(BaseModel):
    items: List[RunStatusOut]


class SubmitRunResponse(BaseModel):
    run: RunOut
    deduped_existing: bool


class PublicShareOut(BaseModel):
    token: str


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


class EndpointUsageOut(BaseModel):
    usage_date: dt_date
    endpoint: str
    status_code: int
    request_count: int
    response_body_bytes: int

    model_config = {"from_attributes": True}


class EgressWarningOut(BaseModel):
    cycle_start: dt_date
    threshold_bytes: int
    estimated_bytes: int
    created_at: datetime

    model_config = {"from_attributes": True}


class EgressOpsOut(BaseModel):
    cycle_start: dt_date
    cycle_end: dt_date
    estimated_response_bytes: int
    estimated_response_gb: float
    warning_thresholds_gb: List[float]
    warnings: List[EgressWarningOut]
    endpoints: List[EndpointUsageOut]
