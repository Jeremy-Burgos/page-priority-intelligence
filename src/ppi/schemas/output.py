"""pydantic schema for the scored output row.

ScoredUrl describes one row of the master scored table. It mirrors the field
list in the report output spec and is used to validate the final result before
it is written to CSV, so the output contract stays stable.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Bucket(str, Enum):
    """The single primary recommendation bucket assigned to each URL."""

    FIX_NOW = "Fix Now"
    QUICK_WIN = "Quick Win"
    REFRESH_EXPAND = "Refresh/Expand"
    INTERNAL_LINK_PUSH = "Internal Link Push"
    AUTHORITY_GAP = "Authority Gap"
    PERFORMANCE_FIX = "Performance Fix"
    PROTECT = "Protect"
    MERGE_PRUNE = "Merge/Prune"
    MONITOR = "Monitor"


class Confidence(str, Enum):
    """Qualitative confidence based on how many sources backed the row."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class ScoredUrl(BaseModel):
    """One fully scored URL in the master output table."""

    # Identity and join provenance
    url: str
    normalized_url: str
    source_url: Optional[str] = None
    url_match_status: str = "matched"

    # Raw context fields carried through for the report
    status_code: Optional[int] = None
    indexability: Optional[str] = None
    gsc_clicks: Optional[int] = None
    gsc_impressions: Optional[int] = None
    gsc_ctr: Optional[float] = None
    gsc_avg_position: Optional[float] = None
    ga4_sessions: Optional[int] = None
    ga4_conversions: Optional[int] = None
    ga4_revenue: Optional[float] = None
    referring_domains: Optional[int] = None
    inlinks: Optional[int] = None
    psi_lcp: Optional[float] = None
    psi_inp: Optional[float] = None
    psi_cls: Optional[float] = None

    # Component scores (all 0 to 1 unless noted)
    demand_score: float = 0.0
    underperformance_score: float = 0.0
    seo_opportunity_score: float = 0.0
    technical_risk_score: float = 0.0
    technical_risk_opportunity_score: float = 0.0
    authority_internal_link_gap_score: float = 0.0
    performance_risk_score: float = 0.0
    performance_risk_opportunity_score: float = 0.0
    traffic_value_score: float = 0.0
    decay_score: float = 0.0
    business_value_score: float = 0.0

    # Final score and recommendation
    priority_score: float = Field(0.0, ge=0.0, le=100.0)
    recommendation_bucket: Bucket = Bucket.MONITOR
    primary_recommendation: str = ""
    confidence_score: Confidence = Confidence.LOW
