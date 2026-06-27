"""Sitewide baselines.

Baselines are computed once per dataset and reused for every page so that each
page is judged against the site, not against a single global average. The two
kinds of baseline:

  1. P90 values for log normalization of skewed metrics.
  2. Median CTR per ranking band, used to measure CTR underperformance fairly
     (a page in positions 4 to 10 should not be compared to one ranking 1 to 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ppi.scoring.normalize_metrics import p90


def ranking_band(position: object) -> str:
    """Bucket an average search position into a CTR comparison band."""
    try:
        pos = float(position)
    except (TypeError, ValueError):
        return "no_data"
    # NaN compares unequal to itself; treat a missing position as no data.
    if pos != pos or pos <= 0:
        return "no_data"
    if pos <= 3:
        return "1-3"
    if pos <= 10:
        return "4-10"
    if pos <= 20:
        return "11-20"
    if pos <= 50:
        return "21-50"
    return "51+"


def ranking_opportunity(position: object) -> float:
    """Score the upside of a page's current ranking band.

    Positions 4 to 10 carry the highest opportunity: visible enough to have
    demand, close enough to page-one gains to move with reasonable effort.
    """
    band = ranking_band(position)
    return {
        "1-3": 0.30,
        "4-10": 1.00,
        "11-20": 0.85,
        "21-50": 0.50,
        "51+": 0.15,
        "no_data": 0.00,
    }[band]


@dataclass
class Baselines:
    """Container for all sitewide baselines used during scoring."""

    p90_impressions: float = 0.0
    p90_query_count: float = 0.0
    p90_clicks: float = 0.0
    p90_sessions: float = 0.0
    p90_conversions: float = 0.0
    p90_revenue: float = 0.0
    p90_referring_domains: float = 0.0
    p90_inlinks: float = 0.0
    median_inlinks: float = 0.0
    # Median CTR keyed by ranking band; empty bands fall back to the global median.
    ctr_median_by_band: dict[str, float] = field(default_factory=dict)
    global_ctr_median: float = 0.0


def _median(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.median()) if not clean.empty else 0.0


def compute_baselines(frame: pd.DataFrame) -> Baselines:
    """Compute every baseline from the joined master frame.

    Args:
        frame: The joined per-URL DataFrame containing whatever source columns
            are available. Missing columns are treated as absent, not as zero.

    Returns:
        A populated Baselines object.
    """

    def col(name: str) -> pd.Series:
        return frame[name] if name in frame.columns else pd.Series(dtype="float64")

    baselines = Baselines(
        p90_impressions=p90(col("gsc_impressions")),
        p90_query_count=p90(col("gsc_query_count")),
        p90_clicks=p90(col("gsc_clicks")),
        p90_sessions=p90(col("ga4_sessions")),
        p90_conversions=p90(col("ga4_conversions")),
        p90_revenue=p90(col("ga4_revenue")),
        p90_referring_domains=p90(col("referring_domains")),
        p90_inlinks=p90(col("inlinks")),
        median_inlinks=_median(col("inlinks")),
        global_ctr_median=_median(col("gsc_ctr")),
    )

    # Median CTR per ranking band.
    if "gsc_ctr" in frame.columns and "gsc_avg_position" in frame.columns:
        working = frame[["gsc_ctr", "gsc_avg_position"]].copy()
        working["band"] = working["gsc_avg_position"].apply(ranking_band)
        working["gsc_ctr"] = pd.to_numeric(working["gsc_ctr"], errors="coerce")
        grouped = working.dropna(subset=["gsc_ctr"]).groupby("band")["gsc_ctr"].median()
        baselines.ctr_median_by_band = {str(k): float(v) for k, v in grouped.items()}

    return baselines


def expected_ctr(baselines: Baselines, position: object) -> float:
    """Return the expected CTR for a page's ranking band.

    Falls back to the global median CTR when a band has no data, and to a small
    positive floor when the site has no CTR data at all, so the gap calculation
    stays defined.
    """
    band = ranking_band(position)
    if band in baselines.ctr_median_by_band and baselines.ctr_median_by_band[band] > 0:
        return baselines.ctr_median_by_band[band]
    if baselines.global_ctr_median > 0:
        return baselines.global_ctr_median
    return 0.01
