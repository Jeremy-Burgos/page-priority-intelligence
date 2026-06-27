"""GA4 Landing Page CSV ingestion.

GA4 usually reports landing pages as paths, not full URLs, so this reader needs
the configured site_domain to build absolute URLs for joining. Rows that cannot
be converted (no domain configured and only a path given) are kept but flagged
with an empty normalized_url so the join layer can report them as unmatched
rather than dropping them silently.
"""

from __future__ import annotations

import pandas as pd

from ppi.ingestion.base import (
    check_expected_columns,
    map_columns,
    read_csv_flexible,
)
from ppi.normalization.url_tools import ga4_path_to_url
from ppi.schemas.inputs import Ga4Row

_COLUMN_MAP = {
    "landing_page": ["Landing page", "Landing Page", "landing_page", "Page path"],
    "ga4_sessions": ["Sessions", "ga4_sessions"],
    "ga4_engaged_sessions": ["Engaged sessions", "ga4_engaged_sessions"],
    "ga4_engagement_rate": ["Engagement rate", "ga4_engagement_rate"],
    "ga4_conversions": ["Conversions", "Key events", "ga4_conversions"],
    "ga4_revenue": ["Revenue", "Total revenue", "ga4_revenue"],
}

_REQUIRED_FIELDS = {"landing_page"}
_EXPECTED_FIELDS = {"ga4_conversions", "ga4_sessions"}


def load_ga4(source: object, site_domain: str, warnings: list[str] | None = None) -> pd.DataFrame:
    """Load a GA4 Landing Page export into a clean DataFrame.

    Args:
        source: Path, bytes, or file-like object for the CSV.
        site_domain: Absolute origin such as "https://example.com". Required to
            convert path-style landing pages into joinable URLs.
        warnings: Optional list to collect data quality warnings about
            missing required or expected columns. Not raised, just recorded.

    Returns:
        A DataFrame of validated rows. normalized_url is empty for rows that
        could not be converted to an absolute URL.
    """
    raw = read_csv_flexible(source)
    mapped = map_columns(raw, _COLUMN_MAP)
    check_expected_columns(
        raw,
        _COLUMN_MAP,
        "GA4",
        _REQUIRED_FIELDS,
        _EXPECTED_FIELDS,
        warnings,
    )

    records: list[dict] = []
    for row in mapped.to_dict(orient="records"):
        if not row.get("landing_page"):
            continue
        validated = Ga4Row(**row)
        record = validated.model_dump()
        record["normalized_url"] = ga4_path_to_url(record["landing_page"], site_domain)
        records.append(record)

    return pd.DataFrame(records)
