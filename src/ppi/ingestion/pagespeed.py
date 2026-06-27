"""PageSpeed Insights CSV ingestion.

Assumed units, documented so scoring thresholds are meaningful:
  - psi_lcp in seconds (Largest Contentful Paint)
  - psi_inp in milliseconds (Interaction to Next Paint)
  - psi_cls as a unitless ratio (Cumulative Layout Shift)
  - score fields on a 0 to 100 scale (Lighthouse)
"""

from __future__ import annotations

import pandas as pd

from ppi.ingestion.base import (
    check_expected_columns,
    map_columns,
    read_csv_flexible,
)
from ppi.normalization.url_tools import normalize_url
from ppi.schemas.inputs import PageSpeedRow

_COLUMN_MAP = {
    "url": ["URL", "Page", "url"],
    "psi_lcp": ["LCP", "psi_lcp"],
    "psi_inp": ["INP", "psi_inp"],
    "psi_cls": ["CLS", "psi_cls"],
    "psi_performance_score": ["Performance score", "Performance", "psi_performance_score"],
    "psi_accessibility_score": ["Accessibility score", "psi_accessibility_score"],
    "psi_seo_score": ["SEO score", "psi_seo_score"],
    "device": ["Device", "Strategy", "device"],
}

_REQUIRED_FIELDS = {"url"}
_EXPECTED_FIELDS = {"psi_cls", "psi_inp", "psi_lcp", "psi_performance_score"}


def load_pagespeed(source: object, warnings: list[str] | None = None) -> pd.DataFrame:
    """Load a PageSpeed export into a clean DataFrame.

    Args:
        source: Path, bytes, or file-like object for the CSV.
        warnings: Optional list to collect data quality warnings about
            missing required or expected columns. Not raised, just recorded.

    Returns:
        A DataFrame of validated rows with an added normalized_url column.
        Rows without a usable URL are dropped.
    """
    raw = read_csv_flexible(source)
    mapped = map_columns(raw, _COLUMN_MAP)
    check_expected_columns(
        raw,
        _COLUMN_MAP,
        "PageSpeed",
        _REQUIRED_FIELDS,
        _EXPECTED_FIELDS,
        warnings,
    )

    records: list[dict] = []
    for row in mapped.to_dict(orient="records"):
        if not row.get("url"):
            continue
        validated = PageSpeedRow(**row)
        record = validated.model_dump()
        record["normalized_url"] = normalize_url(record["url"])
        records.append(record)

    return pd.DataFrame(records)
