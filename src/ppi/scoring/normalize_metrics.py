"""Metric normalization.

SEO metrics (impressions, clicks, sessions, backlinks) are heavily skewed: a
handful of pages dominate the totals. Comparing every page against the mean
rewards those few outliers and buries everything else. The model therefore uses
log scaling against the 90th percentile, capped at 1.0:

    Normalized Metric = min(log1p(value) / log1p(P90_value), 1)

A page at or above the P90 value scores 1.0; everything else scales smoothly
below it. This is the single normalization primitive used across components.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def p90(series: pd.Series) -> float:
    """Return the 90th percentile of the non-null, non-negative values.

    Returns 0.0 when there is no usable data, which makes downstream
    normalization yield 0.0 rather than dividing by zero.
    """
    clean = pd.to_numeric(series, errors="coerce").dropna()
    clean = clean[clean >= 0]
    if clean.empty:
        return 0.0
    return float(np.percentile(clean, 90))


def normalize_log(value: object, p90_value: float) -> float:
    """Normalize a single value with log scaling against a P90 baseline.

    Args:
        value: The page's metric value. None or non-numeric becomes 0.0.
        p90_value: The 90th percentile baseline for this metric across the site.

    Returns:
        A float in the range 0.0 to 1.0.
    """
    if p90_value is None or p90_value <= 0:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    # NaN (e.g. a missing cell after a left join) is missing, not a value.
    if numeric != numeric or numeric <= 0:
        return 0.0

    normalized = math.log1p(numeric) / math.log1p(p90_value)
    return min(normalized, 1.0)


def normalize_series_log(series: pd.Series) -> pd.Series:
    """Normalize an entire series with log scaling against its own P90.

    Convenience wrapper for vectorized use during scoring.
    """
    baseline = p90(series)
    return series.apply(lambda v: normalize_log(v, baseline))
