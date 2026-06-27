"""pydantic schemas for input rows.

Each source has its own row model with permissive parsing. The point of these
models is validation and coercion at the edge: messy CSV cells (empty strings,
percentage signs, thousands separators) become clean typed values, and clearly
invalid rows can be reported rather than silently scoring as zero.

These models describe one cleaned row per source. The ingestion layer is
responsible for mapping raw column headers onto these field names before
validation.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _parse_ctr(value: object) -> Optional[float]:
    """Parse a CTR cell into a 0 to 1 fraction, correct for sub-1% values.

    The presence of a percent sign is decisive: "0.4%" means 0.004, not 0.4.
    Relying on magnitude alone fails here, because 0.4 looks like a fraction but
    "0.4%" is a percentage. So when a percent sign is present the value is always
    divided by 100. Without a percent sign, an API-style fraction is assumed,
    except that a value above 1 is treated as an accidental percentage.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if raw == "":
        return None
    is_percent = "%" in raw
    num = _to_float(raw)
    if num is None:
        return None
    if is_percent:
        return num / 100.0
    return num / 100.0 if num > 1 else num


def _to_float(value: object) -> Optional[float]:
    """Coerce a CSV cell to float, tolerating %, commas, and blanks."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: object) -> Optional[int]:
    """Coerce a CSV cell to int via float, tolerating decimals and blanks."""
    result = _to_float(value)
    return int(round(result)) if result is not None else None


class ScreamingFrogRow(BaseModel):
    """One row from a Screaming Frog Internal All export."""

    url: str
    status_code: Optional[int] = None
    status: Optional[str] = None
    indexability: Optional[str] = None
    indexability_status: Optional[str] = None
    title: Optional[str] = None
    title_length: Optional[int] = None
    meta_description: Optional[str] = None
    meta_description_length: Optional[int] = None
    h1: Optional[str] = None
    word_count: Optional[int] = None
    canonical_link_element: Optional[str] = None
    inlinks: Optional[int] = None
    unique_inlinks: Optional[int] = None
    crawl_depth: Optional[int] = None

    @field_validator(
        "status_code",
        "title_length",
        "meta_description_length",
        "word_count",
        "inlinks",
        "unique_inlinks",
        "crawl_depth",
        mode="before",
    )
    @classmethod
    def _coerce_int(cls, value: object) -> Optional[int]:
        return _to_int(value)


class GscRow(BaseModel):
    """One row from a Google Search Console Pages export."""

    url: str
    gsc_clicks: Optional[int] = None
    gsc_impressions: Optional[int] = None
    gsc_ctr: Optional[float] = None  # stored as a fraction, e.g. 0.034
    gsc_avg_position: Optional[float] = None
    gsc_query_count: Optional[int] = None

    @field_validator("gsc_clicks", "gsc_impressions", "gsc_query_count", mode="before")
    @classmethod
    def _coerce_int(cls, value: object) -> Optional[int]:
        return _to_int(value)

    @field_validator("gsc_avg_position", mode="before")
    @classmethod
    def _coerce_float(cls, value: object) -> Optional[float]:
        return _to_float(value)

    @field_validator("gsc_ctr", mode="before")
    @classmethod
    def _coerce_ctr(cls, value: object) -> Optional[float]:
        return _parse_ctr(value)


class Ga4Row(BaseModel):
    """One row from a GA4 Landing Page export."""

    landing_page: str
    ga4_sessions: Optional[int] = None
    ga4_engaged_sessions: Optional[int] = None
    ga4_engagement_rate: Optional[float] = None
    ga4_conversions: Optional[int] = None
    ga4_revenue: Optional[float] = None

    @field_validator(
        "ga4_sessions", "ga4_engaged_sessions", "ga4_conversions", mode="before"
    )
    @classmethod
    def _coerce_int(cls, value: object) -> Optional[int]:
        return _to_int(value)

    @field_validator("ga4_engagement_rate", "ga4_revenue", mode="before")
    @classmethod
    def _coerce_float(cls, value: object) -> Optional[float]:
        return _to_float(value)


class BacklinkRow(BaseModel):
    """One row from an Ahrefs, Semrush, or manual backlink export."""

    url: str
    backlinks: Optional[int] = None
    referring_domains: Optional[int] = None
    authority_score: Optional[float] = None
    backlink_source: Optional[str] = None

    @field_validator("backlinks", "referring_domains", mode="before")
    @classmethod
    def _coerce_int(cls, value: object) -> Optional[int]:
        return _to_int(value)

    @field_validator("authority_score", mode="before")
    @classmethod
    def _coerce_float(cls, value: object) -> Optional[float]:
        return _to_float(value)


class PageSpeedRow(BaseModel):
    """One row from a PageSpeed Insights export.

    LCP is expected in seconds, INP in milliseconds, CLS as a unitless ratio.
    The ingestion layer documents the assumed units.
    """

    url: str
    psi_lcp: Optional[float] = None
    psi_inp: Optional[float] = None
    psi_cls: Optional[float] = None
    psi_performance_score: Optional[float] = None
    psi_accessibility_score: Optional[float] = None
    psi_seo_score: Optional[float] = None
    device: Optional[str] = None

    @field_validator(
        "psi_lcp",
        "psi_inp",
        "psi_cls",
        "psi_performance_score",
        "psi_accessibility_score",
        "psi_seo_score",
        mode="before",
    )
    @classmethod
    def _coerce_float(cls, value: object) -> Optional[float]:
        return _to_float(value)


class UrlInspectionRow(BaseModel):
    """One row from a URL Inspection export."""

    url: str
    url_inspection_index_status: Optional[str] = None
    url_inspection_coverage_state: Optional[str] = None
    url_inspection_robots_state: Optional[str] = None
    url_inspection_last_crawl: Optional[str] = None
    url_inspection_google_canonical: Optional[str] = None
    url_inspection_user_canonical: Optional[str] = None
    url_inspection_sitemap_presence: Optional[str] = None
